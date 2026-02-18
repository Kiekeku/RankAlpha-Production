from types import SimpleNamespace

from apps.sentiment.src.llm.gpt5_responses_planner_llm import _extract_tool_call_fields


def test_extract_tool_call_fields_handles_nested_function_blob() -> None:
    call = {
        "id": "call_nested",
        "function": {
            "name": "fetch",
            "arguments": '{"url": "https://example.com"}',
        },
    }

    call_id, name, args = _extract_tool_call_fields(call)

    assert call_id == "call_nested"
    assert name == "fetch"
    assert args == '{"url": "https://example.com"}'


def test_extract_tool_call_fields_prefers_attributes() -> None:
    call = SimpleNamespace(call_id="call_attr", name="lookup", arguments={"symbol": "AAPL"})

    call_id, name, args = _extract_tool_call_fields(call)

    assert call_id == "call_attr"
    assert name == "lookup"
    assert args == {"symbol": "AAPL"}
