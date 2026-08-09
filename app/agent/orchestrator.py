from app.agent.classifier import FeedbackClassifier
from app.agent.context import ContextCoordinator
from app.agent.reporter import GroundedReportGenerator
from app.agent.review_rules import evaluate_review
from app.agent.trace import ExecutionTrace
from app.schemas import FeedbackAnalysisResponse, FeedbackRequest


class FeedbackOrchestrator:
    def __init__(
        self,
        classifier: FeedbackClassifier,
        context: ContextCoordinator,
        reporter: GroundedReportGenerator,
    ) -> None:
        self.classifier = classifier
        self.context = context
        self.reporter = reporter

    def analyze(self, request: FeedbackRequest, *, request_id: str) -> FeedbackAnalysisResponse:
        trace = ExecutionTrace(request_id)
        classification = self.classifier.classify(request.feedback_text, request_id=request_id)
        trace.add(
            step="classification",
            action="Classify untrusted guest feedback with structured output",
            status=classification.status.value,
            inputs={"text_length": len(request.feedback_text), "channel": request.channel},
            result_summary=(
                f"Category {classification.primary_category.value}; confidence {classification.confidence:.2f}; "
                f"urgency {classification.urgency.value}."
            ),
        )

        retrieved = self.context.retrieve(request, classification, trace)
        review = evaluate_review(classification, retrieved, confidence_threshold=self.classifier.confidence_threshold)
        trace.add(
            step="human_review",
            action="Apply deterministic review rules",
            status="review_required" if review.required else "complete",
            inputs={},
            result_summary=(
                f"Review required for {len(review.reasons)} reason(s)."
                if review.required
                else "No review triggers matched."
            ),
        )
        report = self.reporter.generate(request, classification, retrieved, review, trace)
        return FeedbackAnalysisResponse(report=report, trace=trace.steps)
