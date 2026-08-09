import json
import logging
import time
from uuid import uuid4

from app.agent.trace import ExecutionTrace
from app.schemas import (
    ActionPriority,
    ClassificationResult,
    FeedbackRequest,
    ReportStatus,
    RetrievedContext,
    ReviewDecision,
    SourceReference,
    StructuredReport,
    SuggestedAction,
)
from app.services.reporting import ReportProposal, ReportProvider, ReportProviderError, ReportProviderResponse

logger = logging.getLogger("uvicorn.error")
GENERAL_RECOMMENDATIONS = {
    "Acknowledge the guest's feedback.",
    "Ask the guest for missing booking or property details.",
    "Avoid commitments beyond retrieved StayFlow policy.",
}


class MockReportProvider:
    name = "mock"
    model = "stayflow-report-v1"

    def generate(self, grounded_input: str) -> ReportProviderResponse:
        data = json.loads(grounded_input)
        workflow = data["retrieved_context"]["workflow"]
        policies = data["retrieved_context"]["policies"]
        return ReportProviderResponse(
            proposal=ReportProposal(
                feedback_summary=data["feedback"][:240],
                workflow_references=[
                    SourceReference(
                        source_id=workflow["workflow_id"],
                        title=workflow["title"],
                        reason_used="Defines the support process and allowed recommendation for this category.",
                    )
                ]
                if workflow
                else [],
                policy_references=[
                    SourceReference(
                        source_id=item["policy_id"],
                        title=item["title"],
                        version=item["version"],
                        reason_used="Provides applicable conditions, exclusions, and approval requirements.",
                    )
                    for item in policies
                ],
                suggested_actions=[
                    SuggestedAction(
                        action=workflow["allowed_recommendations"][0],
                        priority=ActionPriority(data["classification"]["urgency"]),
                        supporting_source_ids=[workflow["workflow_id"]],
                        requires_approval=workflow["financial_action"] or workflow["high_risk_action"],
                    )
                ]
                if workflow and workflow["allowed_recommendations"]
                else [],
                general_recommendations=["Acknowledge the guest's feedback."],
                contradictions=[],
                requires_human_review=False,
                human_review_reasons=[],
            )
        )


class GroundedReportGenerator:
    def __init__(self, provider: ReportProvider) -> None:
        self.provider = provider

    def generate(
        self,
        request: FeedbackRequest,
        classification: ClassificationResult,
        context: RetrievedContext,
        review: ReviewDecision,
        trace: ExecutionTrace,
    ) -> StructuredReport:
        started = time.monotonic()
        trace.add(
            event="report.requested",
            step="report_generation",
            action="Request grounded StayFlow report",
            status="requested",
            inputs={"provider": self.provider.name},
            result_summary="Validated hotel context sent to report provider.",
        )
        try:
            response = self.provider.generate(self._grounded_json(request, classification, context, review))
            report = self._validate(response.proposal, request, classification, context, review)
            duration = (time.monotonic() - started) * 1000
            trace.add(
                event="report.completed",
                step="report_generation",
                action="Validate grounded StayFlow report",
                status="completed",
                inputs={"provider": self.provider.name},
                result_summary="Hotel report generated and references validated.",
                duration_ms=duration,
            )
            self._log(trace.request_id, duration, True, response)
            return report
        except ReportProviderError as exc:
            duration = (time.monotonic() - started) * 1000
            trace.add(
                event="report.failed",
                step="report_generation",
                action="Generate grounded StayFlow report",
                status="failed",
                inputs={"provider": self.provider.name},
                result_summary="Report generation failed safely; hotel context was preserved.",
                duration_ms=duration,
                error_code=exc.code,
            )
            self._log(trace.request_id, duration, False, error_code=exc.code)
            return self._fallback(request, classification, context, review, exc.code)

    @staticmethod
    def _grounded_json(
        request: FeedbackRequest,
        classification: ClassificationResult,
        context: RetrievedContext,
        review: ReviewDecision,
    ) -> str:
        actions = []
        if context.workflow:
            actions = [
                {"action": action, "supporting_source_id": context.workflow.workflow_id}
                for action in context.workflow.allowed_recommendations
            ]
        return json.dumps(
            {
                "fictional_domain": "StayFlow hotel support demonstration",
                "feedback": request.feedback_text,
                "classification": classification.model_dump(mode="json"),
                "retrieved_context": context.model_dump(mode="json"),
                "deterministic_review": review.model_dump(mode="json"),
                "allowed_actions": actions,
                "allowed_general_recommendations": sorted(GENERAL_RECOMMENDATIONS),
            }
        )

    def _validate(
        self,
        proposal: ReportProposal,
        request: FeedbackRequest,
        classification: ClassificationResult,
        context: RetrievedContext,
        review: ReviewDecision,
    ) -> StructuredReport:
        issues: list[str] = []
        workflow_refs: list[SourceReference] = []
        if context.workflow:
            expected = SourceReference(
                source_id=context.workflow.workflow_id,
                title=context.workflow.title,
                reason_used="Defines the support process and allowed recommendation for this category.",
            )
            workflow_refs.append(expected)
            if any(
                item.source_id != expected.source_id or item.title != expected.title
                for item in proposal.workflow_references
            ):
                issues.append("Generated report contained an unsupported workflow reference.")
        elif proposal.workflow_references:
            issues.append("Generated report referenced a workflow that was not retrieved.")
        policies = {item.policy_id: item for item in context.policies}
        policy_refs = [
            SourceReference(
                source_id=record.policy_id,
                title=record.title,
                version=record.version,
                reason_used="Provides applicable conditions, exclusions, and approval requirements.",
            )
            for record in context.policies
        ]
        for reference in proposal.policy_references:
            record = policies.get(reference.source_id)
            if not record or record.title != reference.title:
                issues.append("Generated report contained an unsupported policy reference.")
        allowed_actions = (
            {(action, context.workflow.workflow_id) for action in context.workflow.allowed_recommendations}
            if context.workflow
            else set()
        )
        actions: list[SuggestedAction] = []
        for action in proposal.suggested_actions:
            if (
                len(action.supporting_source_ids) == 1
                and (action.action, action.supporting_source_ids[0]) in allowed_actions
            ):
                actions.append(
                    SuggestedAction(
                        action=action.action,
                        priority=ActionPriority(classification.urgency.value),
                        supporting_source_ids=action.supporting_source_ids,
                        requires_approval=bool(
                            context.workflow
                            and (context.workflow.financial_action or context.workflow.high_risk_action)
                        )
                        or any(policy.required_approvals for policy in context.policies),
                    )
                )
            else:
                issues.append("Generated report contained an unsupported hotel action.")
        general = [item for item in proposal.general_recommendations if item in GENERAL_RECOMMENDATIONS]
        if len(general) != len(proposal.general_recommendations):
            issues.append("Generated report contained an unsupported general recommendation.")
        contradictions = list(dict.fromkeys(self._contradictions(request, context) + issues))
        if contradictions:
            issues.append("Guest statement conflicts with or exceeds retrieved records.")
        reasons = list(dict.fromkeys(review.reasons + issues))
        return self._report(
            request.feedback_text,
            proposal.feedback_summary,
            classification,
            context,
            workflow_refs,
            policy_refs,
            actions,
            general,
            self._missing(context),
            contradictions,
            bool(reasons),
            reasons,
        )

    @staticmethod
    def _contradictions(request: FeedbackRequest, context: RetrievedContext) -> list[str]:
        text = request.feedback_text.casefold()
        contradictions = []
        if "hotel cancelled" in text or "property cancelled" in text:
            for booking in context.bookings:
                if booking.cancellation_source and booking.cancellation_source != "property":
                    contradictions.append(
                        "The guest states that the property cancelled the booking. "
                        f"Booking {booking.booking_id} records the cancellation source as "
                        f"{booking.cancellation_source}. Manual verification is required."
                    )
        if "refund" in text:
            for booking in context.bookings:
                if booking.refund_status == "not_requested":
                    contradictions.append(
                        f"The guest references a refund, while booking {booking.booking_id} records refund status "
                        "as not_requested. Manual verification is required."
                    )
        return contradictions

    @staticmethod
    def _missing(context: RetrievedContext) -> list[str]:
        available = {
            "get_guest": context.guest is not None,
            "get_booking": bool(context.bookings),
            "get_property": context.property is not None,
            "get_workflow": context.workflow is not None,
            "get_policy": bool(context.policies),
        }
        labels = {
            "get_guest": "guest",
            "get_booking": "booking",
            "get_property": "property",
            "get_workflow": "workflow",
            "get_policy": "policy",
        }
        return [labels[name] for name in sorted(context.required_sources) if not available[name]]

    @staticmethod
    def _report(
        original_feedback: str,
        summary: str,
        classification: ClassificationResult,
        context: RetrievedContext,
        workflow_refs: list[SourceReference],
        policy_refs: list[SourceReference],
        actions: list[SuggestedAction],
        general: list[str],
        missing: list[str],
        contradictions: list[str],
        requires_review: bool,
        reasons: list[str],
    ) -> StructuredReport:
        status = (
            ReportStatus.PARTIAL
            if not context.complete
            else ReportStatus.REQUIRES_REVIEW
            if requires_review
            else ReportStatus.COMPLETE
        )
        return StructuredReport(
            report_id=f"RPT-{uuid4()}",
            original_feedback=original_feedback,
            feedback_summary=summary,
            primary_category=classification.primary_category,
            secondary_categories=classification.secondary_categories,
            sentiment=classification.sentiment,
            urgency=classification.urgency,
            business_impact=classification.business_impact,
            classification_confidence=classification.confidence,
            guest_context=context.guest,
            booking_context=context.bookings,
            property_context=context.property,
            workflow_references=workflow_refs,
            policy_references=policy_refs,
            suggested_actions=actions,
            general_recommendations=general,
            missing_context=missing,
            contradictions=contradictions,
            context_complete=context.complete,
            requires_human_review=requires_review,
            human_review_reasons=reasons,
            report_status=status,
        )

    def _fallback(
        self,
        request: FeedbackRequest,
        classification: ClassificationResult,
        context: RetrievedContext,
        review: ReviewDecision,
        code: str,
    ) -> StructuredReport:
        reasons = list(dict.fromkeys(review.reasons + [f"Report generation failed ({code})."]))
        workflows = (
            [
                SourceReference(
                    source_id=context.workflow.workflow_id,
                    title=context.workflow.title,
                    reason_used="Defines the retrieved support process for this category.",
                )
            ]
            if context.workflow
            else []
        )
        policies = [
            SourceReference(
                source_id=item.policy_id,
                title=item.title,
                version=item.version,
                reason_used="Provides retrieved conditions and approval requirements.",
            )
            for item in context.policies
        ]
        report = self._report(
            request.feedback_text,
            request.feedback_text[:240],
            classification,
            context,
            workflows,
            policies,
            [],
            [],
            self._missing(context),
            self._contradictions(request, context),
            True,
            reasons,
        )
        report.report_status = ReportStatus.FAILED
        return report

    def _log(
        self,
        request_id: str,
        duration: float,
        success: bool,
        response: ReportProviderResponse | None = None,
        error_code: str | None = None,
    ) -> None:
        logger.info(
            "report_complete request_id=%s provider=%s model=%s duration_ms=%.1f "
            "success=%s input_tokens=%s output_tokens=%s error_code=%s",
            request_id,
            self.provider.name,
            self.provider.model,
            duration,
            success,
            response.input_tokens if response else None,
            response.output_tokens if response else None,
            error_code,
        )
