import json
from types import SimpleNamespace
from typing import Any

from app.agent.classifier import FeedbackClassifier, MockClassificationProvider
from app.schemas import FeedbackRequest
from app.services.openai_tool_provider import OpenAIToolSelectionProvider
from app.services.tool_calling import ToolCallOutput, ToolSelectionError, tool_definitions


class RecordingResponses:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> object:
        self.requests.append(kwargs)
        return self.responses.pop(0)


def provider_with(responses: list[object]):  # type: ignore[no-untyped-def]
    provider = OpenAIToolSelectionProvider(api_key="test-key", model="gpt-5.6", timeout_seconds=1)
    recorder = RecordingResponses(responses)
    provider._client = SimpleNamespace(responses=recorder)  # type: ignore[assignment]
    return provider, recorder


def classification():  # type: ignore[no-untyped-def]
    return FeedbackClassifier(MockClassificationProvider(), confidence_threshold=0.70, max_retries=0).classify(
        "Duplicate invoice charge", request_id="classification-test"
    )


def test_openai_function_calls_are_mapped_to_internal_requests() -> None:
    response = SimpleNamespace(
        id="response-1",
        output=[
            SimpleNamespace(
                type="function_call",
                call_id="call-1",
                name="get_guest",
                arguments='{"guest_id":"GST-1001","guest_email":null}',
            )
        ],
    )
    provider, recorder = provider_with([response])
    turn = provider.begin(
        FeedbackRequest(feedback_text="I need a refund", guest_id="GST-1001", channel="email"),
        classification(),
    )
    assert turn.response_id == "response-1"
    assert turn.calls[0].name == "get_guest"
    assert recorder.requests[0]["tools"] == tool_definitions()
    assert "untrusted case data" in recorder.requests[0]["input"]


def test_tool_outputs_are_returned_with_the_matching_call_id() -> None:
    provider, recorder = provider_with([SimpleNamespace(id="response-2", output=[])])
    turn = provider.continue_turn(
        "response-1",
        [ToolCallOutput(call_id="call-1", output_json=json.dumps({"found": True}))],
    )
    sent = recorder.requests[0]
    assert sent["previous_response_id"] == "response-1"
    assert sent["input"] == [{"type": "function_call_output", "call_id": "call-1", "output": '{"found": true}'}]
    assert turn.calls == []


def test_function_schemas_are_strict_and_closed() -> None:
    for definition in tool_definitions():
        assert definition["strict"] is True
        parameters = definition["parameters"]
        assert isinstance(parameters, dict)
        assert parameters["additionalProperties"] is False


def test_malformed_tool_selection_response_is_controlled() -> None:
    provider, _ = provider_with([SimpleNamespace(id="response-bad")])
    try:
        provider.begin(
            FeedbackRequest(feedback_text="I need a refund", channel="email"),
            classification(),
        )
    except ToolSelectionError as exc:
        assert exc.code == "invalid_tool_response"
    else:
        raise AssertionError("Malformed response should be rejected")
