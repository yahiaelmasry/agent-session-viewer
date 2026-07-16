#!/usr/bin/env python3
"""Clean a Codex rollout JSONL into a compact JSON conversation log.

Goal (same as clean_claude_session.py): a *distilled* conversation to feed into
other AI sessions — user intent and outcomes, without the raw-output tokens
that pollute a fresh context.

Both the Codex CLI and Codex Desktop write to the same store
(`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`, `CODEX_HOME` overrides), one
line per record shaped `{"timestamp","type","payload"}`. The two surfaces are
distinguished only by `session_meta.payload.originator` ("codex-tui",
"Codex Desktop", …), which is surfaced in the output so this one parser covers
both.

Tool calls (Codex's flat `response_item` stream) are triaged by name into the
same tiers as the Claude distiller:
- KEEP LINE: `apply_patch` (file edits), mutating shell (`exec`/`exec_command`/
  `shell`), `web_search`, unknown tools -> one `actions` line; failed calls get
  " → error". Output dropped.
- COLLAPSE: read-only shell, `view_image`, `tool_search` -> consecutive runs
  coalesce to "exec(ro) ×42". Output dropped.
- DROP: reasoning, tool outputs, event_msg telemetry, and the multi-agent
  orchestration plumbing (`spawn_agent`/`wait`/`send_message`/`followup_task`/
  `update_plan`/…) emit nothing.

Subagents: Codex runs each subagent as its OWN rollout file (the parent's
`sub_agent_activity` event carries `agent_thread_id`, which equals the child's
`session_meta.id`), and the inter-agent messages inside the parent are
Fernet-encrypted (`gAAAA…`). So the parent always gets a
`spawned subagent: <path> — thread <id>` line from the readable spawn events
(tier A). With `--with-subagents` (tier B) the child rollout is resolved by its
thread id under `$CODEX_HOME/sessions` and its final report is inlined as a
`subagent` message. AskUserQuestion has no Codex analog. The context-compaction
boundary is kept as a marker.

Output schema:
{
  "source": "<file name>",
  "originator": "codex-tui" | "Codex Desktop" | ...,   # omitted if unknown
  "messages": [
    {"role": "user", "text": "..."},
    {"role": "assistant", "text": "..."},
    {"role": "assistant", "actions": ["apply_patch a.py", "exec(ro) ×42",
                                       "spawned subagent: luna — thread 019f…"]},
    {"role": "subagent", "name": "luna", "text": "<child's final report>"},  # --with-subagents
    {"role": "marker", "text": "Context compacted here. ..."},
    ...
  ]
}

Usage: clean_codex_rollout.py SRC.jsonl DST.json [--with-subagents]
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

MAX = 140  # one-liner truncation width
# Harness-injected boilerplate that Codex puts in *user*-role messages (often
# repeatedly, mid-stream) — dropped everywhere it appears, like the Claude side.
NOISE_PREFIXES = (
    "<environment_context", "<permissions instructions>", "<in-app-browser-context",
    "<codex_internal_context", "<recommended_plugins", "<skill", "<turn_aborted",
    "<subagent_notification", "<image", "<user_instructions",
    "The following is the Codex agent history",  # compaction dumps (marker covers the boundary)
    "# Browser comments:", "# AGENTS.md instructions for", "# Response annotations:",
    "# Chrome tabs:",
)
CMD_RE = re.compile(r'"cmd"\s*:\s*"((?:\\.|[^"\\])*)"')  # cmd inside exec JS / exec_command args
PATCH_FILE_RE = re.compile(r'^\*\*\*\s+(?:Add|Update|Delete) File:\s+(.+?)\s*$', re.M)
EXIT_RE = re.compile(r'exited with code (\d+)')

EXEC_TOOLS = {"exec", "exec_command", "shell"}  # command execution (Bash equivalent)
DROP_TOOLS = {  # multi-agent orchestration + planning plumbing: emit nothing
    "wait", "wait_agent", "list_agents", "send_message", "followup_task",
    "spawn_agent", "interrupt_agent", "close_agent", "write_stdin", "update_plan",
}
GROUP_LABEL = {"exec": "exec(ro)", "search": "tool_search", "media": "view_image"}
RO_BASH = {"ls", "cat", "pwd", "echo", "head", "tail", "which", "type", "stat", "wc", "tree",
           "file", "rg", "grep", "fd", "find", "eza", "bat", "df", "du", "env", "printenv",
           "date", "whoami", "uname"}  # sed/awk excluded: -i mutates
RO_GIT = {"status", "log", "diff", "show", "branch", "remote", "rev-parse", "describe", "blame"}


def short(s) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= MAX else s[: MAX - 1] + "…"


def _norm_cmd(cmd) -> str:
    if isinstance(cmd, list):
        # ["bash","-lc","<script>"] -> "<script>"
        if len(cmd) >= 3 and str(cmd[0]) in ("bash", "sh", "zsh") and str(cmd[1]) in ("-lc", "-c", "-l"):
            return str(cmd[2])
        return " ".join(str(x) for x in cmd)
    return str(cmd or "")


def cmd_of(raw) -> str:
    """Extract the shell command from an exec-style call input, or '' if none.

    Handles: exec_command args JSON ({"cmd": "..."}), the exec custom-tool JS
    wrapper (`tools.exec_command({"cmd":"..."})`), and shell command arrays.
    """
    if isinstance(raw, dict):
        return _norm_cmd(raw.get("cmd") or raw.get("command") or raw.get("script"))
    s = str(raw or "")
    m = CMD_RE.search(s)
    if m:
        try:
            return _norm_cmd(json.loads('"' + m.group(1) + '"'))
        except Exception:
            return _norm_cmd(m.group(1))
    try:
        d = json.loads(s)
    except Exception:
        return s.strip().splitlines()[0].strip() if s.strip() else ""
    if isinstance(d, dict):
        return _norm_cmd(d.get("cmd") or d.get("command") or d.get("script"))
    return _norm_cmd(d)


def bash_readonly(cmd: str) -> bool:
    # ponytail: leading-token heuristic; compound/piped read-only cmds fall to
    # KEEP-LINE (harmless). `git -C <path>` prefix is skipped so git status still
    # collapses (Codex exec heavily uses `git -C '<cwd>' ...`).
    parts = (cmd or "").split()
    if not parts:
        return False
    if parts[0] == "git":
        i = 1
        while i + 1 < len(parts) and parts[i] == "-C":
            i += 2
        return i < len(parts) and parts[i] in RO_GIT
    return parts[0] in RO_BASH


def patch_label(raw) -> str:
    s = raw if isinstance(raw, str) else json.dumps(raw)
    files = PATCH_FILE_RE.findall(s)
    if not files:
        return "apply_patch"
    extra = f" (+{len(files) - 1})" if len(files) > 1 else ""
    return f"apply_patch {short(files[0])}{extra}"


def tool_label(name: str, raw) -> str:
    d = raw if isinstance(raw, dict) else None
    if d is None and isinstance(raw, str):
        try:
            d = json.loads(raw)
        except Exception:
            d = None
    if isinstance(d, dict):
        for k in ("query", "url", "path", "file_path", "command", "cmd", "message", "prompt"):
            if d.get(k):
                return f"{name}: {short(d[k])}"
    return name or "tool"


def classify(pl: dict):
    """Return (kind, group, label). kind in {drop, collapse, line}."""
    pt = pl.get("type")
    if pt == "web_search_call":
        a = pl.get("action") if isinstance(pl.get("action"), dict) else {}
        tgt = a.get("url") or a.get("query") or a.get("type") or ""
        return ("line", None, f"web_search: {short(tgt)}" if tgt else "web_search")
    if pt == "image_generation_call":
        return ("line", None, "image_generation")
    if pt == "tool_search_call":
        return ("collapse", "search", "tool_search")
    if pt in ("function_call", "custom_tool_call", "local_shell_call"):
        name = pl.get("name", "") or ("shell" if pt == "local_shell_call" else "")
        raw = pl.get("arguments") if pl.get("arguments") is not None else pl.get("input")
        if pt == "local_shell_call" and raw is None:
            raw = pl.get("action")
        if name in DROP_TOOLS:
            return ("drop", None, None)
        if name == "apply_patch":
            return ("line", None, patch_label(raw))
        if name in EXEC_TOOLS or pt == "local_shell_call":
            cmd = cmd_of(raw)
            label = f"$ {short(cmd)}" if cmd else (name or "shell")
            return ("collapse", "exec", label) if bash_readonly(cmd) else ("line", None, label)
        if name == "view_image":
            return ("collapse", "media", "view_image")
        return ("line", None, tool_label(name, raw))
    return ("drop", None, None)  # reasoning, *_output, agent_message, etc.


def output_failed(output) -> bool:
    if not output:
        return False
    s = output if isinstance(output, str) else json.dumps(output)
    m = EXIT_RE.search(s)
    if m:
        return m.group(1) != "0"
    try:
        d = json.loads(s) if isinstance(s, str) else s
    except Exception:
        return False
    md = d.get("metadata") if isinstance(d, dict) else None
    if isinstance(md, dict) and "exit_code" in md:
        return md["exit_code"] != 0
    return False


def is_noise(text: str) -> bool:
    return not text or any(text.startswith(p) for p in NOISE_PREFIXES)


def message_text(pl: dict) -> str:
    blocks = [
        c.get("text", "")
        for c in (pl.get("content") or [])
        if isinstance(c, dict) and c.get("type") in ("input_text", "output_text")
    ]
    return "\n".join(b for b in blocks if b).strip()


COMPACT_MARKER = ("Context compacted here. Conversation continues below with fresh "
                  "context (Codex auto-summarized the prior history).")


def spawn_name(agent_path: str) -> str:
    """/root/triage/review -> triage/review (keeps nesting, drops the /root root)."""
    name = (agent_path or "").strip("/")
    if name.startswith("root/"):
        name = name[len("root/"):]
    return name or "subagent"


def thread_index(root=None) -> dict:
    """Map every rollout's session_meta id/session_id -> its file path.

    Reads only the first line (session_meta) of each file. Used to resolve a
    parent's spawned-subagent thread ids to the child rollout files.
    """
    if root is not None:
        roots = [Path(root)]
    else:
        home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
        roots = [home / "sessions", home / "archived_sessions"]
    idx: dict = {}
    for r in roots:
        if not r.exists():
            continue
        for p in r.rglob("rollout-*.jsonl"):
            try:
                with p.open(encoding="utf-8") as f:
                    first = json.loads(f.readline())
            except Exception:
                continue
            if first.get("type") != "session_meta":
                continue
            pl = first.get("payload") or {}
            for k in ("id", "session_id"):
                if pl.get(k):
                    idx.setdefault(pl[k], p)
    return idx


def final_report(child: Path) -> str:
    """The child rollout's last non-empty assistant message — its report-back."""
    last = ""
    try:
        with child.open(encoding="utf-8") as f:
            for raw in f:
                try:
                    d = json.loads(raw)
                except Exception:
                    continue
                if d.get("type") != "response_item":
                    continue
                pl = d.get("payload") if isinstance(d.get("payload"), dict) else {}
                if pl.get("type") == "message" and pl.get("role") == "assistant":
                    t = message_text(pl)
                    if t:
                        last = t
    except Exception:
        return ""
    return last


def distill(src: Path, resolve_subagents: bool = False, sessions_root=None) -> dict:
    records = []
    with src.open(encoding="utf-8") as f:
        for raw in f:
            try:
                records.append(json.loads(raw))
            except Exception:
                continue

    originator = None
    failed = set()  # call_ids whose output reported a non-zero exit
    for d in records:
        if d.get("type") == "session_meta":
            pl = d.get("payload")
            if isinstance(pl, dict):
                originator = pl.get("originator") or originator
        elif d.get("type") == "response_item":
            pl = d.get("payload") if isinstance(d.get("payload"), dict) else {}
            if pl.get("type") in ("function_call_output", "custom_tool_call_output") and output_failed(pl.get("output")):
                failed.add(pl.get("call_id"))

    index = thread_index(sessions_root) if resolve_subagents else {}
    reported: set = set()  # child thread ids already inlined (dedupe)

    messages: list[dict] = []
    run: list[tuple] = []  # pending (group, label); group None = non-coalescing

    def flush():
        if not run:
            return
        acts, i = [], 0
        while i < len(run):
            g, label = run[i]
            if g is not None:
                j = i
                while j < len(run) and run[j][0] == g:
                    j += 1
                cnt = j - i
                acts.append(label if cnt == 1 else f"{GROUP_LABEL[g]} ×{cnt}")
                i = j
            else:
                acts.append(label)
                i += 1
        messages.append({"role": "assistant", "actions": acts})
        run.clear()

    for d in records:
        t = d.get("type")
        pl = d.get("payload") if isinstance(d.get("payload"), dict) else {}

        if t == "event_msg":
            ept = pl.get("type")
            if ept == "context_compacted":
                flush()
                messages.append({"role": "marker", "text": COMPACT_MARKER})
            elif ept == "sub_agent_activity" and pl.get("kind") == "started":
                tid = pl.get("agent_thread_id")
                name = spawn_name(pl.get("agent_path"))
                label = f"spawned subagent: {name}" + (f" — thread {tid}" if tid else "")
                child = index.get(tid) if (resolve_subagents and tid) else None
                report = final_report(child) if (child and child != src and tid not in reported) else ""
                run.append((None, label))
                if report:
                    reported.add(tid)
                    flush()  # anchor the report right after its spawn line
                    messages.append({"role": "subagent", "name": name, "text": report})
            continue
        if t != "response_item":
            continue

        pt = pl.get("type")
        if pt == "message":
            role = pl.get("role")
            if role not in ("user", "assistant"):  # developer = env/permissions
                continue
            text = message_text(pl)
            if not text:
                continue
            if role == "user" and is_noise(text):
                continue  # harness-injected boilerplate, not user intent
            flush()
            messages.append({"role": role, "text": text})
            continue

        kind, group, label = classify(pl)
        if kind == "drop":
            continue
        if kind == "line" and pl.get("call_id") in failed:
            label += "  → error"
        run.append((group if kind == "collapse" else None, label))
    flush()

    out = {"source": src.name}
    if originator:
        out["originator"] = originator
    out["messages"] = messages
    return out


def main() -> None:
    resolve = "--with-subagents" in sys.argv[1:]
    pos = [a for a in sys.argv[1:] if not a.startswith("-")]
    src, dst = Path(pos[0]), Path(pos[1])
    out = distill(src, resolve_subagents=resolve)
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {dst} ({dst.stat().st_size:,} bytes, {len(out['messages'])} messages)")


if __name__ == "__main__":
    main()
