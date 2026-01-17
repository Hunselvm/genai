"""Auto Generator Page - Automated Video/Image Generation Pipeline"""

import streamlit as st
import asyncio
import io
import time
import tempfile
import os
import uuid
from typing import List, Dict, Tuple

from utils.veo_client import VEOClient
from utils.logger import StreamlitLogger
from utils.quota_display import display_quota
from utils.sidebar import render_sidebar
from utils.progress_persistence import (
    AutomationJob, create_job, save_job, load_job,
    list_resumable_jobs, delete_job
)
from utils.automation_engine import (
    AutomationEngine, ProcessingResult, ErrorCategory,
    validate_prompts, categorize_error,
    create_chunked_zips, create_results_csv, create_failed_csv, create_pipeline_csv,
    RETRY_CONFIG, MAX_ZIP_SIZE_MB
)

st.set_page_config(page_title="Auto Generator", page_icon="🤖", layout="wide")

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
    .progress-log {
        max-height: 200px;
        overflow-y: auto;
        background: #1e1e1e;
        color: #d4d4d4;
        padding: 0.5rem;
        border-radius: 0.5rem;
        font-family: monospace;
        font-size: 0.8rem;
    }
</style>
""", unsafe_allow_html=True)

st.title("🤖 Auto Generator")

# Render Sidebar
render_sidebar()

# Check API key
if not st.session_state.get('api_key'):
    st.warning("⚠️ Please enter your API key in the sidebar first!")
    st.stop()

# Display quota
display_quota()

st.markdown("""
Automated content generation pipeline. Upload prompts and let the system process everything automatically.

**Modes:**
- **B-Roll Pipeline**: Prompts → Images → Videos (most common)
- **A-Roll Only**: Talking head + prompts → Videos
- **Images Only**: Generate images from prompts
""")


# =============================================================================
# Helper Functions
# =============================================================================

def get_unique_id():
    return str(uuid.uuid4())[:8]


def parse_txt_file(file_contents: str) -> List[Dict]:
    """Parse text file with multi-line prompts separated by blank lines."""
    blocks = file_contents.strip().split('\n\n')
    prompts = []
    
    for idx, block in enumerate(blocks, 1):
        block = block.strip()
        if not block:
            continue
        
        lines = block.split('\n')
        if len(lines) == 0:
            continue
        
        if len(lines) == 1:
            prompt_id = f"item_{idx}"
            prompt_text = lines[0].strip()
        else:
            prompt_id = lines[0].strip()
            prompt_text = '\n'.join(lines[1:]).strip()
        
        if prompt_text:
            prompts.append({
                'id': prompt_id if prompt_id else f"item_{idx}",
                'prompt': prompt_text,
                'number_of_images': 1,
                'number_of_videos': 1,
                '_ui_id': get_unique_id()
            })
    
    return prompts


def parse_csv_file(file_contents: str) -> List[Dict]:
    """Parse CSV file with columns: id, prompt, number_of_images/videos."""
    import csv
    prompts = []
    reader = csv.DictReader(io.StringIO(file_contents))

    for idx, row in enumerate(reader, 1):
        if 'prompt' not in row or not row['prompt'].strip():
            continue

        prompts.append({
            'id': row.get('id', f"item_{idx}"),
            'prompt': row['prompt'].strip(),
            'number_of_images': int(row.get('number_of_images', 1)),
            'number_of_videos': int(row.get('number_of_videos', 1)),
            '_ui_id': get_unique_id()
        })

    return prompts


# =============================================================================
# Session State Initialization
# =============================================================================

if 'auto_batch_items' not in st.session_state:
    st.session_state.auto_batch_items = []

if 'auto_results' not in st.session_state:
    st.session_state.auto_results = None

if 'auto_pipeline_results' not in st.session_state:
    st.session_state.auto_pipeline_results = None

if 'auto_is_running' not in st.session_state:
    st.session_state.auto_is_running = False

if 'auto_current_job' not in st.session_state:
    st.session_state.auto_current_job = None

if 'auto_log_messages' not in st.session_state:
    st.session_state.auto_log_messages = []


# =============================================================================
# Resume Previous Jobs Section
# =============================================================================

resumable_jobs = list_resumable_jobs()
if resumable_jobs:
    with st.expander(f"📂 Resume Previous Job ({len(resumable_jobs)} available)", expanded=False):
        for job_info in resumable_jobs:
            col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
            
            with col1:
                progress_pct = (job_info['completed'] + job_info['failed']) / job_info['total'] * 100
                st.text(f"{job_info['mode']} | {job_info['completed']}/{job_info['total']} done | {progress_pct:.0f}%")
            
            with col2:
                st.caption(job_info['last_updated'][:16])
            
            with col3:
                if st.button("▶️ Resume", key=f"resume_{job_info['job_id']}"):
                    job = load_job(job_info['job_id'])
                    if job:
                        st.session_state.auto_current_job = job
                        st.session_state.auto_batch_items = job.get_pending_items()
                        st.success(f"Loaded job with {len(st.session_state.auto_batch_items)} pending items")
                        st.rerun()
            
            with col4:
                if st.button("🗑️", key=f"delete_{job_info['job_id']}"):
                    delete_job(job_info['job_id'])
                    st.rerun()


# =============================================================================
# Mode Selection
# =============================================================================

st.divider()
st.subheader("1. Select Mode")

mode = st.radio(
    "Generation Mode",
    options=['broll_pipeline', 'aroll', 'images'],
    format_func=lambda x: {
        'broll_pipeline': '🎬 B-Roll Pipeline (Images → Videos)',
        'aroll': '🎤 A-Roll Only (Talking Head Videos)',
        'images': '🖼️ Images Only'
    }[x],
    horizontal=True
)


# =============================================================================
# File Upload Section
# =============================================================================

st.divider()
st.subheader("2. Upload Prompts")

col1, col2 = st.columns(2)

with col1:
    uploaded_file = st.file_uploader(
        "Upload Prompts File",
        type=['txt', 'csv'],
        help="TXT: ID + Prompt blocks. CSV: columns 'id', 'prompt'"
    )

with col2:
    if mode == 'aroll':
        reference_frame = st.file_uploader(
            "Upload Talking Head Frame (Required)",
            type=['jpg', 'jpeg', 'png', 'webp'],
            help="Reference frame for A-Roll videos"
        )
        if reference_frame:
            st.image(reference_frame, caption="Reference Frame", width=200)
    else:
        reference_frame = None

if uploaded_file:
    if st.button("📥 Load Prompts", type="secondary"):
        try:
            content = uploaded_file.getvalue().decode('utf-8')
            ext = uploaded_file.name.split('.')[-1].lower()
            
            new_items = []
            if ext == 'txt':
                new_items = parse_txt_file(content)
            elif ext == 'csv':
                new_items = parse_csv_file(content)
            
            if new_items:
                st.session_state.auto_batch_items = new_items
                st.success(f"✅ Loaded {len(new_items)} prompts!")
                st.rerun()
            else:
                st.error("No valid prompts found in file")
        except Exception as e:
            st.error(f"❌ Error parsing file: {str(e)}")


# =============================================================================
# Prompts Preview & Validation
# =============================================================================

batch_items = st.session_state.auto_batch_items

if batch_items:
    st.divider()
    st.subheader(f"3. Review Prompts ({len(batch_items)} items)")
    
    # Validation
    valid_items, validation_errors = validate_prompts(batch_items)
    
    if validation_errors:
        st.warning(f"⚠️ {len(validation_errors)} invalid prompts detected")
        with st.expander("View Validation Errors"):
            for err in validation_errors:
                st.error(err)
        
        if st.checkbox("Proceed with valid prompts only"):
            st.session_state.auto_batch_items = valid_items
            batch_items = valid_items
            st.rerun()
    
    # Preview
    with st.expander("View All Prompts", expanded=False):
        for idx, item in enumerate(batch_items[:20]):  # Show first 20
            st.text(f"{item['id']}: {item['prompt'][:100]}...")
        if len(batch_items) > 20:
            st.caption(f"... and {len(batch_items) - 20} more")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🗑️ Clear All"):
            st.session_state.auto_batch_items = []
            st.session_state.auto_results = None
            st.session_state.auto_pipeline_results = None
            st.rerun()


# =============================================================================
# Settings
# =============================================================================

if batch_items:
    st.divider()
    st.subheader("4. Settings")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if mode == 'images':
            aspect_ratio_options = {
                "Landscape (16:9)": "IMAGE_ASPECT_RATIO_LANDSCAPE",
                "Portrait (9:16)": "IMAGE_ASPECT_RATIO_PORTRAIT",
                "Square (1:1)": "IMAGE_ASPECT_RATIO_SQUARE"
            }
        else:
            aspect_ratio_options = {
                "Landscape (16:9)": "VIDEO_ASPECT_RATIO_LANDSCAPE",
                "Portrait (9:16)": "VIDEO_ASPECT_RATIO_PORTRAIT"
            }
        
        aspect_ratio_label = st.selectbox("Aspect Ratio", list(aspect_ratio_options.keys()))
        aspect_ratio = aspect_ratio_options[aspect_ratio_label]
    
    with col2:
        debug_mode = st.checkbox("🔍 Debug Mode", value=False)
    
    with col3:
        # Show config info
        if mode == 'images':
            config = RETRY_CONFIG['images']
        else:
            config = RETRY_CONFIG['videos']
        
        st.caption(f"Timeout: {config['timeout_minutes']}min")
        st.caption(f"Max concurrent: {config['max_concurrent']}")


# =============================================================================
# Generate Button & Progress
# =============================================================================

if batch_items and (mode != 'aroll' or reference_frame):
    st.divider()
    
    # Estimate
    total_items = len(batch_items)
    if mode == 'broll_pipeline':
        st.info(f"📊 Will generate {total_items} images, then {total_items} videos")
    elif mode == 'images':
        st.info(f"📊 Will generate {total_items} images")
    else:
        st.info(f"📊 Will generate {total_items} videos")
    
    if st.button("🚀 Start Generation", type="primary", use_container_width=True):
        st.session_state.auto_is_running = True
        st.session_state.auto_log_messages = []
        
        # Create containers
        progress_container = st.container()
        log_container = st.container()
        debug_container = st.container() if debug_mode else None
        
        with progress_container:
            st.subheader("⏳ Processing...")
            
            # Progress elements
            progress_bar = st.progress(0)
            col1, col2, col3, col4 = st.columns(4)
            completed_metric = col1.empty()
            failed_metric = col2.empty()
            remaining_metric = col3.empty()
            elapsed_metric = col4.empty()
            
            status_text = st.empty()
            log_display = st.empty()
        
        # Setup logger
        logger = None
        if debug_mode and debug_container:
            with debug_container:
                st.subheader("🔍 Debug Console")
                debug_log_container = st.container()
                logger = StreamlitLogger(debug_log_container)
        
        # Save reference frame to temp file if provided
        start_frame_path = None
        if reference_frame:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                tmp.write(reference_frame.getvalue())
                tmp.flush()
                os.fsync(tmp.fileno())
                start_frame_path = tmp.name
        
        start_time = time.time()
        progress_state = {
            'completed_count': 0,
            'failed_count': 0,
            'log_messages': []
        }
        
        def update_ui():
            total = len(batch_items)
            done = progress_state['completed_count'] + progress_state['failed_count']
            
            progress_bar.progress(done / total if total > 0 else 0)
            completed_metric.metric("✅ Completed", progress_state['completed_count'])
            failed_metric.metric("❌ Failed", progress_state['failed_count'])
            remaining_metric.metric("⏳ Remaining", total - done)
            elapsed_metric.metric("⏱️ Elapsed", f"{time.time() - start_time:.0f}s")
            
            # Show recent logs
            if progress_state['log_messages']:
                recent_logs = progress_state['log_messages'][-10:]
                log_html = "<div class='progress-log'>" + "<br>".join(recent_logs) + "</div>"
                log_display.markdown(log_html, unsafe_allow_html=True)
        
        def progress_callback(event_type: str, data: dict):
            if event_type == 'item_completed':
                progress_state['completed_count'] += 1
                progress_state['log_messages'].append(f"<span style='color:#4caf50'>✅ {data['id']}: Completed</span>")
            elif event_type == 'item_failed':
                progress_state['failed_count'] += 1
                progress_state['log_messages'].append(f"<span style='color:#f44336'>❌ {data['id']}: {data.get('error', 'Failed')[:50]}</span>")
            elif event_type == 'item_started':
                progress_state['log_messages'].append(f"<span style='color:#2196f3'>⏳ {data['id']}: Starting...</span>")
            elif event_type == 'step_started':
                status_text.info(f"📍 {data['name']}")
            elif event_type == 'batch_started':
                status_text.info(f"Starting {data['content_type']} generation ({data['total']} items)")
            
            update_ui()
        
        try:
            # Initialize client
            client = VEOClient(
                api_key=st.session_state.api_key,
                base_url="https://genaipro.vn/api/v1",
                debug=debug_mode,
                logger=logger
            )
            
            # Create job for persistence
            job = create_job(mode, batch_items, {'aspect_ratio': aspect_ratio})
            job.status = 'running'
            save_job(job)
            st.session_state.auto_current_job = job
            
            async def run_generation():
                if mode == 'broll_pipeline':
                    engine = AutomationEngine(
                        client=client,
                        content_type='images',
                        progress_callback=progress_callback,
                        logger=logger
                    )
                    results = await engine.run_broll_pipeline(batch_items, aspect_ratio, job)
                    return results, 'pipeline'
                
                elif mode == 'images':
                    engine = AutomationEngine(
                        client=client,
                        content_type='images',
                        progress_callback=progress_callback,
                        logger=logger
                    )
                    results = await engine.generate_images_batch(batch_items, aspect_ratio, job)
                    return results, 'images'
                
                else:  # aroll
                    engine = AutomationEngine(
                        client=client,
                        content_type='videos',
                        progress_callback=progress_callback,
                        logger=logger
                    )
                    results = await engine.generate_videos_batch(
                        batch_items, aspect_ratio, start_frame_path, job
                    )
                    return results, 'videos'
            
            results, result_type = asyncio.run(run_generation())
            
            if result_type == 'pipeline':
                st.session_state.auto_pipeline_results = results
            else:
                st.session_state.auto_results = results
            
            # Mark job complete
            job.status = 'completed'
            save_job(job)
            
            elapsed = time.time() - start_time
            st.success(f"✅ Generation completed in {elapsed:.0f}s!")
            
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
            if logger:
                logger.error(f"Error: {str(e)}")
        
        finally:
            st.session_state.auto_is_running = False
            
            # Cleanup temp file
            if start_frame_path and os.path.exists(start_frame_path):
                try:
                    os.unlink(start_frame_path)
                except:
                    pass


# =============================================================================
# Results Display
# =============================================================================

# Pipeline results
if st.session_state.auto_pipeline_results:
    results = st.session_state.auto_pipeline_results
    
    st.divider()
    st.subheader("🎬 Pipeline Results")
    
    # Summary
    completed_images = sum(1 for r in results.values() if r.get('image_status') == 'completed')
    completed_videos = sum(1 for r in results.values() if r.get('video_status') == 'completed')
    failed_count = sum(1 for r in results.values() if r.get('image_status') == 'failed' or r.get('video_status') == 'failed')
    
    col1, col2, col3 = st.columns(3)
    col1.metric("🖼️ Images", completed_images)
    col2.metric("🎥 Videos", completed_videos)
    col3.metric("❌ Failed", failed_count)
    
    # Download CSV
    csv_data = create_pipeline_csv(results)
    st.download_button(
        "📥 Download Results CSV",
        csv_data,
        "pipeline_results.csv",
        "text/csv",
        use_container_width=True
    )

# Regular results (images or videos)
elif st.session_state.auto_results:
    results = st.session_state.auto_results
    
    st.divider()
    st.subheader("📦 Results")
    
    # Summary
    completed_results = {k: v for k, v in results.items() if v.status == 'completed'}
    failed_results = {k: v for k, v in results.items() if v.status == 'failed'}
    
    col1, col2 = st.columns(2)
    col1.metric("✅ Completed", len(completed_results))
    col2.metric("❌ Failed", len(failed_results))
    
    # Download section
    if completed_results:
        st.subheader("📥 Downloads")
        
        # Create chunked ZIPs
        prefix = '2_broll_img' if mode == 'images' else '3_broll_vid'
        zip_parts = create_chunked_zips(results, prefix, MAX_ZIP_SIZE_MB)
        
        if len(zip_parts) == 1:
            filename, zip_data = zip_parts[0]
            st.download_button(
                f"📥 Download All ({len(completed_results)} items)",
                zip_data,
                filename,
                "application/zip",
                use_container_width=True
            )
        else:
            st.info(f"📦 Split into {len(zip_parts)} parts (max {MAX_ZIP_SIZE_MB}MB each)")
            cols = st.columns(len(zip_parts))
            for idx, (filename, zip_data) in enumerate(zip_parts):
                with cols[idx]:
                    st.download_button(
                        f"Part {idx+1}",
                        zip_data,
                        filename,
                        "application/zip",
                        key=f"zip_part_{idx}"
                    )
        
        # CSV export
        csv_data = create_results_csv(results)
        st.download_button(
            "📥 Download Results CSV",
            csv_data,
            "results.csv",
            "text/csv"
        )
    
    # Failed items section
    if failed_results:
        st.divider()
        st.subheader("❌ Failed Items")
        
        # Categorize
        permanent_failures = {k: v for k, v in failed_results.items() 
                            if v.error_category == ErrorCategory.PERMANENT.value}
        retryable_failures = {k: v for k, v in failed_results.items() 
                            if v.error_category != ErrorCategory.PERMANENT.value}
        
        if permanent_failures:
            st.error(f"🚫 {len(permanent_failures)} permanent failures (won't retry)")
            with st.expander("View Permanent Failures"):
                for pid, r in permanent_failures.items():
                    st.error(f"**{pid}**: {r.error[:200] if r.error else 'Unknown error'}")
        
        if retryable_failures:
            st.warning(f"🔄 {len(retryable_failures)} retryable failures")
            with st.expander("View Retryable Failures"):
                for pid, r in retryable_failures.items():
                    st.warning(f"**{pid}**: {r.error[:200] if r.error else 'Unknown error'}")
            
            # One-click retry
            if st.button(f"🔄 Retry {len(retryable_failures)} Failed Items", type="primary"):
                retry_items = [
                    {'id': pid, 'prompt': r.prompt, 'number_of_images': 1, 'number_of_videos': 1, '_ui_id': get_unique_id()}
                    for pid, r in retryable_failures.items()
                ]
                st.session_state.auto_batch_items = retry_items
                st.session_state.auto_results = None
                st.rerun()
        
        # Download failed CSV
        failed_csv = create_failed_csv(results, retryable_only=True)
        st.download_button(
            "📥 Download Failed Prompts CSV",
            failed_csv,
            "failed_prompts.csv",
            "text/csv",
            help="Download retryable failed prompts for manual retry"
        )


# =============================================================================
# Tips
# =============================================================================

with st.expander("💡 Tips"):
    st.markdown("""
    **File Formats:**
    - **TXT**: Each block separated by blank line. First line = ID, rest = prompt.
    - **CSV**: Columns `id`, `prompt`, `number_of_images`/`number_of_videos`
    
    **Timeouts:**
    - Images: 10 minutes per item
    - Videos: 20 minutes per item
    
    **Rate Limits:**
    - Images: Max 5 concurrent, 30/min
    - Videos: Max 3 concurrent, 20/min
    
    **Downloads:**
    - Large batches split into 200MB ZIP parts
    - Failed items can be retried with one click
    """)
