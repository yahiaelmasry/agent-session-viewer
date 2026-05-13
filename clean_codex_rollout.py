#!/usr/bin/env python3
"""Clean a Codex rollout JSONL into a compact JSON conversation log.

Keeps only real user and assistant (Codex) messages, in chronological order,
plus a marker for the context-compaction boundary. Drops everything else
(session_meta, turn_context, event_msg, reasoning, all tool/function calls
and outputs, and the `compacted` replacement_history).

Output schema:
{
  "source": "<source file name>",
  "messages": [
    {"role": "user" | "assistant" | "marker", "text": "..."},
    ...
  ]
}

Usage: clean_codex_rollout.py SRC.jsonl DST.json
"""
import json
import sys
from pathlib import Path

SRC = Path(sys.argv[1])
DST = Path(sys.argv[2])

ENV_CTX_PREFIXES = ("<environment_context>", "<permissions instructions>")


def main() -> None:
    messages: list[dict] = []
    skipped_first_user_env = False

    with SRC.open() as f:
        for raw in f:
            try:
                d = json.loads(raw)
            except Exception:
                continue
            t = d.get("type")
            p = d.get("payload") if isinstance(d.get("payload"), dict) else {}
            pt = p.get("type", "")

            if t == "event_msg" and pt == "context_compacted":
                messages.append({
                    "role": "marker",
                    "text": "Context compacted here. Conversation continues below with fresh context (Codex auto-summarized the prior history).",
                })
                continue

            if t != "response_item" or pt != "message":
                continue

            role = p.get("role", "?")
            if role not in ("user", "assistant"):
                continue

            content = p.get("content", []) or []
            text_blocks = [
                c.get("text", "")
                for c in content
                if isinstance(c, dict) and c.get("type") in ("input_text", "output_text")
            ]
            text = "\n".join(b for b in text_blocks if b).strip()
            if not text:
                continue

            if role == "user" and any(text.startswith(pre) for pre in ENV_CTX_PREFIXES):
                if not skipped_first_user_env:
                    skipped_first_user_env = True
                    continue

            messages.append({"role": role, "text": text})

    out = {"source": SRC.name, "messages": messages}
    DST.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {DST} ({DST.stat().st_size:,} bytes, {len(messages)} messages)")


if __name__ == "__main__":
    main()
