from typing import Any

from app.schemas import TraceStep


class ExecutionTrace:
    """Collects safe operational metadata, never hidden reasoning."""

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self._steps: list[TraceStep] = []

    def add(
        self,
        *,
        step: str,
        action: str,
        status: str,
        result_summary: str,
        event: str | None = None,
        tool_name: str | None = None,
        inputs: dict[str, Any] | None = None,
        duration_ms: float | None = None,
        error_code: str | None = None,
    ) -> None:
        self._steps.append(
            TraceStep(
                request_id=self.request_id,
                event=event or step,
                step=step,
                action=action,
                tool_name=tool_name,
                inputs=inputs or {},
                status=status,
                result_summary=result_summary,
                duration_ms=duration_ms,
                error_code=error_code,
            )
        )

    @property
    def steps(self) -> list[TraceStep]:
        return list(self._steps)
