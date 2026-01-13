"""SSE (Server-Sent Events) stream handler for VEO API responses."""

import json
import httpx
from typing import AsyncGenerator, Dict, Any

from utils.exceptions import StreamInterruptedError, VideoGenerationError


async def parse_sse_stream(response: httpx.Response, logger=None) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Parse Server-Sent Events stream from VEO API.

    SSE Format from VEO API:
        data: {"id": "...", "status": "processing", "process_percentage": 45, ...}

        data: {"id": "...", "status": "completed", "file_url": "https://...", ...}

    Args:
        response: httpx Response object with SSE stream
        logger: Optional logger for debugging

    Yields:
        Parsed event data as dictionaries

    Raises:
        VideoGenerationError: Video generation failed (status: 'failed' in event)
        StreamInterruptedError: Stream was interrupted or parsing failed
    """
    event_count = 0
    try:
        if logger:
            logger.debug("Starting SSE stream parsing...")
        
        async for line in response.aiter_lines():
            line = line.strip()

            # Parse data lines
            if line.startswith('data: '):
                data_str = line[6:]  # Remove 'data: ' prefix

                try:
                    event_data = json.loads(data_str)
                    event_count += 1
                    
                    if logger:
                        status = event_data.get('status', 'unknown')
                        progress = event_data.get('process_percentage', 0)
                        logger.debug(f"SSE Event #{event_count}: {status} - {progress}%")

                    # Check for error status in event data
                    if event_data.get('status') == 'failed':
                        error_msg = event_data.get('error', 'Unknown error occurred')
                        if logger:
                            logger.error(f"Video generation failed: {error_msg}")
                        raise VideoGenerationError(f"Video generation failed: {error_msg}")

                    yield event_data

                except json.JSONDecodeError as e:
                    # Log but continue - might be partial data or non-JSON message
                    if logger:
                        logger.warning(f"Failed to parse SSE data: {data_str[:100]}...")
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
        
        if logger:
            logger.debug(f"SSE stream ended. Total events: {event_count}")

    except Exception as e:
        if isinstance(e, VideoGenerationError):
            raise
        if logger:
            logger.error(f"SSE stream interrupted: {str(e)}")
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
