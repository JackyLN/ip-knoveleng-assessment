import logging
import time
from collections.abc import Callable

from app.schemas import BusinessImpact, Category, ClassificationResult, ClassificationStatus, Sentiment, Urgency
from app.services.llm import (
    ClassificationProvider,
    ClassificationProviderError,
    ProviderClassification,
    ProviderResponse,
)

logger = logging.getLogger("uvicorn.error")

CATEGORY_KEYWORDS: dict[Category, tuple[str, ...]] = {
    Category.GUEST_SAFETY: (
        "door would not lock",
        "would not lock",
        "door cannot lock",
        "unsafe",
        "fire",
        "injury",
        "threatened",
    ),
    Category.DATA_PRIVACY: ("personal data", "privacy", "data exposed", "account hacked"),
    Category.OVERBOOKING: (
        "overbooked",
        "no room available",
        "arrived at the hotel",
        "no room",
        "walked to another hotel",
    ),
    Category.ACCESSIBILITY_ISSUE: ("wheelchair", "accessible", "accessibility", "step-free"),
    Category.REFUND_REQUEST: ("refund", "not received my refund", "refund pending", "money back", "reimburse"),
    Category.CANCELLATION_REQUEST: ("cancel my", "cancellation", "cancel booking"),
    Category.PAYMENT_ISSUE: ("charged", "charge", "payment", "card", "invoice"),
    Category.CHECK_IN_ISSUE: ("check in", "check-in", "reception would not"),
    Category.ROOM_ISSUE: ("room", "towel", "air conditioning", "dirty", "cleaning"),
    Category.BOOKING_ISSUE: ("booking", "reservation", "confirmation"),
    Category.HOTEL_SERVICE_COMPLAINT: ("staff", "service", "reception", "hotel experience was terrible"),
    Category.FEATURE_REQUEST: ("feature", "please add", "app should", "suggestion"),
    Category.PRAISE: ("wonderful", "excellent", "great stay", "thank you", "anniversary special"),
    Category.ABUSE_POLICY: ("harassment", "hate speech", "abuse", "threat"),
}
HOTEL_TERMS = tuple({term for terms in CATEGORY_KEYWORDS.values() for term in terms}) + (
    "hotel",
    "stay",
    "guest",
    "property",
    "room",
    "booking",
    "reservation",
)
RISK_KEYWORDS = {
    "security": ("door would not lock", "door cannot lock", "unsafe", "hacked"),
    "privacy": ("privacy", "personal data", "data exposed"),
    "abuse": ("abuse", "harassment", "threat", "hate speech"),
    "prompt_injection": ("ignore all previous instructions", "ignore hotel policies", "reveal your prompt"),
}


def detect_risk_flags(text: str) -> list[str]:
    normalized = text.casefold()
    return [name for name, terms in RISK_KEYWORDS.items() if any(term in normalized for term in terms)]


class MockClassificationProvider:
    name = "mock"
    model = "stayflow-keywords-v1"

    def classify(self, feedback_text: str) -> ProviderResponse:
        normalized = feedback_text.casefold()
        scores = {category: sum(term in normalized for term in terms) for category, terms in CATEGORY_KEYWORDS.items()}
        ranked = sorted(
            ((category, score) for category, score in scores.items() if score),
            key=lambda item: (-item[1], list(Category).index(item[0])),
        )
        primary = ranked[0][0] if ranked else Category.OTHER
        best_score = ranked[0][1] if ranked else 0
        secondary = [category for category, _ in ranked[1:]]
        tied = len(ranked) > 1 and ranked[1][1] == best_score
        out_of_domain = not any(term in normalized for term in HOTEL_TERMS)
        vague = normalized.strip() in {"my hotel experience was terrible.", "my hotel experience was terrible"}
        confidence = (
            0.45 if vague else 0.40 if out_of_domain else 0.66 if tied else min(0.78 + 0.06 * (best_score - 1), 0.96)
        )
        negative = any(
            term in normalized
            for term in ("angry", "furious", "terrible", "charged", "unsafe", "cancelled", "cannot", "would not")
        )
        positive = any(term in normalized for term in ("wonderful", "excellent", "great", "thank you"))
        sentiment = Sentiment.NEGATIVE if negative else Sentiment.POSITIVE if positive else Sentiment.NEUTRAL
        critical = primary == Category.GUEST_SAFETY or any(
            term in normalized for term in ("door would not lock", "fire", "injury")
        )
        high = primary in {Category.OVERBOOKING, Category.DATA_PRIVACY, Category.ACCESSIBILITY_ISSUE}
        urgency = (
            Urgency.CRITICAL
            if critical
            else Urgency.HIGH
            if high
            else Urgency.LOW
            if primary == Category.PRAISE
            else Urgency.MEDIUM
        )
        impact = (
            BusinessImpact.CRITICAL
            if critical
            else BusinessImpact.HIGH
            if high or primary in {Category.REFUND_REQUEST, Category.PAYMENT_ISSUE}
            else BusinessImpact.LOW
            if primary == Category.PRAISE
            else BusinessImpact.MEDIUM
        )
        return ProviderResponse(
            classification=ProviderClassification(
                primary_category=primary,
                secondary_categories=secondary,
                sentiment=sentiment,
                urgency=urgency,
                business_impact=impact,
                confidence=confidence,
                ambiguous=vague or tied or out_of_domain,
                out_of_domain=out_of_domain,
                rationale=(
                    "The feedback is outside the fictional hotel-support domain."
                    if out_of_domain
                    else "The feedback is too broad to identify a specific hotel operation."
                    if vague
                    else f"Matched hotel-support indicators for {primary.value.replace('_', ' ')}."
                ),
            )
        )


class FeedbackClassifier:
    def __init__(
        self,
        provider: ClassificationProvider,
        *,
        confidence_threshold: float,
        max_retries: int,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.provider = provider
        self.confidence_threshold = confidence_threshold
        self.max_retries = max_retries
        self._sleep = sleep

    def classify(self, text: str, *, request_id: str) -> ClassificationResult:
        started = time.monotonic()
        last_error: ClassificationProviderError | None = None
        retries = 0
        for attempt in range(self.max_retries + 1):
            try:
                response = self.provider.classify(text)
                data = response.classification.model_dump()
                data["ambiguous"] = data["ambiguous"] or data["confidence"] < self.confidence_threshold
                data["risk_flags"] = detect_risk_flags(text)
                result = ClassificationResult.model_validate(data)
                self._log(request_id, started, True, retries, response.input_tokens, response.output_tokens)
                return result
            except ClassificationProviderError as exc:
                last_error = exc
                if not exc.retriable or attempt >= self.max_retries:
                    break
                retries += 1
                self._sleep(min(0.1 * (2**attempt), 0.5))
        assert last_error is not None
        self._log(request_id, started, False, retries, error_code=last_error.code)
        return ClassificationResult(
            primary_category=Category.OTHER,
            secondary_categories=[],
            sentiment=Sentiment.NEUTRAL,
            urgency=Urgency.MEDIUM,
            business_impact=BusinessImpact.MEDIUM,
            confidence=0,
            ambiguous=True,
            out_of_domain=False,
            rationale="Automated classification failed; manual hotel-support classification is required.",
            risk_flags=detect_risk_flags(text),
            status=ClassificationStatus.FALLBACK,
            error_code=last_error.code,
        )

    def _log(
        self,
        request_id: str,
        started: float,
        success: bool,
        retries: int,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        error_code: str | None = None,
    ) -> None:
        logger.info(
            "classification_complete request_id=%s provider=%s model=%s duration_ms=%.1f "
            "success=%s retries=%d input_tokens=%s output_tokens=%s error_code=%s",
            request_id,
            self.provider.name,
            self.provider.model,
            (time.monotonic() - started) * 1000,
            success,
            retries,
            input_tokens,
            output_tokens,
            error_code,
        )
