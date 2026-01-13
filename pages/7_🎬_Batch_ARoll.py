"""Batch A-Roll Video Generation Page"""

import streamlit as st
import asyncio
import csv
import io
import time
import tempfile
import os
import uuid
from typing import List, Dict, Tuple, Optional

from utils.veo_client import VEOClient
from utils.sse_handler import parse_sse_stream
from utils.exceptions import VEOAPIError, AuthenticationError, QuotaExceededError, NetworkError
from utils.logger import StreamlitLogger
from utils.quota_display import display_quota

st.set_page_config(page_title="Batch A-Roll", page_icon="🎬", layout="wide")

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

st.title("🎬 Batch A-Roll Generator")

# Check API key
if not st.session_state.get('api_key'):
    st.error("⚠️ Please enter your API key in the sidebar first!")
    st.stop()

# Display quota
display_quota()

st.markdown("""
Generate multiple A-Roll videos in parallel from a single reference frame and multiple prompts.
Upload a `.txt` file (one prompt per line) or `.csv` file (with per-prompt control).
""")


# ============================================================================
# Helper Functions
# ============================================================================

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
                'id': prompt_id if prompt_id else f"video_{idx}",
                'prompt': prompt_text,
                'number_of_videos': 1  # Default
            })
    
    return prompts


def parse_csv_file(file_contents: str) -> List[Dict]:
    """Parse CSV file with columns: id, prompt, number_of_videos."""
    prompts = []
    reader = csv.DictReader(io.StringIO(file_contents))

    for idx, row in enumerate(reader, 1):
        if 'prompt' not in row or not row['prompt'].strip():
            continue  # Skip rows without prompt

        prompts.append({
            'id': row.get('id', f"video_{idx}"),
            'prompt': row['prompt'].strip(),
            'number_of_videos': int(row.get('number_of_videos', 1))
        })

    return prompts


def validate_batch_items(items: List[Dict]) -> Tuple[bool, str]:
    """Validate parsed batch items."""
    if not items:
        return False, "No valid prompts found in file"

    if len(items) > 20:
        return False, "Too many prompts (max 20 per batch for videos)"

    for item in items:
        if not item.get('prompt') or not item['prompt'].strip():
            return False, f"Empty prompt for item {item['id']}"

        num_videos = item.get('number_of_videos', 1)
        if num_videos < 1 or num_videos > 4:
            return False, f"Invalid number_of_videos ({num_videos}) for {item['id']}. Must be 1-4."

    return True, ""


def estimate_quota_usage(batch_items: List[Dict]) -> int:
    """Estimate total videos that will be generated."""
    return sum(item.get('number_of_videos', 1) for item in batch_items)


# ============================================================================
# Batch Video Generator Class
# ============================================================================

class BatchVideoGenerator:
    """Generate videos for multiple prompts in parallel."""

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
        number_of_videos: int,
        start_frame_path: str,
        max_retries: int = 3
    ) -> Optional[Dict]:
        """Generate videos for a single prompt with retry logic."""
        retry_count = 0
        base_delay = 2  # Start with 2 seconds
        
        while retry_count <= max_retries:
            try:
                self.progress[prompt_id] = {
                    'status': 'processing', 
                    'percentage': 0,
                    'retry': retry_count if retry_count > 0 else None
                }

                async with self.client.frames_to_video_stream(
                    start_frame_path=start_frame_path,
                    end_frame_path=None,  # No end frame for A-Roll
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
                            'retry': retry_count if retry_count > 0 else None
                        }

                        if status == 'completed':
                            # Check if file_url is missing, fetch from history
                            if not event_data.get('file_url'):
                                if self.logger:
                                    self.logger.warning(f"Result for '{prompt_id}' missing file_url, fetching from history...")

                                try:
                                    history = await self.client.get_histories(page=1, page_size=10)
                                    for item in history.get('data', []):
                                        if prompt.lower() in item.get('prompt', '').lower():
                                            event_data = item
                                            if self.logger:
                                                self.logger.success(f"Found video in history for '{prompt_id}'")
                                            break
                                except Exception as e:
                                    if self.logger:
                                        self.logger.error(f"Failed to fetch from history: {str(e)}")

                            self.results[prompt_id] = {
                                'status': 'completed',
                                'data': event_data,
                                'prompt': prompt,
                                'number_of_videos': number_of_videos
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
                        'delay': delay
                    }
                    
                    await asyncio.sleep(delay)
                    continue  # Retry
                else:
                    # Final failure or non-retryable error
                    self.progress[prompt_id] = {'status': 'failed', 'percentage': 0, 'error': error_str}
                    self.results[prompt_id] = {
                        'status': 'failed',
                        'error': error_str,
                        'prompt': prompt
                    }
                    if self.logger:
                        self.logger.error(f"Failed to generate for '{prompt}': {error_str}")
                    return None
        
        # Should not reach here, but just in case
        return None

    async def generate_batch(
        self,
        batch_items: List[Dict],
        aspect_ratio: str,
        start_frame_path: str
    ) -> Dict[str, Dict]:
        """Generate videos for all prompts in parallel."""
        tasks = [
            self.generate_single(
                prompt_id=item['id'],
                prompt=item['prompt'],
                aspect_ratio=aspect_ratio,
                number_of_videos=item['number_of_videos'],
                start_frame_path=start_frame_path
            )
            for item in batch_items
        ]

        # Run all tasks concurrently
        await asyncio.gather(*tasks, return_exceptions=True)

        return self.results


# ============================================================================
# UI - Input Section
# ============================================================================

if 'batch_items' not in st.session_state:
    st.session_state.batch_items = []

if 'last_file_ext' not in st.session_state:
    st.session_state.last_file_ext = 'txt'

st.subheader("1. Add Prompts")

input_tab1, input_tab2 = st.tabs(["📁 Upload File", "✍️ Manual Input"])

with input_tab1:
    uploaded_file = st.file_uploader(
        "Upload Prompts File",
        type=['txt', 'csv'],
        help="Text file: ID + Prompt blocks. CSV: columns 'prompt', 'number_of_videos', 'id'"
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
                    st.session_state.batch_items = new_items
                    st.session_state.last_file_ext = ext
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
        placeholder="1 AROLL\n[VISUAL] Capybara...\n\n2 AROLL\n[VISUAL] Another scene..."
    )
    if st.button("� Load from Text"):
        if manual_text.strip():
            new_items = parse_txt_file(manual_text)
            is_valid, msg = validate_batch_items(new_items)
            if is_valid:
                st.session_state.batch_items = new_items
                st.session_state.last_file_ext = 'txt'
                st.success(f"✅ Loaded {len(new_items)} prompts!")
                st.rerun()
            else:
                st.error(f"❌ Invalid format: {msg}")
        else:
            st.warning("⚠️ Please enter some text first")

# ============================================================================
# UI - Edit & Preview Section
# ============================================================================

batch_items = st.session_state.batch_items
file_ext = st.session_state.last_file_ext

if batch_items:
    st.divider()
    st.subheader(f"2. Edit Prompts ({len(batch_items)})")
    
    # Global clear
    if st.button("🗑️ Clear All"):
        st.session_state.batch_items = []
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
                    value=item['id'], 
                    key=f"id_{ui_key}",
                    label_visibility="collapsed",
                    placeholder="ID"
                )
                st.session_state.batch_items[idx]['id'] = new_id
                
                new_count = st.number_input(
                    "Count", 
                    min_value=1, 
                    max_value=4, 
                    value=item['number_of_videos'], 
                    key=f"cnt_{ui_key}", 
                    label_visibility="collapsed"
                )
                st.session_state.batch_items[idx]['number_of_videos'] = new_count

            with col2:
                # Remove button
                if st.button("🗑️", key=f"del_{ui_key}", help="Remove this prompt"):
                    items_to_remove.append(idx)
            
            with col3:
                # Prompt Text
                new_prompt = st.text_area(
                    "Prompt", 
                    value=item['prompt'], 
                    key=f"prm_{ui_key}",
                    height=100,
                    label_visibility="collapsed",
                    placeholder="Enter prompt here..."
                )
                st.session_state.batch_items[idx]['prompt'] = new_prompt
            
            st.divider()

    # Process removals if any
    if items_to_remove:
        # Remove in reverse order
        for idx in sorted(items_to_remove, reverse=True):
            st.session_state.batch_items.pop(idx)
        st.rerun()


# ============================================================================
# UI - Reference Frame Upload (REQUIRED)
# ============================================================================

if batch_items:
    st.divider()
    st.subheader("📷 Reference Frame (Required)")

    reference_frame = st.file_uploader(
        "Upload a reference frame (used for all videos)",
        type=['jpg', 'jpeg', 'png', 'webp'],
        help="This image will be used as the starting frame for all video generations"
    )

    if reference_frame:
        col1, col2 = st.columns([1, 2])
        with col1:
            st.image(reference_frame, caption="Reference Frame", width='stretch')
        with col2:
            st.info("💡 This reference frame will be used as the starting point for all video generations in the batch.")


# ============================================================================
# UI - Global Settings
# ============================================================================

if batch_items and reference_frame:
    st.divider()
    st.subheader("Global Settings")

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

    if file_ext == 'txt':
        st.info("💡 All prompts will generate 1 video each. Use CSV format for per-prompt control.")
    else:
        st.info("💡 Number of videos per prompt is set in the CSV file.")

    # Quota estimation
    total_videos_to_generate = estimate_quota_usage(batch_items)
    st.info(f"📊 This batch will generate approximately **{total_videos_to_generate} videos**")

    # Check if user has enough quota
    if st.session_state.quota_info:
        available = st.session_state.quota_info.get('available_quota', 0)
        if total_videos_to_generate > available:
            st.warning(f"⚠️ You may not have enough quota. Available: {available}, Needed: ~{total_videos_to_generate}")

    debug_mode = st.checkbox("🔍 Enable Debug Mode", value=False, help="Show detailed API communication logs")


# ============================================================================
# UI - Generate Button & Progress Tracking
# ============================================================================

if batch_items and reference_frame and st.button("🚀 Generate All Videos", width='stretch', type="primary"):
    # Create containers
    progress_container = st.container()
    debug_container = st.container() if debug_mode else None

    with progress_container:
        st.info(f"🚀 Starting batch video generation for {len(batch_items)} prompts...")

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

        # Save reference frame to temp file
        start_frame_path = None
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            tmp.write(reference_frame.getvalue())
            start_frame_path = tmp.name

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
            generator = BatchVideoGenerator(client, logger)

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
                        start_frame_path=start_frame_path
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

            elapsed_total = time.time() - start_time
            st.success(f"✅ Batch generation completed in {elapsed_total:.1f}s!")

            # ============================================================================
            # UI - Results Display
            # ============================================================================

            if results:
                st.divider()
                st.subheader("🎥 Generated Videos")

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

                # Failed prompts CSV download
                if failed_count > 0:
                    st.divider()
                    failed_results = {pid: r for pid, r in results.items() if r['status'] == 'failed'}
                    
                    # Create CSV for failed prompts
                    csv_buffer = io.StringIO()
                    csv_writer = csv.writer(csv_buffer)
                    csv_writer.writerow(['id', 'prompt', 'number_of_videos'])
                    
                    for prompt_id, result_data in failed_results.items():
                        csv_writer.writerow([
                            prompt_id,
                            result_data['prompt'],
                            result_data.get('number_of_videos', 1)
                        ])
                    
                    csv_data = csv_buffer.getvalue()
                    
                    st.download_button(
                        label=f"📥 Download Failed Prompts CSV ({failed_count} items)",
                        data=csv_data,
                        file_name="failed_prompts_aroll.csv",
                        mime="text/csv",
                        help="Download a CSV of failed prompts to retry later"
                    )
                    st.caption("💡 Use this CSV to retry only the failed prompts")

                st.divider()

                # Display each result
                for prompt_id, result_data in results.items():
                    with st.expander(f"🎬 {prompt_id}: {result_data['prompt'][:100]}...", expanded=True):
                        if result_data['status'] == 'completed':
                            data = result_data['data']

                            file_url = data.get('file_url')
                            if file_url:
                                # Clean prompt_id for filename (remove special chars)
                                safe_id = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in prompt_id)
                                st.video(file_url)
                                
                                # Create download link with filename suggestion
                                st.markdown(
                                    f'<a href="{file_url}" download="{safe_id}.mp4" target="_blank">'
                                    f'<button style="width:100%; padding:0.5rem; background-color:#0066cc; color:white; border:none; border-radius:0.25rem; cursor:pointer;">⬇️ Download {safe_id}.mp4</button>'
                                    f'</a>',
                                    unsafe_allow_html=True
                                )

                                # Details
                                with st.expander("ℹ️ Details"):
                                    st.json({
                                        "id": data.get('id'),
                                        "prompt": result_data['prompt'],
                                        "number_of_videos": result_data['number_of_videos'],
                                        "file_url": file_url,
                                        "created_at": data.get('created_at')
                                    })
                            else:
                                st.warning("⚠️ Video URL not available. Check the History page.")

                        elif result_data['status'] == 'failed':
                            st.error(f"❌ Generation failed: {result_data['error']}")

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
            # Cleanup reference frame temp file
            if start_frame_path and os.path.exists(start_frame_path):
                try:
                    os.unlink(start_frame_path)
                except:
                    pass


# ============================================================================
# UI - Tips Section
# ============================================================================

with st.expander("💡 Tips for Batch A-Roll Generation"):
    st.markdown("""
    **What is A-Roll?**
    - A-Roll is the main footage that tells your story
    - This tool generates videos from a single starting frame with different prompts
    - Perfect for creating multiple variations from one reference image

    **File Formats:**
    - **Text file (.txt)**: Multi-line prompts separated by blank lines. First line is the ID, subsequent lines are the prompt.
    - **CSV file (.csv)**: Advanced control. Required column: `prompt`. Optional: `number_of_videos` (1-4), `id` (for tracking)

    **Example TXT (multi-line prompts):**
    ```
    2 AROLL
    [VISUAL] Capybara looking into camera with exhausted expression
    [VOICE STYLE] Deep, manly, American accent
    [CAPYBARA VOICEOVER]: Look, I get it...

    3 AROLL
    [VISUAL] Close-up of capybara slowly nodding
    [VOICE STYLE] Deep, manly, American accent
    [CAPYBARA VOICEOVER]: But here's the truth...
    ```
    
    **Example CSV:**
    ```csv
    id,prompt,number_of_videos
    shot1,Slow zoom in on subject with dramatic lighting,1
    shot2,Camera pans left revealing environment,2
    shot3,Subject moves forward towards camera,1
    ```

    **Reference Frame:**
    - **Required** for all batch video generations
    - The same reference frame is used for ALL videos in the batch
    - Choose a high-quality image that represents your desired starting point

    **Batch Size:**
    - Maximum 20 prompts per batch (videos take longer than images)
    - Each prompt can generate 1-4 videos simultaneously
    - All prompts process in parallel for faster completion

    **Multi-line Prompts:**
    - For TXT files, separate each prompt with a blank line
    - First line of each block = ID (e.g., "2 AROLL")
    - Remaining lines = full prompt content (preserves newlines)
    - Perfect for detailed video scripts with visual directions and voiceover

    **Progress Tracking:**
    - Overall progress shows how many prompts are completed
    - Individual progress shows status and percentage per prompt
    - Failed prompts show error messages
    - Automatic retry for reCAPTCHA (403) and server errors (500)

    **Performance Tips:**
    - Videos take longer than images (~30-60s each)
    - Smaller batches (5-10) complete faster
    - Monitor your quota usage carefully
    """)
