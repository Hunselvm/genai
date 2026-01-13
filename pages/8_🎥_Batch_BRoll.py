"""Batch B-Roll Video Generation Page"""

import streamlit as st
import asyncio
import httpx
import csv
import io
import time
import tempfile
import os
import uuid
import zipfile
import re
from typing import List, Dict, Tuple, Optional

from utils.veo_client import VEOClient
from utils.sse_handler import parse_sse_stream
from utils.exceptions import VEOAPIError, AuthenticationError, QuotaExceededError, NetworkError
from utils.logger import StreamlitLogger
from utils.quota_display import display_quota
from utils.sidebar import render_sidebar

st.set_page_config(page_title="Batch B-Roll", page_icon="🎥", layout="wide")

# Custom CSS
st.markdown("""
<style>
    .success-box {
        padding: 1rem;
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        border-radius: 0.5rem;
        color: #155724;
    }
    .debug-console {
        background-color: #f8f9fa;
        border: 1px solid #dee2e6;
        border-radius: 0.5rem;
        padding: 0.5rem;
        font-family: monospace;
        font-size: 0.85rem;
        max-height: 300px;
        overflow-y: auto;
    }
    .image-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
        gap: 1rem;
        margin: 1rem 0;
    }
    .image-item {
        text-align: center;
        padding: 0.5rem;
        border: 1px solid #dee2e6;
        border-radius: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)

st.title("🎥 Batch B-Roll Generator")

# Render Sidebar
render_sidebar()

# Check API key
if not st.session_state.get('api_key'):
    st.warning("⚠️ Please enter your API key in the sidebar first!")
    st.stop()

# Display quota
display_quota()

st.sidebar.divider()
debug_mode = st.sidebar.checkbox(
    "🔍 Enable Debug Mode",
    value=False,
    help="Show detailed API communication logs in the main window"
)

st.markdown("""
Generate multiple B-Roll videos in parallel, each with its own unique reference image.
Upload multiple images (numbered like `1_broll_1.jpg`, `2_something.jpg`) and matching prompts.
""")


# ============================================================================
# Helper Functions
# ============================================================================

def get_unique_id():
    """Generate a unique ID for UI widgets."""
    return str(uuid.uuid4())


def extract_image_number(filename: str) -> Optional[int]:
    """
    Extract number from filename, looking at first part before underscore.
    Examples: 1_broll_1.jpg → 1, 2_something.jpg → 2, 10.jpg → 10
    """
    # Remove extension
    name = filename.rsplit('.', 1)[0]

    # Take first part before underscore (if underscore exists)
    first_part = name.split('_')[0]

    # Extract number from first part
    numbers = re.findall(r'\d+', first_part)
    return int(numbers[0]) if numbers else None


def parse_txt_file_broll(file_contents: str) -> List[Dict]:
    """Parse text file with multi-line prompts separated by blank lines.

    Format:
    ID_LINE
    prompt line 1
    prompt line 2

    NEXT_ID
    next prompt...
    """
    # Split by double newlines to get prompt blocks
    blocks = file_contents.strip().split('\n\n')
    prompts = []

    for idx, block in enumerate(blocks, 1):
        block = block.strip()
        if not block:
            continue

        lines = block.split('\n')
        if len(lines) == 0:
            continue

        # First line is the ID
        first_line = lines[0].strip()

        # Extract image number from ID line
        img_num = extract_image_number(first_line)
        if not img_num:
            img_num = idx  # Fallback to sequential numbering

        # Rest is the prompt
        if len(lines) == 1:
            # Single line: use as both ID and prompt
            prompt_id = first_line
            prompt_text = first_line
        else:
            # Multi-line: first line is ID, rest is prompt
            prompt_id = first_line
            prompt_text = '\n'.join(lines[1:]).strip()

        if prompt_text:  # Only add if we have prompt content
            prompts.append({
                'id': prompt_id if prompt_id else f"video_{img_num}",
                'prompt': prompt_text,
                'image_number': img_num,
                'number_of_videos': 1,  # Default
                '_ui_id': get_unique_id()
            })

    return prompts


def parse_csv_file_broll(file_contents: str) -> List[Dict]:
    """Parse CSV file where id IS the image number (or use explicit image_number column)."""
    prompts = []
    reader = csv.DictReader(io.StringIO(file_contents))

    for idx, row in enumerate(reader, 1):
        if 'prompt' not in row or not row['prompt'].strip():
            continue  # Skip rows without prompt

        prompt_id = row.get('id', str(idx))

        # Prioritize explicit image_number column (from failed prompts CSV)
        if 'image_number' in row and row['image_number'].strip():
            try:
                img_num = int(row['image_number'])
            except (ValueError, TypeError):
                # Fall back to extracting from id
                img_num = int(prompt_id) if prompt_id.isdigit() else idx
        else:
            # Extract image number from id (id should be numeric like "1", "2", "3")
            img_num = int(prompt_id) if prompt_id.isdigit() else idx

        prompts.append({
            'id': prompt_id,
            'prompt': row['prompt'].strip(),
            'image_number': img_num,  # From image_number column or extracted from id
            'number_of_videos': int(row.get('number_of_videos', 1)),
            '_ui_id': get_unique_id()
        })

    return prompts


def validate_broll_batch(
    batch_items: List[Dict],
    uploaded_images: Dict[int, bytes]
) -> Tuple[bool, str, List[str]]:
    """Validate B-Roll batch configuration."""
    # Check basics
    if not batch_items:
        return False, "No valid prompts found in file", []

    if len(batch_items) > 20:
        return False, "Too many prompts (max 20 per batch for videos)", []

    if not uploaded_images:
        return False, "No reference images uploaded. Please upload at least one image.", []

    # Check all referenced images exist
    missing_images = set()
    for item in batch_items:
        # Check prompt
        if not item.get('prompt') or not item['prompt'].strip():
            return False, f"Empty prompt for item {item['id']}", []

        # Check number_of_videos
        num_videos = item.get('number_of_videos', 1)
        if num_videos < 1 or num_videos > 4:
            return False, f"Invalid number_of_videos ({num_videos}) for {item['id']}. Must be 1-4.", []

        # Check image_number
        img_num = item.get('image_number')
        if not img_num:
            return False, f"Missing image_number for {item['id']}", []

        if img_num not in uploaded_images:
            missing_images.add(img_num)

    if missing_images:
        missing_str = ', '.join(str(n) for n in sorted(missing_images))
        return False, f"Missing reference images for numbers: {missing_str}", []

    # Warnings for unused images
    warnings = []
    used_images = {item['image_number'] for item in batch_items}
    unused_images = set(uploaded_images.keys()) - used_images
    if unused_images:
        unused_str = ', '.join(str(n) for n in sorted(unused_images))
        warnings.append(f"Uploaded images not used: {unused_str}")

    return True, "", warnings


def estimate_quota_usage(batch_items: List[Dict]) -> int:
    """Estimate total videos that will be generated."""
    return sum(item.get('number_of_videos', 1) for item in batch_items)


# ============================================================================
# Batch B-Roll Video Generator Class
# ============================================================================

class BatchBRollVideoGenerator:
    """Generate B-Roll videos with per-prompt reference images."""

    def __init__(self, client: VEOClient, logger=None):
        self.client = client
        self.logger = logger
        self.results = {}  # {prompt_id: result_data}
        self.progress = {}  # {prompt_id: {status, percentage, error, image_number}}

    async def generate_single(
        self,
        prompt_id: str,
        prompt: str,
        aspect_ratio: str,
        number_of_videos: int,
        image_number: int,
        image_bytes_dict: Dict[int, bytes],
        max_retries: int = 3
    ) -> Optional[Dict]:
        """Generate videos for a single prompt with its specific reference image."""
        # Verify image exists
        if image_number not in image_bytes_dict:
            error_msg = f"Image #{image_number} not found in uploaded images"
            self.progress[prompt_id] = {
                'status': 'failed',
                'percentage': 0,
                'error': error_msg,
                'image_number': image_number
            }
            self.results[prompt_id] = {
                'status': 'failed',
                'error': error_msg,
                'prompt': prompt,
                'image_number': image_number
            }
            return None

        # Create temp file for THIS specific image
        start_frame_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                tmp.write(image_bytes_dict[image_number])
                tmp.flush()  # Ensure data is written to disk
                os.fsync(tmp.fileno())  # Force OS to write to disk
                start_frame_path = tmp.name

            retry_count = 0
            base_delay = 2  # Start with 2 seconds

            while retry_count <= max_retries:
                try:
                    self.progress[prompt_id] = {
                        'status': 'processing',
                        'percentage': 0,
                        'retry': retry_count if retry_count > 0 else None,
                        'image_number': image_number
                    }

                    async with self.client.frames_to_video_stream(
                        start_frame_path=start_frame_path,
                        end_frame_path=None,  # No end frame for B-Roll (only start frame)
                        prompt=prompt,
                        aspect_ratio=aspect_ratio,
                        number_of_videos=number_of_videos
                    ) as response:
                        async for event_data in parse_sse_stream(response, logger=self.logger):
                            # Update progress
                            percentage = event_data.get('process_percentage', 0)
                            status = event_data.get('status', 'processing')

                            self.progress[prompt_id] = {
                                'status': status,
                                'percentage': percentage,
                                'retry': retry_count if retry_count > 0 else None,
                                'image_number': image_number
                            }

                            if status == 'completed':
                                # Fetch video bytes for reliable downloading
                                video_bytes_list = []
                                file_urls = event_data.get('file_urls', [])
                                if not file_urls and event_data.get('file_url'):
                                    file_urls = [event_data.get('file_url')]

                                if file_urls:
                                    try:
                                        async with httpx.AsyncClient() as client:
                                            for url in file_urls:
                                                resp = await client.get(url, timeout=60.0)
                                                if resp.status_code == 200:
                                                    video_bytes_list.append(resp.content)
                                    except Exception as e:
                                        if self.logger:
                                            self.logger.error(f"Failed to download video bytes: {str(e)}")

                                self.results[prompt_id] = {
                                    'status': 'completed',
                                    'data': event_data,
                                    'prompt': prompt,
                                    'image_number': image_number,
                                    'number_of_videos': number_of_videos,
                                    'video_bytes_list': video_bytes_list
                                }
                                return event_data

                            elif status == 'failed':
                                error_msg = event_data.get('error', 'Generation failed')
                                raise Exception(error_msg)

                except Exception as e:
                    error_str = str(e)

                    # Check if it's a retryable error (403 reCAPTCHA or 500 server error)
                    is_recaptcha_error = '403' in error_str and 'recaptcha' in error_str.lower()
                    is_server_error = '500' in error_str
                    is_retryable = is_recaptcha_error or is_server_error

                    if is_retryable and retry_count < max_retries:
                        retry_count += 1
                        delay = base_delay * (2 ** (retry_count - 1))  # Exponential backoff: 2s, 4s, 8s

                        error_type = "reCAPTCHA error" if is_recaptcha_error else "Server error"
                        if self.logger:
                            self.logger.warning(f"{error_type} for '{prompt_id}', retrying in {delay}s (attempt {retry_count}/{max_retries})...")

                        self.progress[prompt_id] = {
                            'status': 'retrying',
                            'percentage': 0,
                            'retry': retry_count,
                            'delay': delay,
                            'image_number': image_number
                        }

                        await asyncio.sleep(delay)
                        continue  # Retry
                    else:
                        # Final failure or non-retryable error
                        self.progress[prompt_id] = {
                            'status': 'failed',
                            'percentage': 0,
                            'error': error_str,
                            'image_number': image_number
                        }
                        self.results[prompt_id] = {
                            'status': 'failed',
                            'error': error_str,
                            'prompt': prompt,
                            'image_number': image_number
                        }
                        if self.logger:
                            self.logger.error(f"Failed to generate for '{prompt}': {error_str}")
                        return None

        finally:
            # CRITICAL: Cleanup temp file immediately
            if start_frame_path and os.path.exists(start_frame_path):
                try:
                    os.unlink(start_frame_path)
                except:
                    pass

        # Should not reach here, but just in case
        return None

    async def generate_batch(
        self,
        batch_items: List[Dict],
        aspect_ratio: str,
        image_bytes_dict: Dict[int, bytes]
    ) -> Dict[str, Dict]:
        """Generate B-Roll videos for all prompts in parallel."""
        tasks = [
            self.generate_single(
                prompt_id=item['id'],
                prompt=item['prompt'],
                aspect_ratio=aspect_ratio,
                number_of_videos=item['number_of_videos'],
                image_number=item['image_number'],
                image_bytes_dict=image_bytes_dict
            )
            for item in batch_items
        ]

        # Run all tasks concurrently
        await asyncio.gather(*tasks, return_exceptions=True)

        return self.results


# ============================================================================
# UI - Session State Initialization
# ============================================================================

if 'broll_uploaded_images' not in st.session_state:
    st.session_state.broll_uploaded_images = {}  # {img_num: bytes}

if 'broll_image_filenames' not in st.session_state:
    st.session_state.broll_image_filenames = {}  # {img_num: filename}

if 'batch_broll_items' not in st.session_state:
    st.session_state.batch_broll_items = []

if 'broll_last_file_ext' not in st.session_state:
    st.session_state.broll_last_file_ext = 'txt'

if 'broll_results' not in st.session_state:
    st.session_state.broll_results = None


# ============================================================================
# UI - Image Upload Section
# ============================================================================

st.subheader("1. Upload Reference Images")

uploaded_images = st.file_uploader(
    "Upload multiple reference images (one per prompt)",
    type=['jpg', 'jpeg', 'png', 'webp'],
    accept_multiple_files=True,
    help="Name images with numbers: 1_description.jpg, 2_another.png, etc."
)

if uploaded_images:
    # Clear and repopulate on each upload
    st.session_state.broll_uploaded_images.clear()
    st.session_state.broll_image_filenames.clear()

    for uploaded_file in uploaded_images:
        img_num = extract_image_number(uploaded_file.name)
        if img_num:
            st.session_state.broll_uploaded_images[img_num] = uploaded_file.getvalue()
            st.session_state.broll_image_filenames[img_num] = uploaded_file.name
        else:
            st.warning(f"⚠️ Could not extract number from filename: {uploaded_file.name}")

    # Display uploaded images in grid
    if st.session_state.broll_uploaded_images:
        st.success(f"✅ Loaded {len(st.session_state.broll_uploaded_images)} images")

        with st.expander("📸 Preview Uploaded Images", expanded=False):
            # Create grid display
            sorted_nums = sorted(st.session_state.broll_uploaded_images.keys())
            cols = st.columns(min(5, len(sorted_nums)))

            for idx, img_num in enumerate(sorted_nums):
                col_idx = idx % len(cols)
                with cols[col_idx]:
                    st.image(
                        st.session_state.broll_uploaded_images[img_num],
                        caption=f"Image {img_num}",
                        use_container_width=True
                    )
                    st.caption(st.session_state.broll_image_filenames[img_num])


# ============================================================================
# UI - Prompt Input Section
# ============================================================================

st.subheader("2. Add Prompts")

input_tab1, input_tab2 = st.tabs(["📁 Upload File", "✍️ Manual Input"])

with input_tab1:
    uploaded_file = st.file_uploader(
        "Upload Prompts File",
        type=['txt', 'csv'],
        help="Text file: ID + Prompt blocks. CSV: columns 'id' (image number), 'prompt', 'number_of_videos'"
    )

    if uploaded_file:
        if st.button("📥 Load from File", type="secondary"):
            try:
                content = uploaded_file.getvalue().decode('utf-8')
                ext = uploaded_file.name.split('.')[-1].lower()

                new_items = []
                if ext == 'txt':
                    new_items = parse_txt_file_broll(content)
                elif ext == 'csv':
                    new_items = parse_csv_file_broll(content)

                is_valid, msg, warnings = validate_broll_batch(
                    new_items,
                    st.session_state.broll_uploaded_images
                )

                if is_valid:
                    st.session_state.batch_broll_items = new_items
                    st.session_state.broll_last_file_ext = ext
                    st.success(f"✅ Loaded {len(new_items)} prompts!")

                    if warnings:
                        for warning in warnings:
                            st.warning(f"⚠️ {warning}")

                    st.rerun()
                else:
                    st.error(f"❌ Invalid file: {msg}")
            except Exception as e:
                st.error(f"❌ Error parsing file: {str(e)}")

with input_tab2:
    manual_text = st.text_area(
        "Paste Prompts (TXT format)",
        height=200,
        placeholder="1 BROLL\n[VISUAL] Wide shot...\n\n2 BROLL\n[VISUAL] Close-up..."
    )
    if st.button("📥 Load from Text"):
        if manual_text.strip():
            new_items = parse_txt_file_broll(manual_text)
            is_valid, msg, warnings = validate_broll_batch(
                new_items,
                st.session_state.broll_uploaded_images
            )

            if is_valid:
                st.session_state.batch_broll_items = new_items
                st.session_state.broll_last_file_ext = 'txt'
                st.success(f"✅ Loaded {len(new_items)} prompts!")

                if warnings:
                    for warning in warnings:
                        st.warning(f"⚠️ {warning}")

                st.rerun()
            else:
                st.error(f"❌ Invalid format: {msg}")
        else:
            st.warning("⚠️ Please enter some text first")


# ============================================================================
# UI - Edit & Preview Section with Image Mapping
# ============================================================================

batch_items = st.session_state.batch_broll_items
file_ext = st.session_state.broll_last_file_ext

if batch_items:
    st.divider()
    st.subheader(f"3. Edit Prompts & Image Mapping ({len(batch_items)})")

    # Global clear
    if st.button("🗑️ Clear All"):
        st.session_state.batch_broll_items = []
        st.rerun()

    # Editable list with image preview
    items_to_remove = []

    for idx, item in enumerate(batch_items):
        with st.container():
            col1, col2, col3, col4 = st.columns([1, 1, 3, 0.5])

            # Ensure unique key for each widget using _ui_id
            ui_key = item.get('_ui_id', f"fallback_{idx}")

            with col1:
                # ID input
                new_id = st.text_input(
                    "ID",
                    value=item.get('id', f"video_{idx}"),
                    key=f"id_{ui_key}",
                    label_visibility="collapsed",
                    placeholder="ID"
                )
                st.session_state.batch_broll_items[idx]['id'] = new_id

                # Video count
                new_count = st.number_input(
                    "Count",
                    min_value=1,
                    max_value=4,
                    value=item.get('number_of_videos', 1),
                    key=f"cnt_{ui_key}",
                    label_visibility="collapsed"
                )
                st.session_state.batch_broll_items[idx]['number_of_videos'] = new_count

            with col2:
                # Image number input
                new_img_num = st.number_input(
                    "Image #",
                    min_value=1,
                    value=item.get('image_number', 1),
                    key=f"imgnum_{ui_key}",
                    label_visibility="collapsed"
                )
                st.session_state.batch_broll_items[idx]['image_number'] = new_img_num

                # Show thumbnail if available
                if new_img_num in st.session_state.broll_uploaded_images:
                    st.image(
                        st.session_state.broll_uploaded_images[new_img_num],
                        width=80,
                        caption=f"#{new_img_num}"
                    )
                else:
                    st.error(f"❌ Missing #{new_img_num}")

            with col3:
                # Prompt Text
                new_prompt = st.text_area(
                    "Prompt",
                    value=item.get('prompt', ''),
                    key=f"prm_{ui_key}",
                    height=100,
                    label_visibility="collapsed",
                    placeholder="Enter prompt here..."
                )
                st.session_state.batch_broll_items[idx]['prompt'] = new_prompt

            with col4:
                # Remove button
                if st.button("🗑️", key=f"del_{ui_key}", help="Remove this prompt"):
                    items_to_remove.append(idx)

            st.divider()

    # Process removals if any
    if items_to_remove:
        # Remove in reverse order
        for idx in sorted(items_to_remove, reverse=True):
            st.session_state.batch_broll_items.pop(idx)
        st.rerun()


# ============================================================================
# UI - Global Settings
# ============================================================================

if batch_items and st.session_state.broll_uploaded_images:
    st.divider()
    st.subheader("4. Global Settings")

    aspect_ratio_map = {
        "Landscape (16:9)": "VIDEO_ASPECT_RATIO_LANDSCAPE",
        "Portrait (9:16)": "VIDEO_ASPECT_RATIO_PORTRAIT"
    }

    aspect_ratio_label = st.selectbox(
        "Aspect Ratio (applies to all)",
        options=list(aspect_ratio_map.keys()),
        index=0
    )
    aspect_ratio = aspect_ratio_map[aspect_ratio_label]

    # Quota estimation
    total_videos_to_generate = estimate_quota_usage(batch_items)
    st.info(f"📊 This batch will generate approximately **{total_videos_to_generate} videos**")

    # Check if user has enough quota
    if st.session_state.quota_info:
        available = st.session_state.quota_info.get('available_quota', 0)
        if total_videos_to_generate > available:
            st.warning(f"⚠️ You may not have enough quota. Available: {available}, Needed: ~{total_videos_to_generate}")


# ============================================================================
# UI - Generate Button & Progress Tracking
# ============================================================================

if batch_items and st.session_state.broll_uploaded_images and st.button("🚀 Generate All B-Roll Videos", use_container_width=True, type="primary"):
    # Final validation
    is_valid, error_msg, warnings = validate_broll_batch(
        batch_items,
        st.session_state.broll_uploaded_images
    )

    if not is_valid:
        st.error(f"❌ Validation failed: {error_msg}")
        st.stop()

    # Create containers
    progress_container = st.container()
    debug_container = st.container() if debug_mode else None

    with progress_container:
        st.info(f"🚀 Starting batch B-Roll generation for {len(batch_items)} prompts...")

        # Overall progress
        st.subheader("Overall Progress")
        overall_progress_bar = st.progress(0)
        overall_status = st.empty()
        time_text = st.empty()

        # Individual progress
        st.subheader("Individual Progress")
        progress_placeholders = {}
        for item in batch_items:
            progress_placeholders[item['id']] = st.empty()

        start_time = time.time()

        # Setup logger
        logger = None
        if debug_mode and debug_container:
            with debug_container:
                st.subheader("🔍 Debug Console")
                log_container = st.container()
                logger = StreamlitLogger(log_container)

        try:
            # Initialize client
            client = VEOClient(
                api_key=st.session_state.api_key,
                base_url="https://genaipro.vn/api/v1",
                debug=debug_mode,
                logger=logger
            )

            if logger:
                logger.info(f"Starting batch B-Roll generation for {len(batch_items)} prompts")

            # Initialize batch generator
            generator = BatchBRollVideoGenerator(client, logger)

            # Progress update function
            def update_progress_display():
                # Overall
                total = len(batch_items)
                completed = sum(1 for p in generator.progress.values() if p['status'] in ['completed', 'failed'])
                overall_progress_bar.progress(completed / total if total > 0 else 0)
                overall_status.text(f"Progress: {completed}/{total} prompts completed")

                elapsed = time.time() - start_time
                time_text.caption(f"Elapsed time: {elapsed:.1f}s")

                # Individual
                for prompt_id, placeholder in progress_placeholders.items():
                    progress_info = generator.progress.get(prompt_id, {'status': 'pending', 'percentage': 0})
                    status = progress_info['status']
                    percentage = progress_info.get('percentage', 0)
                    retry = progress_info.get('retry')
                    img_num = progress_info.get('image_number', '?')

                    if status == 'completed':
                        retry_text = f" (after {retry} retries)" if retry else ""
                        placeholder.success(f"✅ {prompt_id} (Image #{img_num}): Completed{retry_text}")
                    elif status == 'failed':
                        error = progress_info.get('error', 'Unknown error')
                        placeholder.error(f"❌ {prompt_id} (Image #{img_num}): Failed - {error[:100]}")
                    elif status == 'retrying':
                        delay = progress_info.get('delay', 0)
                        placeholder.warning(f"🔄 {prompt_id} (Image #{img_num}): Retrying in {delay}s (attempt {retry}/3)...")
                    elif status == 'processing':
                        retry_text = f" (retry {retry}/3)" if retry else ""
                        placeholder.info(f"⏳ {prompt_id} (Image #{img_num}): Processing... {percentage}%{retry_text}")
                    else:
                        placeholder.text(f"⏸️ {prompt_id} (Image #{img_num}): Pending...")

            # Run batch generation with progress updates
            async def run_with_updates():
                # Start generation task
                generation_task = asyncio.create_task(
                    generator.generate_batch(
                        batch_items=batch_items,
                        aspect_ratio=aspect_ratio,
                        image_bytes_dict=st.session_state.broll_uploaded_images
                    )
                )

                # Update progress while generating
                while not generation_task.done():
                    update_progress_display()
                    await asyncio.sleep(0.5)  # Update every 500ms

                # Final update
                update_progress_display()

                return await generation_task

            results = asyncio.run(run_with_updates())
            st.session_state.broll_results = results

            elapsed_total = time.time() - start_time
            st.success(f"✅ Batch B-Roll generation completed in {elapsed_total:.1f}s!")

        except AuthenticationError as e:
            st.error(f"🔐 Authentication Error: {str(e)}")
            st.info("💡 **Troubleshooting:**\n- Check that your API key is correct\n- Verify the key hasn't expired\n- Get a new key from https://genaipro.vn/docs-api")

        except QuotaExceededError as e:
            st.error(f"📊 Quota Exceeded: {str(e)}")
            st.info("💡 **Troubleshooting:**\n- Check your quota above\n- Wait for quota to reset\n- Upgrade your plan if needed")

        except NetworkError as e:
            st.error(f"🌐 Network Error: {str(e)}")
            st.info("💡 **Troubleshooting:**\n- Check your internet connection\n- Try again in a few moments\n- The API server might be experiencing issues")

        except VEOAPIError as e:
            st.error(f"❌ API Error: {str(e)}")
            st.info("💡 Enable Debug Mode above to see detailed logs")

        except Exception as e:
            st.error(f"❌ Unexpected Error: {str(e)}")
            st.info("💡 Enable Debug Mode above to see what went wrong")
            if logger:
                logger.error(f"Unexpected error: {str(e)}")


# ============================================================================
# UI - Results Display (Persistent)
# ============================================================================

if st.session_state.broll_results:
    results = st.session_state.broll_results
    st.divider()
    st.subheader("🎥 Generated B-Roll Videos")

    # Summary
    completed_results = [r for r in results.values() if r['status'] == 'completed']
    total_videos = sum(
        r['number_of_videos']
        for r in completed_results
    )
    completed_count = len(completed_results)
    failed_count = sum(1 for r in results.values() if r['status'] == 'failed')

    col1, col2, col3 = st.columns(3)
    col1.metric("✅ Successful", completed_count)
    col2.metric("🎬 Total Videos", total_videos)
    col3.metric("❌ Failed", failed_count)

    # -------------------------------------------------------------------------
    # Bulk Download (ZIP)
    # -------------------------------------------------------------------------
    if completed_count > 0:
        st.divider()
        st.subheader("📦 Bulk Download")

        # Prepare ZIP file
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for prompt_id, result_data in results.items():
                if result_data['status'] == 'completed':
                    video_bytes_list = result_data.get('video_bytes_list', [])

                    for idx, vid_bytes in enumerate(video_bytes_list):
                        # Clean prompt_id for filename
                        safe_id = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in prompt_id)
                        suffix = f"_{idx+1}" if len(video_bytes_list) > 1 else ""
                        filename = f"{safe_id}{suffix}.mp4"

                        zip_file.writestr(filename, vid_bytes)

        st.download_button(
            label=f"📥 Download All {total_videos} Videos (ZIP)",
            data=zip_buffer.getvalue(),
            file_name=f"batch_broll_{int(time.time())}.zip",
            mime="application/zip",
            type="primary",
            use_container_width=True
        )

    # -------------------------------------------------------------------------
    # Failed Prompts CSV
    # -------------------------------------------------------------------------
    if failed_count > 0:
        st.divider()
        failed_results = {pid: r for pid, r in results.items() if r['status'] == 'failed'}

        # Create CSV for failed prompts
        csv_buffer = io.StringIO()
        csv_writer = csv.writer(csv_buffer)
        csv_writer.writerow(['id', 'prompt', 'image_number', 'number_of_videos'])

        for prompt_id, result_data in failed_results.items():
            csv_writer.writerow([
                prompt_id,
                result_data['prompt'],
                result_data.get('image_number', ''),
                result_data.get('number_of_videos', 1)
            ])

        csv_data = csv_buffer.getvalue()

        st.download_button(
            label=f"📥 Download Failed Prompts CSV ({failed_count} items)",
            data=csv_data,
            file_name="failed_prompts_broll.csv",
            mime="text/csv",
            help="Download a CSV of failed prompts to retry later",
            use_container_width=True
        )
        st.caption("💡 Use this CSV to retry only the failed prompts")

    st.divider()

    # Display each result with source image
    for prompt_id, result_data in results.items():
        img_num = result_data.get('image_number', '?')

        with st.expander(f"🎬 {prompt_id} (Image #{img_num}): {result_data['prompt'][:100]}...", expanded=True):
            if result_data['status'] == 'completed':
                # Show source image alongside videos
                col1, col2 = st.columns([1, 3])

                with col1:
                    st.caption("**Source Image**")
                    if img_num in st.session_state.broll_uploaded_images:
                        st.image(
                            st.session_state.broll_uploaded_images[img_num],
                            caption=f"Image {img_num}",
                            use_container_width=True
                        )
                        st.caption(st.session_state.broll_image_filenames.get(img_num, f"image_{img_num}"))

                with col2:
                    data = result_data['data']
                    file_urls = data.get('file_urls', [])
                    if not file_urls and data.get('file_url'):
                        file_urls = [data.get('file_url')]

                    if file_urls:
                        for idx, vid_url in enumerate(file_urls):
                            if not vid_url: continue

                            # Clean prompt_id for filename
                            safe_id = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in prompt_id)
                            suffix = f"_{idx+1}" if len(file_urls) > 1 else ""

                            st.video(vid_url)

                            # Download button
                            vid_bytes = None
                            if result_data.get('video_bytes_list') and len(result_data['video_bytes_list']) > idx:
                                vid_bytes = result_data['video_bytes_list'][idx]

                            if vid_bytes:
                                st.download_button(
                                    label=f"⬇️ Download {safe_id}{suffix}.mp4",
                                    data=vid_bytes,
                                    file_name=f"{safe_id}{suffix}.mp4",
                                    mime="video/mp4",
                                    key=f"dl_{safe_id}_{idx}",
                                    use_container_width=True
                                )

                    # Details
                    with st.expander("ℹ️ Details"):
                        st.json({
                            "id": data.get('id'),
                            "prompt": result_data['prompt'],
                            "image_number": img_num,
                            "number_of_videos": result_data['number_of_videos'],
                            "file_urls": file_urls,
                            "created_at": data.get('created_at')
                        })

            elif result_data['status'] == 'failed':
                st.error(f"❌ Generation failed: {result_data['error']}")


# ============================================================================
# UI - Tips Section
# ============================================================================

with st.expander("💡 Tips for Batch B-Roll Generation"):
    st.markdown("""
    **What is B-Roll?**
    - B-Roll is supplementary footage that enriches your story
    - This tool generates videos from MULTIPLE reference images (one per prompt)
    - Each prompt uses its own unique starting frame
    - Perfect for creating diverse shots from different reference images

    **Image Naming:**
    - System extracts number from FIRST part before underscore
    - Examples: `1_broll_1.jpg` → 1, `2_something.jpg` → 2, `10.jpg` → 10
    - Use format: `{number}_{description}.{ext}` (e.g., `1_wide_shot.jpg`, `2_closeup.png`)

    **File Formats:**
    - **Text file (.txt)**: Multi-line prompts separated by blank lines. First line is the ID (with number), subsequent lines are the prompt.
    - **CSV file (.csv)**: Advanced control. Required columns: `id` (image number), `prompt`. Optional: `number_of_videos` (1-4)

    **Example TXT:**
    ```
    1 BROLL
    [VISUAL] Wide shot of landscape with dramatic lighting
    Camera slowly pans left

    2 BROLL
    [VISUAL] Close-up of subject with shallow depth of field
    Slow zoom in on eyes
    ```

    **Example CSV:**
    ```csv
    id,prompt,number_of_videos
    1,Wide shot with dramatic lighting,1
    2,Close-up with shallow DOF,2
    3,Aerial view of location,1
    ```

    **Image-to-Prompt Mapping:**
    - The `id` in CSV or first line in TXT determines which image to use
    - Example: Prompt with ID "1" uses image `1_something.jpg`
    - You can use the same image for multiple prompts (style variations)
    - Verify the mapping before generating to avoid wasted quota

    **Batch Size:**
    - Maximum 20 prompts per batch (videos take time)
    - Each prompt can generate 1-4 videos simultaneously
    - All prompts process in parallel for faster completion

    **Progress Tracking:**
    - Shows which image number is being used for each prompt
    - Individual progress displays status and percentage
    - Automatic retry for reCAPTCHA (403) and server errors (500)

    **Performance Tips:**
    - Videos take ~30-60s each to generate
    - Upload all images before loading prompts
    - Smaller batches (5-10) complete faster
    - Monitor your quota usage carefully
    """)
