from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class Category(StrEnum):
    BOOKING_ISSUE = "booking_issue"
    CANCELLATION_REQUEST = "cancellation_request"
    REFUND_REQUEST = "refund_request"
    PAYMENT_ISSUE = "payment_issue"
    CHECK_IN_ISSUE = "check_in_issue"
    ROOM_ISSUE = "room_issue"
    HOTEL_SERVICE_COMPLAINT = "hotel_service_complaint"
    OVERBOOKING = "overbooking"
    GUEST_SAFETY = "guest_safety"
    DATA_PRIVACY = "data_privacy"
    ACCESSIBILITY_ISSUE = "accessibility_issue"
    FEATURE_REQUEST = "feature_request"
    PRAISE = "praise"
    ABUSE_POLICY = "abuse_policy"
    OTHER = "other"


class Sentiment(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class Urgency(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class BusinessImpact(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ClassificationStatus(StrEnum):
    SUCCESS = "success"
    FALLBACK = "fallback"


class ReportStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    REQUIRES_REVIEW = "requires_review"
    FAILED = "failed"


class ActionPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FeedbackRequest(BaseModel):
    feedback_text: str = Field(min_length=3, max_length=5000)
    guest_id: str | None = Field(default=None, max_length=100)
    guest_email: EmailStr | None = None
    booking_id: str | None = Field(default=None, max_length=100)
    property_id: str | None = Field(default=None, max_length=100)
    channel: str = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def normalize_fields(self) -> "FeedbackRequest":
        self.feedback_text = self.feedback_text.strip()
        self.channel = self.channel.strip().lower()
        self.guest_id = self.guest_id.strip() if self.guest_id else None
        self.booking_id = self.booking_id.strip() if self.booking_id else None
        self.property_id = self.property_id.strip() if self.property_id else None
        return self


class ClassificationResult(BaseModel):
    primary_category: Category
    secondary_categories: list[Category] = Field(default_factory=list)
    sentiment: Sentiment
    urgency: Urgency
    business_impact: BusinessImpact
    confidence: float = Field(ge=0, le=1)
    ambiguous: bool = False
    out_of_domain: bool = False
    rationale: str = Field(min_length=1, max_length=500)
    risk_flags: list[str] = Field(default_factory=list)
    status: ClassificationStatus = ClassificationStatus.SUCCESS
    error_code: str | None = None


class GuestRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guest_id: str
    name: str
    email: EmailStr
    loyalty_tier: str
    account_created_at: date
    region: str
    previous_stays: int = Field(ge=0)
    previous_support_cases: int = Field(ge=0)
    accessibility_requirements: list[str]
    flags: list[str]


class BookingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    booking_id: str
    guest_id: str
    property_id: str
    room_type: str
    booking_status: str
    check_in_date: date
    check_out_date: date
    number_of_guests: int = Field(ge=1)
    booking_channel: str
    payment_status: str
    total_amount: float = Field(ge=0)
    currency: str
    cancellation_status: str
    cancellation_source: str | None = None
    refund_status: str
    check_in_status: str
    room_assignment: str | None = None
    created_at: datetime
    updated_at: datetime


class PropertyRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property_id: str
    property_name: str
    city: str
    country: str
    property_status: str
    support_contact: EmailStr
    check_in_time: str
    check_out_time: str
    amenities: list[str]
    active_incidents: list[str]
    operational_notes: list[str]
    accessibility_capabilities: list[str]


class WorkflowRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    category: Category
    title: str
    description: str
    required_context: list[str]
    steps: list[str]
    escalation_conditions: list[str]
    allowed_recommendations: list[str]
    financial_action: bool = False
    high_risk_action: bool = False


class PolicyRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str
    title: str
    applicable_categories: list[Category]
    effective_date: date
    version: str
    conditions: list[str]
    exclusions: list[str]
    required_approvals: list[str]
    summary: str


class ToolResult(BaseModel):
    tool_name: str
    found: bool
    ambiguous: bool = False
    data: (
        GuestRecord | BookingRecord | PropertyRecord | WorkflowRecord | list[BookingRecord] | list[PolicyRecord] | None
    ) = None
    summary: str


class GetGuestArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    guest_id: str | None = Field(default=None, max_length=100)
    guest_email: EmailStr | None = None


class GetBookingArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    booking_id: str | None = Field(default=None, max_length=100)
    guest_id: str | None = Field(default=None, max_length=100)


class GetPropertyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    property_id: str = Field(min_length=1, max_length=100)


class GetWorkflowArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Category


class GetPolicyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Category
    property_country: str | None = Field(default=None, max_length=100)
    booking_channel: str | None = Field(default=None, max_length=100)


class TraceStep(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    request_id: str
    event: str
    step: str
    action: str
    tool_name: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    status: str
    result_summary: str
    duration_ms: float | None = Field(default=None, ge=0)
    error_code: str | None = None


class RetrievedContext(BaseModel):
    guest: GuestRecord | None = None
    bookings: list[BookingRecord] = Field(default_factory=list)
    property: PropertyRecord | None = None
    workflow: WorkflowRecord | None = None
    policies: list[PolicyRecord] = Field(default_factory=list)
    attempted_sources: set[str] = Field(default_factory=set)
    required_sources: set[str] = Field(default_factory=set)
    ambiguous_sources: set[str] = Field(default_factory=set)
    failure_codes: list[str] = Field(default_factory=list)
    complete: bool = False


class ReviewDecision(BaseModel):
    required: bool
    reasons: list[str] = Field(default_factory=list)


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    title: str
    version: str | None = None
    reason_used: str = Field(min_length=1, max_length=500)


class SuggestedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str
    priority: ActionPriority
    supporting_source_ids: list[str] = Field(min_length=1)
    requires_approval: bool


class HotelFeedbackReport(BaseModel):
    report_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    original_feedback: str
    feedback_summary: str
    primary_category: Category
    secondary_categories: list[Category]
    sentiment: Sentiment
    urgency: Urgency
    business_impact: BusinessImpact
    classification_confidence: float = Field(ge=0, le=1)
    guest_context: GuestRecord | None
    booking_context: list[BookingRecord]
    property_context: PropertyRecord | None
    workflow_references: list[SourceReference]
    policy_references: list[SourceReference]
    suggested_actions: list[SuggestedAction]
    general_recommendations: list[str]
    missing_context: list[str]
    contradictions: list[str]
    context_complete: bool
    requires_human_review: bool
    human_review_reasons: list[str]
    report_status: ReportStatus


# Backwards-compatible import name for callers from earlier project phases.
StructuredReport = HotelFeedbackReport


class FeedbackAnalysisResponse(BaseModel):
    report: StructuredReport
    trace: list[TraceStep]
