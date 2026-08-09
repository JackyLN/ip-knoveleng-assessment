from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.agent.classifier import FeedbackClassifier, MockClassificationProvider
from app.agent.context import ContextCoordinator
from app.agent.orchestrator import FeedbackOrchestrator
from app.agent.reporter import GroundedReportGenerator, MockReportProvider
from app.config import BASE_DIR, get_settings
from app.schemas import FeedbackAnalysisResponse, FeedbackRequest
from app.services.data_loader import DataLoadError, JsonDataLoader
from app.services.llm import ClassificationProvider, ProviderConfigurationError
from app.services.openai_provider import OpenAIClassificationProvider
from app.services.openai_report_provider import OpenAIReportProvider
from app.services.openai_tool_provider import OpenAIToolSelectionProvider
from app.services.rate_limit import SlidingWindowRateLimiter
from app.services.tool_calling import MockToolSelectionProvider, ToolSelectionProvider
from app.tools.registry import ToolRegistry

settings = get_settings()
app = FastAPI(title="StayFlow — Hotel Booking and Guest Operations Support")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
analysis_limiter = SlidingWindowRateLimiter(
    limit=settings.analysis_rate_limit_requests,
    window_seconds=settings.analysis_rate_limit_window_seconds,
)


def get_orchestrator() -> FeedbackOrchestrator:
    loader = JsonDataLoader(settings.data_dir)
    tools = ToolRegistry.from_loader(loader)
    classification_provider: ClassificationProvider
    tool_provider: ToolSelectionProvider
    report_provider: MockReportProvider | OpenAIReportProvider
    if settings.llm_provider == "openai":
        api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        classification_provider = OpenAIClassificationProvider(
            api_key=api_key,
            model=settings.openai_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
        tool_provider = OpenAIToolSelectionProvider(
            api_key=api_key,
            model=settings.openai_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
        report_provider = OpenAIReportProvider(
            api_key=api_key,
            model=settings.openai_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    else:
        classification_provider = MockClassificationProvider()
        tool_provider = MockToolSelectionProvider()
        report_provider = MockReportProvider()
    classifier = FeedbackClassifier(
        classification_provider,
        confidence_threshold=settings.classification_confidence_threshold,
        max_retries=settings.llm_max_retries,
    )
    context = ContextCoordinator(tools, tool_provider, max_iterations=5)
    return FeedbackOrchestrator(classifier, context, GroundedReportGenerator(report_provider))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="index.html", context={"error": None, "values": {}})


@app.post("/feedback/analyze", response_class=HTMLResponse)
def analyze_feedback(
    request: Request,
    feedback_text: Annotated[str, Form()],
    channel: Annotated[str, Form()],
    guest_id: Annotated[str | None, Form()] = None,
    guest_email: Annotated[str | None, Form()] = None,
    booking_id: Annotated[str | None, Form()] = None,
    property_id: Annotated[str | None, Form()] = None,
) -> Response:
    if not analysis_limiter.allow():
        return PlainTextResponse(
            "Analysis rate limit exceeded. Try again later.",
            status_code=429,
            headers={"Retry-After": str(settings.analysis_rate_limit_window_seconds)},
        )
    values = {
        "feedback_text": feedback_text,
        "channel": channel,
        "guest_id": guest_id or "",
        "guest_email": guest_email or "",
        "booking_id": booking_id or "",
        "property_id": property_id or "",
    }
    request_id = request.headers.get("x-request-id") or str(uuid4())
    try:
        payload = FeedbackRequest(
            feedback_text=feedback_text,
            guest_id=guest_id or None,
            guest_email=guest_email or None,
            booking_id=booking_id or None,
            property_id=property_id or None,
            channel=channel,
        )
        analysis = get_orchestrator().analyze(payload, request_id=request_id)
    except ValidationError as exc:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"error": exc.errors()[0]["msg"], "values": values},
            status_code=422,
        )
    except DataLoadError:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"error": "Reference data could not be loaded. Check the local JSON files.", "values": values},
            status_code=500,
        )
    except ProviderConfigurationError as exc:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"error": str(exc), "values": values},
            status_code=503,
        )
    response = templates.TemplateResponse(
        request=request, name="result.html", context={"analysis": analysis, "request_id": request_id}
    )
    response.headers["x-request-id"] = request_id
    return response


@app.post("/api/feedback/analyze", response_model=FeedbackAnalysisResponse)
def analyze_feedback_json(payload: FeedbackRequest, request: Request) -> FeedbackAnalysisResponse:
    """Return the complete structured runtime report and safe execution trace."""
    if not analysis_limiter.allow():
        raise HTTPException(
            status_code=429,
            detail="Analysis rate limit exceeded. Try again later.",
            headers={"Retry-After": str(settings.analysis_rate_limit_window_seconds)},
        )
    request_id = request.headers.get("x-request-id") or str(uuid4())
    try:
        return get_orchestrator().analyze(payload, request_id=request_id)
    except DataLoadError as exc:
        raise HTTPException(status_code=500, detail="Reference data could not be loaded.") from exc
    except ProviderConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.exception_handler(RequestValidationError)
async def form_validation_error(request: Request, exc: RequestValidationError) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"error": "Please complete all required fields.", "values": {}},
        status_code=422,
    )
