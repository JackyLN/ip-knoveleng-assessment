import json
import time
from typing import Any

from pydantic import ValidationError

from app.agent.trace import ExecutionTrace
from app.schemas import (
    BookingRecord,
    ClassificationResult,
    FeedbackRequest,
    GuestRecord,
    PolicyRecord,
    PropertyRecord,
    RetrievedContext,
    WorkflowRecord,
)
from app.services.tool_calling import (
    ToolCallOutput,
    ToolCallRequest,
    ToolSelectionError,
    ToolSelectionProvider,
    required_arguments,
    required_tools,
)
from app.tools.registry import ToolRegistry


def sanitize_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in arguments.items():
        if any(marker in key.casefold() for marker in ("key", "secret", "token", "password")):
            result[key] = "[redacted]"
        elif key == "guest_email" and isinstance(value, str) and "@" in value:
            local, domain = value.split("@", 1)
            result[key] = f"{local[:1]}***@{domain}"
        else:
            result[key] = value[:120] if isinstance(value, str) else value
    return result


class ContextCoordinator:
    def __init__(self, tools: ToolRegistry, provider: ToolSelectionProvider, *, max_iterations: int = 5) -> None:
        self.tools, self.provider, self.max_iterations = tools, provider, max_iterations

    def retrieve(
        self, request: FeedbackRequest, classification: ClassificationResult, trace: ExecutionTrace
    ) -> RetrievedContext:
        context = RetrievedContext(required_sources=required_tools(classification.primary_category, request))
        signatures: set[str] = set()
        try:
            turn = self.provider.begin(request, classification)
            for iteration in range(self.max_iterations):
                if not turn.calls:
                    break
                outputs = [
                    self._handle(call, context, trace, signatures, classification.primary_category.value)
                    for call in turn.calls
                ]
                if iteration == self.max_iterations - 1:
                    trace.add(
                        event="tool.rejected",
                        step="tool_iteration_limit",
                        action="Stop model tool selection at limit",
                        status="rejected",
                        result_summary=f"Maximum of {self.max_iterations} tool iterations reached.",
                        error_code="max_iterations",
                    )
                    break
                turn = self.provider.continue_turn(turn.response_id, outputs)
        except ToolSelectionError as exc:
            context.failure_codes.append(exc.code)
            trace.add(
                event="tool.failed",
                step="tool_provider",
                action="Request tool selection",
                status="failed",
                result_summary="Tool provider failed; controlled lookups will be attempted.",
                error_code=exc.code,
            )
        if "get_guest" in context.required_sources and context.guest is None and context.bookings:
            derived_guest = context.bookings[0].guest_id
            if not request.guest_id and not request.guest_email:
                self._handle(
                    ToolCallRequest(
                        call_id="controlled-derived-guest",
                        name="get_guest",
                        arguments_json=json.dumps({"guest_id": derived_guest, "guest_email": None}),
                    ),
                    context,
                    trace,
                    signatures,
                    classification.primary_category.value,
                    controlled=True,
                )
        if "get_property" in context.required_sources and context.property is None and context.bookings:
            derived_property = context.bookings[0].property_id
            if not request.property_id:
                self._handle(
                    ToolCallRequest(
                        call_id="controlled-derived-property",
                        name="get_property",
                        arguments_json=json.dumps({"property_id": derived_property}),
                    ),
                    context,
                    trace,
                    signatures,
                    classification.primary_category.value,
                    controlled=True,
                )
        for name in sorted(context.required_sources - context.attempted_sources):
            call = ToolCallRequest(
                call_id=f"controlled-{name}",
                name=name,
                arguments_json=json.dumps(required_arguments(name, request, classification, context)),
            )
            self._handle(
                call,
                context,
                trace,
                signatures,
                classification.primary_category.value,
                controlled=True,
            )
        context.complete = self._complete(context)
        trace.add(
            event="context.complete" if context.complete else "context.incomplete",
            step="context",
            action="Verify category-specific hotel context",
            status="complete" if context.complete else "incomplete",
            result_summary="Required hotel context is available."
            if context.complete
            else "One or more required hotel context sources are missing or failed.",
        )
        return context

    @staticmethod
    def _complete(context: RetrievedContext) -> bool:
        available = {
            "get_guest": context.guest is not None,
            "get_booking": bool(context.bookings),
            "get_property": context.property is not None,
            "get_workflow": context.workflow is not None,
            "get_policy": bool(context.policies),
        }
        return (
            context.attempted_sources.issuperset(context.required_sources)
            and all(available[name] for name in context.required_sources)
            and not (context.ambiguous_sources & context.required_sources)
            and not context.failure_codes
        )

    def _handle(
        self,
        call: ToolCallRequest,
        context: RetrievedContext,
        trace: ExecutionTrace,
        signatures: set[str],
        expected_category: str,
        *,
        controlled: bool = False,
    ) -> ToolCallOutput:
        try:
            raw = json.loads(call.arguments_json)
            if not isinstance(raw, dict):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            raw = None
        inputs = sanitize_arguments(raw) if raw is not None else {}
        trace.add(
            event="tool.requested",
            step="tool_call",
            action="Request controlled lookup" if controlled else "Model requested lookup",
            tool_name=call.name,
            inputs=inputs,
            status="requested",
            result_summary=f"Tool {call.name} requested.",
        )
        if raw is None:
            return self._reject(call, trace, "Invalid JSON arguments.", "invalid_arguments")
        if call.name in {"get_workflow", "get_policy"} and raw.get("category") != expected_category:
            return self._reject(
                call,
                trace,
                "Workflow or policy category differs from the validated primary classification.",
                "category_mismatch",
                inputs,
            )
        signature = f"{call.name}:{json.dumps(raw, sort_keys=True)}"
        if signature in signatures:
            return self._reject(call, trace, "Duplicate identical tool call rejected.", "duplicate_call", inputs)
        signatures.add(signature)
        if call.name not in self.tools.names:
            return self._reject(call, trace, "Unknown tool rejected.", "unknown_tool", inputs)
        try:
            arguments = self.tools.validate(call.name, raw)
        except ValidationError:
            return self._reject(call, trace, "Tool arguments failed schema validation.", "invalid_arguments", inputs)
        safe = sanitize_arguments(arguments.model_dump(mode="json"))
        trace.add(
            event="tool.validated",
            step="tool_call",
            action="Validate tool arguments",
            tool_name=call.name,
            inputs=safe,
            status="validated",
            result_summary="Arguments matched the registered schema.",
        )
        context.attempted_sources.add(call.name)
        trace.add(
            event="tool.started",
            step="tool_call",
            action="Execute registered JSON retrieval tool",
            tool_name=call.name,
            inputs=safe,
            status="started",
            result_summary=f"Started {call.name}.",
        )
        started = time.monotonic()
        try:
            result = self.tools.execute(call.name, arguments)
        except Exception:
            context.failure_codes.append("tool_execution_error")
            trace.add(
                event="tool.failed",
                step="tool_call",
                action="Execute registered JSON retrieval tool",
                tool_name=call.name,
                inputs=safe,
                status="failed",
                result_summary="Retrieval failed safely.",
                duration_ms=(time.monotonic() - started) * 1000,
                error_code="tool_execution_error",
            )
            return ToolCallOutput(
                call_id=call.call_id, output_json=json.dumps({"found": False, "error_code": "tool_execution_error"})
            )
        if result.ambiguous:
            context.ambiguous_sources.add(call.name)
        self._capture(call.name, result.data, context)
        trace.add(
            event="tool.completed",
            step="tool_call",
            action="Execute registered JSON retrieval tool",
            tool_name=call.name,
            inputs=safe,
            status="completed" if result.found else "not_found",
            result_summary=result.summary,
            duration_ms=(time.monotonic() - started) * 1000,
        )
        return ToolCallOutput(call_id=call.call_id, output_json=result.model_dump_json())

    @staticmethod
    def _capture(name: str, data: object, context: RetrievedContext) -> None:
        if name == "get_guest" and isinstance(data, GuestRecord):
            context.guest = data
        elif name == "get_booking" and isinstance(data, list):
            context.bookings = [x for x in data if isinstance(x, BookingRecord)]
        elif name == "get_property" and isinstance(data, PropertyRecord):
            context.property = data
        elif name == "get_workflow" and isinstance(data, WorkflowRecord):
            context.workflow = data
        elif name == "get_policy" and isinstance(data, list):
            context.policies = [x for x in data if isinstance(x, PolicyRecord)]

    @staticmethod
    def _reject(
        call: ToolCallRequest, trace: ExecutionTrace, summary: str, code: str, inputs: dict[str, Any] | None = None
    ) -> ToolCallOutput:
        trace.add(
            event="tool.rejected",
            step="tool_call",
            action="Reject unsafe or invalid tool request",
            tool_name=call.name,
            inputs=inputs or {},
            status="rejected",
            result_summary=summary,
            error_code=code,
        )
        return ToolCallOutput(call_id=call.call_id, output_json=json.dumps({"found": False, "error_code": code}))
