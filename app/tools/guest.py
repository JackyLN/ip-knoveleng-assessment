from app.schemas import GuestRecord, ToolResult
from app.services.data_loader import JsonDataLoader


class GuestTool:
    name = "get_guest"

    def __init__(self, loader: JsonDataLoader) -> None:
        self.loader = loader

    def run(self, guest_id: str | None, guest_email: str | None) -> ToolResult:
        guests = self.loader.load("guests.json", GuestRecord)
        match = next((item for item in guests if guest_id and item.guest_id == guest_id), None)
        if match is None and guest_email:
            match = next((item for item in guests if str(item.email).casefold() == guest_email.casefold()), None)
        return ToolResult(
            tool_name=self.name,
            found=match is not None,
            data=match,
            summary=f"Found guest {match.guest_id}." if match else "No matching guest record found.",
        )
