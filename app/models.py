"""Pydantic models for request and response validation."""

from typing import Optional, List
from pydantic import BaseModel, Field, validator


class TextToVideoRequest(BaseModel):
    """Request model for text-to-video generation."""

    prompt: str = Field(..., min_length=1, description="Text description for video")
    aspect_ratio: str = Field(
        ...,
        description="Aspect ratio: VIDEO_ASPECT_RATIO_LANDSCAPE or VIDEO_ASPECT_RATIO_PORTRAIT"
    )
    number_of_videos: int = Field(1, ge=1, le=4, description="Number of videos (1-4)")

    @validator('prompt')
    def prompt_not_empty(cls, v):
        """Ensure prompt is not empty."""
        if not v.strip():
            raise ValueError('Prompt cannot be empty')
        return v.strip()

    @validator('aspect_ratio')
    def valid_aspect_ratio(cls, v):
        """Validate aspect ratio value."""
        valid = ['VIDEO_ASPECT_RATIO_LANDSCAPE', 'VIDEO_ASPECT_RATIO_PORTRAIT']
        if v not in valid:
            raise ValueError(f'Invalid aspect ratio. Must be one of: {valid}')
        return v


class FramesToVideoRequest(BaseModel):
    """Request model for frames-to-video generation."""

    prompt: str = Field(..., min_length=1, description="Text description for video")

    @validator('prompt')
    def prompt_not_empty(cls, v):
        """Ensure prompt is not empty."""
        if not v.strip():
            raise ValueError('Prompt cannot be empty')
        return v.strip()


class IngredientsToVideoRequest(BaseModel):
    """Request model for ingredients-to-video generation."""

    prompt: str = Field(..., min_length=1, description="Text description for video")

    @validator('prompt')
    def prompt_not_empty(cls, v):
        """Ensure prompt is not empty."""
        if not v.strip():
            raise ValueError('Prompt cannot be empty')
        return v.strip()


class BatchJobRequest(BaseModel):
    """Request model for adding a batch job."""

    job_type: str = Field(..., description="Job type: text, frames, or ingredients")
    config: dict = Field(..., description="Job configuration")

    @validator('job_type')
    def valid_job_type(cls, v):
        """Validate job type."""
        valid = ['text', 'frames', 'ingredients']
        if v not in valid:
            raise ValueError(f'Invalid job type. Must be one of: {valid}')
        return v


class ScanDirectoryRequest(BaseModel):
    """Request model for scanning directory for images."""

    directory_path: str = Field(..., min_length=1, description="Path to directory")

    @validator('directory_path')
    def path_not_empty(cls, v):
        """Ensure path is not empty."""
        if not v.strip():
            raise ValueError('Directory path cannot be empty')
        return v.strip()


class QuotaResponse(BaseModel):
    """Response model for quota information."""

    total_quota: int
    used_quota: int
    available_quota: int


class ErrorResponse(BaseModel):
    """Error response model."""

    error: str
    message: str
    type: str


class BatchJobStatus(BaseModel):
    """Status of a batch job."""

    id: str
    type: str
    config: dict
    status: str
    progress: int
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str


class ImageFile(BaseModel):
    """Image file information."""

    path: str
    filename: str
    size: int
    format: str
    thumbnail_url: Optional[str] = None
