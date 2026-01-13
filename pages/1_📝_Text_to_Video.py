"""Text to Video Generation Page"""

import streamlit as st
import asyncio
from utils.veo_client import VEOClient
from utils.sse_handler import parse_sse_stream
from utils.exceptions import VEOAPIError
import time

st.set_page_config(page_title="Text to Video", page_icon="📝", layout="wide")

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
</style>
""", unsafe_allow_html=True)

st.title("📝 Text to Video Generation")

# Check API key
if not st.session_state.get('api_key'):
    st.error("⚠️ Please enter your API key in the sidebar first!")
    st.stop()

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

    submit_button = st.form_submit_button("🎬 Generate Video", use_container_width=True)

# Process form submission
if submit_button:
    if not prompt.strip():
        st.error("Please enter a prompt!")
    else:
        # Create placeholder for progress
        progress_container = st.container()

        with progress_container:
            st.info(f"🚀 Starting video generation...")

            progress_bar = st.progress(0)
            status_text = st.empty()
            time_text = st.empty()

            start_time = time.time()

            try:
                # Initialize VEO client
                client = VEOClient(
                    api_key=st.session_state.api_key,
                    base_url="https://genaipro.vn/api/v1"
                )

                # Generate video
                async def generate():
                    result = None
                    async with client.text_to_video_stream(
                        prompt=prompt,
                        aspect_ratio=aspect_ratio,
                        number_of_videos=number_of_videos
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

                if result:
                    progress_bar.progress(1.0)
                    status_text.text("Status: COMPLETED - 100%")

                    st.success("✅ Video generated successfully!")

                    # Display result
                    st.divider()
                    st.subheader("🎥 Generated Video")

                    if result.get('file_url'):
                        # Display video
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

                    # Update quota
                    if st.session_state.quota_info:
                        try:
                            quota = asyncio.run(client.get_quota())
                            st.session_state.quota_info = quota
                        except:
                            pass

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
