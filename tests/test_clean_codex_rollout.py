import json
import os
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


def run(tmp_path: Path, records: list[dict]) -> dict:
    src, dst = tmp_path / "in.jsonl", tmp_path / "out.json"
    write_jsonl(src, records)
    run_script(src, dst)
    return json.loads(dst.read_text(encoding="utf-8"))


def response_message(role: str, text: str, kind: str = "input_text") -> dict:
    return {
        "type": "response_item",
        "payload": {"type": "message", "role": role, "content": [{"type": kind, "text": text}]},
    }


def resp(payload: dict) -> dict:
    return {"type": "response_item", "payload": payload}


def fcall(name: str, arguments, call_id: str = "c") -> dict:
    return resp({"type": "function_call", "name": name, "arguments": arguments, "call_id": call_id})


def ctcall(name: str, input_, call_id: str = "c") -> dict:
    return resp({"type": "custom_tool_call", "name": name, "input": input_, "call_id": call_id})


def foutput(call_id: str, output) -> dict:
    return resp({"type": "function_call_output", "call_id": call_id, "output": output})


# --- prose ---------------------------------------------------------------

def test_user_and_assistant_kept(tmp_path: Path) -> None:
    data = run(tmp_path, [
        response_message("user", "hello", "input_text"),
        response_message("assistant", "hi", "output_text"),
    ])
    assert data["messages"] == [
        {"role": "user", "text": "hello"},
        {"role": "assistant", "text": "hi"},
    ]


def test_developer_role_dropped(tmp_path: Path) -> None:
    data = run(tmp_path, [
        response_message("developer", "<permissions instructions>read-only"),
        response_message("user", "kept"),
    ])
    assert data["messages"] == [{"role": "user", "text": "kept"}]


def test_reasoning_and_outputs_dropped(tmp_path: Path) -> None:
    data = run(tmp_path, [
        resp({"type": "reasoning", "summary": "thinking"}),
        foutput("c1", "some output"),
        resp({"type": "custom_tool_call_output", "call_id": "c2", "output": "x"}),
        response_message("user", "kept"),
    ])
    assert data["messages"] == [{"role": "user", "text": "kept"}]


def test_multiple_text_blocks_concatenated(tmp_path: Path) -> None:
    data = run(tmp_path, [resp({
        "type": "message", "role": "assistant",
        "content": [{"type": "output_text", "text": "part 1"}, {"type": "output_text", "text": "part 2"}],
    })])
    assert data["messages"] == [{"role": "assistant", "text": "part 1\npart 2"}]


def test_empty_content_skipped(tmp_path: Path) -> None:
    data = run(tmp_path, [
        resp({"type": "message", "role": "user", "content": []}),
        response_message("user", "kept"),
    ])
    assert data["messages"] == [{"role": "user", "text": "kept"}]


# --- tool tiers ----------------------------------------------------------

def test_unknown_tool_kept_as_line(tmp_path: Path) -> None:
    data = run(tmp_path, [fcall("mystery_tool", json.dumps({"query": "q"}))])
    assert data["messages"] == [{"role": "assistant", "actions": ["mystery_tool: q"]}]


def test_apply_patch_line(tmp_path: Path) -> None:
    patch = "*** Begin Patch\n*** Update File: /repo/app.py\n@@\n+print(1)\n*** End Patch"
    data = run(tmp_path, [ctcall("apply_patch", patch)])
    assert data["messages"] == [{"role": "assistant", "actions": ["apply_patch /repo/app.py"]}]


def test_readonly_exec_collapses(tmp_path: Path) -> None:
    data = run(tmp_path, [
        response_message("user", "look around"),
        fcall("exec_command", json.dumps({"cmd": "ls -la"}), "a"),
        foutput("a", "Process exited with code 0\nfiles"),
        fcall("exec_command", json.dumps({"cmd": "cat foo"}), "b"),
        fcall("exec_command", json.dumps({"cmd": "rg needle"}), "d"),
        response_message("assistant", "done"),
    ])
    assert data["messages"] == [
        {"role": "user", "text": "look around"},
        {"role": "assistant", "actions": ["exec(ro) ×3"]},
        {"role": "assistant", "text": "done"},
    ]


def test_mutating_exec_is_line(tmp_path: Path) -> None:
    data = run(tmp_path, [fcall("exec_command", json.dumps({"cmd": "rm -rf build"}))])
    assert data["messages"] == [{"role": "assistant", "actions": ["$ rm -rf build"]}]


def test_exec_custom_tool_extracts_cmd(tmp_path: Path) -> None:
    js = 'const r = await tools.exec_command({"cmd":"npm install","max_output_tokens":20000});\ntext(r.output);\n'
    data = run(tmp_path, [ctcall("exec", js)])
    assert data["messages"] == [{"role": "assistant", "actions": ["$ npm install"]}]


def test_git_status_collapses_through_dash_c(tmp_path: Path) -> None:
    # `git -C <path> status` is read-only -> a single collapse item keeps its
    # full label (count == 1); it only shows as "exec(ro) ×N" when it repeats.
    data = run(tmp_path, [fcall("exec_command", json.dumps({"cmd": "git -C '/some/repo' status"}))])
    assert data["messages"] == [{"role": "assistant", "actions": ["$ git -C '/some/repo' status"]}]


def test_web_search_line(tmp_path: Path) -> None:
    data = run(tmp_path, [resp({
        "type": "web_search_call", "status": "completed",
        "action": {"type": "open_page", "url": "https://example.com"},
    })])
    assert data["messages"] == [{"role": "assistant", "actions": ["web_search: https://example.com"]}]


def test_orchestration_tools_dropped(tmp_path: Path) -> None:
    data = run(tmp_path, [
        fcall("spawn_agent", json.dumps({"task_name": "luna"}), "a"),
        fcall("wait_agent", json.dumps({"timeout_ms": 1000}), "b"),
        fcall("send_message", json.dumps({"target": "/root/x"}), "d"),
        fcall("update_plan", json.dumps({"plan": []}), "e"),
        response_message("user", "kept"),
    ])
    assert data["messages"] == [{"role": "user", "text": "kept"}]


def test_failed_command_annotated(tmp_path: Path) -> None:
    data = run(tmp_path, [
        fcall("exec_command", json.dumps({"cmd": "rm nope"}), "c1"),
        foutput("c1", "Process exited with code 1\nrm: nope: No such file"),
    ])
    assert data["messages"] == [{"role": "assistant", "actions": ["$ rm nope  → error"]}]


def test_custom_output_exit_code_annotated(tmp_path: Path) -> None:
    bad = json.dumps({"output": "boom", "metadata": {"exit_code": 2}})
    data = run(tmp_path, [
        fcall("exec_command", json.dumps({"cmd": "make"}), "c1"),
        resp({"type": "custom_tool_call_output", "call_id": "c1", "output": bad}),
    ])
    assert data["messages"] == [{"role": "assistant", "actions": ["$ make  → error"]}]


def test_collapse_run_breaks_on_prose(tmp_path: Path) -> None:
    data = run(tmp_path, [
        fcall("exec_command", json.dumps({"cmd": "ls"}), "a"),
        fcall("exec_command", json.dumps({"cmd": "cat x"}), "b"),
        response_message("assistant", "interjection"),
        fcall("exec_command", json.dumps({"cmd": "rg y"}), "d"),
    ])
    assert data["messages"] == [
        {"role": "assistant", "actions": ["exec(ro) ×2"]},
        {"role": "assistant", "text": "interjection"},
        {"role": "assistant", "actions": ["$ rg y"]},
    ]


# --- subagents (tier A: spawn lines, tier B: inlined reports) ------------

def sub_activity(agent_path: str, thread_id: str, kind: str = "started") -> dict:
    return {"type": "event_msg", "payload": {
        "type": "sub_agent_activity", "kind": kind,
        "agent_path": agent_path, "agent_thread_id": thread_id,
    }}


def test_spawn_line_emitted(tmp_path: Path) -> None:
    # default (no --with-subagents): a spawn line, no inlined report.
    data = run(tmp_path, [
        response_message("user", "delegate this"),
        sub_activity("/root/luna", "t1", "started"),
        sub_activity("/root/luna", "t1", "interacted"),  # only "started" emits
    ])
    assert data["messages"] == [
        {"role": "user", "text": "delegate this"},
        {"role": "assistant", "actions": ["spawned subagent: luna — thread t1"]},
    ]
    assert not any(m["role"] == "subagent" for m in data["messages"])


def test_spawn_line_shows_nesting(tmp_path: Path) -> None:
    data = run(tmp_path, [sub_activity("/root/triage_790/review_standards", "t9")])
    assert data["messages"] == [
        {"role": "assistant", "actions": ["spawned subagent: triage_790/review_standards — thread t9"]},
    ]


def test_inline_subagent_report(tmp_path: Path) -> None:
    home = tmp_path / "codexhome"
    sess = home / "sessions" / "2026" / "07" / "16"
    sess.mkdir(parents=True)
    write_jsonl(sess / "rollout-child.jsonl", [
        {"type": "session_meta", "payload": {"id": "tid-1", "originator": "codex-tui"}},
        response_message("assistant", "early chatter", "output_text"),
        {"type": "response_item", "payload": {"type": "reasoning", "summary": "x"}},
        response_message("assistant", "FINAL CHILD REPORT", "output_text"),
    ])
    parent, dst = tmp_path / "parent.jsonl", tmp_path / "out.json"
    write_jsonl(parent, [
        response_message("user", "do it"),
        sub_activity("/root/luna", "tid-1", "started"),
    ])
    env = {**os.environ, "CODEX_HOME": str(home)}
    subprocess.run(
        [sys.executable, str(SCRIPT), str(parent), str(dst), "--with-subagents"],
        env=env, capture_output=True, text=True, check=True,
    )
    data = json.loads(dst.read_text(encoding="utf-8"))
    assert data["messages"] == [
        {"role": "user", "text": "do it"},
        {"role": "assistant", "actions": ["spawned subagent: luna — thread tid-1"]},
        {"role": "subagent", "name": "luna", "text": "FINAL CHILD REPORT"},
    ]


def test_inline_skips_when_child_missing(tmp_path: Path) -> None:
    # --with-subagents on, but the thread id resolves to nothing -> spawn line only.
    home = tmp_path / "codexhome"
    (home / "sessions").mkdir(parents=True)
    parent, dst = tmp_path / "parent.jsonl", tmp_path / "out.json"
    write_jsonl(parent, [sub_activity("/root/ghost", "nope", "started")])
    env = {**os.environ, "CODEX_HOME": str(home)}
    subprocess.run(
        [sys.executable, str(SCRIPT), str(parent), str(dst), "--with-subagents"],
        env=env, capture_output=True, text=True, check=True,
    )
    data = json.loads(dst.read_text(encoding="utf-8"))
    assert data["messages"] == [
        {"role": "assistant", "actions": ["spawned subagent: ghost — thread nope"]},
    ]


# --- session structure ---------------------------------------------------

def test_originator_surfaced(tmp_path: Path) -> None:
    data = run(tmp_path, [
        {"type": "session_meta", "payload": {"id": "abc", "originator": "Codex Desktop"}},
        response_message("user", "hi"),
    ])
    assert data["originator"] == "Codex Desktop"
    assert data["messages"] == [{"role": "user", "text": "hi"}]


def test_session_meta_and_turn_context_dropped(tmp_path: Path) -> None:
    data = run(tmp_path, [
        {"type": "session_meta", "payload": {"id": "abc"}},
        {"type": "turn_context", "payload": {"turn": 1}},
        {"type": "world_state", "payload": {}},
        response_message("user", "kept"),
    ])
    assert data["messages"] == [{"role": "user", "text": "kept"}]
    assert "originator" not in data  # none present -> field omitted


def test_context_compacted_emits_marker(tmp_path: Path) -> None:
    data = run(tmp_path, [
        response_message("user", "before"),
        {"type": "event_msg", "payload": {"type": "context_compacted"}},
        response_message("user", "after"),
    ])
    assert data["messages"] == [
        {"role": "user", "text": "before"},
        {"role": "marker", "text": (
            "Context compacted here. Conversation continues below with fresh "
            "context (Codex auto-summarized the prior history).")},
        {"role": "user", "text": "after"},
    ]


def test_event_msg_telemetry_dropped(tmp_path: Path) -> None:
    data = run(tmp_path, [
        {"type": "event_msg", "payload": {"type": "token_count", "n": 5}},
        {"type": "event_msg", "payload": {"type": "agent_reasoning", "text": "hmm"}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "dupe"}},
        response_message("user", "kept"),
    ])
    assert data["messages"] == [{"role": "user", "text": "kept"}]


def test_all_environment_context_dropped(tmp_path: Path) -> None:
    # Codex re-injects these mid-stream, so every occurrence is dropped (not
    # just the first) — they are never user intent.
    data = run(tmp_path, [
        response_message("user", "<environment_context>cwd: /foo</environment_context>"),
        response_message("user", "real prompt"),
        response_message("user", "<environment_context>another</environment_context>"),
    ])
    assert data["messages"] == [{"role": "user", "text": "real prompt"}]


def test_harness_injected_user_boilerplate_dropped(tmp_path: Path) -> None:
    data = run(tmp_path, [
        response_message("user", "<permissions instructions>read-only mode"),
        response_message("user", "<in-app-browser-context>tab: github.com</in-app-browser-context>"),
        response_message("user", "<recommended_plugins>install foo</recommended_plugins>"),
        response_message("user", "<codex_internal_context>x</codex_internal_context>"),
        response_message("user", "The following is the Codex agent history added for context..."),
        response_message("user", "# AGENTS.md instructions for /Users/yehia/x"),
        response_message("user", "real prompt"),
    ])
    assert data["messages"] == [{"role": "user", "text": "real prompt"}]


# --- robustness ----------------------------------------------------------

def test_malformed_line_skipped(tmp_path: Path) -> None:
    src, dst = tmp_path / "in.jsonl", tmp_path / "out.json"
    src.write_text(
        json.dumps(response_message("user", "first")) + "\n"
        "garbage line\n"
        + json.dumps(response_message("user", "second")) + "\n",
        encoding="utf-8",
    )
    run_script(src, dst)
    data = json.loads(dst.read_text(encoding="utf-8"))
    assert [m["text"] for m in data["messages"]] == ["first", "second"]


def test_unicode_text_preserved(tmp_path: Path) -> None:
    data = run(tmp_path, [response_message("user", "مرحبا 👋 héllo")])
    assert data["messages"] == [{"role": "user", "text": "مرحبا 👋 héllo"}]


def test_reads_utf8_under_non_utf8_locale(tmp_path: Path) -> None:
    src, dst = tmp_path / "in.jsonl", tmp_path / "out.json"
    write_jsonl(src, [response_message("user", "مرحبا 👋 héllo")])
    env = {**os.environ, "PYTHONUTF8": "0", "LC_ALL": "C", "LANG": "C"}
    subprocess.run(
        [sys.executable, str(SCRIPT), str(src), str(dst)],
        env=env, capture_output=True, text=True, check=True,
    )
    data = json.loads(dst.read_text(encoding="utf-8"))
    assert data["messages"] == [{"role": "user", "text": "مرحبا 👋 héllo"}]


def test_empty_input_file(tmp_path: Path) -> None:
    src, dst = tmp_path / "empty.jsonl", tmp_path / "out.json"
    src.write_text("", encoding="utf-8")
    run_script(src, dst)
    data = json.loads(dst.read_text(encoding="utf-8"))
    assert data == {"source": "empty.jsonl", "messages": []}


def test_output_schema(tmp_path: Path) -> None:
    data = run(tmp_path, [response_message("user", "hi")])
    assert data["source"] == "in.jsonl"
    assert isinstance(data["messages"], list)
    assert set(data.keys()) == {"source", "messages"}
