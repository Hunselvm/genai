"""Automation Engine Module

Core processing logic for automated video/image generation.
Completely Streamlit-free for testability.
"""

import asyncio
import io
import os
import csv
import time
import tempfile
import zipfile
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Dict, Optional, Callable, Any
import httpx

from utils.veo_client import VEOClient
from utils.sse_handler import parse_sse_stream
from utils.progress_persistence import AutomationJob, save_job


# =============================================================================
# Configuration
# =============================================================================

RETRY_CONFIG = {
    'images': {
        'timeout_minutes': 10,
        'initial_poll_seconds': 5,
        'max_poll_seconds': 30,
        'max_concurrent': 5,
        'requests_per_minute': 30
    },
    'videos': {
        'timeout_minutes': 20,
        'initial_poll_seconds': 5,
        'max_poll_seconds': 45,
        'max_concurrent': 3,
        'requests_per_minute': 20
    }
}

MAX_ZIP_SIZE_MB = 200


# =============================================================================
# Error Categorization
# =============================================================================

class ErrorCategory(Enum):
    PERMANENT = "permanent"      # Don't retry - content policy, auth errors
    RETRYABLE = "retryable"      # Retry - timeout, rate limit, server errors
    UNKNOWN = "unknown"          # Retry with warning


PERMANENT_ERROR_PATTERNS = [
    "content policy",
    "blocked",
    "authentication",
    "unauthorized",
    "forbidden",
    "invalid api key",
    "account suspended",
    "inappropriate",
    "violates",
    "not allowed"
]

RETRYABLE_ERROR_PATTERNS = [
    "timeout",
    "timed out",
    "rate limit",
    "too many requests",
    "server error",
    "internal error",
    "503",
    "502",
    "500",
    "connection",
    "network",
    "temporarily",
    "try again",
    "overloaded",
    "recaptcha"
]


def categorize_error(error_msg: str) -> ErrorCategory:
    """Categorize an error message to determine retry strategy."""
    error_lower = error_msg.lower()
    
    for pattern in PERMANENT_ERROR_PATTERNS:
        if pattern in error_lower:
            return ErrorCategory.PERMANENT
    
    for pattern in RETRYABLE_ERROR_PATTERNS:
        if pattern in error_lower:
            return ErrorCategory.RETRYABLE
    
    return ErrorCategory.UNKNOWN


# =============================================================================
# Rate Limiter
# =============================================================================

class RateLimiter:
    """Token bucket rate limiter for API requests."""
    
    def __init__(self, requests_per_minute: int):
        self.rpm = requests_per_minute
        self.timestamps: deque = deque()
        self._lock = asyncio.Lock()
    
    async def acquire(self):
        """Wait until we can make a request without exceeding rate limit."""
        async with self._lock:
            now = time.time()
            
            # Remove timestamps older than 1 minute
            while self.timestamps and now - self.timestamps[0] > 60:
                self.timestamps.popleft()
            
            # If at limit, wait
            if len(self.timestamps) >= self.rpm:
                sleep_time = 60 - (now - self.timestamps[0]) + 0.1
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                    # Clean up again after sleeping
                    now = time.time()
                    while self.timestamps and now - self.timestamps[0] > 60:
                        self.timestamps.popleft()
            
            self.timestamps.append(time.time())


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ProcessingItem:
    """Represents an item to be processed."""
    id: str
    prompt: str
    count: int = 1  # number_of_images or number_of_videos
    reference_frame_url: Optional[str] = None
    reference_frame_path: Optional[str] = None


@dataclass
class ProcessingResult:
    """Result of processing an item."""
    id: str
    prompt: str
    status: str  # 'completed', 'failed'
    urls: List[str] = field(default_factory=list)
    error: Optional[str] = None
    error_category: Optional[str] = None
    bytes_list: List[bytes] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'prompt': self.prompt,
            'status': self.status,
            'urls': self.urls,
            'error': self.error,
            'error_category': self.error_category
        }


# =============================================================================
# Input Validation
# =============================================================================

def validate_prompts(items: List[Dict]) -> tuple[List[Dict], List[str]]:
    """Validate prompts before processing.
    
    Returns:
        Tuple of (valid_items, error_messages)
    """
    valid = []
    errors = []
    
    for item in items:
        prompt = item.get('prompt', '').strip()
        item_id = item.get('id', 'unknown')
        
        if not prompt:
            errors.append(f"{item_id}: Empty prompt")
        elif len(prompt) < 10:
            errors.append(f"{item_id}: Too short (min 10 chars, got {len(prompt)})")
        elif len(prompt) > 2000:
            errors.append(f"{item_id}: Too long (max 2000 chars, got {len(prompt)})")
        else:
            valid.append(item)
    
    return valid, errors


# =============================================================================
# Automation Engine
# =============================================================================

class AutomationEngine:
    """Core engine for automated content generation."""
    
    def __init__(
        self,
        client: VEOClient,
        content_type: str = 'videos',
        progress_callback: Optional[Callable[[str, Dict], None]] = None,
        logger = None
    ):
        self.client = client
        self.content_type = content_type
        self.config = RETRY_CONFIG[content_type]
        self.progress_callback = progress_callback
        self.logger = logger
        
        self.semaphore = asyncio.Semaphore(self.config['max_concurrent'])
        self.rate_limiter = RateLimiter(self.config['requests_per_minute'])
        
        self.results: Dict[str, ProcessingResult] = {}
        self._stop_requested = False
    
    def request_stop(self):
        """Request graceful stop of processing."""
        self._stop_requested = True
    
    def _emit_progress(self, event_type: str, data: Dict):
        """Emit progress event if callback is set."""
        if self.progress_callback:
            self.progress_callback(event_type, data)
    
    def _log(self, level: str, message: str):
        """Log a message if logger is available."""
        if self.logger:
            if level == 'info':
                self.logger.info(message)
            elif level == 'success':
                self.logger.success(message)
            elif level == 'warning':
                self.logger.warning(message)
            elif level == 'error':
                self.logger.error(message)
    
    async def _poll_with_backoff(
        self,
        item: ProcessingItem,
        check_func: Callable
    ) -> Optional[Dict]:
        """Poll for completion with exponential backoff."""
        start_time = time.time()
        poll_interval = self.config['initial_poll_seconds']
        
        while True:
            elapsed = time.time() - start_time
            timeout_seconds = self.config['timeout_minutes'] * 60
            
            if elapsed > timeout_seconds:
                raise TimeoutError(
                    f"Generation exceeded {self.config['timeout_minutes']}min timeout"
                )
            
            await asyncio.sleep(poll_interval)
            
            try:
                result = await check_func(item)
                if result:
                    if result.get('status') == 'completed':
                        return result
                    elif result.get('status') == 'failed':
                        raise Exception(result.get('error', 'Generation failed'))
            except Exception as e:
                if 'completed' in str(e) or 'failed' in str(e):
                    raise
                self._log('warning', f"Poll error for {item.id}: {e}")
            
            # Exponential backoff with cap
            poll_interval = min(
                poll_interval * 1.5,
                self.config['max_poll_seconds']
            )
    
    async def _check_history_for_item(self, item: ProcessingItem) -> Optional[Dict]:
        """Check generation history for a completed item."""
        try:
            history = await self.client.get_histories(page=1, page_size=10)
            if not history or not history.get('data'):
                return None
            
            for hist_item in history['data']:
                hist_prompt = hist_item.get('prompt', '').lower()
                if item.prompt.lower() in hist_prompt or hist_prompt in item.prompt.lower():
                    return hist_item
            
            return None
        except Exception as e:
            self._log('warning', f"History check failed: {e}")
            return None
    
    async def _download_content(self, urls: List[str]) -> List[bytes]:
        """Download content from URLs."""
        bytes_list = []
        async with httpx.AsyncClient(timeout=60.0) as client:
            for url in urls:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        bytes_list.append(resp.content)
                except Exception as e:
                    self._log('warning', f"Download failed: {e}")
        return bytes_list
    
    async def generate_single_image(
        self,
        item: ProcessingItem,
        aspect_ratio: str
    ) -> ProcessingResult:
        """Generate images for a single prompt."""
        async with self.semaphore:
            await self.rate_limiter.acquire()
            
            if self._stop_requested:
                return ProcessingResult(
                    id=item.id,
                    prompt=item.prompt,
                    status='failed',
                    error='Processing stopped by user'
                )
            
            self._emit_progress('item_started', {'id': item.id, 'prompt': item.prompt})
            self._log('info', f"Starting image generation: {item.id}")
            
            try:
                result = None
                
                # Try SSE stream first
                try:
                    async with self.client.create_image_stream(
                        prompt=item.prompt,
                        aspect_ratio=aspect_ratio,
                        number_of_images=item.count,
                        reference_images=[item.reference_frame_path] if item.reference_frame_path else None
                    ) as response:
                        async for event_data in parse_sse_stream(response, logger=self.logger):
                            status = event_data.get('status', 'processing')
                            
                            if status == 'completed':
                                result = event_data
                                break
                            elif status == 'failed':
                                raise Exception(event_data.get('error', 'Generation failed'))
                except Exception as stream_error:
                    self._log('warning', f"Stream failed for {item.id}: {stream_error}, switching to polling")
                
                # If no result from stream, poll history
                if not result:
                    result = await self._poll_with_backoff(
                        item,
                        self._check_history_for_item
                    )
                
                if not result:
                    raise Exception("No result received")
                
                # Extract URLs
                urls = result.get('file_urls', [])
                if not urls and result.get('file_url'):
                    urls = [result.get('file_url')]
                
                # Download content
                bytes_list = await self._download_content(urls)
                
                self._log('success', f"Completed: {item.id}")
                self._emit_progress('item_completed', {'id': item.id, 'urls': urls})
                
                return ProcessingResult(
                    id=item.id,
                    prompt=item.prompt,
                    status='completed',
                    urls=urls,
                    bytes_list=bytes_list
                )
            
            except Exception as e:
                error_msg = str(e)
                error_cat = categorize_error(error_msg)
                
                self._log('error', f"Failed: {item.id} - {error_msg}")
                self._emit_progress('item_failed', {
                    'id': item.id,
                    'error': error_msg,
                    'category': error_cat.value
                })
                
                return ProcessingResult(
                    id=item.id,
                    prompt=item.prompt,
                    status='failed',
                    error=error_msg,
                    error_category=error_cat.value
                )
    
    async def generate_single_video(
        self,
        item: ProcessingItem,
        aspect_ratio: str,
        start_frame_path: Optional[str] = None
    ) -> ProcessingResult:
        """Generate videos for a single prompt."""
        async with self.semaphore:
            await self.rate_limiter.acquire()
            
            if self._stop_requested:
                return ProcessingResult(
                    id=item.id,
                    prompt=item.prompt,
                    status='failed',
                    error='Processing stopped by user'
                )
            
            self._emit_progress('item_started', {'id': item.id, 'prompt': item.prompt})
            self._log('info', f"Starting video generation: {item.id}")
            
            # Use item's reference frame if provided, otherwise use passed frame
            frame_path = item.reference_frame_path or start_frame_path
            
            try:
                result = None
                
                # Try SSE stream first
                try:
                    if frame_path:
                        # Frames to video
                        async with self.client.frames_to_video_stream(
                            start_frame_path=frame_path,
                            end_frame_path=None,
                            prompt=item.prompt,
                            aspect_ratio=aspect_ratio,
                            number_of_videos=item.count
                        ) as response:
                            async for event_data in parse_sse_stream(response, logger=self.logger):
                                status = event_data.get('status', 'processing')
                                
                                if status == 'completed':
                                    result = event_data
                                    break
                                elif status == 'failed':
                                    raise Exception(event_data.get('error', 'Generation failed'))
                    else:
                        # Text to video
                        async with self.client.text_to_video_stream(
                            prompt=item.prompt,
                            aspect_ratio=aspect_ratio,
                            number_of_videos=item.count
                        ) as response:
                            async for event_data in parse_sse_stream(response, logger=self.logger):
                                status = event_data.get('status', 'processing')
                                
                                if status == 'completed':
                                    result = event_data
                                    break
                                elif status == 'failed':
                                    raise Exception(event_data.get('error', 'Generation failed'))
                
                except Exception as stream_error:
                    self._log('warning', f"Stream failed for {item.id}: {stream_error}, switching to polling")
                
                # If no result from stream, poll history
                if not result:
                    result = await self._poll_with_backoff(
                        item,
                        self._check_history_for_item
                    )
                
                if not result:
                    raise Exception("No result received")
                
                # Extract URLs
                urls = result.get('file_urls', [])
                if not urls and result.get('file_url'):
                    urls = [result.get('file_url')]
                
                # Download content
                bytes_list = await self._download_content(urls)
                
                self._log('success', f"Completed: {item.id}")
                self._emit_progress('item_completed', {'id': item.id, 'urls': urls})
                
                return ProcessingResult(
                    id=item.id,
                    prompt=item.prompt,
                    status='completed',
                    urls=urls,
                    bytes_list=bytes_list
                )
            
            except Exception as e:
                error_msg = str(e)
                error_cat = categorize_error(error_msg)
                
                self._log('error', f"Failed: {item.id} - {error_msg}")
                self._emit_progress('item_failed', {
                    'id': item.id,
                    'error': error_msg,
                    'category': error_cat.value
                })
                
                return ProcessingResult(
                    id=item.id,
                    prompt=item.prompt,
                    status='failed',
                    error=error_msg,
                    error_category=error_cat.value
                )
    
    async def generate_images_batch(
        self,
        items: List[Dict],
        aspect_ratio: str,
        job: Optional[AutomationJob] = None
    ) -> Dict[str, ProcessingResult]:
        """Generate images for multiple prompts in parallel."""
        self._emit_progress('batch_started', {
            'total': len(items),
            'content_type': 'images'
        })
        
        tasks = []
        for item_dict in items:
            proc_item = ProcessingItem(
                id=item_dict['id'],
                prompt=item_dict['prompt'],
                count=item_dict.get('number_of_images', 1),
                reference_frame_path=item_dict.get('reference_frame_path')
            )
            
            task = asyncio.create_task(
                self._process_and_save(
                    self.generate_single_image(proc_item, aspect_ratio),
                    proc_item.id,
                    job
                )
            )
            tasks.append(task)
        
        await asyncio.gather(*tasks, return_exceptions=True)
        
        self._emit_progress('batch_completed', {
            'completed': sum(1 for r in self.results.values() if r.status == 'completed'),
            'failed': sum(1 for r in self.results.values() if r.status == 'failed')
        })
        
        return self.results
    
    async def generate_videos_batch(
        self,
        items: List[Dict],
        aspect_ratio: str,
        start_frame_path: Optional[str] = None,
        job: Optional[AutomationJob] = None
    ) -> Dict[str, ProcessingResult]:
        """Generate videos for multiple prompts in parallel."""
        self._emit_progress('batch_started', {
            'total': len(items),
            'content_type': 'videos'
        })
        
        tasks = []
        for item_dict in items:
            proc_item = ProcessingItem(
                id=item_dict['id'],
                prompt=item_dict['prompt'],
                count=item_dict.get('number_of_videos', 1),
                reference_frame_path=item_dict.get('reference_frame_path')
            )
            
            task = asyncio.create_task(
                self._process_and_save(
                    self.generate_single_video(proc_item, aspect_ratio, start_frame_path),
                    proc_item.id,
                    job
                )
            )
            tasks.append(task)
        
        await asyncio.gather(*tasks, return_exceptions=True)
        
        self._emit_progress('batch_completed', {
            'completed': sum(1 for r in self.results.values() if r.status == 'completed'),
            'failed': sum(1 for r in self.results.values() if r.status == 'failed')
        })
        
        return self.results
    
    async def _process_and_save(
        self,
        coro,
        item_id: str,
        job: Optional[AutomationJob] = None
    ):
        """Process item and save result to job if provided."""
        result = await coro
        self.results[item_id] = result
        
        if job:
            job.update_result(item_id, result.to_dict())
            save_job(job)
    
    async def run_broll_pipeline(
        self,
        items: List[Dict],
        aspect_ratio: str,
        job: Optional[AutomationJob] = None
    ) -> Dict[str, Dict]:
        """Run complete B-Roll pipeline: Images -> Videos.
        
        Returns dict with both image and video results per item.
        """
        pipeline_results = {}
        
        # Step 1: Generate images
        self._emit_progress('step_started', {'step': 1, 'name': 'Generating images'})
        if job:
            job.current_step = 'images'
            job.status = 'running'
            save_job(job)
        
        image_engine = AutomationEngine(
            client=self.client,
            content_type='images',
            progress_callback=self.progress_callback,
            logger=self.logger
        )
        
        image_results = await image_engine.generate_images_batch(items, aspect_ratio, job)
        
        # Initialize pipeline results with image data
        for item_id, result in image_results.items():
            pipeline_results[item_id] = {
                'id': item_id,
                'prompt': result.prompt,
                'image_status': result.status,
                'image_urls': result.urls,
                'image_error': result.error
            }
        
        # Step 2: Generate videos using images
        self._emit_progress('step_started', {'step': 2, 'name': 'Generating videos'})
        if job:
            job.current_step = 'videos'
            save_job(job)
        
        # Prepare video items with image frames
        video_items = []
        for item_id, result in image_results.items():
            if result.status == 'completed' and result.urls:
                # Download image to temp file for use as frame
                image_path = None
                if result.bytes_list:
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
                        tmp.write(result.bytes_list[0])
                        tmp.flush()
                        image_path = tmp.name
                
                video_items.append({
                    'id': item_id,
                    'prompt': result.prompt,
                    'number_of_videos': 1,
                    'reference_frame_path': image_path
                })
        
        if video_items:
            video_engine = AutomationEngine(
                client=self.client,
                content_type='videos',
                progress_callback=self.progress_callback,
                logger=self.logger
            )
            
            video_results = await video_engine.generate_videos_batch(video_items, aspect_ratio, job=job)
            
            # Merge video results
            for item_id, result in video_results.items():
                if item_id in pipeline_results:
                    pipeline_results[item_id]['video_status'] = result.status
                    pipeline_results[item_id]['video_urls'] = result.urls
                    pipeline_results[item_id]['video_error'] = result.error
            
            # Cleanup temp image files
            for item in video_items:
                if item.get('reference_frame_path'):
                    try:
                        os.unlink(item['reference_frame_path'])
                    except:
                        pass
        
        if job:
            job.status = 'completed'
            save_job(job)
        
        return pipeline_results


# =============================================================================
# ZIP Creation
# =============================================================================

def create_chunked_zips(
    results: Dict[str, ProcessingResult],
    prefix: str = 'batch',
    max_size_mb: int = MAX_ZIP_SIZE_MB
) -> List[tuple[str, bytes]]:
    """Create ZIP files with content, chunked by size.
    
    Returns list of (filename, zip_bytes) tuples.
    """
    zips = []
    current_files = []
    current_size = 0
    part_num = 1
    
    completed_results = [r for r in results.values() if r.status == 'completed']
    
    for result in completed_results:
        for idx, content in enumerate(result.bytes_list):
            size_mb = len(content) / (1024 * 1024)
            
            # Start new ZIP if this would exceed limit
            if current_size + size_mb > max_size_mb and current_files:
                zip_bytes = _create_zip_from_files(current_files)
                zips.append((f"{prefix}_part{part_num}.zip", zip_bytes))
                current_files = []
                current_size = 0
                part_num += 1
            
            # Determine filename
            suffix = f"_{idx+1}" if len(result.bytes_list) > 1 else ""
            ext = '.png' if prefix.endswith('img') else '.mp4'
            filename = f"{prefix}_{result.id}{suffix}{ext}"
            
            current_files.append((filename, content))
            current_size += size_mb
    
    # Create final ZIP
    if current_files:
        zip_bytes = _create_zip_from_files(current_files)
        if len(zips) > 0:
            zips.append((f"{prefix}_part{part_num}.zip", zip_bytes))
        else:
            zips.append((f"{prefix}.zip", zip_bytes))
    
    return zips


def _create_zip_from_files(files: List[tuple[str, bytes]]) -> bytes:
    """Create ZIP from list of (filename, content) tuples."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for filename, content in files:
            zf.writestr(filename, content)
    return buffer.getvalue()


# =============================================================================
# CSV Export
# =============================================================================

def create_results_csv(results: Dict[str, ProcessingResult]) -> str:
    """Create CSV with all results."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id', 'prompt', 'status', 'urls', 'error'])
    
    for result in results.values():
        writer.writerow([
            result.id,
            result.prompt,
            result.status,
            ';'.join(result.urls) if result.urls else '',
            result.error or ''
        ])
    
    return output.getvalue()


def create_failed_csv(results: Dict[str, ProcessingResult], retryable_only: bool = True) -> str:
    """Create CSV with failed prompts for retry."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id', 'prompt', 'number_of_images'])
    
    for result in results.values():
        if result.status != 'failed':
            continue
        
        if retryable_only and result.error_category == ErrorCategory.PERMANENT.value:
            continue
        
        writer.writerow([
            result.id,
            result.prompt,
            1
        ])
    
    return output.getvalue()


def create_pipeline_csv(results: Dict[str, Dict]) -> str:
    """Create CSV for B-Roll pipeline results."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'id', 'prompt', 
        'image_status', 'image_urls', 'image_error',
        'video_status', 'video_urls', 'video_error'
    ])
    
    for item_id, data in results.items():
        writer.writerow([
            data.get('id', item_id),
            data.get('prompt', ''),
            data.get('image_status', ''),
            ';'.join(data.get('image_urls', [])),
            data.get('image_error', ''),
            data.get('video_status', ''),
            ';'.join(data.get('video_urls', [])),
            data.get('video_error', '')
        ])
    
    return output.getvalue()
