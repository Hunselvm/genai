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

    def __init__(self, api_key: str, base_url: str, timeout: float = 300.0, debug: bool = False, logger=None):
        """
        Initialize VEO API client.

        Args:
            api_key: JWT token for authentication
            base_url: Base URL for the API (e.g., https://genaipro.vn/api/v1)
            timeout: Request timeout in seconds
            debug: Enable debug logging
            logger: Optional logger instance for output
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.debug = debug
        self.logger = logger

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

    def _log(self, message: str, level: str = "info"):
        """Log message if logger is available."""
        if self.logger:
            if level == "error":
                self.logger.error(message)
            elif level == "warning":
                self.logger.warning(message)
            elif level == "debug":
                self.logger.debug(message)
            else:
                self.logger.info(message)

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        max_retries: int = 3,
        on_retry=None,
        **kwargs
    ) -> httpx.Response:
        """
        Make HTTP request with retry logic for transient errors.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            max_retries: Maximum number of retry attempts
            on_retry: Optional callback function called on retry (retry_num, delay)
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
                if self.debug:
                    self._log(f"API Request: {method} {url}", "debug")
                
                response = await self.client.request(method, url, **kwargs)
                
                if self.debug:
                    self._log(f"API Response: {response.status_code}", "debug")
                
                response.raise_for_status()
                return response

            except httpx.HTTPStatusError as e:
                error_detail = e.response.text[:200] if e.response.text else "No details"
                
                if e.response.status_code == 429:  # Rate limit
                    retry_after = int(e.response.headers.get('Retry-After', 60))
                    self._log(f"Rate limited. Waiting {retry_after}s before retry...", "warning")
                    
                    if on_retry:
                        on_retry(attempt + 1, retry_after)
                    
                    await asyncio.sleep(retry_after)
                    continue

                elif e.response.status_code == 401:  # Auth error
                    self._log(f"Authentication failed: {error_detail}", "error")
                    raise AuthenticationError(f"Invalid API key: {error_detail}")

                elif e.response.status_code == 402:  # Payment required / Quota exceeded
                    self._log(f"Quota exceeded: {error_detail}", "error")
                    raise QuotaExceededError(f"API quota exceeded: {error_detail}")

                elif e.response.status_code >= 500:  # Server error
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        self._log(f"Server error (attempt {attempt + 1}/{max_retries}). Retrying in {delay}s...", "warning")
                        
                        if on_retry:
                            on_retry(attempt + 1, delay)
                        
                        await asyncio.sleep(delay)
                        continue
                    
                self._log(f"HTTP error {e.response.status_code}: {error_detail}", "error")
                raise NetworkError(f"HTTP {e.response.status_code}: {error_detail}")

            except (httpx.NetworkError, httpx.TimeoutException) as e:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    self._log(f"Network error (attempt {attempt + 1}/{max_retries}). Retrying in {delay}s...", "warning")
                    
                    if on_retry:
                        on_retry(attempt + 1, delay)
                    
                    await asyncio.sleep(delay)
                    continue
                
                self._log(f"Network error: {str(e)}", "error")
                raise NetworkError(f"Failed to connect to VEO API: {str(e)}")

        self._log(f"Max retries ({max_retries}) exceeded", "error")
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
            if self.debug:
                self._log(f"Starting text-to-video stream: {prompt[:50]}...", "debug")
            
            async with self.client.stream('POST', url, json=payload, headers=headers) as response:
                if self.debug:
                    self._log(f"Stream connected: {response.status_code}", "debug")
                
                response.raise_for_status()
                yield response
        except httpx.HTTPStatusError as e:
            await e.response.aread()
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
            await e.response.aread()
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
            await e.response.aread()
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
    async def create_image_stream(
        self,
        prompt: str,
        aspect_ratio: str,
        number_of_images: int = 1,
        reference_images: Optional[List[str]] = None
    ) -> AsyncGenerator[httpx.Response, None]:
        """
        Stream SSE response for image generation.

        Args:
            prompt: Text description for image
            aspect_ratio: IMAGE_ASPECT_RATIO_LANDSCAPE, IMAGE_ASPECT_RATIO_PORTRAIT, or IMAGE_ASPECT_RATIO_SQUARE
            number_of_images: Number of images to generate (1-4)
            reference_images: Optional list of paths to reference images

        Yields:
            httpx.Response with SSE stream

        Raises:
            VideoGenerationError: Image generation failed
            NetworkError: Connection failed
        """
        url = f"{self.base_url}/veo/create-image"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        # Prepare form data
        data = {
            'prompt': prompt,
            'aspect_ratio': aspect_ratio,
            'number_of_images': str(number_of_images)
        }

        # Add reference images if provided
        files = []
        if reference_images:
            for idx, img_path in enumerate(reference_images):
                with open(img_path, 'rb') as f:
                    image_data = f.read()
                files.append(('reference_images', (f'ref_{idx}.jpg', image_data, 'image/jpeg')))

        try:
            if self.debug:
                self._log(f"Starting image generation: {prompt[:50]}...", "debug")
            
            if files:
                async with self.client.stream('POST', url, files=files, data=data, headers=headers) as response:
                    if self.debug:
                        self._log(f"Stream connected: {response.status_code}", "debug")
                    response.raise_for_status()
                    yield response
            else:
                # No files, use form data only
                async with self.client.stream('POST', url, data=data, headers=headers) as response:
                    if self.debug:
                        self._log(f"Stream connected: {response.status_code}", "debug")
                    response.raise_for_status()
                    yield response
        except httpx.HTTPStatusError as e:
            await e.response.aread()
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid API key")
            elif e.response.status_code == 402:
                raise QuotaExceededError("API quota exceeded")
            raise VideoGenerationError(f"Image generation failed: {e.response.text}")
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
