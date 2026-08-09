import json
from pathlib import Path
from typing import Any

from app.agent.classifier import FeedbackClassifier, MockClassificationProvider
from app.agent.context import ContextCoordinator
from app.agent.orchestrator import FeedbackOrchestrator
from app.agent.reporter import GroundedReportGenerator, MockReportProvider
from app.schemas import FeedbackRequest
from app.services.data_loader import JsonDataLoader
from app.services.tool_calling import MockToolSelectionProvider
from app.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = Path(__file__).resolve().parent
SAMPLE_IDS = {
    "refund_pending": "refund_investigation",
    "ambiguous_feedback": "ambiguous_complaint",
    "missing_record": "missing_booking",
    "guest_safety": "guest_safety",
    "prompt_injection": "prompt_injection",
}


def orchestrator() -> FeedbackOrchestrator:
    tools = ToolRegistry.from_loader(JsonDataLoader(ROOT / "app" / "data"))
    classifier = FeedbackClassifier(MockClassificationProvider(), confidence_threshold=0.70, max_retries=0)
    context = ContextCoordinator(tools, MockToolSelectionProvider(), max_iterations=5)
    return FeedbackOrchestrator(classifier, context, GroundedReportGenerator(MockReportProvider()))


def load_inputs() -> dict[str, dict[str, Any]]:
    scenarios = json.loads((ROOT / "evaluation" / "scenarios.json").read_text())
    return {item["id"]: item["input"] for item in scenarios}


def generate() -> None:
    inputs = load_inputs()
    agent = orchestrator()
    for folder, scenario_id in SAMPLE_IDS.items():
        target = EXAMPLES / folder
        target.mkdir(exist_ok=True)
        payload = FeedbackRequest.model_validate(inputs[scenario_id])
        analysis = agent.analyze(payload, request_id=f"EXAMPLE-{scenario_id.upper()}")
        report = analysis.report.model_dump(mode="json")
        tool_calls = [
            {
                "tool_name": step.tool_name,
                "sanitized_arguments": step.inputs,
                "status": step.status,
                "result_summary": step.result_summary,
            }
            for step in analysis.trace
            if step.event == "tool.completed"
        ]
        saved = {
            "input": payload.model_dump(mode="json"),
            "classification": {
                key: report[key]
                for key in (
                    "primary_category",
                    "secondary_categories",
                    "sentiment",
                    "urgency",
                    "business_impact",
                    "classification_confidence",
                )
            },
            "tool_calls": tool_calls,
            "retrieved_context": {
                "guest": report["guest_context"],
                "bookings": report["booking_context"],
                "property": report["property_context"],
                "workflows": report["workflow_references"],
                "policies": report["policy_references"],
            },
            "hotel_feedback_report": report,
            "human_review_decision": {
                "required": report["requires_human_review"],
                "reasons": report["human_review_reasons"],
            },
            "execution_trace": [step.model_dump(mode="json") for step in analysis.trace],
        }
        (target / "input.json").write_text(json.dumps(payload.model_dump(mode="json"), indent=2) + "\n")
        (target / "output.json").write_text(json.dumps(saved, indent=2) + "\n")
        command = (
            "curl -X POST http://localhost:8000/api/feedback/analyze "
            "-H 'Content-Type: application/json' "
            f"-d @examples/{folder}/input.json"
        )
        (target / "README.md").write_text(
            f"# {folder.replace('_', ' ').title()}\n\nReproduce after starting StayFlow:\n\n```bash\n{command}\n```\n"
        )
        print(f"WROTE {folder}")


if __name__ == "__main__":
    generate()
