from app.schemas import Category, ToolResult, WorkflowRecord
from app.services.data_loader import JsonDataLoader


class WorkflowTool:
    name = "get_workflow"

    def __init__(self, loader: JsonDataLoader) -> None:
        self.loader = loader

    def run(self, category: Category) -> ToolResult:
        workflows = self.loader.load("workflows.json", WorkflowRecord)
        match = next((item for item in workflows if item.category == category), None)
        return ToolResult(
            tool_name=self.name,
            found=match is not None,
            data=match,
            summary=f"Found workflow {match.workflow_id}." if match else f"No workflow found for {category.value}.",
        )
