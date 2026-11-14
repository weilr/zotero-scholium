"""Session accounting uses call identity, never token equality, to detect replays."""
import importlib.util
import json
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    "session_usage", Path(__file__).resolve().parents[1] / "scripts" / "session_usage.py")
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)


def read_rows(tmp_path, harness, rows):
    path = tmp_path / (harness + ".jsonl")
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf8")
    return getattr(usage, "read_" + harness)(path)


def claude_message(mid, tokens, content=None):
    return {"type": "assistant", "message": {"id": mid, "usage": tokens, "content": content or []}}


def codex_tokens(total=None, last=None, timestamp=None):
    return {"type": "event_msg", "timestamp": timestamp,
            "payload": {"type": "token_count", "info": {
                "total_token_usage": total, "last_token_usage": last}}}


def token_counts(inp, cached, output):
    return {"input_tokens": inp, "cached_input_tokens": cached, "output_tokens": output}


def test_claude_message_blocks_and_retransmission_count_one_call(tmp_path):
    tokens = {"input_tokens": 100, "cache_read_input_tokens": 900,
              "cache_creation_input_tokens": 100, "output_tokens": 20}
    rows = [claude_message("msg_one", tokens, [{"type": "thinking", "thinking": "thinking"}]),
            claude_message("msg_one", tokens, [{"type": "text", "text": "answer"}]),
            claude_message("msg_one", tokens)]
    result = read_rows(tmp_path, "claude", rows)
    assert (result["calls"], result["input"], result["cached"], result["output"], result["peak"]) == (1, 1100, 900, 20, 1100)


def test_claude_final_usage_updates_one_message_without_losing_missing_fields(tmp_path):
    rows = [claude_message("m1", {"input_tokens": 100, "cache_read_input_tokens": 50, "output_tokens": 4}),
            claude_message("m1", {"output_tokens": 12}),
            claude_message("m1", None),
            claude_message("m2", {"input_tokens": 100, "cache_read_input_tokens": 50, "output_tokens": 12})]
    result = read_rows(tmp_path, "claude", rows)
    assert (result["calls"], result["input"], result["cached"], result["output"], result["peak"]) == (2, 300, 100, 24, 150)


def test_claude_replayed_old_record_does_not_replace_final_usage(tmp_path):
    first = dict(claude_message("m1", {"input_tokens": 100, "output_tokens": 4}), uuid="first")
    final = dict(claude_message("m1", {"input_tokens": 100, "output_tokens": 12}), uuid="final")
    result = read_rows(tmp_path, "claude", [first, final, first])
    assert (result["calls"], result["input"], result["output"]) == (1, 100, 12)


def test_claude_tool_ids_deduplicate_calls_and_final_result_size(tmp_path):
    first = {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "paper.txt"}}
    second = dict(first, id="t2")
    result = {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "text"}]}}
    rows = [claude_message("m1", None, [first]), claude_message("m1", None, [first]),
            claude_message("m2", None, [second]), result, result,
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t2", "content": "text"}]}}]
    stats = read_rows(tmp_path, "claude", rows)
    assert stats["tools"] == {"read file": 2}
    assert stats["tool_output_chars"] == 8
    assert stats["calls"] == 0


def test_claude_legacy_no_ids_keep_equal_independent_calls(tmp_path):
    row = claude_message(None, {"input_tokens": 10, "output_tokens": 2},
                         [{"type": "tool_use", "name": "Read", "input": {}}])
    output = {"type": "user", "message": {"content": [{"type": "tool_result", "content": "abc"}]}}
    result = read_rows(tmp_path, "claude", [row, output, row, output])
    assert (result["calls"], result["input"], result["output"]) == (2, 20, 4)
    assert result["tools"] == {"read file": 2}
    assert result["tool_output_chars"] == 6


def test_codex_cumulative_repetition_does_not_hide_equal_independent_calls(tmp_path):
    last = token_counts(100, 60, 20)
    rows = [codex_tokens(last, last), codex_tokens(last, last),
            codex_tokens(token_counts(200, 120, 40), last),
            codex_tokens(token_counts(200, 120, 40), last)]
    result = read_rows(tmp_path, "codex", rows)
    assert (result["calls"], result["input"], result["cached"], result["output"], result["peak"]) == (2, 200, 120, 40, 100)


def test_codex_uses_cumulative_delta_when_last_is_stale_or_absent(tmp_path):
    rows = [codex_tokens(token_counts(100, 60, 20), token_counts(100, 60, 20)),
            codex_tokens(token_counts(250, 140, 50), token_counts(100, 60, 20)),
            codex_tokens(token_counts(450, 240, 90))]
    result = read_rows(tmp_path, "codex", rows)
    assert (result["calls"], result["input"], result["cached"], result["output"], result["peak"]) == (3, 450, 240, 90, 200)


def test_codex_replayed_old_event_does_not_look_like_counter_reset(tmp_path):
    first = codex_tokens(token_counts(100, 60, 20), token_counts(100, 60, 20), "2026-11-11T00:00:00Z")
    second = codex_tokens(token_counts(250, 140, 50), token_counts(150, 80, 30), "2026-11-11T00:00:01Z")
    rows = [first, second, first, codex_tokens(token_counts(450, 240, 90), token_counts(200, 100, 40), "2026-11-11T00:00:02Z")]
    result = read_rows(tmp_path, "codex", rows)
    assert (result["calls"], result["input"], result["cached"], result["output"], result["peak"]) == (3, 450, 240, 90, 200)


def test_codex_reset_starts_new_cumulative_segment(tmp_path):
    rows = [codex_tokens(token_counts(100, 60, 20), token_counts(100, 60, 20)),
            codex_tokens(token_counts(250, 140, 50), token_counts(150, 80, 30)),
            codex_tokens(token_counts(40, 10, 5), token_counts(40, 10, 5)),
            codex_tokens(token_counts(40, 10, 5), token_counts(40, 10, 5)),
            codex_tokens(token_counts(100, 20, 10), token_counts(60, 10, 5))]
    result = read_rows(tmp_path, "codex", rows)
    assert (result["calls"], result["input"], result["cached"], result["output"], result["peak"]) == (4, 350, 160, 60, 150)


def test_codex_new_session_can_repeat_previous_totals(tmp_path):
    tokens = token_counts(100, 60, 20)
    meta = lambda sid: {"type": "session_meta", "payload": {"id": sid}}
    result = read_rows(tmp_path, "codex", [meta("s1"), codex_tokens(tokens, tokens),
                                           meta("s1"), codex_tokens(tokens, tokens),
                                           meta("s2"), codex_tokens(tokens, tokens)])
    assert (result["calls"], result["input"], result["output"]) == (2, 200, 40)


def test_codex_legacy_last_only_keeps_equal_calls_and_missing_fields(tmp_path):
    last = {"input_tokens": 100, "output_tokens": 20}
    rows = [codex_tokens(last=last), codex_tokens(last=last), codex_tokens(),
            codex_tokens(last={"output_tokens": 5})]
    result = read_rows(tmp_path, "codex", rows)
    assert (result["calls"], result["input"], result["cached"], result["output"], result["peak"]) == (3, 200, 0, 45, 100)


def test_codex_partial_counters_preserve_known_totals(tmp_path):
    rows = [codex_tokens(token_counts(100, 60, 20), token_counts(100, 60, 20)),
            codex_tokens({"input_tokens": 250}, token_counts(150, 80, 30)),
            codex_tokens(token_counts(450, 240, 90), token_counts(200, 100, 40))]
    result = read_rows(tmp_path, "codex", rows)
    assert (result["calls"], result["input"], result["cached"], result["output"]) == (3, 450, 240, 90)


@pytest.mark.parametrize("final_output", [20, None])
def test_codex_new_usage_fields_complete_the_existing_call(tmp_path, final_output):
    rows = [codex_tokens({"input_tokens": 100}, {"input_tokens": 100}),
            codex_tokens({"input_tokens": 100, "output_tokens": 20}, {"input_tokens": 100, "output_tokens": final_output}),
            codex_tokens(token_counts(100, 50, 20), token_counts(100, 50, 20))]
    result = read_rows(tmp_path, "codex", rows)
    assert (result["calls"], result["input"], result["cached"], result["output"]) == (1, 100, 50, 20)


def test_codex_missing_cumulative_field_is_not_counted_twice_when_it_appears(tmp_path):
    rows = [codex_tokens({"input_tokens": 100}, token_counts(100, 50, 20)),
            codex_tokens(token_counts(100, 50, 20), token_counts(100, 50, 20))]
    result = read_rows(tmp_path, "codex", rows)
    assert (result["calls"], result["input"], result["cached"], result["output"]) == (1, 100, 50, 20)


def test_codex_unchanged_cache_counter_does_not_hide_a_new_uncached_call(tmp_path):
    rows = [codex_tokens(token_counts(100, 0, 10), token_counts(100, 0, 10)),
            codex_tokens({"cached_input_tokens": 0}, token_counts(200, 0, 20))]
    result = read_rows(tmp_path, "codex", rows)
    assert (result["calls"], result["input"], result["cached"], result["output"], result["peak"]) == (2, 300, 0, 30, 200)


def test_codex_missing_total_between_cumulative_events_is_not_counted_twice(tmp_path):
    rows = [codex_tokens(token_counts(100, 60, 20), token_counts(100, 60, 20)),
            codex_tokens(last=token_counts(50, 20, 10)),
            codex_tokens(token_counts(200, 100, 40), token_counts(50, 20, 10))]
    result = read_rows(tmp_path, "codex", rows)
    assert (result["calls"], result["input"], result["cached"], result["output"], result["peak"]) == (3, 200, 100, 40, 100)


def test_codex_first_cumulative_event_uses_last_to_exclude_earlier_history(tmp_path):
    rows = [codex_tokens(token_counts(1000, 600, 200), token_counts(100, 60, 20)),
            codex_tokens(token_counts(1200, 700, 250), token_counts(200, 100, 50))]
    result = read_rows(tmp_path, "codex", rows)
    assert (result["calls"], result["input"], result["cached"], result["output"], result["peak"]) == (2, 300, 160, 70, 200)


def test_codex_tool_call_replay_counts_once(tmp_path):
    call = {"type": "response_item", "payload": {"type": "function_call", "name": "exec",
            "call_id": "c1", "arguments": json.dumps({"cmd": "cat paper.txt"})}}
    output = {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": "text"}}
    result = read_rows(tmp_path, "codex", [call, output, call, output])
    assert result["tools"] == {"read file": 1}
    assert result["tool_output_chars"] == 4


def test_codex_different_output_chunks_for_one_call_are_kept(tmp_path):
    call = {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
            "call_id": "c1", "input": "cat paper.txt"}}
    first = {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c1", "output": "first"}}
    second = {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c1", "output": "last"}}
    result = read_rows(tmp_path, "codex", [call, first, first, second, second])
    assert result["tools"] == {"read file": 1}
    assert result["tool_output_chars"] == 9


def test_codex_equal_output_chunks_with_distinct_event_ids_are_kept(tmp_path):
    call = {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "call_id": "c1", "input": "cat paper.txt"}}
    first = {"id": "o1", "type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c1", "output": "ok"}}
    second = dict(first, id="o2")
    result = read_rows(tmp_path, "codex", [call, first, second, first])
    assert result["tools"] == {"read file": 1}
    assert result["tool_output_chars"] == 4
