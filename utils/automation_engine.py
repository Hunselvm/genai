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
from dataclasses import dataclass, field, fields
from datetime import datetime
from enum import Enum
from typing import List, Dict, Optional, Callable, Any
import httpx

from utils.veo_client import VEOClient
from utils.sse_handler import parse_sse_stream
from utils.progress_persistence import AutomationJob, save_job
from utils.retry_handler import RetryHandler


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


def video_to_image_aspect_ratio(video_ar: str) -> str:
    """Convert VIDEO_ASPECT_RATIO_* to IMAGE_ASPECT_RATIO_*."""
    mapping = {
        'VIDEO_ASPECT_RATIO_LANDSCAPE': 'IMAGE_ASPECT_RATIO_LANDSCAPE',
        'VIDEO_ASPECT_RATIO_PORTRAIT': 'IMAGE_ASPECT_RATIO_PORTRAIT',
    }
    return mapping.get(video_ar, 'IMAGE_ASPECT_RATIO_LANDSCAPE')


def image_to_video_aspect_ratio(image_ar: str) -> str:
    """Convert IMAGE_ASPECT_RATIO_* to VIDEO_ASPECT_RATIO_*."""
    mapping = {
        'IMAGE_ASPECT_RATIO_LANDSCAPE': 'VIDEO_ASPECT_RATIO_LANDSCAPE',
        'IMAGE_ASPECT_RATIO_PORTRAIT': 'VIDEO_ASPECT_RATIO_PORTRAIT',
        'IMAGE_ASPECT_RATIO_SQUARE': 'VIDEO_ASPECT_RATIO_LANDSCAPE',  # Fallback
    }
    return mapping.get(image_ar, 'VIDEO_ASPECT_RATIO_LANDSCAPE')


# =============================================================================
# Error Categorization
# =============================================================================

class ErrorCategory(Enum):
    PERMANENT = "permanent"      # Don't retry - content policy, auth errors
    RETRYABLE = "retryable"      # Retry - timeout, rate limit, server errors
    UNKNOWN = "unknown"          # Retry with warning


PERMANENT_ERROR_PATTERNS = [
    "content policy", "blocked", "authentication", "unauthorized", "forbidden",
    "invalid api key", "account suspended", "inappropriate", "violates", "not allowed"
]

RETRYABLE_ERROR_PATTERNS = [
    "timeout", "timed out", "rate limit", "too many requests", "server error",
    "internal error", "503", "502", "500", "connection", "network",
    "temporarily", "try again", "overloaded", "recaptcha"
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
            while self.timestamps and now - self.timestamps[0] > 60:
                self.timestamps.popleft()
            
            if len(self.timestamps) >= self.rpm:
                sleep_time = 60 - (now - self.timestamps[0]) + 0.1
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
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
    count: int = 1
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
    file_paths: List[str] = field(default_factory=list)
    
    def __getitem__(self, key):
        return getattr(self, key)
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'prompt': self.prompt,
            'status': self.status,
            'urls': self.urls,
            'error': self.error,
            'error_category': self.error_category,
            'file_paths': self.file_paths
        }
    
    @classmethod
    def from_dict(cls, data: Dict):
        valid_keys = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


# =============================================================================
# Input Validation
# =============================================================================

def validate_prompts(items: List[Dict]) -> tuple[List[Dict], List[str]]:
    """Validate prompts before processing.
    Checks 'prompt', 'image_prompt', and 'video_prompt' keys.
    """
    valid = []
    errors = []
    
    for item in items:
        item_id = item.get('id', 'unknown')
        item_errors = []
        
        # Check all potential prompt fields
        fields_to_check = []
        if 'prompt' in item: fields_to_check.append(('prompt', item['prompt']))
        if 'image_prompt' in item: fields_to_check.append(('image_prompt', item['image_prompt']))
        if 'video_prompt' in item: fields_to_check.append(('video_prompt', item['video_prompt']))
        
        for name, val in fields_to_check:
            val = str(val).strip()
            if not val:
                item_errors.append(f"{name}: Empty")
            elif len(val) < 10:
                item_errors.append(f"{name}: Too short (min 10 chars)")
            elif len(val) > 2000:
                item_errors.append(f"{name}: Too long (max 2000 chars)")
        
        if item_errors:
            errors.append(f"{item_id}: " + ", ".join(item_errors))
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
        self._stop_requested = True
    
    def _emit_progress(self, event_type: str, data: Dict):
        if self.progress_callback:
            self.progress_callback(event_type, data)
    
    def _log(self, level: str, message: str):
        if self.logger:
            if level == 'info': self.logger.info(message)
            elif level == 'success': self.logger.success(message)
            elif level == 'warning': self.logger.warning(message)
            elif level == 'error': self.logger.error(message)
    
    async def _poll_with_backoff(self, item: ProcessingItem, check_func: Callable) -> Optional[Dict]:
        start_time = time.time()
        poll_interval = self.config['initial_poll_seconds']
        
        while True:
            elapsed = time.time() - start_time
            timeout_seconds = self.config['timeout_minutes'] * 60
            
            if elapsed > timeout_seconds:
                raise TimeoutError(f"Generation exceeded {self.config['timeout_minutes']}min timeout")
            
            await asyncio.sleep(poll_interval)
            
            try:
                result = await check_func(item)
                if result:
                    if result.get('status') == 'completed': return result
                    elif result.get('status') == 'failed':
                        raise Exception(result.get('error', 'Generation failed'))
            except Exception as e:
                if 'completed' in str(e) or 'failed' in str(e): raise
                self._log('warning', f"Poll error for {item.id}: {e}")
            
            poll_interval = min(poll_interval * 1.5, self.config['max_poll_seconds'])
    
    async def _check_history_for_item(self, item: ProcessingItem) -> Optional[Dict]:
        try:
            history = await self.client.get_histories(page=1, page_size=10)
            if not history or not history.get('data'): return None
            for hist_item in history['data']:
                hist_prompt = hist_item.get('prompt', '').lower()
                if item.prompt.lower() in hist_prompt or hist_prompt in item.prompt.lower():
                    return hist_item
            return None
        except Exception as e:
            self._log('warning', f"History check failed: {e}")
            return None
    
    async def _download_content(self, urls: List[str]) -> List[str]:
        """Download content to temporary files. Returns file paths."""
        paths = []
        async with httpx.AsyncClient(timeout=60.0) as client:
            for url in urls:
                try:
                    ext = '.mp4' if '/video' in url or url.endswith('.mp4') else '.png'
                    fd, path = tempfile.mkstemp(suffix=ext)
                    os.close(fd)
                    
                    self._log('info', f"Downloading {url} to {path}")
                    async with client.stream('GET', url) as resp:
                        resp.raise_for_status()
                        with open(path, 'wb') as f:
                            async for chunk in resp.aiter_bytes():
                                f.write(chunk)
                    paths.append(path)
                except Exception as e:
                    self._log('warning', f"Download failed for {url}: {e}")
                    # Try to cleanup empty file
                    if 'path' in locals() and os.path.exists(path):
                        try: os.unlink(path)
                        except: pass
        return paths
    
    async def generate_single_image(self, item: ProcessingItem, aspect_ratio: str) -> ProcessingResult:
        async with self.semaphore:
            await self.rate_limiter.acquire()
            if self._stop_requested:
                return ProcessingResult(item.id, item.prompt, 'failed', error='Stopped by user')
            
            self._emit_progress('item_started', {'id': item.id, 'prompt': item.prompt})
            
            async def do_generate():
                """Core generation logic - wrapped with retry."""
                result = None
                try:
                    async with self.client.create_image_stream(
                        item.prompt, aspect_ratio, item.count,
                        [item.reference_frame_path] if item.reference_frame_path else None
                    ) as response:
                        async for event_data in parse_sse_stream(response, logger=self.logger):
                            if event_data.get('status') == 'completed':
                                result = event_data
                                break
                            elif event_data.get('status') == 'failed':
                                raise Exception(event_data.get('error', 'Generation failed'))
                except Exception as e:
                    self._log('warning', f"Stream error: {e}, switching to polling")
                
                if not result:
                    result = await self._poll_with_backoff(item, self._check_history_for_item)
                
                if not result: 
                    raise Exception("No result received")
                
                return result
            
            # Retry callback for progress updates
            def on_retry(retry_count: int, delay: float, error_msg: str):
                self._emit_progress('item_retrying', {
                    'id': item.id, 
                    'retry': retry_count, 
                    'delay': delay,
                    'error': error_msg[:50]
                })
                self._log('info', f"Retry {retry_count} for {item.id} after {delay:.0f}s: {error_msg[:50]}")
            
            try:
                result = await RetryHandler.retry_with_backoff(
                    do_generate,
                    logger=self.logger,
                    on_retry=on_retry
                )
                
                urls = result.get('file_urls', []) or [result.get('file_url')]
                file_paths = await self._download_content(urls)
                
                self._emit_progress('item_completed', {'id': item.id, 'urls': urls})
                return ProcessingResult(item.id, item.prompt, 'completed', urls=urls, file_paths=file_paths)
            
            except Exception as e:
                error_msg = str(e)
                error_cat = categorize_error(error_msg)
                self._emit_progress('item_failed', {'id': item.id, 'error': error_msg, 'category': error_cat.value})
                return ProcessingResult(item.id, item.prompt, 'failed', error=error_msg, error_category=error_cat.value)

    async def generate_single_video(self, item: ProcessingItem, aspect_ratio: str, start_frame_path: Optional[str] = None) -> ProcessingResult:
        async with self.semaphore:
            await self.rate_limiter.acquire()
            if self._stop_requested:
                return ProcessingResult(item.id, item.prompt, 'failed', error='Stopped by user')
            
            self._emit_progress('item_started', {'id': item.id, 'prompt': item.prompt})
            frame_path = item.reference_frame_path or start_frame_path
            
            async def do_generate():
                """Core generation logic - wrapped with retry."""
                result = None
                try:
                    if frame_path:
                        gen_func = self.client.frames_to_video_stream(frame_path, None, item.prompt, aspect_ratio, item.count)
                    else:
                        gen_func = self.client.text_to_video_stream(item.prompt, aspect_ratio, item.count)
                        
                    async with gen_func as response:
                        async for event_data in parse_sse_stream(response, logger=self.logger):
                            if event_data.get('status') == 'completed':
                                result = event_data
                                break
                            elif event_data.get('status') == 'failed':
                                raise Exception(event_data.get('error', 'Generation failed'))
                except Exception as e:
                    self._log('warning', f"Stream error: {e}, switching to polling")
                
                if not result:
                    result = await self._poll_with_backoff(item, self._check_history_for_item)
                
                if not result: 
                    raise Exception("No result received")
                
                return result
            
            # Retry callback for progress updates
            def on_retry(retry_count: int, delay: float, error_msg: str):
                self._emit_progress('item_retrying', {
                    'id': item.id, 
                    'retry': retry_count, 
                    'delay': delay,
                    'error': error_msg[:50]
                })
                self._log('info', f"Retry {retry_count} for {item.id} after {delay:.0f}s: {error_msg[:50]}")
            
            try:
                result = await RetryHandler.retry_with_backoff(
                    do_generate,
                    logger=self.logger,
                    on_retry=on_retry
                )
                
                urls = result.get('file_urls', []) or [result.get('file_url')]
                file_paths = await self._download_content(urls)
                
                self._emit_progress('item_completed', {'id': item.id, 'urls': urls})
                return ProcessingResult(item.id, item.prompt, 'completed', urls=urls, file_paths=file_paths)
            
            except Exception as e:
                error_msg = str(e)
                error_cat = categorize_error(error_msg)
                self._emit_progress('item_failed', {'id': item.id, 'error': error_msg, 'category': error_cat.value})
                return ProcessingResult(item.id, item.prompt, 'failed', error=error_msg, error_category=error_cat.value)

    async def generate_images_batch(self, items: List[Dict], aspect_ratio: str, job: Optional[AutomationJob] = None) -> Dict[str, ProcessingResult]:
        self._emit_progress('batch_started', {'total': len(items), 'content_type': 'images'})
        tasks = []
        for d in items:
            item = ProcessingItem(d['id'], d['prompt'], d.get('number_of_images', 1), reference_frame_path=d.get('reference_frame_path'))
            tasks.append(asyncio.create_task(self._process_and_save(self.generate_single_image(item, aspect_ratio), item.id, job)))
        await asyncio.gather(*tasks)
        return self.results

    async def generate_videos_batch(self, items: List[Dict], aspect_ratio: str, start_frame_path: Optional[str] = None, job: Optional[AutomationJob] = None) -> Dict[str, ProcessingResult]:
        self._emit_progress('batch_started', {'total': len(items), 'content_type': 'videos'})
        tasks = []
        for d in items:
            item = ProcessingItem(d['id'], d['prompt'], d.get('number_of_videos', 1), reference_frame_path=d.get('reference_frame_path'))
            tasks.append(asyncio.create_task(self._process_and_save(self.generate_single_video(item, aspect_ratio, start_frame_path), item.id, job)))
        await asyncio.gather(*tasks)
        return self.results
    
    async def _process_and_save(self, coro, item_id: str, job: Optional[AutomationJob]):
        result = await coro
        self.results[item_id] = result
        if job:
            job.update_result(item_id, result.to_dict())
            save_job(job)

    async def run_broll_pipeline(self, items: List[Dict], aspect_ratio: str, job: Optional[AutomationJob] = None) -> Dict[str, Dict]:
        """Run B-Roll pipeline (Image -> Video) with suffix-based ID management and smart resume."""
        pipeline_results = {}
        
        # Define suffix IDs
        items_map = {}
        for item in items:
            items_map[item['id']] = {
                'raw': item,
                'img_id': f"{item['id']}_img",
                'vid_id': f"{item['id']}_vid"
            }
        
        # ---- Step 1: Images ----
        self._emit_progress('step_started', {'step': 1, 'name': 'Generating B-Roll Images'})
        if job:
            job.current_step = 'images'
            job.status = 'running'
            save_job(job)
        
        # Filter: Check if image task already completed in job history AND files exist
        image_work_items = []
        existing_results = job.results if job else {}
        
        for item in items:
            meta = items_map[item['id']]
            
            # Check for existing result
            cached = existing_results.get(meta['img_id'])
            files_ok = False
            if cached and cached.get('status') == 'completed' and cached.get('file_paths'):
                # Check if file actually exists
                if os.path.exists(cached['file_paths'][0]):
                    files_ok = True
            
            if not files_ok:
                image_work_items.append({
                    'id': meta['img_id'],
                    'prompt': item.get('image_prompt', item.get('prompt')),
                    'number_of_images': item.get('number_of_images', 1),
                    'reference_frame_path': item.get('image_reference_frame_path')
                })
        
        # Run Image Gen with CONVERTED aspect ratio
        if image_work_items:
            img_aspect_ratio = video_to_image_aspect_ratio(aspect_ratio)
            img_engine = AutomationEngine(self.client, 'images', self.progress_callback, self.logger)
            await img_engine.generate_images_batch(image_work_items, img_aspect_ratio, job)
        
        # Refresh results from job (to get what we just generated + what was cached)
        current_results = job.results if job else {}
        
        # ---- Step 2: Videos ----
        self._emit_progress('step_started', {'step': 2, 'name': 'Generating B-Roll Videos'})
        if job: job.current_step = 'videos'; save_job(job)
        
        video_work_items = []
        
        for item in items:
            meta = items_map[item['id']]
            img_res_dict = current_results.get(meta['img_id'])
            
            # Can only proceed if image is done
            if img_res_dict and img_res_dict.get('status') == 'completed' and img_res_dict.get('file_paths'):
                # Check cache for video
                cached_vid = current_results.get(meta['vid_id'])
                vid_files_ok = False
                if cached_vid and cached_vid.get('status') == 'completed' and cached_vid.get('file_paths'):
                     if os.path.exists(cached_vid['file_paths'][0]):
                         vid_files_ok = True
                
                if not vid_files_ok:
                    video_work_items.append({
                        'id': meta['vid_id'],
                        'prompt': item.get('video_prompt', item.get('prompt')),
                        'number_of_videos': item.get('number_of_videos', 1),
                        'reference_frame_path': img_res_dict['file_paths'][0]  # Use generated image
                    })
        
        # Run Video Gen
        if video_work_items:
            vid_engine = AutomationEngine(self.client, 'videos', self.progress_callback, self.logger)
            await vid_engine.generate_videos_batch(video_work_items, aspect_ratio, job)
        
        # Config final results
        final_results_source = job.results if job else {}
        if job: job.status = 'completed'; save_job(job)
        
        for item in items:
            meta = items_map[item['id']]
            pipeline_results[item['id']] = {
                'id': item['id'],
                'image_result': final_results_source.get(meta['img_id']),
                'video_result': final_results_source.get(meta['vid_id'])
            }
            
        return pipeline_results


# =============================================================================
# ZIP Creation
# =============================================================================

def create_chunked_zips(results: List[Any], prefix: str = 'batch', max_size_mb: int = MAX_ZIP_SIZE_MB) -> List[tuple[str, bytes]]:
    """Create ZIP files from ProcessingResult objects (or dicts)."""
    zips = []
    current_files = [] # List[(filename, path)]
    current_size = 0
    part_num = 1
    
    # Filter for completed
    completed = []
    for r in results:
        # Support dict (resumed) or object (new)
        status = r['status'] if isinstance(r, dict) else r.status
        if status == 'completed':
            completed.append(r)
            
    for result in completed:
        # Access safely
        file_paths = result['file_paths'] if isinstance(result, dict) else result.file_paths
        item_id = result['id'] if isinstance(result, dict) else result.id
        
        for idx, path in enumerate(file_paths):
            if not os.path.exists(path): continue
            
            size_mb = os.path.getsize(path) / (1024 * 1024)
            
            if current_size + size_mb > max_size_mb and current_files:
                zips.append((f"{prefix}_part{part_num}.zip", _create_zip_from_paths(current_files)))
                current_files = []
                current_size = 0
                part_num += 1
            
            # Determine filename in zip
            suffix = f"_{idx+1}" if len(file_paths) > 1 else ""
            ext = os.path.splitext(path)[1]
            filename = f"{prefix}_{item_id}{suffix}{ext}"
            
            current_files.append((filename, path))
            current_size += size_mb
            
    if current_files:
        filename = f"{prefix}_part{part_num}.zip" if zips else f"{prefix}.zip"
        zips.append((filename, _create_zip_from_paths(current_files)))
        
    return zips

def _create_zip_from_paths(files: List[tuple[str, str]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for arcname, path in files:
            if os.path.exists(path):
                zf.write(path, arcname=arcname)
    return buffer.getvalue()


# =============================================================================
# CSV Export
# =============================================================================

def create_results_csv(results: Dict[str, Any]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id', 'prompt', 'status', 'urls', 'error'])
    
    for r in results.values():
         # Handle dict/obj
        rid = r['id'] if isinstance(r, dict) else r.id
        prompt = r['prompt'] if isinstance(r, dict) else r.prompt
        status = r['status'] if isinstance(r, dict) else r.status
        urls = r['urls'] if isinstance(r, dict) else r.urls
        err = r['error'] if isinstance(r, dict) else r.error
        
        writer.writerow([rid, prompt, status, ';'.join(urls) if urls else '', err or ''])
    return output.getvalue()

def create_failed_csv(results: Dict[str, Any]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id', 'prompt'])
    
    for r in results.values():
        status = r['status'] if isinstance(r, dict) else r.status
        if status == 'failed':
            cat = r.get('error_category') if isinstance(r, dict) else r.error_category
            if cat != ErrorCategory.PERMANENT.value:
                rid = r['id'] if isinstance(r, dict) else r.id
                prompt = r['prompt'] if isinstance(r, dict) else r.prompt
                writer.writerow([rid, prompt])
    return output.getvalue()

def create_pipeline_csv(pipeline_results: Dict[str, Dict]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'id', 'image_status', 'image_url', 'image_error',
        'video_status', 'video_url', 'video_error'
    ])
    
    def safe_get_url(obj):
        """Safely extract first URL from urls list."""
        try:
            if isinstance(obj, dict):
                urls = obj.get('urls') or obj.get('file_urls') or []
                return urls[0] if urls else ''
            elif hasattr(obj, 'urls') and obj.urls:
                return obj.urls[0]
            elif hasattr(obj, 'file_urls') and obj.file_urls:
                return obj.file_urls[0]
            return ''
        except (IndexError, TypeError, AttributeError):
            return ''
    
    for pid, data in pipeline_results.items():
        if not isinstance(data, dict):
            continue
            
        img = data.get('image_result') or {}
        vid = data.get('video_result') or {}
        
        # extract safely
        i_stat = img.get('status', '') if isinstance(img, dict) else getattr(img, 'status', '')
        i_url = safe_get_url(img)
        i_err = img.get('error', '') if isinstance(img, dict) else getattr(img, 'error', '')
        
        v_stat = vid.get('status', '') if isinstance(vid, dict) else getattr(vid, 'status', '')
        v_url = safe_get_url(vid)
        v_err = vid.get('error', '') if isinstance(vid, dict) else getattr(vid, 'error', '')
        
        writer.writerow([pid, i_stat or '', i_url or '', i_err or '', v_stat or '', v_url or '', v_err or ''])
        
    return output.getvalue()
