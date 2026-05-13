# agent-session-viewer

Export Claude Code or Codex CLI session logs to clean JSON, then to a standalone HTML viewer.

## Usage

```bash
python clean_claude_session.py SRC.jsonl DST.json     # CC session → JSON
python clean_codex_rollout.py  SRC.jsonl DST.json     # Codex rollout → JSON
python render_conversation_html.py SRC.json [DST.html] # JSON → HTML
```

Both extractors emit `{source, messages: [{role, text}]}` (`role`: `user` | `assistant` | `marker`).

## Source files

macOS / Linux:
  - Claude Code: `~/.claude/projects/<cwd-slug>/<uuid>.jsonl`
  - Codex CLI: `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`

Windows:
  - Claude Code: `%USERPROFILE%\.claude\projects\<cwd-slug>\<uuid>.jsonl`
  - Codex CLI: `%USERPROFILE%\.codex\sessions\YYYY\MM\DD\rollout-*.jsonl`

Override defaults with `CLAUDE_CONFIG_DIR` or `CODEX_HOME`.

Python 3.9+, stdlib only. HTML viewer loads marked, highlight.js, mermaid, svg-pan-zoom from CDN.
