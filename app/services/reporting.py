from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import SourceReference, SuggestedAction


class ReportProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback_summary: str = Field(min_length=1, max_length=500)
    workflow_references: list[SourceReference]
    policy_references: list[SourceReference]
    suggested_actions: list[SuggestedAction]
    general_recommendations: list[str]
    contradictions: list[str]
    requires_human_review: bool
    human_review_reasons: list[str]


@dataclass(frozen=True)
class ReportProviderResponse:
    proposal: ReportProposal
    input_tokens: int | None = None
    output_tokens: int | None = None


class ReportProviderError(RuntimeError):
    def __init__(self, message: str, *, code: str = "report_provider_error") -> None:
        super().__init__(message)
        self.code = code


class ReportProvider(Protocol):
    name: str
    model: str

    def generate(self, grounded_input: str) -> ReportProviderResponse: ...
