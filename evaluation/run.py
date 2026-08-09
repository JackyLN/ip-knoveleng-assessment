import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.agent.reporter import GENERAL_RECOMMENDATIONS
from app.main import get_orchestrator
from app.schemas import FeedbackAnalysisResponse, FeedbackRequest, PolicyRecord, WorkflowRecord
from app.services.data_loader import JsonDataLoader

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_PATH = ROOT / "evaluation" / "scenarios.json"
OUTPUT_DIR = ROOT / "evaluation" / "outputs"


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    input: FeedbackRequest
    expected_classification: str
    expected_secondary_categories: list[str]
    expected_tool_calls: list[str]
    expected_source_records: list[str]
    expected_human_review: bool
    expected_missing_context: list[str]
    explanation: str


class EvaluationResult(BaseModel):
    scenario_id: str
    passed: bool
    checks: dict[str, bool]
    explanation: str
    output: dict[str, Any]


def load_scenarios() -> list[Scenario]:
    raw = json.loads(SCENARIOS_PATH.read_text())
    return [Scenario.model_validate(item) for item in raw]


def valid_source_ids() -> set[str]:
    loader = JsonDataLoader(ROOT / "app" / "data")
    return {item.workflow_id for item in loader.load("workflows.json", WorkflowRecord)} | {
        item.policy_id for item in loader.load("policies.json", PolicyRecord)
    }


def normalized_output(analysis: FeedbackAnalysisResponse) -> dict[str, Any]:
    return {
        "report": analysis.report.model_dump(mode="json"),
        "trace": [
            {
                "event": step.event,
                "tool_name": step.tool_name,
                "status": step.status,
                "result_summary": step.result_summary,
                "error_code": step.error_code,
            }
            for step in analysis.trace
        ],
    }


def evaluate_scenario(scenario: Scenario) -> EvaluationResult:
    analysis = get_orchestrator().analyze(scenario.input, request_id=f"EVAL-{scenario.id}")
    validated = FeedbackAnalysisResponse.model_validate(analysis.model_dump())
    report = validated.report
    attempted_tools = {step.tool_name for step in validated.trace if step.event == "tool.started"}
    source_ids = {item.source_id for item in report.workflow_references + report.policy_references}
    allowed_ids = valid_source_ids()
    supported_actions = all(
        set(action.supporting_source_ids).issubset(source_ids) for action in report.suggested_actions
    )
    safe_general = all(item in GENERAL_RECOMMENDATIONS for item in report.general_recommendations)
    trace_events = {step.event for step in validated.trace}
    trace_complete = {
        "classification",
        "tool.requested",
        "tool.validated",
        "tool.started",
        "tool.completed",
        "human_review",
        "report.requested",
        "report.completed",
    }.issubset(trace_events) and bool({"context.complete", "context.incomplete"} & trace_events)
    checks = {
        "category_match": report.primary_category.value == scenario.expected_classification,
        "secondary_categories_match": [item.value for item in report.secondary_categories]
        == scenario.expected_secondary_categories,
        "required_tool_calls": attempted_tools == set(scenario.expected_tool_calls),
        "expected_sources": source_ids == set(scenario.expected_source_records),
        "source_id_validity": source_ids.issubset(allowed_ids),
        "structured_output_validity": isinstance(validated, FeedbackAnalysisResponse),
        "human_review_decision": report.requires_human_review == scenario.expected_human_review,
        "missing_context_behaviour": report.missing_context == scenario.expected_missing_context,
        "unsupported_claim_detection": supported_actions and safe_general,
        "trace_completeness": trace_complete,
    }
    return EvaluationResult(
        scenario_id=scenario.id,
        passed=all(checks.values()),
        checks=checks,
        explanation=scenario.explanation,
        output=normalized_output(validated),
    )


def run_evaluation(*, write_outputs: bool = False) -> list[EvaluationResult]:
    results = [evaluate_scenario(scenario) for scenario in load_scenarios()]
    if write_outputs:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        for result in results:
            target = OUTPUT_DIR / f"{result.scenario_id}.json"
            target.write_text(json.dumps(result.model_dump(mode="json"), indent=2) + "\n")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic StayFlow hotel-feedback evaluations.")
    parser.add_argument("--write-outputs", action="store_true", help="Refresh normalized sample outputs.")
    args = parser.parse_args()
    results = run_evaluation(write_outputs=args.write_outputs)
    for result in results:
        failed = [name for name, passed in result.checks.items() if not passed]
        print(f"{'PASS' if result.passed else 'FAIL'} {result.scenario_id}", end="")
        print(f" ({', '.join(failed)})" if failed else "")
    passed = sum(result.passed for result in results)
    print(f"{passed}/{len(results)} scenarios passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
