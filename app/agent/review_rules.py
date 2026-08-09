from app.schemas import Category, ClassificationResult, ClassificationStatus, RetrievedContext, ReviewDecision


def evaluate_review(
    classification: ClassificationResult, context: RetrievedContext, *, confidence_threshold: float = 0.70
) -> ReviewDecision:
    reasons: list[str] = []
    if classification.status == ClassificationStatus.FALLBACK:
        reasons.append("Automated classification failed.")
    if classification.ambiguous:
        reasons.append("Classification is ambiguous.")
    if classification.out_of_domain:
        reasons.append("Feedback is outside the hotel-support domain.")
    if classification.confidence < confidence_threshold:
        reasons.append(f"Classification confidence is below {confidence_threshold:.2f}.")
    missing_map = {
        "get_guest": "Required guest record is missing.",
        "get_booking": "Required booking record is missing.",
        "get_property": "Required property context is missing.",
        "get_workflow": "No applicable workflow was found.",
        "get_policy": "No applicable policy was found.",
    }
    available = {
        "get_guest": context.guest is not None,
        "get_booking": bool(context.bookings),
        "get_property": context.property is not None,
        "get_workflow": context.workflow is not None,
        "get_policy": bool(context.policies),
    }
    for source in sorted(context.required_sources):
        if not available[source]:
            reasons.append(missing_map[source])
    category_reasons = {
        Category.OVERBOOKING: "Overbooking requires mandatory escalation.",
        Category.GUEST_SAFETY: "Guest safety requires mandatory escalation.",
        Category.DATA_PRIVACY: "Guest-data privacy requires mandatory escalation.",
        Category.ACCESSIBILITY_ISSUE: "Accessibility obligations require human review.",
        Category.ABUSE_POLICY: "Abusive or threatening content requires human review.",
    }
    if classification.primary_category in category_reasons:
        reasons.append(category_reasons[classification.primary_category])
    if context.workflow and (context.workflow.financial_action or context.workflow.high_risk_action):
        reasons.append("A financial or high-risk hotel action may be required.")
    if classification.risk_flags:
        reasons.append(f"Sensitive issue detected: {', '.join(classification.risk_flags)}.")
    if "get_booking" in context.ambiguous_sources:
        reasons.append("Multiple booking records matched; the relevant booking is ambiguous.")
    if context.failure_codes:
        reasons.append(f"Automated context retrieval failed: {', '.join(dict.fromkeys(context.failure_codes))}.")
    return ReviewDecision(required=bool(reasons), reasons=list(dict.fromkeys(reasons)))
