import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "render_conversation_html.py"


def run_script(src: Path, dst: Path = None) -> None:
    cmd = [sys.executable, str(SCRIPT), str(src)]
    if dst is not None:
        cmd.append(str(dst))
    subprocess.run(cmd, capture_output=True, text=True, check=True)


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_writes_html_at_default_path(tmp_path: Path) -> None:
    src = tmp_path / "conv.json"
    write_json(src, {"source": "test.jsonl", "messages": [{"role": "user", "text": "hi"}]})
    run_script(src)
    assert (tmp_path / "conv.html").exists()


def test_writes_html_at_explicit_path(tmp_path: Path) -> None:
    src = tmp_path / "in.json"
    dst = tmp_path / "out.html"
    write_json(src, {"source": "x.jsonl", "messages": []})
    run_script(src, dst)
    assert dst.exists()


def test_html_contains_source_and_count(tmp_path: Path) -> None:
    src = tmp_path / "conv.json"
    dst = tmp_path / "conv.html"
    write_json(src, {
        "source": "my-session.jsonl",
        "messages": [
            {"role": "user", "text": "q"},
            {"role": "assistant", "text": "a"},
        ],
    })
    run_script(src, dst)
    html = dst.read_text(encoding="utf-8")
    assert "<title>Conversation — my-session.jsonl</title>" in html
    assert "<code>my-session.jsonl</code>" in html
    assert "2 messages" in html


def test_data_embedded_as_json(tmp_path: Path) -> None:
    src = tmp_path / "conv.json"
    dst = tmp_path / "conv.html"
    write_json(src, {
        "source": "x.jsonl",
        "messages": [{"role": "user", "text": "unique-marker-xyz"}],
    })
    run_script(src, dst)
    html = dst.read_text(encoding="utf-8")
    assert 'id="data"' in html
    assert "unique-marker-xyz" in html


def test_script_close_tag_escaped(tmp_path: Path) -> None:
    src = tmp_path / "conv.json"
    dst = tmp_path / "conv.html"
    write_json(src, {
        "source": "x.jsonl",
        "messages": [{"role": "user", "text": "before </script> after"}],
    })
    run_script(src, dst)
    html = dst.read_text(encoding="utf-8")
    data_start = html.index('id="data"')
    data_end = html.index("</script>", data_start)
    data_block = html[data_start:data_end]
    assert "</script>" not in data_block
    assert "<\\/script>" in data_block


def test_html_structure(tmp_path: Path) -> None:
    src = tmp_path / "conv.json"
    dst = tmp_path / "conv.html"
    write_json(src, {"source": "x.jsonl", "messages": []})
    run_script(src, dst)
    html = dst.read_text(encoding="utf-8")
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert "<title>" in html
    assert "</html>" in html


def test_marker_role_branch_present(tmp_path: Path) -> None:
    src = tmp_path / "conv.json"
    dst = tmp_path / "conv.html"
    write_json(src, {
        "source": "x.jsonl",
        "messages": [
            {"role": "user", "text": "before"},
            {"role": "marker", "text": "Context compacted here."},
            {"role": "user", "text": "after"},
        ],
    })
    run_script(src, dst)
    html = dst.read_text(encoding="utf-8")
    assert "Context compacted here." in html
    assert "'marker'" in html
    assert "3 messages" in html


def test_cdn_libraries_loaded(tmp_path: Path) -> None:
    src = tmp_path / "conv.json"
    dst = tmp_path / "conv.html"
    write_json(src, {"source": "x.jsonl", "messages": []})
    run_script(src, dst)
    html = dst.read_text(encoding="utf-8")
    assert "cdn.jsdelivr.net/npm/marked" in html
    assert "cdn-release" in html and "highlight.min.js" in html
    assert "cdn.jsdelivr.net/npm/mermaid" in html
    assert "cdn.jsdelivr.net/npm/svg-pan-zoom" in html


def test_unicode_in_message_preserved(tmp_path: Path) -> None:
    src = tmp_path / "conv.json"
    dst = tmp_path / "conv.html"
    write_json(src, {
        "source": "x.jsonl",
        "messages": [{"role": "user", "text": "مرحبا 👋 héllo"}],
    })
    run_script(src, dst)
    html = dst.read_text(encoding="utf-8")
    assert "مرحبا 👋 héllo" in html
