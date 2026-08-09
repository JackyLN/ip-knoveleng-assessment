from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import BusinessImpact, Category, Sentiment, Urgency


class ProviderClassification(BaseModel):
    """Schema supplied to structured-output providers."""

    model_config = ConfigDict(extra="forbid")

    primary_category: Category
    secondary_categories: list[Category]
    sentiment: Sentiment
    urgency: Urgency
    business_impact: BusinessImpact
    confidence: float = Field(ge=0, le=1)
    ambiguous: bool
    out_of_domain: bool
    rationale: str = Field(min_length=1, max_length=500)


@dataclass(frozen=True)
class ProviderResponse:
    classification: ProviderClassification
    input_tokens: int | None = None
    output_tokens: int | None = None


class ClassificationProviderError(RuntimeError):
    def __init__(self, message: str, *, code: str = "provider_error", retriable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.retriable = retriable


class ProviderConfigurationError(ClassificationProviderError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="configuration_error", retriable=False)


class ClassificationProvider(Protocol):
    name: str
    model: str

    def classify(self, feedback_text: str) -> ProviderResponse: ...
