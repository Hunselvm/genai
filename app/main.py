"""FastAPI application for VEO API video generation."""

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.models import (
    TextToVideoRequest,
    QuotaResponse,
    ErrorResponse
)
from app.services.veo_client import VEOClient
from app.services.sse_handler import parse_sse_stream, format_sse_event
from app.utils.exceptions import VEOAPIError, AuthenticationError, QuotaExceededError


# Global VEO client instance
veo_client: VEOClient = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles startup and shutdown events.
    """
    global veo_client

    # Startup
    print("Starting VEO API application...")

    # Initialize VEO client
    veo_client = VEOClient(
        api_key=settings.veo_api_key,
        base_url=settings.veo_base_url
    )

    # Create necessary directories
    Path(settings.upload_dir).mkdir(exist_ok=True)
    Path("data").mkdir(exist_ok=True)

    print(f"Server running at http://{settings.app_host}:{settings.app_port}")

    yield  # Application runs

    # Shutdown
    print("Shutting down VEO API application...")
    if veo_client:
        await veo_client.close()


# Initialize FastAPI app
app = FastAPI(
    title="VEO API Video Generation",
    description="Web application for generating videos using GenAIPro VEO API",
    version="1.0.0",
    lifespan=lifespan
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup templates
templates = Jinja2Templates(directory="templates")


# Exception Handlers

@app.exception_handler(VEOAPIError)
async def veo_exception_handler(request: Request, exc: VEOAPIError):
    """Handle VEO API specific errors."""
    return JSONResponse(
        status_code=400,
        content={
            "error": exc.__class__.__name__,
            "message": str(exc),
            "type": "veo_api_error"
        }
    )


@app.exception_handler(AuthenticationError)
async def auth_exception_handler(request: Request, exc: AuthenticationError):
    """Handle authentication errors."""
    return JSONResponse(
        status_code=401,
        content={
            "error": "AuthenticationError",
            "message": str(exc),
            "type": "auth_error"
        }
    )


@app.exception_handler(QuotaExceededError)
async def quota_exception_handler(request: Request, exc: QuotaExceededError):
    """Handle quota exceeded errors."""
    return JSONResponse(
        status_code=402,
        content={
            "error": "QuotaExceededError",
            "message": str(exc),
            "type": "quota_error"
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle all other exceptions."""
    print(f"Unhandled exception: {exc}")

    return JSONResponse(
        status_code=500,
        content={
            "error": "InternalServerError",
            "message": "An unexpected error occurred. Please try again.",
            "type": "server_error"
        }
    )


# Routes

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render main dashboard."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/quota", response_model=QuotaResponse)
async def get_quota():
    """
    Get current user's VEO quota information.

    Returns:
        Quota information with total, used, and available quota
    """
    quota_data = await veo_client.get_quota()
    return QuotaResponse(**quota_data)


@app.post("/api/video/text-to-video")
async def text_to_video(request: TextToVideoRequest):
    """
    Generate video from text prompt.

    Returns SSE (Server-Sent Events) stream with real-time progress updates.

    Args:
        request: Text-to-video request with prompt, aspect_ratio, number_of_videos

    Returns:
        StreamingResponse with SSE events
    """
    async def event_generator():
        """Generate SSE events from VEO API stream."""
        try:
            async with veo_client.text_to_video_stream(
                prompt=request.prompt,
                aspect_ratio=request.aspect_ratio,
                number_of_videos=request.number_of_videos
            ) as response:
                async for event_data in parse_sse_stream(response):
                    # Forward event to frontend
                    yield format_sse_event(event_data)

                    # Stop after completion or failure
                    if event_data.get('status') in ['completed', 'failed']:
                        break

        except VEOAPIError as e:
            # Send error event
            error_data = {
                "status": "failed",
                "error": str(e),
                "error_type": e.__class__.__name__
            }
            yield format_sse_event(error_data)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.get("/api/history")
async def get_history(page: int = 1, page_size: int = 20):
    """
    Get video generation history.

    Args:
        page: Page number (default: 1)
        page_size: Items per page (default: 20, max: 100)

    Returns:
        History data with pagination
    """
    if page_size > 100:
        page_size = 100

    history_data = await veo_client.get_histories(page=page, page_size=page_size)
    return history_data


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": "1.0.0"}


# Add more routes as needed for frames-to-video, ingredients-to-video, batch processing, etc.
# These will be implemented in subsequent phases
