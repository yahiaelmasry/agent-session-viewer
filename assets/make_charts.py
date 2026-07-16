#!/usr/bin/env python3
"""Regenerate the README charts (composition.svg, reduction.svg).

Numbers are baked in from a measured run of the distillers over the author's own
session stores (see the block below); this keeps the generator stdlib-only and
free of any dependency on private session data. To refresh them, re-run
analyze.py / analyze_codex.py and paste the aggregates here.

Charts are self-contained SVGs with their own dark panel so they render the same
on GitHub's light and dark themes (no external fonts, no scripts, no CSS media
queries — GitHub sanitizes those out of <img>-embedded SVG).

Methodology: token counts use the o200k_base proxy tokenizer; the ratio is the
point. Codex reduction is measured in bytes over the whole store (exact) and
cross-checked in tokens on a seeded sample.
"""
from __future__ import annotations
from pathlib import Path

# --- measured aggregates -------------------------------------------------
CLAUDE = dict(
    label="Claude Code", scope="400 of 2,065 sessions",
    raw="67.4M tokens", dist="1.30M tokens", reduction=98.06, kept_median=5.56,
    # composition buckets as % of raw tokens (sum ~100)
    buckets=[("Conversation", 1.68), ("Tool I/O", 32.13),
             ("Telemetry & snapshots", 9.43), ("JSON envelope", 56.75)],
)
CODEX = dict(
    label="Codex (CLI + Desktop)", scope="all 200 sessions",
    raw="5.6 GB", dist="5.2 MB", reduction=99.91, kept_median=0.26,
    buckets=[("Conversation", 0.05), ("Tool I/O & event echoes", 63.24),
             ("Telemetry & snapshots", 24.57), ("JSON envelope", 12.15)],
)
SUBAGENTS = (1138, 1138, 102)  # spawn events, resolved, distinct children

# category -> colour (GitHub-neutral: legible on both #fff and #0d1117 panels)
COL = {
    "Conversation": "#3fb950", "Conversation & reasoning": "#3fb950",
    "Tool I/O": "#58a6ff", "Tool I/O & event echoes": "#58a6ff",
    "Telemetry & snapshots": "#d29922", "JSON envelope": "#6e7681",
}
BG, BORDER, TX, MUT, GREEN = "#0d1117", "#30363d", "#e6edf3", "#8b949e", "#3fb950"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Menlo,monospace"


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def panel(w: int, h: int, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'width="{w}" height="{h}" font-family="{FONT}" role="img">'
        f'<rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" rx="12" '
        f'fill="{BG}" stroke="{BORDER}"/>{body}</svg>\n'
    )


def stacked_bar(x, y, w, h, buckets, min_seg=3.0):
    """100%-stacked bar. The tiny leading (green) segment is floored to min_seg
    px so it stays visible; the distortion is <0.5% and the true % is labelled."""
    segs, cx = [], x
    total = sum(v for _, v in buckets) or 100.0
    raw_w = [w * v / total for _, v in buckets]
    # steal the min-width shortfall of segment 0 from the largest segment
    if raw_w[0] < min_seg:
        big = max(range(len(raw_w)), key=lambda i: raw_w[i])
        raw_w[big] -= (min_seg - raw_w[0]); raw_w[0] = min_seg
    for (name, val), ww in zip(buckets, raw_w):
        segs.append(f'<rect x="{cx:.1f}" y="{y}" width="{ww:.1f}" height="{h}" '
                    f'fill="{COL[name]}"><title>{esc(name)}: {val}%</title></rect>')
        # label % inside segment if it is wide enough
        if ww > 46:
            segs.append(f'<text x="{cx+ww/2:.1f}" y="{y+h/2+4}" text-anchor="middle" '
                        f'font-family="{MONO}" font-size="12" fill="#0d1117" '
                        f'font-weight="600">{val:g}%</text>')
        cx += ww
    return "".join(segs)


def composition_svg() -> str:
    W, H = 780, 372
    b = []
    b.append(f'<text x="28" y="42" font-size="20" font-weight="700" fill="{TX}">'
             f'Where the tokens go</text>')
    b.append(f'<text x="28" y="66" font-size="13.5" fill="{MUT}">'
             f'A raw agent session log is almost all machine scaffolding. '
             f'Green is what the distiller keeps.</text>')
    rows = [CLAUDE, CODEX]
    top = 104
    for i, d in enumerate(rows):
        ry = top + i * 118
        conv = d["buckets"][0][1]
        b.append(f'<text x="28" y="{ry-8}" font-size="15" font-weight="600" '
                 f'fill="{TX}">{esc(d["label"])}</text>')
        b.append(f'<text x="752" y="{ry-8}" text-anchor="end" font-size="12.5" '
                 f'font-family="{MONO}" fill="{MUT}">{d["raw"]} raw</text>')
        b.append(stacked_bar(28, ry, 724, 40, d["buckets"]))
        # green callout under the bar
        b.append(f'<circle cx="34" cy="{ry+70}" r="5" fill="{GREEN}"/>')
        b.append(f'<text x="46" y="{ry+74}" font-size="13" fill="{TX}">'
                 f'<tspan fill="{GREEN}" font-weight="700" font-family="{MONO}">'
                 f'{conv}%</tspan> is actual conversation — kept. '
                 f'The other <tspan font-family="{MONO}">{100-conv:.2f}%</tspan> '
                 f'is dropped or collapsed to one line.</text>')
    # legend
    ly = top + 2 * 118 - 6
    lx = 28
    for name in ["Conversation", "Tool I/O & event echoes", "Telemetry & snapshots", "JSON envelope"]:
        b.append(f'<rect x="{lx}" y="{ly-9}" width="11" height="11" rx="2" fill="{COL[name]}"/>')
        b.append(f'<text x="{lx+16}" y="{ly}" font-size="12" fill="{MUT}">{esc(name)}</text>')
        lx += 20 + len(name) * 7.1
    return panel(W, H, "".join(b))


def reduction_svg() -> str:
    W, H = 780, 216
    b = []
    b.append(f'<text x="28" y="42" font-size="20" font-weight="700" fill="{TX}">'
             f'You never paste the raw log</text>')
    b.append(f'<text x="28" y="66" font-size="13.5" fill="{MUT}">'
             f'Aggregate size before and after distillation.</text>')
    for i, d in enumerate((CLAUDE, CODEX)):
        cx = 28 + i * 376
        cw = 348
        b.append(f'<rect x="{cx}" y="92" width="{cw}" height="100" rx="10" '
                 f'fill="none" stroke="{BORDER}"/>')
        b.append(f'<text x="{cx+18}" y="120" font-size="13.5" font-weight="600" '
                 f'fill="{TX}">{esc(d["label"])} <tspan fill="{MUT}" '
                 f'font-weight="400">· {d["scope"]}</tspan></text>')
        b.append(f'<text x="{cx+18}" y="164" font-size="30" font-weight="800" '
                 f'font-family="{MONO}" fill="{GREEN}">{d["reduction"]:g}%</text>')
        b.append(f'<text x="{cx+18}" y="184" font-size="12.5" fill="{MUT}">'
                 f'smaller</text>')
        b.append(f'<text x="{cx+cw-18}" y="150" text-anchor="end" font-size="16" '
                 f'font-family="{MONO}" fill="{TX}">{d["raw"]}</text>')
        b.append(f'<text x="{cx+cw-18}" y="172" text-anchor="end" font-size="13" '
                 f'font-family="{MONO}" fill="{MUT}">&#8595; {d["dist"]}</text>')
    return panel(W, H, "".join(b))


def main():
    here = Path(__file__).parent
    (here / "composition.svg").write_text(composition_svg(), encoding="utf-8")
    (here / "reduction.svg").write_text(reduction_svg(), encoding="utf-8")
    # self-check: bucket %s are sane
    for d in (CLAUDE, CODEX):
        s = sum(v for _, v in d["buckets"])
        assert 99.0 <= s <= 101.0, f"{d['label']} buckets sum to {s}, expected ~100"
    print("wrote composition.svg, reduction.svg")


if __name__ == "__main__":
    main()
