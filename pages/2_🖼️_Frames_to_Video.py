"""Frames to Video Generation Page"""

import streamlit as st
import asyncio
from utils.veo_client import VEOClient
from utils.sse_handler import parse_sse_stream
from utils.exceptions import VEOAPIError, InvalidImageError
from PIL import Image
import time
import tempfile
import os

st.set_page_config(page_title="Frames to Video", page_icon="🖼️", layout="wide")

st.title("🖼️ Frames to Video Generation")

# Check API key
if not st.session_state.get('api_key'):
    st.error("⚠️ Please enter your API key in the sidebar first!")
    st.stop()

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
        st.image(start_frame, caption="Start Frame", use_container_width=True)

with col2:
    st.subheader("End Frame (Optional)")
    end_frame = st.file_uploader(
        "Upload end frame",
        type=['jpg', 'jpeg', 'png', 'webp'],
        help="The last frame of your video (optional)",
        key="end_frame"
    )

    if end_frame:
        st.image(end_frame, caption="End Frame", use_container_width=True)

# Prompt input
prompt = st.text_area(
    "Video Prompt",
    placeholder="Describe the transition or video you want...\nExample: Smooth transition from day to night, cinematic",
    height=100,
    help="Describe what should happen in the video"
)

# Generate button
if st.button("🎬 Generate Video from Frames", use_container_width=True):
    if not start_frame:
        st.error("Please upload at least a start frame!")
    elif not prompt.strip():
        st.error("Please enter a prompt!")
    else:
        # Save uploaded files to temporary files
        progress_container = st.container()

        with progress_container:
            st.info("🚀 Starting video generation from frames...")

            progress_bar = st.progress(0)
            status_text = st.empty()
            time_text = st.empty()

            start_time = time.time()

            try:
                # Save start frame to temp file
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_start:
                    tmp_start.write(start_frame.getvalue())
                    start_frame_path = tmp_start.name

                # Save end frame if provided
                end_frame_path = None
                if end_frame:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_end:
                        tmp_end.write(end_frame.getvalue())
                        end_frame_path = tmp_end.name

                # Initialize VEO client
                client = VEOClient(
                    api_key=st.session_state.api_key,
                    base_url="https://genaipro.vn/api/v1"
                )

                # Generate video
                async def generate():
                    result = None
                    async with client.frames_to_video_stream(
                        start_frame_path=start_frame_path,
                        end_frame_path=end_frame_path,
                        prompt=prompt
                    ) as response:
                        async for event_data in parse_sse_stream(response):
                            # Update progress
                            progress = event_data.get('process_percentage', 0)
                            status = event_data.get('status', 'processing')

                            progress_bar.progress(progress / 100.0)
                            status_text.text(f"Status: {status.upper()} - {progress}%")

                            elapsed = time.time() - start_time
                            time_text.caption(f"Elapsed time: {elapsed:.1f}s")

                            # Check for completion
                            if status == 'completed':
                                result = event_data
                                break
                            elif status == 'failed':
                                raise Exception(event_data.get('error', 'Generation failed'))

                    await client.close()
                    return result

                # Run async function
                result = asyncio.run(generate())

                # Cleanup temp files
                os.unlink(start_frame_path)
                if end_frame_path:
                    os.unlink(end_frame_path)

                if result:
                    progress_bar.progress(1.0)
                    status_text.text("Status: COMPLETED - 100%")

                    st.success("✅ Video generated successfully!")

                    # Display result
                    st.divider()
                    st.subheader("🎥 Generated Video")

                    if result.get('file_url'):
                        st.video(result['file_url'])

                        col1, col2 = st.columns(2)
                        with col1:
                            st.link_button("🔗 Open in New Tab", result['file_url'])
                        with col2:
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

            except VEOAPIError as e:
                st.error(f"❌ API Error: {str(e)}")
                progress_bar.empty()
                status_text.empty()
                time_text.empty()

            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
                progress_bar.empty()
                status_text.empty()
                time_text.empty()

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
