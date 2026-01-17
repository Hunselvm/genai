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


def parse_file(uploaded_file):
    content = uploaded_file.getvalue().decode('utf-8')
    ext = uploaded_file.name.split('.')[-1].lower()
    if ext == 'txt': return parse_txt_file(content)
    elif ext == 'csv': return parse_csv_file(content)
    return []


def save_temp_file(uploaded_file):
    if not uploaded_file: return None
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
        tmp.write(uploaded_file.getvalue())
        return tmp.name


def merge_broll_items(img_items, vid_items):
    # Merge logic: 1-to-1 matching by index if IDs don't match, or by ID if they do
    merged = []
    # Create map of vid items by ID
    vid_map = {item['id']: item for item in vid_items}
    
    for idx, img_item in enumerate(img_items):
        # Try finding video by ID, else use index
        vid_item = vid_map.get(img_item['id'])
        if not vid_item and idx < len(vid_items):
            vid_item = vid_items[idx]
        
        if vid_item:
            merged.append({
                'id': img_item['id'],
                'image_prompt': img_item['prompt'],
                'video_prompt': vid_item['prompt'],
                'prompt': vid_item['prompt'], # Default for compatibility
                'number_of_images': img_item.get('number_of_images', 1),
                'number_of_videos': vid_item.get('number_of_videos', 1),
                '_ui_id': get_unique_id()
            })
    return merged


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

    st.session_state.auto_log_messages = []

if 'auto_aroll_items' not in st.session_state:
    st.session_state.auto_aroll_items = []

if 'auto_broll_items' not in st.session_state:
    st.session_state.auto_broll_items = []

if 'auto_ref_aroll' not in st.session_state:
    st.session_state.auto_ref_aroll = None

if 'auto_ref_broll' not in st.session_state:
    st.session_state.auto_ref_broll = None

if 'auto_stop_requested' not in st.session_state:
    st.session_state.auto_stop_requested = False


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
    options=['total_package', 'broll_pipeline', 'aroll', 'images'],
    format_func=lambda x: {
        'total_package': '📦 Total Package (A-Roll + B-Roll Pipeline)',
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
st.subheader("2. Upload Prompts & References")

# Initialize containers
uploaded_files = {}
reference_frames = {}

# Layout based on mode
if mode == 'total_package':
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("**1. A-Roll (Talking Head)**")
        aroll_file = st.file_uploader("A-Roll Prompts (TXT/CSV)", key="aroll_file")
        aroll_text = st.text_area("Or Paste A-Roll (TXT)", height=150, placeholder="ID\nPrompt...", key="aroll_text")
        aroll_ref = st.file_uploader("A-Roll Reference (Face)", type=['jpg', 'png'], key="aroll_ref")
        if aroll_ref: st.image(aroll_ref, width=150)
        
    with col2:
        st.markdown("**2. B-Roll Images**")
        broll_img_file = st.file_uploader("Image Prompts (TXT/CSV)", key="broll_img_file")
        broll_img_text = st.text_area("Or Paste Image Prompts (TXT)", height=150, placeholder="ID\nPrompt...", key="broll_img_text")
        broll_ref = st.file_uploader("Character Reference (Style)", type=['jpg', 'png'], key="broll_ref")
        if broll_ref: st.image(broll_ref, width=150)
        
    with col3:
        st.markdown("**3. B-Roll Videos**")
        broll_vid_file = st.file_uploader("Video Prompts (TXT/CSV)", key="broll_vid_file")
        broll_vid_text = st.text_area("Or Paste Video Prompts (TXT)", height=150, placeholder="ID\nPrompt...", key="broll_vid_text")

    if st.button("📥 Load All Files", type="secondary"):
        # Check inputs (File OR Text must be present for each)
        has_aroll = aroll_file or aroll_text.strip()
        has_img = broll_img_file or broll_img_text.strip()
        has_vid = broll_vid_file or broll_vid_text.strip()
        
        if has_aroll and has_img and has_vid and aroll_ref and broll_ref:
            try:
                # Helper to get content from File OR Text
                def get_content(f, t):
                    if f: return parse_file(f)
                    return parse_txt_file(t)
                
                # Parse all inputs
                aroll_items = get_content(aroll_file, aroll_text)
                img_items = get_content(broll_img_file, broll_img_text)
                vid_items = get_content(broll_vid_file, broll_vid_text)
                
                st.session_state.auto_aroll_items = aroll_items
                st.session_state.auto_broll_items = merge_broll_items(img_items, vid_items)
                
                # Save references to temp
                st.session_state.auto_ref_aroll = save_temp_file(aroll_ref)
                st.session_state.auto_ref_broll = save_temp_file(broll_ref)
                
                st.success(f"✅ Loaded: {len(aroll_items)} A-Roll, {len(st.session_state.auto_broll_items)} B-Roll items")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error parsing: {e}")
        else:
            st.error("⚠️ Please provide prompts (File/Text) for all 3 sections and upload 2 reference images")

elif mode == 'broll_pipeline':
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**1. Image Generation**")
        img_file = st.file_uploader("Image Prompts (TXT/CSV)", key="img_file")
        img_text = st.text_area("Or Paste Image Prompts (TXT)", height=150, placeholder="ID\nPrompt...", key="img_text")
        ref_img = st.file_uploader("Character Reference (Style)", type=['jpg', 'png'], key="ref_img")
        if ref_img: st.image(ref_img, width=150)
        
    with col2:
        st.markdown("**2. Video Generation**")
        vid_file = st.file_uploader("Video Prompts (TXT/CSV)", key="vid_file")
        vid_text = st.text_area("Or Paste Video Prompts (TXT)", height=150, placeholder="ID\nPrompt...", key="vid_text")
        
    if st.button("📥 Load Pipeline Files", type="secondary"):
        has_img = img_file or img_text.strip()
        has_vid = vid_file or vid_text.strip()
        
        if has_img and has_vid and ref_img:
            try:
                def get_content(f, t):
                    if f: return parse_file(f)
                    return parse_txt_file(t)

                img_items = get_content(img_file, img_text)
                vid_items = get_content(vid_file, vid_text)
                
                merged = merge_broll_items(img_items, vid_items)
                st.session_state.auto_batch_items = merged
                
                # Save ref
                st.session_state.auto_ref_broll = save_temp_file(ref_img)
                
                st.success(f"✅ Loaded {len(merged)} pipeline items")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error: {e}")
        else:
            st.error("⚠️ Please provide prompts (File/Text) and Character Reference")

elif mode == 'aroll':
    col1, col2 = st.columns(2)
    with col1:
        f = st.file_uploader("A-Roll Prompts (TXT/CSV)", key="aroll_only_file")
        t = st.text_area("Or Paste Prompts (TXT)", height=150, placeholder="ID\nPrompt...", key="aroll_only_text")
    with col2:
        ref = st.file_uploader("Talking Head Reference", type=['jpg', 'png'], key="aroll_only_ref")
        if ref: st.image(ref, width=150)
        
    if st.button("📥 Load A-Roll", type="secondary"):
        if (f or t.strip()) and ref:
            try:
                items = parse_file(f) if f else parse_txt_file(t)
                st.session_state.auto_batch_items = items
                st.session_state.auto_ref_aroll = save_temp_file(ref)
                st.success(f"✅ Loaded {len(items)} items")
                st.rerun()
            except Exception as e: st.error(str(e))
        else:
            st.error("⚠️ Please provide prompts (File/Text) and Reference Image")

else: # images
    f = st.file_uploader("Image Prompts (TXT/CSV)", key="img_only_file")
    t = st.text_area("Or Paste Prompts (TXT)", height=150, placeholder="ID\nPrompt...", key="img_only_text")
    
    if st.button("📥 Load Images", type="secondary"):
        if f or t.strip():
            try:
                items = parse_file(f) if f else parse_txt_file(t)
                st.session_state.auto_batch_items = items
                st.success(f"✅ Loaded {len(items)} items")
                st.rerun()
            except Exception as e: st.error(str(e))
        else:
            st.error("⚠️ Please provide prompts (File/Text)")



# =============================================================================
# Prompts Preview & Validation (Editable)
# =============================================================================

batch_items = st.session_state.auto_batch_items

if batch_items:
    st.divider()
    st.subheader(f"3. Edit Prompts ({len(batch_items)} items)")
    
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
    
    # Action buttons row
    col_add, col_clear, _ = st.columns([1, 1, 2])
    with col_add:
        if st.button("➕ Add New Prompt"):
            st.session_state.auto_batch_items.append({
                'id': f"new_{len(batch_items)+1}",
                'prompt': '',
                'number_of_images': 1,
                'number_of_videos': 1,
                '_ui_id': get_unique_id()
            })
            st.rerun()
    with col_clear:
        if st.button("🗑️ Clear All"):
            st.session_state.auto_batch_items = []
            st.session_state.auto_results = None
            st.session_state.auto_pipeline_results = None
            st.rerun()
    
    # Editable prompts list
    items_to_remove = []
    
    with st.expander("✏️ Edit Prompts", expanded=True):
        for idx, item in enumerate(batch_items):
            ui_key = item.get('_ui_id', f"fallback_{idx}")
            
            col1, col2, col3, col4 = st.columns([1.5, 0.5, 0.5, 0.3])
            
            with col1:
                # ID input
                new_id = st.text_input(
                    "ID",
                    value=item.get('id', f"item_{idx}"),
                    key=f"auto_id_{ui_key}",
                    label_visibility="collapsed",
                    placeholder="ID"
                )
                st.session_state.auto_batch_items[idx]['id'] = new_id
            
            with col2:
                # Image count (for images/broll_pipeline modes)
                new_img_count = st.number_input(
                    "Imgs",
                    min_value=1,
                    max_value=4,
                    value=item.get('number_of_images', 1),
                    key=f"auto_img_{ui_key}",
                    label_visibility="collapsed",
                    help="# of images"
                )
                st.session_state.auto_batch_items[idx]['number_of_images'] = new_img_count
            
            with col3:
                # Video count (for video modes)
                new_vid_count = st.number_input(
                    "Vids",
                    min_value=1,
                    max_value=4,
                    value=item.get('number_of_videos', 1),
                    key=f"auto_vid_{ui_key}",
                    label_visibility="collapsed",
                    help="# of videos"
                )
                st.session_state.auto_batch_items[idx]['number_of_videos'] = new_vid_count
            
            with col4:
                # Remove button
                if st.button("🗑️", key=f"auto_del_{ui_key}", help="Remove"):
                    items_to_remove.append(idx)
            
            # Prompt text (full width below)
            new_prompt = st.text_area(
                "Prompt",
                value=item.get('prompt', ''),
                key=f"auto_prm_{ui_key}",
                height=80,
                label_visibility="collapsed",
                placeholder="Enter prompt here..."
            )
            st.session_state.auto_batch_items[idx]['prompt'] = new_prompt
            
            # Check for pipeline-specific fields
            if 'image_prompt' in item or 'video_prompt' in item:
                c1, c2 = st.columns(2)
                with c1:
                    img_prm = st.text_area(
                        "Image Prompt",
                        value=item.get('image_prompt', ''),
                        key=f"auto_imgprm_{ui_key}",
                        height=60,
                        placeholder="Image generation prompt..."
                    )
                    st.session_state.auto_batch_items[idx]['image_prompt'] = img_prm
                with c2:
                    vid_prm = st.text_area(
                        "Video Prompt", 
                        value=item.get('video_prompt', ''),
                        key=f"auto_vidprm_{ui_key}",
                        height=60,
                        placeholder="Video motion prompt..."
                    )
                    st.session_state.auto_batch_items[idx]['video_prompt'] = vid_prm
            
            st.divider()
    
    # Process removals
    if items_to_remove:
        for idx in sorted(items_to_remove, reverse=True):
            st.session_state.auto_batch_items.pop(idx)
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

if (mode == 'total_package' and st.session_state.auto_aroll_items and st.session_state.auto_broll_items) or \
   (mode != 'total_package' and st.session_state.auto_batch_items):
    
    st.divider()
    
    # Estimate
    if mode == 'total_package':
        n_aroll = len(st.session_state.auto_aroll_items)
        n_broll = len(st.session_state.auto_broll_items)
        st.info(f"📊 Will generate {n_aroll} A-Roll videos, then {n_broll} images & {n_broll} B-Roll videos")
    else:
        total = len(st.session_state.auto_batch_items)
        if mode == 'broll_pipeline':
            st.info(f"📊 Will generate {total} images, then {total} videos")
        elif mode == 'images':
            st.info(f"📊 Will generate {total} images")
        else:
            st.info(f"📊 Will generate {total} videos")
    
    if st.button("🚀 Start Generation", type="primary", use_container_width=True):
        st.session_state.auto_is_running = True
        st.session_state.auto_stop_requested = False
        st.session_state.auto_log_messages = []
        st.session_state.auto_results = None
        st.session_state.auto_pipeline_results = None
        
        # Create containers
        progress_container = st.container()
        stop_container = st.container()
        log_container = st.container()
        debug_container = st.container() if debug_mode else None
        
        with progress_container:
            st.subheader("⏳ Processing...")
            progress_bar = st.progress(0)
            col1, col2, col3, col4 = st.columns(4)
            completed_metric = col1.empty()
            failed_metric = col2.empty()
            remaining_metric = col3.empty()
            elapsed_metric = col4.empty()
            status_text = st.empty()
            log_display = st.empty()
        
        # Stop button (will be checked in callbacks)
        with stop_container:
            stop_col1, stop_col2 = st.columns([1, 3])
            with stop_col1:
                if st.button("🛑 Stop Generation", type="secondary", use_container_width=True):
                    st.session_state.auto_stop_requested = True
                    st.warning("⚠️ Stop requested. Saving completed files...")
            with stop_col2:
                st.caption("Stopping will save all completed files. You can download them after stopping.")
        
        # Setup logger
        logger = None
        if debug_mode and debug_container:
            with debug_container:
                st.subheader("🔍 Debug Console")
                debug_log_container = st.container()
                logger = StreamlitLogger(debug_log_container)
        
        start_time = time.time()
        progress_state = {
            'completed_count': 0,
            'failed_count': 0,
            'log_messages': []
        }
        
        def update_ui():
            if mode == 'total_package':
                total = len(st.session_state.auto_aroll_items) + (len(st.session_state.auto_broll_items) * 2) # approx steps
            else:
                total = len(st.session_state.auto_batch_items)
                if mode == 'broll_pipeline': total *= 2 
            
            # Rough progress estimation
            done = progress_state['completed_count'] + progress_state['failed_count']
            pct = min(done / total if total > 0 else 0, 1.0)
            
            progress_bar.progress(pct)
            completed_metric.metric("✅ Completed", progress_state['completed_count'])
            failed_metric.metric("❌ Failed", progress_state['failed_count'])
            remaining_metric.metric("⏳ Remaining", total - done)
            elapsed_metric.metric("⏱️ Elapsed", f"{time.time() - start_time:.0f}s")
            
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
            client = VEOClient(
                api_key=st.session_state.api_key,
                base_url="https://genaipro.vn/api/v1",
                debug=debug_mode,
                logger=logger
            )
            
            async def run_generation():
                final_results = {}
                pipeline_results = {}
                
                # TOTAL PACKAGE MODE
                if mode == 'total_package':
                    # 1. A-Roll
                    status_text.info("🚀 Starting Phase 1: A-Roll Videos")
                    aroll_job = create_job('aroll', st.session_state.auto_aroll_items, {'aspect_ratio': aspect_ratio})
                    aroll_engine = AutomationEngine(client, 'videos', progress_callback, logger)
                    
                    aroll_results = await aroll_engine.generate_videos_batch(
                        st.session_state.auto_aroll_items, 
                        aspect_ratio, 
                        st.session_state.auto_ref_aroll, 
                        aroll_job
                    )
                    final_results.update(aroll_results)
                    
                    # 2. B-Roll Pipeline
                    status_text.info("🚀 Starting Phase 2: B-Roll Pipeline")
                    
                    # Inject reference frame
                    broll_items = st.session_state.auto_broll_items
                    for item in broll_items:
                        item['image_reference_frame_path'] = st.session_state.auto_ref_broll
                        
                    broll_job = create_job('broll_pipeline', broll_items, {'aspect_ratio': aspect_ratio})
                    broll_engine = AutomationEngine(client, 'images', progress_callback, logger) # content_type unused for pipeline
                    
                    p_results = await broll_engine.run_broll_pipeline(broll_items, aspect_ratio, broll_job)
                    pipeline_results.update(p_results)
                    
                    return final_results, pipeline_results, 'total'

                # B-ROLL PIPELINE MODE
                elif mode == 'broll_pipeline':
                    items = st.session_state.auto_batch_items
                    for item in items:
                        item['image_reference_frame_path'] = st.session_state.auto_ref_broll
                        
                    job = create_job('broll_pipeline', items, {'aspect_ratio': aspect_ratio})
                    engine = AutomationEngine(client, 'images', progress_callback, logger)
                    p_results = await engine.run_broll_pipeline(items, aspect_ratio, job)
                    return {}, p_results, 'pipeline'
                
                # OTHER MODES
                else:
                    items = st.session_state.auto_batch_items
                    job = create_job(mode, items, {'aspect_ratio': aspect_ratio})
                    
                    if mode == 'images':
                        engine = AutomationEngine(client, 'images', progress_callback, logger)
                        res = await engine.generate_images_batch(items, aspect_ratio, job)
                        return res, {}, 'images'
                    else: # aroll only
                        engine = AutomationEngine(client, 'videos', progress_callback, logger)
                        res = await engine.generate_videos_batch(
                            items, aspect_ratio, st.session_state.auto_ref_aroll, job
                        )
                        return res, {}, 'videos'

            res, p_res, r_type = asyncio.run(run_generation())
            
            st.session_state.auto_results = res if res else None
            st.session_state.auto_pipeline_results = p_res if p_res else None
            
            elapsed = time.time() - start_time
            
            if st.session_state.auto_stop_requested:
                st.warning(f"⏹️ Generation stopped after {elapsed:.0f}s. Partial results saved ({progress_state['completed_count']} completed).")
            else:
                st.success(f"✅ Generation completed in {elapsed:.0f}s!")
            
        except Exception as e:
            # Save partial results even on error
            if 'res' in dir() and res:
                st.session_state.auto_results = res
            if 'p_res' in dir() and p_res:
                st.session_state.auto_pipeline_results = p_res
            
            st.error(f"❌ Error: {str(e)}")
            if logger: logger.error(f"Error: {str(e)}")
            
            if progress_state['completed_count'] > 0:
                st.info(f"ℹ️ {progress_state['completed_count']} items were completed before the error. Check Results section below.")
        finally:
            st.session_state.auto_is_running = False
            st.session_state.auto_stop_requested = False


# =============================================================================
# Results Display
# =============================================================================

if st.session_state.auto_results or st.session_state.auto_pipeline_results:
    st.divider()
    st.subheader("✅ Generation Results")
    
    # helper for result metrics
    def display_metrics(results_dict, label):
        completed = sum(1 for r in results_dict.values() if (r.get('status') if isinstance(r, dict) else r.status) == 'completed')
        failed = sum(1 for r in results_dict.values() if (r.get('status') if isinstance(r, dict) else r.status) == 'failed')
        st.markdown(f"**{label}**: {completed} completed, {failed} failed")
    
    # 1. Pipeline Results (B-Roll)
    if st.session_state.auto_pipeline_results:
        st.markdown("### 🎬 B-Roll Pipeline Results")
        p_res = st.session_state.auto_pipeline_results
        
        # Calculate metrics for pipeline (image & video)
        img_completed = sum(1 for r in p_res.values() if (r.get('image_result', {}).get('status') if isinstance(r, dict) else r['image_result']['status']) == 'completed')
        vid_completed = sum(1 for r in p_res.values() if (r.get('video_result', {}).get('status') if isinstance(r, dict) else r['video_result']['status']) == 'completed')
        st.write(f"Images: {img_completed} completed. Videos: {vid_completed} completed.")
        
        col1, col2, col3 = st.columns(3)
        
        # CSVs
        csv_data = create_pipeline_csv(p_res)
        col1.download_button("📥 Pipeline CSV", csv_data, "broll_pipeline_results.csv", "text/csv")
        
        # Zips (Images)
        # Extract image results list
        img_results_list = []
        vid_results_list = []
        for r in p_res.values():
            if 'image_result' in r and r['image_result']: img_results_list.append(r['image_result'])
            if 'video_result' in r and r['video_result']: vid_results_list.append(r['video_result'])
            
        img_zips = create_chunked_zips(img_results_list, prefix='broll_img', max_size_mb=200)
        for name, data in img_zips:
            col2.download_button(f"📦 {name}", data, name, "application/zip", key=f"dl_{name}")
            
        # Zips (Videos)
        vid_zips = create_chunked_zips(vid_results_list, prefix='broll_vid', max_size_mb=200)
        for name, data in vid_zips:
            col3.download_button(f"📦 {name}", data, name, "application/zip", key=f"dl_{name}")

    if st.session_state.auto_results and st.session_state.auto_pipeline_results:
        st.divider()

    # 2. Standard Results (A-Roll or Single Mode)
    if st.session_state.auto_results:
        label = "A-Roll (Videos)" if mode == 'total_package' else ("Images" if mode == 'images' else "Videos")
        st.markdown(f"### {label} Results")
        
        res = st.session_state.auto_results
        display_metrics(res, label)
        
        col1, col2, col3 = st.columns(3)
        
        # Success CSV
        csv_data = create_results_csv(res)
        prefix = "aroll" if mode == 'total_package' else mode
        col1.download_button(f"📥 Results CSV", csv_data, f"{prefix}_results.csv", "text/csv")
        
        # Failed CSV (Retryable)
        failed_csv = create_failed_csv(res)
        if len(failed_csv.split('\n')) > 2:
            col2.download_button("⚠️ Failed CSV (Retry)", failed_csv, f"{prefix}_failed.csv", "text/csv")
        
        # Zips
        # Convert dict values to list for create_chunked_zips
        results_list = list(res.values())
        zips = create_chunked_zips(results_list, prefix=prefix, max_size_mb=200)
        
        if zips:
            for name, data in zips:
                col3.download_button(f"📦 {name}", data, name, "application/zip", key=f"dl_{name}")
        else:
            col3.info("No completed files to download")
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
