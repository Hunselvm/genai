"""SSE (Server-Sent Events) stream handler for VEO API responses."""

import json
import httpx
import asyncio
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
    last_event_time = asyncio.get_event_loop().time()
    timeout_seconds = 30  # Timeout if no events for 30 seconds
    current_event_type = None  # Track current event type
    
    try:
        if logger:
            logger.debug("Starting SSE stream parsing...")
        
        async for line in response.aiter_lines():
            line = line.strip()
            last_event_time = asyncio.get_event_loop().time()  # Reset timeout on any line
            
            # Log raw lines in debug mode
            if logger and line:
                logger.debug(f"Raw SSE line: {line[:100]}")

            # Parse data lines
            if line.startswith('data:'):
                # Remove 'data:' prefix and optional whitespace
                data_str = line[5:].strip()

                try:
                    # Try parsing as JSON first
                    event_data = json.loads(data_str)
                    event_count += 1
                    
                    # Check if this is an error event (event:error)
                    if current_event_type == 'error':
                        error_msg = event_data.get('error', 'Unknown error occurred')
                        error_code = event_data.get('code', 'Unknown')
                        if logger:
                            logger.error(f"API Error ({error_code}): {error_msg}")
                        # Reset event type
                        current_event_type = None
                        raise VideoGenerationError(f"API Error ({error_code}): {error_msg}")

                    # Handle array responses (multiple videos or completion with array)
                    if isinstance(event_data, list):
                        if logger:
                            logger.debug(f"SSE Event #{event_count}: Received array with {len(event_data)} items")

                        # If it's an array of results, take the first one and mark as completed
                        if len(event_data) > 0 and isinstance(event_data[0], dict):
                            result = event_data[0]
                            # Mark as completed since we received the final results
                            if 'status' not in result:
                                result['status'] = 'completed'
                            if 'process_percentage' not in result:
                                result['process_percentage'] = 100

                            if logger:
                                logger.success(f"Received completion array with {len(event_data)} video(s)")

                            yield result
                        else:
                            # Empty array or unexpected format
                            yield {
                                "status": "completed",
                                "process_percentage": 100,
                                "raw_data": event_data
                            }

                    # Handle dictionary responses (normal progress updates)
                    elif isinstance(event_data, dict):
                        if logger:
                            status = event_data.get('status', 'unknown')
                            progress = event_data.get('process_percentage', 0)
                            logger.debug(f"SSE Event #{event_count}: {status} - {progress}%")

                        # Check for error status in event data
                        if event_data.get('status') == 'failed':
                            error_msg = event_data.get('error', 'Unknown error occurred')
                            if logger:
                                logger.error(f"Video/Image generation failed: {error_msg}")
                            raise VideoGenerationError(f"Generation failed: {error_msg}")

                        yield event_data

                    else:
                        # Unexpected type, wrap it
                        if logger:
                            logger.warning(f"Unexpected data type: {type(event_data)}")
                        yield {
                            "status": "processing",
                            "process_percentage": 0,
                            "raw_data": event_data
                        }

                except json.JSONDecodeError:
                    # If not JSON, it might be a simple status string like "generating"
                    # Create a synthetic event object
                    if logger:
                        logger.debug(f"Received non-JSON data: {data_str}")
                    
                    event_count += 1
                    yield {
                        "status": data_str,
                        "process_percentage": 0, # Unknown progress for simple status
                        "raw_data": data_str
                    }

            # Parse event type (optional, for named events)
            elif line.startswith('event:'):
                event_type = line[6:].strip()
                current_event_type = event_type
                if logger and event_type == 'error':
                    logger.warning("Error event detected")
                continue

            # Empty line signals end of event
            elif line == '':
                continue
        
        if logger:
            if event_count == 0:
                logger.error(f"SSE stream ended with 0 events! This usually means:")
                logger.error("- API rate limiting (quota exceeded)")
                logger.error("- Invalid API key or authentication issue")
                logger.error("- API server error (check status at genaipro.vn)")
            else:
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
