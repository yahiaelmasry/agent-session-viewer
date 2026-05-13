import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "clean_codex_rollout.py"


def run_script(src: Path, dst: Path) -> None:
    subprocess.run(
        [sys.executable, str(SCRIPT), str(src), str(dst)],
        capture_output=True, text=True, check=True,
    )


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")


def response_message(role: str, text: str, kind: str = "input_text") -> dict:
    return {
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": role,
            "content": [{"type": kind, "text": text}],
        },
    }


def test_user_and_assistant_kept(tmp_path: Path) -> None:
    src = tmp_path / "in.jsonl"
    dst = tmp_path / "out.json"
    write_jsonl(src, [
        response_message("user", "hello", "input_text"),
        response_message("assistant", "hi", "output_text"),
    ])
    run_script(src, dst)
    data = json.loads(dst.read_text())
    assert data["messages"] == [
        {"role": "user", "text": "hello"},
        {"role": "assistant", "text": "hi"},
    ]


def test_non_message_response_items_dropped(tmp_path: Path) -> None:
    src = tmp_path / "in.jsonl"
    dst = tmp_path / "out.json"
    write_jsonl(src, [
        {"type": "response_item", "payload": {"type": "reasoning", "summary": "thinking"}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "x"}},
        {"type": "response_item", "payload": {"type": "function_call_output", "output": "y"}},
        response_message("user", "kept"),
    ])
    run_script(src, dst)
    data = json.loads(dst.read_text())
    assert data["messages"] == [{"role": "user", "text": "kept"}]


def test_session_meta_and_turn_context_dropped(tmp_path: Path) -> None:
    src = tmp_path / "in.jsonl"
    dst = tmp_path / "out.json"
    write_jsonl(src, [
        {"type": "session_meta", "payload": {"id": "abc"}},
        {"type": "turn_context", "payload": {"turn": 1}},
        response_message("user", "kept"),
    ])
    run_script(src, dst)
    data = json.loads(dst.read_text())
    assert data["messages"] == [{"role": "user", "text": "kept"}]


def test_context_compacted_emits_marker(tmp_path: Path) -> None:
    src = tmp_path / "in.jsonl"
    dst = tmp_path / "out.json"
    write_jsonl(src, [
        response_message("user", "before"),
        {"type": "event_msg", "payload": {"type": "context_compacted"}},
        response_message("user", "after"),
    ])
    run_script(src, dst)
    data = json.loads(dst.read_text())
    assert data["messages"] == [
        {"role": "user", "text": "before"},
        {
            "role": "marker",
            "text": "Context compacted here. Conversation continues below with fresh context (Codex auto-summarized the prior history).",
        },
        {"role": "user", "text": "after"},
    ]


def test_first_environment_context_dropped(tmp_path: Path) -> None:
    src = tmp_path / "in.jsonl"
    dst = tmp_path / "out.json"
    write_jsonl(src, [
        response_message("user", "<environment_context>cwd: /foo</environment_context>"),
        response_message("user", "real prompt"),
        response_message("user", "<environment_context>another</environment_context>"),
    ])
    run_script(src, dst)
    data = json.loads(dst.read_text())
    texts = [m["text"] for m in data["messages"]]
    assert texts[0] == "real prompt"
    assert texts[1].startswith("<environment_context>")


def test_first_permissions_instructions_dropped(tmp_path: Path) -> None:
    src = tmp_path / "in.jsonl"
    dst = tmp_path / "out.json"
    write_jsonl(src, [
        response_message("user", "<permissions instructions>read-only mode"),
        response_message("user", "real prompt"),
    ])
    run_script(src, dst)
    data = json.loads(dst.read_text())
    assert data["messages"] == [{"role": "user", "text": "real prompt"}]


def test_malformed_line_skipped(tmp_path: Path) -> None:
    src = tmp_path / "in.jsonl"
    dst = tmp_path / "out.json"
    src.write_text(
        json.dumps(response_message("user", "first")) + "\n"
        "garbage line\n"
        + json.dumps(response_message("user", "second")) + "\n",
        encoding="utf-8",
    )
    run_script(src, dst)
    data = json.loads(dst.read_text())
    assert [m["text"] for m in data["messages"]] == ["first", "second"]


def test_multiple_text_blocks_concatenated(tmp_path: Path) -> None:
    src = tmp_path / "in.jsonl"
    dst = tmp_path / "out.json"
    write_jsonl(src, [
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "part 1"},
                    {"type": "output_text", "text": "part 2"},
                ],
            },
        },
    ])
    run_script(src, dst)
    data = json.loads(dst.read_text())
    assert data["messages"] == [{"role": "assistant", "text": "part 1\npart 2"}]


def test_empty_content_skipped(tmp_path: Path) -> None:
    src = tmp_path / "in.jsonl"
    dst = tmp_path / "out.json"
    write_jsonl(src, [
        {
            "type": "response_item",
            "payload": {"type": "message", "role": "user", "content": []},
        },
        response_message("user", "kept"),
    ])
    run_script(src, dst)
    data = json.loads(dst.read_text())
    assert data["messages"] == [{"role": "user", "text": "kept"}]


def test_unicode_text_preserved(tmp_path: Path) -> None:
    src = tmp_path / "in.jsonl"
    dst = tmp_path / "out.json"
    write_jsonl(src, [response_message("user", "مرحبا 👋 héllo")])
    run_script(src, dst)
    data = json.loads(dst.read_text(encoding="utf-8"))
    assert data["messages"] == [{"role": "user", "text": "مرحبا 👋 héllo"}]


def test_empty_input_file(tmp_path: Path) -> None:
    src = tmp_path / "empty.jsonl"
    dst = tmp_path / "out.json"
    src.write_text("", encoding="utf-8")
    run_script(src, dst)
    data = json.loads(dst.read_text())
    assert data == {"source": "empty.jsonl", "messages": []}


def test_output_schema(tmp_path: Path) -> None:
    src = tmp_path / "rollout.jsonl"
    dst = tmp_path / "out.json"
    write_jsonl(src, [response_message("user", "hi")])
    run_script(src, dst)
    data = json.loads(dst.read_text())
    assert data["source"] == "rollout.jsonl"
    assert isinstance(data["messages"], list)
    assert set(data.keys()) == {"source", "messages"}
