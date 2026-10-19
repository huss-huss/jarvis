"""Tool-call text parsing fallbacks."""

from jarvis.agent.orchestrator import _parse_text_tool_calls


def test_parse_standard_text_tool():
    text = '{"name":"get_running_apps","parameters":{}}'
    calls = _parse_text_tool_calls(text)
    assert len(calls) == 1
    assert calls[0].name == "get_running_apps"


def test_parse_malformed_function_dump():
    # Real llama dump that previously leaked into the chat UI
    text = '{"type":"function","name":"run_command","parameters{"type":"string","value":"ps -ef"}}'
    calls = _parse_text_tool_calls(text)
    assert len(calls) == 1
    # Remapped to the dedicated apps tool
    assert calls[0].name == "get_running_apps"


def test_parse_function_with_proper_parameters():
    text = '{"type":"function","name":"get_current_time","parameters":{}}'
    calls = _parse_text_tool_calls(text)
    assert len(calls) == 1
    assert calls[0].name == "get_current_time"
