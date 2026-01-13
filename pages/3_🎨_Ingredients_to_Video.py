"""Ingredients to Video Generation Page"""

import streamlit as st
import asyncio
from utils.veo_client import VEOClient
from utils.sse_handler import parse_sse_stream
from utils.exceptions import VEOAPIError
import time
import tempfile
import os

st.set_page_config(page_title="Ingredients to Video", page_icon="🎨", layout="wide")

st.title("🎨 Ingredients to Video Generation")

# Check API key
if not st.session_state.get('api_key'):
    st.error("⚠️ Please enter your API key in the sidebar first!")
    st.stop()

# Display quota
from utils.quota_display import display_quota
display_quota()

st.markdown("""
Generate a video using multiple reference images. The AI will use these images
as visual inspiration and guidance for creating your video.
""")

# File uploader for multiple images
reference_images = st.file_uploader(
    "Upload Reference Images",
    type=['jpg', 'jpeg', 'png', 'webp'],
    accept_multiple_files=True,
    help="Upload multiple images that will guide the video generation"
)

# Display uploaded images in grid
if reference_images:
    st.subheader(f"📸 Uploaded Images ({len(reference_images)})")

    # Create columns for image grid
    cols = st.columns(4)
    for idx, img in enumerate(reference_images):
        with cols[idx % 4]:
            st.image(img, caption=f"Image {idx+1}", use_container_width=True)

# Prompt input
prompt = st.text_area(
    "Video Prompt",
    placeholder="Describe the video you want to create using these reference images...\nExample: Create a cinematic video combining these scenes with smooth transitions",
    height=120,
    help="Describe how you want the reference images to be used in the video"
)

# Generate button
if st.button("🎬 Generate Video from Ingredients", use_container_width=True):
    if not reference_images:
        st.error("Please upload at least one reference image!")
    elif not prompt.strip():
        st.error("Please enter a prompt!")
    else:
        progress_container = st.container()

        with progress_container:
            st.info(f"🚀 Starting video generation with {len(reference_images)} reference images...")

            progress_bar = st.progress(0)
            status_text = st.empty()
            time_text = st.empty()

            start_time = time.time()

            temp_files = []

            try:
                # Save uploaded images to temporary files
                image_paths = []
                for img in reference_images:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                        tmp.write(img.getvalue())
                        image_paths.append(tmp.name)
                        temp_files.append(tmp.name)

                # Initialize VEO client
                client = VEOClient(
                    api_key=st.session_state.api_key,
                    base_url="https://genaipro.vn/api/v1"
                )

                # Generate video
                async def generate():
                    result = None
                    async with client.ingredients_to_video_stream(
                        image_paths=image_paths,
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
                                "num_reference_images": len(reference_images),
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
                # Cleanup temp files
                for temp_file in temp_files:
                    try:
                        os.unlink(temp_file)
                    except:
                        pass

# Tips section
with st.expander("💡 Tips for Better Results"):
    st.markdown("""
    **Reference Image Guidelines:**
    - Upload 2-6 images for best results
    - Use high-quality, clear images
    - Images should be thematically related
    - Avoid very different styles or conflicting subjects
    - Consider lighting and color consistency

    **Prompt Tips:**
    - Explain how images should be combined
    - Describe desired transitions or flow
    - Specify mood, pace, and style
    - Mention camera movements if needed

    **Good Examples:**
    - "Combine these landscape scenes into a smooth panning shot, golden hour lighting"
    - "Create a product showcase using these angles, professional and clean"
    - "Blend these character poses into a continuous motion, dynamic and energetic"

    **How It Works:**
    The AI uses your reference images as visual guidance to create a cohesive video
    that incorporates elements, styles, and composition from your uploads.
    """)
