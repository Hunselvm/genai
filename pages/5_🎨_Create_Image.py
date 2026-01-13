"""Image Generation Page"""

import streamlit as st
import asyncio
from utils.veo_client import VEOClient
from utils.sse_handler import parse_sse_stream
from utils.exceptions import VEOAPIError, AuthenticationError, QuotaExceededError, NetworkError
from utils.logger import StreamlitLogger
from utils.quota_display import display_quota
import time

st.set_page_config(page_title="Create Image", page_icon="🎨", layout="wide")

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

st.title("🎨 AI Image Generation")

# Check API key
if not st.session_state.get('api_key'):
    st.error("⚠️ Please enter your API key in the sidebar first!")
    st.stop()

# Display quota
display_quota()

# Debug mode toggle
debug_mode = st.checkbox("🔍 Enable Debug Mode", value=False, help="Show detailed API communication logs")

# Input form
with st.form("create_image_form"):
    prompt = st.text_area(
        "Image Prompt",
        placeholder="Describe the image you want to generate...\nExample: A serene mountain landscape at sunset with a lake reflection",
        height=150,
        help="Describe what you want to see in the image. Be detailed!"
    )

    col1, col2 = st.columns(2)

    with col1:
        aspect_ratio = st.selectbox(
            "Aspect Ratio",
            options=[
                "IMAGE_ASPECT_RATIO_LANDSCAPE",
                "IMAGE_ASPECT_RATIO_PORTRAIT",
                "IMAGE_ASPECT_RATIO_SQUARE"
            ],
            format_func=lambda x: {
                "IMAGE_ASPECT_RATIO_LANDSCAPE": "Landscape (16:9)",
                "IMAGE_ASPECT_RATIO_PORTRAIT": "Portrait (9:16)",
                "IMAGE_ASPECT_RATIO_SQUARE": "Square (1:1)"
            }[x],
            help="Choose the image orientation"
        )

    with col2:
        number_of_images = st.number_input(
            "Number of Images",
            min_value=1,
            max_value=4,
            value=1,
            help="Generate 1-4 images at once"
        )

    submit_button = st.form_submit_button("🎨 Generate Images", use_container_width=True)

# Process form submission
if submit_button:
    if not prompt.strip():
        st.error("Please enter a prompt!")
    else:
        # Create containers
        progress_container = st.container()
        debug_container = st.container() if debug_mode else None

        with progress_container:
            st.info(f"🚀 Starting image generation...")

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
                    logger.info(f"Generating images with prompt: {prompt[:50]}...")
                    logger.info(f"Aspect ratio: {aspect_ratio}")
                    logger.info(f"Number of images: {number_of_images}")

                # Generate images
                async def generate():
                    result = None
                    event_count = 0
                    
                    async with client.create_image_stream(
                        prompt=prompt,
                        aspect_ratio=aspect_ratio,
                        number_of_images=number_of_images
                    ) as response:
                        if logger:
                            logger.success("Stream connection established!")
                        
                        async for event_data in parse_sse_stream(response, logger=logger):
                            event_count += 1
                            
                            # Update progress
                            status = event_data.get('status', 'processing')
                            
                            # Images don't have process_percentage, so estimate
                            if status == 'completed':
                                progress = 100
                            elif status == 'processing':
                                progress = 50
                            else:
                                progress = 25

                            progress_bar.progress(progress / 100.0)
                            status_text.text(f"Status: {status.upper()}")

                            elapsed = time.time() - start_time
                            time_text.caption(f"Elapsed time: {elapsed:.1f}s | Events received: {event_count}")

                            # Check for completion
                            if status == 'completed':
                                if logger:
                                    logger.success(f"Image generation completed! (Total events: {event_count})")
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
                            logger.info("Image generation started in background. Checking history...")
                        
                        status_text.text("⏳ Images queued for generation. Checking status...")
                        
                        # Poll history for recent images
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
                                                logger.info(f"Found matching image: {item_status}")
                                            
                                            if item_status == 'completed':
                                                result = item
                                                if logger:
                                                    logger.success("Image generation completed!")
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
                                logger.warning("Polling timeout. Images may still be processing.")
                            raise Exception(
                                "Image generation is taking longer than expected.\n"
                                "Please check the History page in a few minutes to see your images."
                            )

                    await client.close()
                    return result

                # Run async function
                if logger:
                    logger.info("Starting async image generation...")
                
                result = asyncio.run(generate())

                if result:
                    progress_bar.progress(1.0)
                    status_text.text("Status: COMPLETED - 100%")
                    retry_text.empty()

                    st.success("✅ Images generated successfully!")

                    # Display result
                    st.divider()
                    st.subheader("🖼️ Generated Images")

                    file_urls = result.get('file_urls', [])
                    if file_urls:
                        # Display images in columns
                        if len(file_urls) == 1:
                            st.image(file_urls[0], use_container_width=True)
                            st.link_button("⬇️ Download Image", file_urls[0], use_container_width=True)
                        else:
                            cols = st.columns(min(len(file_urls), 2))
                            for idx, img_url in enumerate(file_urls):
                                with cols[idx % 2]:
                                    st.image(img_url, caption=f"Image {idx + 1}")
                                    st.link_button(f"⬇️ Download #{idx + 1}", img_url, use_container_width=True, key=f"download_{idx}")

                        # Image details
                        with st.expander("ℹ️ Image Details"):
                            st.json({
                                "image_id": result.get('id'),
                                "prompt": result.get('prompt', prompt),
                                "status": result.get('status'),
                                "file_urls": file_urls,
                                "created_at": result.get('created_at'),
                            })
                    else:
                        st.warning("Image URLs not available yet. Check the History page.")

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
                st.info("💡 **Troubleshooting:**\n- Check your quota above\n- Wait for quota to reset\n- Upgrade your plan if needed")
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
    - Include details about style, mood, lighting
    - Mention art style if desired (realistic, cartoon, oil painting, etc.)
    - Specify colors and composition
    - Add quality descriptors (high quality, detailed, professional, etc.)

    **Good Examples:**
    - "A photorealistic mountain landscape at golden hour, with snow-capped peaks reflecting in a crystal clear lake"
    - "Minimalist logo design of a coffee cup, modern style, black and white, clean lines"
    - "Fantasy digital art of a dragon flying over a medieval castle, dramatic lighting, vibrant colors"

    **Avoid:**
    - Very short or vague prompts
    - Too many conflicting elements
    - Inappropriate or harmful content
    """)
