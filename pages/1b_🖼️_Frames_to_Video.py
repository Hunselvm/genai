"""Frames to Video Generation Page"""

import streamlit as st
import asyncio
from utils.veo_client import VEOClient
from utils.sse_handler import parse_sse_stream
from utils.exceptions import VEOAPIError, InvalidImageError, AuthenticationError, QuotaExceededError, NetworkError
from utils.logger import StreamlitLogger
from utils.quota_display import display_quota
from utils.sidebar import render_sidebar
import time
import tempfile
import os

st.set_page_config(page_title="Frames to Video", page_icon="🖼️", layout="wide")

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

st.title("🖼️ Frames to Video Generation")

# Render Sidebar
render_sidebar()

# Check API key
if not st.session_state.get('api_key'):
    st.warning("⚠️ Please enter your API key in the sidebar first!")
    st.stop()

# Display quota
display_quota()

# Debug mode toggle
debug_mode = st.checkbox("🔍 Enable Debug Mode", value=False, help="Show detailed API communication logs")

st.markdown("""
Generate a video by interpolating between a start frame and an optional end frame.
The AI will create smooth transitions between your images.
""")

# File uploaders
col1, col2 = st.columns(2)

with col1:
    st.subheader("Start Frame (Required)")
    start_frame = st.file_uploader(
        "Upload start frame",
        type=['jpg', 'jpeg', 'png', 'webp'],
        help="The first frame of your video",
        key="start_frame"
    )

    if start_frame:
        st.image(start_frame, caption="Start Frame", width='stretch')

with col2:
    st.subheader("End Frame (Optional)")
    end_frame = st.file_uploader(
        "Upload end frame",
        type=['jpg', 'jpeg', 'png', 'webp'],
        help="The last frame of your video (optional)",
        key="end_frame"
    )

    if end_frame:
        st.image(end_frame, caption="End Frame", width='stretch')

# Prompt input
prompt = st.text_area(
    "Video Prompt",
    placeholder="Describe the transition or video you want...\nExample: Smooth transition from day to night, cinematic",
    height=100,
    help="Describe what should happen in the video"
)

# Aspect Ratio selector
aspect_ratio = st.selectbox(
    "Aspect Ratio",
    options=["VIDEO_ASPECT_RATIO_LANDSCAPE", "VIDEO_ASPECT_RATIO_PORTRAIT"],
    format_func=lambda x: "Landscape (16:9)" if x == "VIDEO_ASPECT_RATIO_LANDSCAPE" else "Portrait (9:16)",
    index=0,
    help="Select the aspect ratio for the generated video"
)

# Number of videos slider
num_videos = st.slider(
    "Number of Videos",
    min_value=1,
    max_value=4,
    value=1,
    help="Number of videos to generate in parallel"
)

# Generate button
if st.button("🎬 Generate Video from Frames", width='stretch'):
    if not start_frame:
        st.error("Please upload at least a start frame!")
    elif not prompt.strip():
        st.error("Please enter a prompt!")
    else:
        # Create containers
        progress_container = st.container()
        debug_container = st.container() if debug_mode else None

        with progress_container:
            st.info("🚀 Starting video generation from frames...")

            progress_bar = st.progress(0)
            status_text = st.empty()
            time_text = st.empty()
            retry_text = st.empty()

            start_time = time.time()
            
            # Setup logger
            logger = None
            if debug_mode and debug_container:
                with debug_container:
                    st.subheader("🔍 Debug Console")
                    log_container = st.container()
                    logger = StreamlitLogger(log_container)

            try:
                # Save start frame to temp file
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_start:
                    tmp_start.write(start_frame.getvalue())
                    tmp_start.flush()  # Ensure data is written to disk
                    os.fsync(tmp_start.fileno())  # Force OS to write to disk
                    start_frame_path = tmp_start.name

                # Save end frame if provided
                end_frame_path = None
                if end_frame:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_end:
                        tmp_end.write(end_frame.getvalue())
                        tmp_end.flush()  # Ensure data is written to disk
                        os.fsync(tmp_end.fileno())  # Force OS to write to disk
                        end_frame_path = tmp_end.name

                if logger:
                    logger.info("Initializing VEO API client...")

                # Initialize VEO client
                client = VEOClient(
                    api_key=st.session_state.api_key,
                    base_url="https://genaipro.vn/api/v1",
                    debug=debug_mode,
                    logger=logger
                )

                if logger:
                    logger.info(f"Generating video with prompt: {prompt[:50]}...")
                    logger.info(f"Start frame: {start_frame_path}")
                    if end_frame_path:
                        logger.info(f"End frame: {end_frame_path}")

                # Generate video
                async def generate():
                    result = None
                    event_count = 0
                    
                    async with client.frames_to_video_stream(
                        start_frame_path=start_frame_path,
                        end_frame_path=end_frame_path,
                        prompt=prompt,
                        aspect_ratio=aspect_ratio,
                        number_of_videos=num_videos
                    ) as response:
                        if logger:
                            logger.success("Stream connection established!")
                        
                        async for event_data in parse_sse_stream(response, logger=logger):
                            event_count += 1
                            
                            # Update progress
                            progress = event_data.get('process_percentage', 0)
                            status = event_data.get('status', 'processing')

                            progress_bar.progress(progress / 100.0)
                            status_text.text(f"Status: {status.upper()} - {progress}%")

                            elapsed = time.time() - start_time
                            time_text.caption(f"Elapsed time: {elapsed:.1f}s | Events received: {event_count}")

                            # Check for completion
                            if status == 'completed':
                                if logger:
                                    logger.success(f"Video generation completed! (Total events: {event_count})")
                                    logger.info(f"Result data keys: {list(event_data.keys())}")
                                    if 'file_url' in event_data:
                                        logger.info(f"Video URL: {event_data['file_url']}")
                                    else:
                                        logger.warning("No file_url in result! Full data:")
                                        logger.info(str(event_data))
                                result = event_data
                                break
                            elif status == 'failed':
                                error_msg = event_data.get('error', 'Generation failed')
                                if logger:
                                    logger.error(f"Generation failed: {error_msg}")
                                raise Exception(error_msg)
                    
                    # If no events received, try polling history
                    if event_count == 0:
                        if logger:
                            logger.warning("No SSE events received. Switching to polling mode...")
                            logger.info("Video generation started in background. Checking history...")
                        
                        status_text.text("⏳ Video queued for generation. Checking status...")
                        
                        # Poll history for recent videos
                        max_polls = 60
                        poll_interval = 5
                        
                        for poll_count in range(max_polls):
                            await asyncio.sleep(poll_interval)
                            
                            elapsed = time.time() - start_time
                            time_text.caption(f"Polling... ({poll_count + 1}/{max_polls}) | Elapsed: {elapsed:.0f}s")
                            
                            try:
                                history = await client.get_histories(page=1, page_size=5)
                                
                                if history and history.get('data'):
                                    for item in history['data']:
                                        item_prompt = item.get('prompt', '')
                                        item_status = item.get('status', '')
                                        
                                        if prompt.lower() in item_prompt.lower():
                                            if logger:
                                                logger.info(f"Found matching video: {item_status}")
                                            
                                            if item_status == 'completed':
                                                result = item
                                                if logger:
                                                    logger.success("Video generation completed!")
                                                break
                                            elif item_status == 'processing':
                                                progress_bar.progress(0.5)
                                                status_text.text(f"Status: PROCESSING (polling)")
                                            elif item_status == 'failed':
                                                error_msg = item.get('error', 'Generation failed')
                                                if logger:
                                                    logger.error(f"Generation failed: {error_msg}")
                                                raise Exception(error_msg)
                                    
                                    if result:
                                        break
                            
                            except Exception as e:
                                if logger:
                                    logger.warning(f"Polling error: {str(e)}")
                        
                        if not result:
                            if logger:
                                logger.warning("Polling timeout. Video may still be processing.")
                            raise Exception(
                                "Video generation is taking longer than expected.\n"
                                "Please check the History page in a few minutes to see your video."
                            )

                    # If result doesn't have file_url, try fetching from history
                    if result and not result.get('file_url'):
                        if logger:
                            logger.warning("Result missing file_url, fetching from history...")

                        try:
                            history = await client.get_histories(page=1, page_size=5)
                            if history and history.get('data'):
                                # Find the video we just created by ID or prompt
                                video_id = result.get('id')
                                for item in history['data']:
                                    if video_id and item.get('id') == video_id:
                                        if logger:
                                            logger.success("Found video in history by ID!")
                                        result = item
                                        break
                                    elif prompt.lower() in item.get('prompt', '').lower():
                                        if logger:
                                            logger.success("Found video in history by prompt!")
                                        result = item
                                        break
                        except Exception as e:
                            if logger:
                                logger.error(f"Failed to fetch from history: {str(e)}")

                    await client.close()
                    return result

                # Run async function
                if logger:
                    logger.info("Starting async video generation...")
                
                result = asyncio.run(generate())

                if result:
                    progress_bar.progress(1.0)
                    status_text.text("Status: COMPLETED - 100%")
                    retry_text.empty()

                    st.success("✅ Video generated successfully!")

                    # Display result
                    st.divider()
                    st.subheader("🎥 Generated Video")

                    if result.get('file_url'):
                        st.video(result['file_url'])

                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.link_button("🔗 Open in New Tab", result['file_url'])
                        with col2:
                            st.link_button("⬇️ Download Video", result['file_url'], help="Right-click and 'Save As' to download")
                        with col3:
                            if st.button("📋 Copy URL"):
                                st.code(result['file_url'], language=None)

                        # Video details
                        with st.expander("ℹ️ Video Details"):
                            st.json({
                                "video_id": result.get('id'),
                                "prompt": result.get('prompt', prompt),
                                "status": result.get('status'),
                                "file_url": result.get('file_url'),
                                "created_at": result.get('created_at'),
                            })
                    else:
                        st.warning("Video URL not available yet. Check the History page.")

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
                # Cleanup temp files if they exist
                try:
                    if 'start_frame_path' in locals():
                        os.unlink(start_frame_path)
                    if 'end_frame_path' in locals() and end_frame_path:
                        os.unlink(end_frame_path)
                except:
                    pass

# Tips section
with st.expander("💡 Tips for Better Results"):
    st.markdown("""
    **Frame Selection:**
    - Use high-quality images (1024x1024 or larger recommended)
    - Frames should be related or have clear visual connection
    - Consider composition and framing
    - End frame is optional - without it, AI will animate the start frame

    **Prompt Tips:**
    - Describe the desired motion or transition
    - Specify camera movements (zoom, pan, rotate)
    - Add mood or atmosphere descriptors
    - Keep it concise but descriptive

    **Examples:**
    - "Smooth zoom in on subject, dramatic lighting"
    - "Gentle fade transition, peaceful atmosphere"
    - "Dynamic movement, camera rotating around subject"
    """)
