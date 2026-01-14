"""Text to Video Generation Page"""

import streamlit as st
import asyncio
from utils.veo_client import VEOClient
from utils.sse_handler import parse_sse_stream
from utils.exceptions import VEOAPIError, AuthenticationError, QuotaExceededError, NetworkError
from utils.logger import StreamlitLogger
from utils.quota_display import display_quota
from utils.sidebar import render_sidebar
import time

st.set_page_config(page_title="Text to Video", page_icon="📝", layout="wide")

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

st.title("📝 Text to Video Generation")

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

# Input form
with st.form("text_to_video_form"):
    prompt = st.text_area(
        "Video Prompt",
        placeholder="Describe the video you want to generate...\nExample: A cat playing with a ball in a sunny garden",
        height=150,
        help="Describe what you want to see in the video. Be detailed!"
    )

    col1, col2 = st.columns(2)

    with col1:
        aspect_ratio = st.selectbox(
            "Aspect Ratio",
            options=[
                "VIDEO_ASPECT_RATIO_LANDSCAPE",
                "VIDEO_ASPECT_RATIO_PORTRAIT"
            ],
            format_func=lambda x: "Landscape (16:9)" if "LANDSCAPE" in x else "Portrait (9:16)",
            help="Choose the video orientation"
        )

    with col2:
        number_of_videos = st.number_input(
            "Number of Videos",
            min_value=1,
            max_value=4,
            value=1,
            help="Generate 1-4 videos at once"
        )

    submit_button = st.form_submit_button("🎬 Generate Video", width='stretch')

# Process form submission
if submit_button:
    if not prompt.strip():
        st.error("Please enter a prompt!")
    else:
        # Create containers
        progress_container = st.container()
        debug_container = st.container() if debug_mode else None

        with progress_container:
            st.info(f"🚀 Starting video generation...")

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
                # Initialize VEO client
                if logger:
                    logger.info("Initializing VEO API client...")
                
                client = VEOClient(
                    api_key=st.session_state.api_key,
                    base_url="https://genaipro.vn/api/v1",
                    debug=debug_mode,
                    logger=logger
                )

                if logger:
                    logger.info(f"Generating video with prompt: {prompt[:50]}...")
                    logger.info(f"Aspect ratio: {aspect_ratio}")
                    logger.info(f"Number of videos: {number_of_videos}")

                # Retry callback
                def on_retry(attempt, delay):
                    retry_text.warning(f"⏳ Retry attempt {attempt}. Waiting {delay}s...")
                    if logger:
                        logger.warning(f"Retrying (attempt {attempt}, delay {delay}s)")

                # Generate video
                async def generate():
                    result = None
                    event_count = 0
                    video_started = False
                    
                    async with client.text_to_video_stream(
                        prompt=prompt,
                        aspect_ratio=aspect_ratio,
                        number_of_videos=number_of_videos
                    ) as response:
                        if logger:
                            logger.success("Stream connection established!")
                        
                        async for event_data in parse_sse_stream(response, logger=logger):
                            event_count += 1
                            video_started = True
                            
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
                        max_polls = 60  # Poll for up to 5 minutes (60 * 5 seconds)
                        poll_interval = 5  # Check every 5 seconds
                        
                        for poll_count in range(max_polls):
                            await asyncio.sleep(poll_interval)
                            
                            elapsed = time.time() - start_time
                            time_text.caption(f"Polling... ({poll_count + 1}/{max_polls}) | Elapsed: {elapsed:.0f}s")
                            
                            try:
                                # Get recent history
                                history = await client.get_histories(page=1, page_size=5)
                                
                                if history and history.get('data'):
                                    # Look for our video (most recent with matching prompt)
                                    for item in history['data']:
                                        item_prompt = item.get('prompt', '')
                                        item_status = item.get('status', '')
                                        
                                        # Check if this might be our video
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
                        # Display video
                        st.video(result['file_url'])

                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.link_button("🔗 Open in New Tab", result['file_url'])
                        with col2:
                            # Download button
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
                progress_bar.empty()
                status_text.empty()
                time_text.empty()
                retry_text.empty()

            except QuotaExceededError as e:
                st.error(f"📊 Quota Exceeded: {str(e)}")
                st.info("💡 **Troubleshooting:**\n- Check your quota in the sidebar\n- Wait for quota to reset\n- Upgrade your plan if needed")
                progress_bar.empty()
                status_text.empty()
                time_text.empty()
                retry_text.empty()

            except NetworkError as e:
                st.error(f"🌐 Network Error: {str(e)}")
                st.info("💡 **Troubleshooting:**\n- Check your internet connection\n- Try again in a few moments\n- The API server might be experiencing issues")
                progress_bar.empty()
                status_text.empty()
                time_text.empty()
                retry_text.empty()

            except VEOAPIError as e:
                st.error(f"❌ API Error: {str(e)}")
                st.info("💡 Enable Debug Mode above to see detailed logs")
                progress_bar.empty()
                status_text.empty()
                time_text.empty()
                retry_text.empty()

            except Exception as e:
                st.error(f"❌ Unexpected Error: {str(e)}")
                st.info("💡 Enable Debug Mode above to see what went wrong")
                if logger:
                    logger.error(f"Unexpected error: {str(e)}")
                progress_bar.empty()
                status_text.empty()
                time_text.empty()
                retry_text.empty()

# Tips section
with st.expander("💡 Tips for Better Results"):
    st.markdown("""
    **Prompt Writing Tips:**
    - Be specific and descriptive
    - Include details about setting, lighting, mood
    - Mention camera movements if desired (pan, zoom, etc.)
    - Specify time of day or season
    - Add style descriptors (cinematic, dramatic, etc.)

    **Good Examples:**
    - "A golden retriever running through a meadow at sunset, slow motion, cinematic"
    - "Close-up of raindrops falling on a window, soft focus background, peaceful mood"
    - "Aerial view of a city skyline at night, lights twinkling, camera slowly panning"

    **Avoid:**
    - Very short or vague prompts
    - Too many conflicting elements
    - Inappropriate or harmful content
    """)
