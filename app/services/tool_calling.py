import json
from dataclasses import dataclass
from typing import Protocol

from app.schemas import Category, ClassificationResult, FeedbackRequest, RetrievedContext


@dataclass(frozen=True)
class ToolCallRequest:
    call_id: str
    name: str
    arguments_json: str


@dataclass(frozen=True)
class ToolCallOutput:
    call_id: str
    output_json: str


@dataclass(frozen=True)
class ToolTurn:
    response_id: str
    calls: list[ToolCallRequest]


class ToolSelectionError(RuntimeError):
    def __init__(self, message: str, *, code: str = "tool_provider_error") -> None:
        super().__init__(message)
        self.code = code


class ToolSelectionProvider(Protocol):
    name: str
    model: str

    def begin(self, request: FeedbackRequest, classification: ClassificationResult) -> ToolTurn: ...
    def continue_turn(self, previous_response_id: str, outputs: list[ToolCallOutput]) -> ToolTurn: ...


CATEGORY_CONTEXT: dict[Category, set[str]] = {
    Category.BOOKING_ISSUE: {"get_guest", "get_booking", "get_workflow", "get_policy"},
    Category.CANCELLATION_REQUEST: {"get_guest", "get_booking", "get_workflow", "get_policy"},
    Category.REFUND_REQUEST: {"get_guest", "get_booking", "get_workflow", "get_policy"},
    Category.PAYMENT_ISSUE: {"get_guest", "get_booking", "get_workflow", "get_policy"},
    Category.CHECK_IN_ISSUE: {"get_guest", "get_booking", "get_property", "get_workflow", "get_policy"},
    Category.ROOM_ISSUE: {"get_guest", "get_booking", "get_property", "get_workflow", "get_policy"},
    Category.HOTEL_SERVICE_COMPLAINT: {"get_guest", "get_booking", "get_property", "get_workflow", "get_policy"},
    Category.OVERBOOKING: {"get_guest", "get_booking", "get_property", "get_workflow", "get_policy"},
    Category.GUEST_SAFETY: {"get_workflow", "get_policy"},
    Category.DATA_PRIVACY: {"get_workflow", "get_policy"},
    Category.ACCESSIBILITY_ISSUE: {"get_guest", "get_booking", "get_property", "get_workflow", "get_policy"},
    Category.FEATURE_REQUEST: {"get_workflow", "get_policy"},
    Category.PRAISE: {"get_workflow", "get_policy"},
    Category.ABUSE_POLICY: {"get_workflow", "get_policy"},
    Category.OTHER: {"get_workflow", "get_policy"},
}


def required_tools(category: Category, request: FeedbackRequest) -> set[str]:
    required = set(CATEGORY_CONTEXT[category])
    if category in {Category.GUEST_SAFETY, Category.DATA_PRIVACY}:
        if request.guest_id or request.guest_email:
            required.add("get_guest")
        if request.booking_id:
            required.add("get_booking")
        if request.property_id:
            required.add("get_property")
    return required


class MockToolSelectionProvider:
    name = "mock"
    model = "stayflow-tools-v1"

    def begin(self, request: FeedbackRequest, classification: ClassificationResult) -> ToolTurn:
        context = RetrievedContext()
        calls = [
            ToolCallRequest(
                call_id=f"mock-{name}",
                name=name,
                arguments_json=json.dumps(required_arguments(name, request, classification, context)),
            )
            for name in sorted(required_tools(classification.primary_category, request))
        ]
        return ToolTurn(response_id="mock-context-1", calls=calls)

    def continue_turn(self, previous_response_id: str, outputs: list[ToolCallOutput]) -> ToolTurn:
        return ToolTurn(response_id="mock-context-complete", calls=[])


def required_arguments(
    name: str, request: FeedbackRequest, classification: ClassificationResult, context: RetrievedContext
) -> dict[str, object]:
    booking = context.bookings[0] if len(context.bookings) == 1 else None
    if name == "get_guest":
        return {"guest_id": request.guest_id, "guest_email": str(request.guest_email) if request.guest_email else None}
    if name == "get_booking":
        return {"booking_id": request.booking_id, "guest_id": request.guest_id}
    if name == "get_property":
        property_id = request.property_id or (booking.property_id if booking else None)
        return {"property_id": property_id or "MISSING-PROPERTY-ID"}
    if name == "get_workflow":
        return {"category": classification.primary_category.value}
    if name == "get_policy":
        return {
            "category": classification.primary_category.value,
            "property_country": context.property.country if context.property else None,
            "booking_channel": booking.booking_channel if booking else None,
        }
    raise KeyError(name)


def tool_definitions() -> list[dict[str, object]]:
    nullable = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    categories = [item.value for item in Category]

    def definition(name: str, description: str, properties: dict[str, object]) -> dict[str, object]:
        return {
            "type": "function",
            "name": name,
            "description": description,
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            },
        }

    return [
        definition(
            "get_guest", "Retrieve a fictional guest by ID or email.", {"guest_id": nullable, "guest_email": nullable}
        ),
        definition(
            "get_booking",
            "Retrieve fictional bookings by booking or guest ID.",
            {"booking_id": nullable, "guest_id": nullable},
        ),
        definition("get_property", "Retrieve a fictional hotel property.", {"property_id": {"type": "string"}}),
        definition(
            "get_workflow", "Retrieve the hotel support workflow.", {"category": {"type": "string", "enum": categories}}
        ),
        definition(
            "get_policy",
            "Retrieve applicable fictional hotel policies.",
            {
                "category": {"type": "string", "enum": categories},
                "property_country": nullable,
                "booking_channel": nullable,
            },
        ),
    ]
