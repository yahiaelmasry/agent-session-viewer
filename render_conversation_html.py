#!/usr/bin/env python3
"""Render a cleaned conversation JSON into a standalone HTML viewer.

Consumes the schema produced by `clean_claude_session.py` and
`clean_codex_rollout.py`:
    {
      "source": "<filename>",
      "messages": [
        {"role": "user" | "assistant" | "marker", "text": "..."},
        ...
      ]
    }

Output is a single HTML file with chat-style layout. Markdown in message
bodies (tables, code blocks, lists, links) is rendered client-side via
marked.js + highlight.js loaded from a CDN. Open in any browser.

Usage: render_conversation_html.py SRC.json [DST.html]
"""
import json
import re
import sys
from pathlib import Path

SRC = Path(sys.argv[1])
DST = Path(sys.argv[2]) if len(sys.argv) > 2 else SRC.with_suffix(".html")


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Conversation — {title}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/styles/github.min.css">
<script src="https://cdn.jsdelivr.net/npm/marked@12.0.0/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/highlight.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.2/dist/svg-pan-zoom.min.js"></script>
<style>
  :root {{
    --bg: #f6f7f9;
    --card: #ffffff;
    --border: #e3e5e8;
    --text: #1f2328;
    --muted: #656d76;
    --user-tint: #eef4ff;
    --user-bar: #4a73d6;
    --assistant-tint: #ffffff;
    --assistant-bar: #6d6d6d;
    --marker-bg: #fff7e6;
    --marker-bar: #d49b00;
    --code-bg: #f3f4f6;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0d1117;
      --card: #161b22;
      --border: #30363d;
      --text: #e6edf3;
      --muted: #8b949e;
      --user-tint: #1a2740;
      --user-bar: #6087e5;
      --assistant-tint: #161b22;
      --assistant-bar: #8b949e;
      --marker-bg: #2a2210;
      --marker-bar: #d49b00;
      --code-bg: #0d1117;
    }}
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: var(--bg); color: var(--text); }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 15px;
    line-height: 1.55;
  }}
  header {{
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
    background: var(--card);
    position: sticky;
    top: 0;
    z-index: 10;
  }}
  header h1 {{ margin: 0; font-size: 16px; font-weight: 600; }}
  header .meta {{ margin-top: 4px; color: var(--muted); font-size: 13px; }}
  main {{ max-width: 1300px; margin: 0 auto; padding: 12px 8px 60px; }}
  .msg {{
    background: var(--card);
    border: 1px solid var(--border);
    border-left: 3px solid var(--assistant-bar);
    border-radius: 6px;
    margin: 0 0 14px;
    padding: 14px 18px;
  }}
  .msg.user {{ border-left-color: var(--user-bar); background: var(--user-tint); }}
  .msg.assistant {{ border-left-color: var(--assistant-bar); background: var(--assistant-tint); }}
  .msg.marker {{
    background: var(--marker-bg);
    border-left-color: var(--marker-bar);
    color: var(--muted);
    font-style: italic;
    text-align: center;
    padding: 10px 18px;
  }}
  .role {{
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 0.06em;
    color: var(--muted);
    font-weight: 600;
    margin-bottom: 6px;
  }}
  .body {{ word-wrap: break-word; }}
  .body > *:first-child {{ margin-top: 0; }}
  .body > *:last-child {{ margin-bottom: 0; }}
  .body pre {{
    background: var(--code-bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 10px 12px;
    overflow-x: auto;
    font-size: 13px;
  }}
  .body code {{
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    background: var(--code-bg);
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 0.9em;
  }}
  .body pre code {{ background: transparent; padding: 0; border: 0; }}
  .body table {{
    border-collapse: collapse;
    margin: 12px 0;
    font-size: 14px;
  }}
  .body th, .body td {{
    border: 1px solid var(--border);
    padding: 6px 10px;
    text-align: left;
  }}
  .body th {{ background: var(--code-bg); font-weight: 600; }}
  .body blockquote {{
    border-left: 3px solid var(--border);
    color: var(--muted);
    margin: 8px 0;
    padding: 4px 12px;
  }}
  .body a {{ color: var(--user-bar); }}
  .body .mermaid-wrap {{
    position: relative;
    margin: 12px 0;
    cursor: zoom-in;
  }}
  .body .mermaid-wrap:hover .expand-btn {{ opacity: 1; }}
  .body .mermaid {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 12px;
    margin: 0;
    overflow: hidden;
    text-align: center;
  }}
  .body .mermaid svg {{
    display: block !important;
    margin: 0 auto !important;
    max-width: 100% !important;
    max-height: min(55vh, 480px) !important;
    width: auto !important;
    height: auto !important;
  }}
  .expand-btn {{
    position: absolute;
    top: 8px;
    right: 8px;
    background: var(--card);
    border: 1px solid var(--border);
    color: var(--text);
    border-radius: 4px;
    padding: 4px 10px;
    font-size: 12px;
    cursor: pointer;
    opacity: 0.85;
    z-index: 2;
  }}
  .expand-btn:hover {{ opacity: 1; }}
  .modal-backdrop {{
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.92);
    display: flex;
    flex-direction: column;
    z-index: 1000;
  }}
  .modal-toolbar {{
    display: flex;
    gap: 6px;
    padding: 8px 12px;
    background: var(--card);
    border-bottom: 1px solid var(--border);
    align-items: center;
    color: var(--text);
  }}
  .modal-toolbar button {{
    background: var(--code-bg);
    border: 1px solid var(--border);
    color: var(--text);
    border-radius: 4px;
    padding: 6px 12px;
    font-size: 13px;
    cursor: pointer;
    font-family: inherit;
  }}
  .modal-toolbar button:hover {{ background: var(--user-tint); }}
  .modal-toolbar .spacer {{ flex: 1; }}
  .modal-toolbar .hint {{ color: var(--muted); font-size: 12px; }}
  .modal-svg-container {{
    flex: 1;
    overflow: hidden;
    background: var(--bg);
  }}
  .modal-svg-container svg {{ width: 100%; height: 100%; display: block; }}
  .empty {{ color: var(--muted); font-style: italic; }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <div class="meta">{count} messages · source: <code>{source}</code></div>
</header>
<main id="root"></main>
<script id="data" type="application/json">{data}</script>
<script>
  const data = JSON.parse(document.getElementById('data').textContent);
  const isDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  mermaid.initialize({{ startOnLoad: false, theme: isDark ? 'dark' : 'default', securityLevel: 'loose' }});
  marked.setOptions({{
    gfm: true,
    breaks: false,
    highlight: function(code, lang) {{
      if (lang === 'mermaid') return code;
      if (lang && hljs.getLanguage(lang)) {{
        try {{ return hljs.highlight(code, {{ language: lang }}).value; }} catch (e) {{}}
      }}
      try {{ return hljs.highlightAuto(code).value; }} catch (e) {{}}
      return code;
    }}
  }});
  const root = document.getElementById('root');
  for (const m of data.messages) {{
    const el = document.createElement('div');
    el.className = 'msg ' + m.role;
    if (m.role === 'marker') {{
      el.textContent = m.text;
    }} else {{
      const role = document.createElement('div');
      role.className = 'role';
      role.textContent = m.role;
      const body = document.createElement('div');
      body.className = 'body';
      body.innerHTML = marked.parse(m.text || '');
      body.querySelectorAll('pre code.language-mermaid').forEach((codeEl) => {{
        const pre = codeEl.parentElement;
        const div = document.createElement('div');
        div.className = 'mermaid';
        div.textContent = codeEl.textContent;
        pre.replaceWith(div);
      }});
      el.appendChild(role);
      el.appendChild(body);
    }}
    root.appendChild(el);
  }}
  document.querySelectorAll('pre code').forEach((b) => {{ try {{ hljs.highlightElement(b); }} catch (e) {{}} }});

  function wrapMermaid(div) {{
    if (div.parentElement && div.parentElement.classList.contains('mermaid-wrap')) return;
    const wrap = document.createElement('div');
    wrap.className = 'mermaid-wrap';
    wrap.title = 'Click to expand';
    div.parentElement.insertBefore(wrap, div);
    wrap.appendChild(div);
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'expand-btn';
    btn.textContent = '⛶ Expand';
    wrap.appendChild(btn);
    wrap.addEventListener('click', (e) => {{
      e.preventDefault();
      openModal(div);
    }});
  }}

  function openModal(sourceDiv) {{
    const svg = sourceDiv.querySelector('svg');
    if (!svg) return;
    const clone = svg.cloneNode(true);
    clone.removeAttribute('style');
    clone.style.width = '100%';
    clone.style.height = '100%';
    clone.style.maxWidth = 'none';
    clone.style.maxHeight = 'none';

    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';

    const toolbar = document.createElement('div');
    toolbar.className = 'modal-toolbar';

    const container = document.createElement('div');
    container.className = 'modal-svg-container';
    container.appendChild(clone);

    backdrop.appendChild(toolbar);
    backdrop.appendChild(container);
    document.body.appendChild(backdrop);

    let pz = null;
    try {{
      pz = svgPanZoom(clone, {{
        zoomEnabled: true,
        panEnabled: true,
        controlIconsEnabled: false,
        dblClickZoomEnabled: false,
        mouseWheelZoomEnabled: true,
        preventMouseEventsDefault: true,
        fit: true,
        center: true,
        minZoom: 0.1,
        maxZoom: 30,
      }});
    }} catch (e) {{ console.warn('svg-pan-zoom init failed', e); }}

    const mk = (label, fn, title) => {{
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = label;
      if (title) b.title = title;
      b.addEventListener('click', fn);
      return b;
    }};
    toolbar.appendChild(mk('−', () => pz && pz.zoomOut(), 'Zoom out'));
    toolbar.appendChild(mk('+', () => pz && pz.zoomIn(), 'Zoom in'));
    toolbar.appendChild(mk('Fit', () => {{ if (pz) {{ pz.resize(); pz.fit(); pz.center(); }} }}, 'Fit to view'));
    toolbar.appendChild(mk('1:1', () => pz && pz.reset(), 'Reset zoom and pan'));
    const hint = document.createElement('span');
    hint.className = 'hint';
    hint.textContent = 'Drag to pan · scroll to zoom · Esc to close';
    toolbar.appendChild(hint);
    const spacer = document.createElement('div');
    spacer.className = 'spacer';
    toolbar.appendChild(spacer);
    toolbar.appendChild(mk('Close ✕', close, 'Close (Esc)'));

    function close() {{
      if (pz) {{ try {{ pz.destroy(); }} catch (e) {{}} }}
      if (backdrop.parentElement) backdrop.parentElement.removeChild(backdrop);
      document.removeEventListener('keydown', onKey);
    }}
    function onKey(e) {{ if (e.key === 'Escape') close(); }}
    document.addEventListener('keydown', onKey);
    backdrop.addEventListener('click', (e) => {{ if (e.target === backdrop) close(); }});
  }}

  if (document.querySelector('.mermaid')) {{
    Promise.resolve()
      .then(() => mermaid.run({{ querySelector: '.mermaid' }}))
      .then(() => {{ document.querySelectorAll('.mermaid').forEach(wrapMermaid); }})
      .catch((e) => console.warn('mermaid render failed', e));
  }}
</script>
</body>
</html>
"""


def main() -> None:
    raw = SRC.read_text(encoding="utf-8")
    data = json.loads(raw)

    source = data.get("source", SRC.name)
    messages = data.get("messages", [])
    title = source

    # Embed JSON safely inside a <script type="application/json"> block.
    # The only escape we need is </script> -> <\/script>; JSON itself can't
    # contain raw </script> but message text certainly can.
    safe = json.dumps(data, ensure_ascii=False)
    safe = re.sub(r"</(script)", r"<\\/\1", safe, flags=re.IGNORECASE)

    html = HTML_TEMPLATE.format(
        title=title,
        source=source,
        count=len(messages),
        data=safe,
    )
    DST.write_text(html, encoding="utf-8")
    print(f"Wrote {DST} ({DST.stat().st_size:,} bytes, {len(messages)} messages)")


if __name__ == "__main__":
    main()
