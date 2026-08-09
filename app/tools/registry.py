from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.schemas import GetBookingArgs, GetGuestArgs, GetPolicyArgs, GetPropertyArgs, GetWorkflowArgs, ToolResult
from app.services.data_loader import JsonDataLoader
from app.tools.booking import BookingTool
from app.tools.guest import GuestTool
from app.tools.policy import PolicyTool
from app.tools.property import PropertyTool
from app.tools.workflow import WorkflowTool


@dataclass(frozen=True)
class ToolRegistry:
    guest: GuestTool
    booking: BookingTool
    property_tool: PropertyTool
    workflow: WorkflowTool
    policy: PolicyTool

    @classmethod
    def from_loader(cls, loader: JsonDataLoader) -> "ToolRegistry":
        return cls(
            GuestTool(loader), BookingTool(loader), PropertyTool(loader), WorkflowTool(loader), PolicyTool(loader)
        )

    @property
    def names(self) -> set[str]:
        return {self.guest.name, self.booking.name, self.property_tool.name, self.workflow.name, self.policy.name}

    def validate(self, name: str, arguments: dict[str, Any]) -> BaseModel:
        models: dict[str, type[BaseModel]] = {
            "get_guest": GetGuestArgs,
            "get_booking": GetBookingArgs,
            "get_property": GetPropertyArgs,
            "get_workflow": GetWorkflowArgs,
            "get_policy": GetPolicyArgs,
        }
        model = models.get(name)
        if model is None:
            raise KeyError(name)
        return model.model_validate(arguments)

    def execute(self, name: str, arguments: BaseModel) -> ToolResult:
        if name == "get_guest" and isinstance(arguments, GetGuestArgs):
            return self.guest.run(arguments.guest_id, str(arguments.guest_email) if arguments.guest_email else None)
        if name == "get_booking" and isinstance(arguments, GetBookingArgs):
            return self.booking.run(arguments.booking_id, arguments.guest_id)
        if name == "get_property" and isinstance(arguments, GetPropertyArgs):
            return self.property_tool.run(arguments.property_id)
        if name == "get_workflow" and isinstance(arguments, GetWorkflowArgs):
            return self.workflow.run(arguments.category)
        if name == "get_policy" and isinstance(arguments, GetPolicyArgs):
            return self.policy.run(arguments.category, arguments.property_country, arguments.booking_channel)
        raise KeyError(name)
