"""VEO API client wrapper for handling all API interactions."""

import asyncio
import httpx
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict, Any, List, Optional

from utils.exceptions import (
    AuthenticationError,
    NetworkError,
    QuotaExceededError,
    VideoGenerationError
)


class VEOClient:
    """Client for interacting with the GenAIPro VEO API."""

    def __init__(self, api_key: str, base_url: str, timeout: float = 300.0):
        """
        Initialize VEO API client.

        Args:
            api_key: JWT token for authentication
            base_url: Base URL for the API (e.g., https://genaipro.vn/api/v1)
            timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout

        # Configure timeout with longer read timeout for streaming
        timeout_config = httpx.Timeout(
            timeout=10.0,      # Connection timeout
            read=timeout,       # Read timeout (for SSE streaming)
            write=30.0,         # Write timeout
            pool=5.0            # Pool timeout
        )

        # Configure limits for connection pooling
        limits = httpx.Limits(
            max_keepalive_connections=5,
            max_connections=10,
            keepalive_expiry=30.0
        )

        # Create client with proper configuration
        self.client = httpx.AsyncClient(
            timeout=timeout_config,
            limits=limits,
            follow_redirects=True
        )

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        max_retries: int = 3,
        **kwargs
    ) -> httpx.Response:
        """
        Make HTTP request with retry logic for transient errors.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            max_retries: Maximum number of retry attempts
            **kwargs: Additional arguments for httpx.request

        Returns:
            HTTP response

        Raises:
            AuthenticationError: Invalid API key
            QuotaExceededError: API quota exceeded
            NetworkError: Network connection failed
        """
        base_delay = 1

        for attempt in range(max_retries):
            try:
                response = await self.client.request(method, url, **kwargs)
                response.raise_for_status()
                return response

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:  # Rate limit
                    retry_after = int(e.response.headers.get('Retry-After', 60))
                    await asyncio.sleep(retry_after)
                    continue

                elif e.response.status_code == 401:  # Auth error
                    raise AuthenticationError("Invalid API key")

                elif e.response.status_code == 402:  # Payment required / Quota exceeded
                    raise QuotaExceededError("API quota exceeded")

                elif e.response.status_code >= 500:  # Server error
                    if attempt < max_retries - 1:
                        await asyncio.sleep(base_delay * (2 ** attempt))
                        continue
                raise NetworkError(f"HTTP {e.response.status_code}: {e.response.text}")

            except (httpx.NetworkError, httpx.TimeoutException) as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(base_delay * (2 ** attempt))
                    continue
                raise NetworkError(f"Failed to connect to VEO API: {str(e)}")

        raise NetworkError(f"Max retries ({max_retries}) exceeded")

    async def get_quota(self) -> Dict[str, Any]:
        """
        Get current user's VEO quota information.

        Returns:
            Dictionary with quota info:
            {
                "total_quota": int,
                "used_quota": int,
                "available_quota": int
            }

        Raises:
            AuthenticationError: Invalid API key
            NetworkError: Connection failed
        """
        url = f"{self.base_url}/veo/me"
        response = await self._request_with_retry(
            "GET",
            url,
            headers=self._get_headers()
        )
        return response.json()

    @asynccontextmanager
    async def text_to_video_stream(
        self,
        prompt: str,
        aspect_ratio: str,
        number_of_videos: int = 1
    ) -> AsyncGenerator[httpx.Response, None]:
        """
        Stream SSE response for text-to-video generation.

        Args:
            prompt: Text description for video
            aspect_ratio: VIDEO_ASPECT_RATIO_LANDSCAPE or VIDEO_ASPECT_RATIO_PORTRAIT
            number_of_videos: Number of videos to generate (1-4)

        Yields:
            httpx.Response with SSE stream

        Raises:
            VideoGenerationError: Video generation failed
            NetworkError: Connection failed
        """
        url = f"{self.base_url}/veo/text-to-video"
        headers = self._get_headers()
        payload = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "number_of_videos": number_of_videos
        }

        try:
            async with self.client.stream('POST', url, json=payload, headers=headers) as response:
                response.raise_for_status()
                yield response
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid API key")
            elif e.response.status_code == 402:
                raise QuotaExceededError("API quota exceeded")
            raise VideoGenerationError(f"Video generation failed: {e.response.text}")
        except httpx.ReadError as e:
            raise NetworkError(f"Connection closed unexpectedly. Please try again: {str(e)}")
        except httpx.RemoteProtocolError as e:
            raise NetworkError(f"Server connection error. Please try again: {str(e)}")
        except httpx.ConnectError as e:
            raise NetworkError(f"Cannot connect to VEO API. Check your internet connection: {str(e)}")
        except (httpx.NetworkError, httpx.TimeoutException) as e:
            raise NetworkError(f"Connection failed: {str(e)}")

    @asynccontextmanager
    async def frames_to_video_stream(
        self,
        start_frame_path: str,
        end_frame_path: Optional[str],
        prompt: str
    ) -> AsyncGenerator[httpx.Response, None]:
        """
        Stream SSE response for frames-to-video generation.

        Args:
            start_frame_path: Path to start frame image
            end_frame_path: Path to end frame image (optional)
            prompt: Text description for video

        Yields:
            httpx.Response with SSE stream

        Raises:
            VideoGenerationError: Video generation failed
            NetworkError: Connection failed
        """
        url = f"{self.base_url}/veo/frames-to-video"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        # Read file contents into memory for streaming
        with open(start_frame_path, 'rb') as f:
            start_frame_data = f.read()

        files = {
            'start_frame': ('start_frame.jpg', start_frame_data, 'image/jpeg')
        }

        if end_frame_path:
            with open(end_frame_path, 'rb') as f:
                end_frame_data = f.read()
            files['end_frame'] = ('end_frame.jpg', end_frame_data, 'image/jpeg')

        data = {'prompt': prompt}

        try:
            async with self.client.stream('POST', url, files=files, data=data, headers=headers) as response:
                response.raise_for_status()
                yield response
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid API key")
            elif e.response.status_code == 402:
                raise QuotaExceededError("API quota exceeded")
            raise VideoGenerationError(f"Video generation failed: {e.response.text}")
        except httpx.ReadError as e:
            raise NetworkError(f"Connection closed unexpectedly. Please try again: {str(e)}")
        except httpx.RemoteProtocolError as e:
            raise NetworkError(f"Server connection error. Please try again: {str(e)}")
        except httpx.ConnectError as e:
            raise NetworkError(f"Cannot connect to VEO API. Check your internet connection: {str(e)}")
        except (httpx.NetworkError, httpx.TimeoutException) as e:
            raise NetworkError(f"Connection failed: {str(e)}")

    @asynccontextmanager
    async def ingredients_to_video_stream(
        self,
        image_paths: List[str],
        prompt: str
    ) -> AsyncGenerator[httpx.Response, None]:
        """
        Stream SSE response for ingredients-to-video generation.

        Args:
            image_paths: List of paths to reference images
            prompt: Text description for video

        Yields:
            httpx.Response with SSE stream

        Raises:
            VideoGenerationError: Video generation failed
            NetworkError: Connection failed
        """
        url = f"{self.base_url}/veo/ingredients-to-video"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        # Read all image files into memory for streaming
        files = []
        for idx, img_path in enumerate(image_paths):
            with open(img_path, 'rb') as f:
                image_data = f.read()
            files.append(('images', (f'image_{idx}.jpg', image_data, 'image/jpeg')))

        data = {'prompt': prompt}

        try:
            async with self.client.stream('POST', url, files=files, data=data, headers=headers) as response:
                response.raise_for_status()
                yield response
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid API key")
            elif e.response.status_code == 402:
                raise QuotaExceededError("API quota exceeded")
            raise VideoGenerationError(f"Video generation failed: {e.response.text}")
        except httpx.ReadError as e:
            raise NetworkError(f"Connection closed unexpectedly. Please try again: {str(e)}")
        except httpx.RemoteProtocolError as e:
            raise NetworkError(f"Server connection error. Please try again: {str(e)}")
        except httpx.ConnectError as e:
            raise NetworkError(f"Cannot connect to VEO API. Check your internet connection: {str(e)}")
        except (httpx.NetworkError, httpx.TimeoutException) as e:
            raise NetworkError(f"Connection failed: {str(e)}")

    async def get_histories(self, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """
        Get video/image generation history.

        Args:
            page: Page number (starts from 1)
            page_size: Items per page (max 100)

        Returns:
            Dictionary with history data and pagination info

        Raises:
            AuthenticationError: Invalid API key
            NetworkError: Connection failed
        """
        url = f"{self.base_url}/veo/histories"
        params = {"page": page, "page_size": page_size}

        response = await self._request_with_retry(
            "GET",
            url,
            headers=self._get_headers(),
            params=params
        )
        return response.json()
