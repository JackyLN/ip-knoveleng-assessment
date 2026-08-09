from app.schemas import PropertyRecord, ToolResult
from app.services.data_loader import JsonDataLoader


class PropertyTool:
    name = "get_property"

    def __init__(self, loader: JsonDataLoader) -> None:
        self.loader = loader

    def run(self, property_id: str) -> ToolResult:
        properties = self.loader.load("properties.json", PropertyRecord)
        match = next((item for item in properties if item.property_id == property_id), None)
        return ToolResult(
            tool_name=self.name,
            found=match is not None,
            data=match,
            summary=f"Found property {match.property_id}." if match else "No matching property record found.",
        )
