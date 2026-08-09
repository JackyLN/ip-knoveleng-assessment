from app.schemas import BookingRecord, ToolResult
from app.services.data_loader import JsonDataLoader


class BookingTool:
    name = "get_booking"

    def __init__(self, loader: JsonDataLoader) -> None:
        self.loader = loader

    def run(self, booking_id: str | None, guest_id: str | None) -> ToolResult:
        bookings = self.loader.load("bookings.json", BookingRecord)
        matches = [
            item
            for item in bookings
            if (booking_id and item.booking_id == booking_id)
            or (not booking_id and guest_id and item.guest_id == guest_id)
        ]
        return ToolResult(
            tool_name=self.name,
            found=bool(matches),
            ambiguous=not booking_id and len(matches) > 1,
            data=matches,
            summary=(f"Found {len(matches)} booking record(s)." if matches else "No matching booking record found."),
        )
