"""Batch Image Generation Page"""

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
from typing import List, Dict, Tuple, Optional

from utils.veo_client import VEOClient
from utils.sse_handler import parse_sse_stream
from utils.exceptions import VEOAPIError, AuthenticationError, QuotaExceededError, NetworkError
from utils.logger import StreamlitLogger
from utils.quota_display import display_quota
from utils.sidebar import render_sidebar
from utils.retry_handler import RetryHandler

st.set_page_config(page_title="B-ROLL Images", page_icon="📦", layout="wide")

# Password protection
from utils.auth import require_password
require_password()

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
</style>
""", unsafe_allow_html=True)

st.title("📦 B-ROLL Images Generation")

# Render Sidebar
render_sidebar()

# Check API key
if not st.session_state.get('api_key'):
    st.warning("⚠️ Please enter your API key in the sidebar first!")
    st.stop()

# Display quota
display_quota()

st.markdown("""
Generate multiple images in parallel from a list of prompts.
Upload a `.txt` file (one prompt per line) or `.csv` file (with per-prompt control).
""")


# ============================================================================
# Helper Functions
# ============================================================================

def get_unique_id():
    """Generate a unique ID for UI widgets."""
    return str(uuid.uuid4())


def parse_txt_file(file_contents: str) -> List[Dict]:
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
        
        # First line is the ID, rest is the prompt
        if len(lines) == 1:
            # Single line: use as both ID and prompt
            prompt_id = lines[0].strip()
            prompt_text = lines[0].strip()
        else:
            # Multi-line: first line is ID, rest is prompt
            prompt_id = lines[0].strip()
            prompt_text = '\n'.join(lines[1:]).strip()
        
        if prompt_text:  # Only add if we have prompt content
            prompts.append({
                'id': prompt_id if prompt_id else f"prompt_{idx}",
                'prompt': prompt_text,
                'number_of_images': 1,  # Default
                '_ui_id': get_unique_id()  # For stable UI keys
            })
    
    return prompts


def parse_csv_file(file_contents: str) -> List[Dict]:
    """Parse CSV file with columns: id, prompt, number_of_images."""
    prompts = []
    reader = csv.DictReader(io.StringIO(file_contents))

    for idx, row in enumerate(reader, 1):
        if 'prompt' not in row or not row['prompt'].strip():
            continue  # Skip rows without prompt

        prompts.append({
            'id': row.get('id', f"prompt_{idx}"),
            'prompt': row['prompt'].strip(),
            'number_of_images': int(row.get('number_of_images', 1)),
            '_ui_id': get_unique_id()
        })

    return prompts


def validate_batch_items(items: List[Dict]) -> Tuple[bool, str]:
    """Validate parsed batch items."""
    if not items:
        return False, "No valid prompts found in file"

    if len(items) > 50:
        return False, "Too many prompts (max 50 per batch)"

    for item in items:
        if not item.get('prompt') or not item['prompt'].strip():
            return False, f"Empty prompt for item {item['id']}"

        num_images = item.get('number_of_images', 1)
        if num_images < 1 or num_images > 4:
            return False, f"Invalid number_of_images ({num_images}) for {item['id']}. Must be 1-4."

    return True, ""


def estimate_quota_usage(batch_items: List[Dict]) -> int:
    """Estimate total images that will be generated."""
    return sum(item.get('number_of_images', 1) for item in batch_items)


# ============================================================================
# Batch Image Generator Class
# ============================================================================

class BatchImageGenerator:
    """Generate images for multiple prompts in parallel."""

    def __init__(self, client: VEOClient, logger=None):
        self.client = client
        self.logger = logger
        self.results = {}  # {prompt_id: result_data}
        self.progress = {}  # {prompt_id: {status, percentage, error}}

    async def generate_single(
        self,
        prompt_id: str,
        prompt: str,
        aspect_ratio: str,
        number_of_images: int,
        reference_image_path: Optional[str] = None
    ) -> Optional[Dict]:
        """Generate images for a single prompt with retry logic for reCAPTCHA errors."""

        # Define the generation function to be retried
        async def do_generation():
            self.progress[prompt_id] = {
                'status': 'processing',
                'percentage': 0
            }

            reference_images = [reference_image_path] if reference_image_path else None

            async with self.client.create_image_stream(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                number_of_images=number_of_images,
                reference_images=reference_images
            ) as response:
                async for event_data in parse_sse_stream(response, logger=self.logger):
                    # Update progress
                    percentage = event_data.get('process_percentage', 0)
                    status = event_data.get('status', 'processing')

                    self.progress[prompt_id] = {
                        'status': status,
                        'percentage': percentage
                    }

                    if status == 'completed':
                        # Check if file_url is missing, fetch from history
                        if not event_data.get('file_url') and not event_data.get('file_urls'):
                            if self.logger:
                                self.logger.warning(f"Result for '{prompt_id}' missing file_url, fetching from history...")

                            try:
                                history = await self.client.get_histories(page=1, page_size=5)
                                for item in history.get('data', []):
                                    if prompt.lower() in item.get('prompt', '').lower():
                                        event_data = item
                                        if self.logger:
                                            self.logger.success(f"Found video in history for '{prompt_id}'")
                                        break
                            except Exception as e:
                                if self.logger:
                                    self.logger.error(f"Failed to fetch from history: {str(e)}")

                        # Fetch image bytes for reliable downloading/renaming
                        image_bytes_list = []
                        file_urls = event_data.get('file_urls', [])
                        if not file_urls and event_data.get('file_url'):
                            file_urls = [event_data.get('file_url')]

                        if file_urls:
                            try:
                                async with httpx.AsyncClient() as client:
                                    for url in file_urls:
                                        resp = await client.get(url, timeout=30.0)
                                        if resp.status_code == 200:
                                            image_bytes_list.append(resp.content)
                            except Exception as dl_err:
                                if self.logger:
                                    self.logger.error(f"Failed to download image bytes: {str(dl_err)}")

                        self.results[prompt_id] = {
                            'status': 'completed',
                            'data': event_data,
                            'prompt': prompt,
                            'number_of_images': number_of_images,
                            'image_bytes_list': image_bytes_list
                        }
                        return event_data

                    elif status == 'failed':
                        error_msg = event_data.get('error', 'Generation failed')
                        raise Exception(error_msg)

        # Callback for retry progress updates
        def on_retry_callback(retry_count: int, delay: float, error_msg: str):
            self.progress[prompt_id] = {
                'status': 'retrying',
                'percentage': 0,
                'retry': retry_count,
                'delay': delay,
                'error': error_msg[:100]
            }

        # Execute with retry logic using shared handler
        try:
            result = await RetryHandler.retry_with_backoff(
                do_generation,
                logger=self.logger,
                on_retry=on_retry_callback
            )
            return result
        except Exception as e:
            # Final failure after all retries exhausted
            error_str = str(e)
            self.progress[prompt_id] = {'status': 'failed', 'percentage': 0, 'error': error_str}
            self.results[prompt_id] = {
                'status': 'failed',
                'error': error_str,
                'prompt': prompt
            }
            if self.logger:
                self.logger.error(f"Failed to generate for '{prompt}': {error_str}")
            return None

    async def generate_batch(
        self,
        batch_items: List[Dict],
        aspect_ratio: str,
        reference_image_path: Optional[str] = None
    ) -> Dict[str, Dict]:
        """Generate images for all prompts with staggered start times."""
        tasks = []

        # Start tasks with staggered delays to avoid overwhelming the API
        for idx, item in enumerate(batch_items):
            # Add a small delay between starting each task (0.5 seconds)
            # This spreads out the initial API requests
            if idx > 0:
                await asyncio.sleep(0.5)

            task = asyncio.create_task(
                self.generate_single(
                    prompt_id=item['id'],
                    prompt=item['prompt'],
                    aspect_ratio=aspect_ratio,
                    number_of_images=item['number_of_images'],
                    reference_image_path=reference_image_path
                )
            )
            tasks.append(task)

            if self.logger:
                self.logger.info(f"Started generation {idx + 1}/{len(batch_items)}: {item['id']}")

        # Wait for all tasks to complete
        await asyncio.gather(*tasks, return_exceptions=True)

        return self.results


# ============================================================================
# UI - Input Section
# ============================================================================

if 'batch_image_items' not in st.session_state:
    st.session_state.batch_image_items = []

if 'image_last_file_ext' not in st.session_state:
    st.session_state.image_last_file_ext = 'txt'

if 'image_results' not in st.session_state:
    st.session_state.image_results = None

st.subheader("1. Add Prompts")

input_tab1, input_tab2 = st.tabs(["📁 Upload File", "✍️ Manual Input"])

with input_tab1:
    uploaded_file = st.file_uploader(
        "Upload Prompts File",
        type=['txt', 'csv'],
        help="Text file: ID + Prompt blocks. CSV: columns 'prompt', 'number_of_images', 'id'"
    )
    
    if uploaded_file:
        if st.button("📥 Load from File", type="secondary"):
            try:
                content = uploaded_file.getvalue().decode('utf-8')
                ext = uploaded_file.name.split('.')[-1].lower()
                
                new_items = []
                if ext == 'txt':
                    new_items = parse_txt_file(content)
                elif ext == 'csv':
                    new_items = parse_csv_file(content)
                
                is_valid, msg = validate_batch_items(new_items)
                if is_valid:
                    st.session_state.batch_image_items = new_items
                    st.session_state.image_last_file_ext = ext
                    st.success(f"✅ Loaded {len(new_items)} prompts!")
                    st.rerun()
                else:
                    st.error(f"❌ Invalid file: {msg}")
            except Exception as e:
                st.error(f"❌ Error parsing file: {str(e)}")

with input_tab2:
    manual_text = st.text_area(
        "Paste Prompts (TXT format)", 
        height=200,
        placeholder="1 PROMPT\nA beautiful landscape...\n\n2 PROMPT\nA futuristic city..."
    )
    if st.button("📥 Load from Text"):
        if manual_text.strip():
            new_items = parse_txt_file(manual_text)
            is_valid, msg = validate_batch_items(new_items)
            if is_valid:
                st.session_state.batch_image_items = new_items
                st.session_state.image_last_file_ext = 'txt'
                st.success(f"✅ Loaded {len(new_items)} prompts!")
                st.rerun()
            else:
                st.error(f"❌ Invalid format: {msg}")
        else:
            st.warning("⚠️ Please enter some text first")

# ============================================================================
# UI - Edit & Preview Section
# ============================================================================

batch_items = st.session_state.batch_image_items
file_ext = st.session_state.image_last_file_ext

if batch_items:
    st.divider()
    st.subheader(f"2. Edit Prompts ({len(batch_items)})")
    
    # Global clear
    if st.button("🗑️ Clear All"):
        st.session_state.batch_image_items = []
        st.rerun()

    # Editable list
    items_to_remove = []
    
    for idx, item in enumerate(batch_items):
        with st.container():
            col1, col2, col3 = st.columns([1, 0.2, 4])
            
            # Ensure unique key for each widget using _ui_id
            ui_key = item.get('_ui_id', f"fallback_{idx}")
            
            with col1:
                # ID and Count
                new_id = st.text_input(
                    "ID", 
                    value=item.get('id', f"prompt_{idx}"), 
                    key=f"id_{ui_key}",
                    label_visibility="collapsed",
                    placeholder="ID"
                )
                st.session_state.batch_image_items[idx]['id'] = new_id
                
                new_count = st.number_input(
                    "Count", 
                    min_value=1, 
                    max_value=4, 
                    value=item.get('number_of_images', 1), 
                    key=f"cnt_{ui_key}", 
                    label_visibility="collapsed"
                )
                st.session_state.batch_image_items[idx]['number_of_images'] = new_count

            with col2:
                # Remove button
                if st.button("🗑️", key=f"del_{ui_key}", help="Remove this prompt"):
                    items_to_remove.append(idx)
            
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
                st.session_state.batch_image_items[idx]['prompt'] = new_prompt
            
            st.divider()

    # Process removals if any
    if items_to_remove:
        # Remove in reverse order
        for idx in sorted(items_to_remove, reverse=True):
            st.session_state.batch_image_items.pop(idx)
        st.rerun()


# ============================================================================
# UI - Reference Image Upload
# ============================================================================

if batch_items:
    st.divider()
    st.subheader("Optional Reference Image")

    reference_image = st.file_uploader(
        "Upload a reference image (used for all prompts)",
        type=['jpg', 'jpeg', 'png', 'webp'],
        help="This image will be used as a reference for all image generations"
    )

    if reference_image:
        col1, col2 = st.columns([1, 2])
        with col1:
            st.image(reference_image, caption="Reference Image", use_container_width=True)
        with col2:
            st.info("💡 This reference image will be used for all image generations in the batch.")


# ============================================================================
# UI - Global Settings
# ============================================================================

if batch_items:
    st.divider()
    st.subheader("Global Settings")

    aspect_ratio_map = {
        "Landscape (16:9)": "IMAGE_ASPECT_RATIO_LANDSCAPE",
        "Portrait (9:16)": "IMAGE_ASPECT_RATIO_PORTRAIT",
        "Square (1:1)": "IMAGE_ASPECT_RATIO_SQUARE"
    }

    aspect_ratio_label = st.selectbox(
        "Aspect Ratio (applies to all)",
        options=list(aspect_ratio_map.keys()),
        index=0
    )
    aspect_ratio = aspect_ratio_map[aspect_ratio_label]

    if file_ext == 'txt':
        st.info("💡 All prompts will generate 1 image each. Use CSV format for per-prompt control.")
    else:
        st.info("💡 Number of images per prompt is set in the CSV file.")

    # Quota estimation
    total_images_to_generate = estimate_quota_usage(batch_items)
    st.info(f"📊 This batch will generate approximately **{total_images_to_generate} images**")

    # Check if user has enough quota
    if st.session_state.quota_info:
        available = st.session_state.quota_info.get('available_quota', 0)
        if total_images_to_generate > available:
            st.warning(f"⚠️ You may not have enough quota. Available: {available}, Needed: ~{total_images_to_generate}")

    debug_mode = st.checkbox("🔍 Enable Debug Mode", value=False, help="Show detailed API communication logs")


# ============================================================================
# UI - Generate Button & Progress Tracking
# ============================================================================

if batch_items and st.button("🚀 Generate All Images", use_container_width=True, type="primary"):
    # Create containers
    progress_container = st.container()
    debug_container = st.container() if debug_mode else None

    with progress_container:
        st.info(f"🚀 Starting batch generation for {len(batch_items)} prompts...")

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

        # Save reference image to temp file if provided
        reference_image_path = None
        if 'reference_image' in locals() and reference_image:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                tmp.write(reference_image.getvalue())
                tmp.flush()  # Ensure data is written to disk
                os.fsync(tmp.fileno())  # Force OS to write to disk
                reference_image_path = tmp.name

        try:
            # Initialize client
            client = VEOClient(
                api_key=st.session_state.api_key,
                base_url="https://genaipro.vn/api/v1",
                debug=debug_mode,
                logger=logger
            )

            if logger:
                logger.info(f"Starting batch generation for {len(batch_items)} prompts")

            # Initialize batch generator
            generator = BatchImageGenerator(client, logger)

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

                    if status == 'completed':
                        retry_text = f" (after {retry} retries)" if retry else ""
                        placeholder.success(f"✅ {prompt_id}: Completed{retry_text}")
                    elif status == 'failed':
                        error = progress_info.get('error', 'Unknown error')
                        placeholder.error(f"❌ {prompt_id}: Failed - {error[:100]}")
                    elif status == 'retrying':
                        delay = progress_info.get('delay', 0)
                        placeholder.warning(f"🔄 {prompt_id}: Retrying in {delay}s (attempt {retry}/3)...")
                    elif status == 'processing':
                        retry_text = f" (retry {retry}/3)" if retry else ""
                        placeholder.info(f"⏳ {prompt_id}: Processing... {percentage}%{retry_text}")
                    else:
                        placeholder.text(f"⏸️ {prompt_id}: Pending...")

            # Run batch generation with progress updates
            async def run_with_updates():
                # Start generation task
                generation_task = asyncio.create_task(
                    generator.generate_batch(
                        batch_items=batch_items,
                        aspect_ratio=aspect_ratio,
                        reference_image_path=reference_image_path
                    )
                )

                # Update progress while generating
                while not generation_task.done():
                    update_progress_display()
                    await asyncio.sleep(0.5)  # Update every 500ms

                update_progress_display()

                return await generation_task


            results = asyncio.run(run_with_updates())
            st.session_state.image_results = results

            elapsed_total = time.time() - start_time
            st.success(f"✅ Batch generation completed in {elapsed_total:.1f}s!")

            # Update quota
            if st.session_state.quota_info:
                try:
                    quota = asyncio.run(client.get_quota())
                    st.session_state.quota_info = quota
                except:
                    pass

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

        finally:
            # Cleanup reference image temp file
            if reference_image_path and os.path.exists(reference_image_path):
                try:
                    os.unlink(reference_image_path)
                except:
                    pass


# ============================================================================
# UI - Results Display (Persistent)
# ============================================================================

if st.session_state.image_results:
    results = st.session_state.image_results
    st.divider()
    st.subheader("🖼️ Generated Images")

    # Summary
    completed_results = [r for r in results.values() if r['status'] == 'completed']
    total_images = sum(
        r['number_of_images']
        for r in completed_results
    )
    completed_count = len(completed_results)
    failed_count = sum(1 for r in results.values() if r['status'] == 'failed')

    col1, col2, col3 = st.columns(3)
    col1.metric("✅ Successful", completed_count)
    col2.metric("🖼️ Total Images", total_images)
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
                    image_bytes_list = result_data.get('image_bytes_list', [])

                    for idx, img_bytes in enumerate(image_bytes_list):
                        # Clean prompt_id for filename
                        safe_id = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in prompt_id)
                        suffix = f"_{idx+1}" if len(image_bytes_list) > 1 else ""
                        filename = f"{safe_id}{suffix}.png"

                        zip_file.writestr(filename, img_bytes)

        st.download_button(
            label=f"📥 Download All {total_images} Images (ZIP)",
            data=zip_buffer.getvalue(),
            file_name=f"batch_images_{int(time.time())}.zip",
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
        csv_writer.writerow(['id', 'prompt', 'number_of_images'])

        for prompt_id, result_data in failed_results.items():
            csv_writer.writerow([
                prompt_id,
                result_data['prompt'],
                result_data.get('number_of_images', 1)
            ])

        csv_data = csv_buffer.getvalue()

        st.download_button(
            label=f"📥 Download Failed Prompts CSV ({failed_count} items)",
            data=csv_data,
            file_name="failed_prompts_images.csv",
            mime="text/csv",
            help="Download a CSV of failed prompts to retry later",
            use_container_width=True
        )
        st.caption("💡 Use this CSV to retry only the failed prompts")

    st.divider()

    # Display each result
    for prompt_id, result_data in results.items():
        with st.expander(f"🖼️ {prompt_id}: {result_data['prompt'][:100]}...", expanded=True):
            if result_data['status'] == 'completed':
                data = result_data['data']

                file_urls = data.get('file_urls', [])
                if not file_urls and data.get('file_url'):
                    file_urls = [data.get('file_url')]

                if file_urls:
                    # Display images in grid
                    cols = st.columns(min(3, len(file_urls)))
                    for idx, img_url in enumerate(file_urls):
                        if not img_url: continue

                        col_idx = idx % len(cols)
                        with cols[col_idx]:
                            # Clean prompt_id for filename
                            safe_id = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in prompt_id)
                            suffix = f"_{idx+1}" if len(file_urls) > 1 else ""

                            st.image(img_url, use_container_width=True)

                            # Download button
                            img_bytes = None
                            if result_data.get('image_bytes_list') and len(result_data['image_bytes_list']) > idx:
                                img_bytes = result_data['image_bytes_list'][idx]

                            if img_bytes:
                                st.download_button(
                                    label=f"⬇️ Download",
                                    data=img_bytes,
                                    file_name=f"{safe_id}{suffix}.png",
                                    mime="image/png",
                                    key=f"dl_{safe_id}_{idx}",
                                    use_container_width=True
                                )

                    # Details
                    with st.expander("ℹ️ Details"):
                        st.json({
                            "id": data.get('id'),
                            "prompt": result_data['prompt'],
                            "number_of_images": result_data['number_of_images'],
                            "file_urls": file_urls,
                            "created_at": data.get('created_at')
                        })
                else:
                    st.warning("⚠️ Image URLs not available. Check the History page.")

            elif result_data['status'] == 'failed':
                st.error(f"❌ Generation failed: {result_data['error']}")


# ============================================================================
# UI - Tips Section
# ============================================================================

with st.expander("💡 Tips for Batch Image Generation"):
    st.markdown("""
    **File Formats:**
    - **Text file (.txt)**: Simple format, one prompt per line. All prompts generate 1 image each.
    - **CSV file (.csv)**: Advanced control. Required column: `prompt`. Optional: `number_of_images` (1-4), `id` (for tracking)

    **Example CSV:**
    ```csv
    id,prompt,number_of_images
    cap1,capybara eating grass,2
    cat1,cat sleeping on couch,1
    dog1,dog running in park,3
    ```

    **Reference Images:**
    - Uploading a reference image is optional
    - The same reference will be used for ALL prompts in the batch
    - Useful for maintaining consistent style across all generations

    **Batch Size:**
    - Maximum 50 prompts per batch
    - Larger batches may take longer and use more quota
    - All prompts generate simultaneously (parallel processing)

    **Progress Tracking:**
    - Overall progress shows how many prompts are completed
    - Individual progress shows status per prompt
    - Failed prompts show error message

    **Rate Limiting:**
    - The API may temporarily rate-limit if too many requests
    - Don't worry - the system automatically retries after waiting
    - For very large batches, consider splitting into multiple smaller batches
    """)
