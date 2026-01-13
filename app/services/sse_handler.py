"""SSE (Server-Sent Events) stream handler for VEO API responses."""

import json
import httpx
from typing import AsyncGenerator, Dict, Any

from app.utils.exceptions import StreamInterruptedError, VideoGenerationError


async def parse_sse_stream(response: httpx.Response) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Parse Server-Sent Events stream from VEO API.

    SSE Format from VEO API:
        data: {"id": "...", "status": "processing", "process_percentage": 45, ...}

        data: {"id": "...", "status": "completed", "file_url": "https://...", ...}

    Args:
        response: httpx Response object with SSE stream

    Yields:
        Parsed event data as dictionaries

    Raises:
        VideoGenerationError: Video generation failed (status: 'failed' in event)
        StreamInterruptedError: Stream was interrupted or parsing failed
    """
    try:
        async for line in response.aiter_lines():
            line = line.strip()

            # Parse data lines
            if line.startswith('data: '):
                data_str = line[6:]  # Remove 'data: ' prefix

                try:
                    event_data = json.loads(data_str)

                    # Check for error status in event data
                    if event_data.get('status') == 'failed':
                        error_msg = event_data.get('error', 'Unknown error occurred')
                        raise VideoGenerationError(f"Video generation failed: {error_msg}")

                    yield event_data

                except json.JSONDecodeError:
                    # Log but continue - might be partial data or non-JSON message
                    print(f"Warning: Failed to parse SSE data: {data_str}")
                    continue

            # Parse event type (optional, for named events)
            elif line.startswith('event: '):
                event_name = line[7:]
                # Could be used for different event types if needed
                continue

            # Empty line signals end of event
            elif line == '':
                continue

    except Exception as e:
        if isinstance(e, VideoGenerationError):
            raise
        raise StreamInterruptedError(f"SSE stream interrupted: {str(e)}")


async def parse_sse_stream_with_progress(
    response: httpx.Response
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Parse SSE stream and add progress tracking.

    This enhanced version tracks completion and provides additional metadata.

    Args:
        response: httpx Response object with SSE stream

    Yields:
        Event data with progress information
    """
    last_progress = 0

    async for event_data in parse_sse_stream(response):
        # Track progress
        current_progress = event_data.get('process_percentage', last_progress)
        last_progress = current_progress

        # Add progress metadata
        event_data['_progress'] = current_progress
        event_data['_is_complete'] = event_data.get('status') == 'completed'
        event_data['_is_processing'] = event_data.get('status') == 'processing'

        yield event_data


def format_sse_event(data: Dict[str, Any], event_type: str = "message") -> str:
    """
    Format data as SSE event for forwarding to frontend.

    Args:
        data: Event data to format
        event_type: Event type name (optional)

    Returns:
        Formatted SSE event string
    """
    lines = []

    if event_type and event_type != "message":
        lines.append(f"event: {event_type}")

    lines.append(f"data: {json.dumps(data)}")
    lines.append("")  # Empty line signals end of event

    return "\n".join(lines) + "\n"
