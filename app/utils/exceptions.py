"""Custom exception classes for VEO API interactions."""


class VEOAPIError(Exception):
    """Base exception for VEO API errors."""
    pass


class AuthenticationError(VEOAPIError):
    """Invalid API key or authentication failed."""
    pass


class QuotaExceededError(VEOAPIError):
    """API quota exceeded."""
    pass


class VideoGenerationError(VEOAPIError):
    """Video generation failed."""
    pass


class StreamInterruptedError(VEOAPIError):
    """SSE stream was interrupted."""
    pass


class InvalidImageError(VEOAPIError):
    """Invalid image file or format."""
    pass


class NetworkError(VEOAPIError):
    """Network connection error."""
    pass
