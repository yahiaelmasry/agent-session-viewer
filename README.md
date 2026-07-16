# agent-session-viewer

Export Claude Code or Codex CLI session logs to clean JSON, then to a standalone HTML viewer.

## Usage

```bash
python clean_claude_session.py SRC.jsonl DST.json     # CC session → JSON
python clean_codex_rollout.py  SRC.jsonl DST.json     # Codex rollout → JSON
python clean_codex_rollout.py  SRC.jsonl DST.json --with-subagents  # + inline child reports
python render_conversation_html.py SRC.json [DST.html] # JSON → HTML
```

Both scripts emit `{source, messages: [...]}` with the same tiered shape: prose
turns (`role`: `user` | `assistant`), a per-turn `actions` list (tool calls,
triaged into keep-line / collapsed runs / dropped), and a `marker` for the
context-compaction boundary. See each module's docstring for the tiering rules.
`clean_claude_session.py` adds a `subagent` role (kept agent reports) and
`[decision]` user lines (AskUserQuestion answers). `clean_codex_rollout.py` adds
an `originator` field (`codex-tui` | `Codex Desktop` | …) since the Codex CLI and
Desktop share one session store. Codex runs each subagent as its own rollout
file, so the parent always gets a `spawned subagent: <path> — thread <id>` line;
with `--with-subagents` each child is resolved by its thread id (under
`$CODEX_HOME/sessions`) and its final report is inlined as a `subagent` message.

## Source files

macOS / Linux:
  - Claude Code: `~/.claude/projects/<cwd-slug>/<uuid>.jsonl`
  - Codex CLI & Desktop: `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` (both surfaces share this store)

Windows:
  - Claude Code: `%USERPROFILE%\.claude\projects\<cwd-slug>\<uuid>.jsonl`
  - Codex CLI & Desktop: `%USERPROFILE%\.codex\sessions\YYYY\MM\DD\rollout-*.jsonl`

Override defaults with `CLAUDE_CONFIG_DIR` or `CODEX_HOME`.

Python 3.9+, stdlib only. HTML viewer loads marked, highlight.js, mermaid, svg-pan-zoom from CDN.
