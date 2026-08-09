from app.schemas import Category, PolicyRecord, ToolResult
from app.services.data_loader import JsonDataLoader


class PolicyTool:
    name = "get_policy"

    def __init__(self, loader: JsonDataLoader) -> None:
        self.loader = loader

    def run(self, category: Category, property_country: str | None, booking_channel: str | None) -> ToolResult:
        del property_country, booking_channel
        policies = self.loader.load("policies.json", PolicyRecord)
        matches = [item for item in policies if category in item.applicable_categories]
        return ToolResult(
            tool_name=self.name,
            found=bool(matches),
            data=matches,
            summary=f"Found {len(matches)} applicable policy record(s)."
            if matches
            else f"No policy found for {category.value}.",
        )
