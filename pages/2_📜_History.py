"""Generation History Page"""

import streamlit as st
import asyncio
from utils.veo_client import VEOClient
from utils.exceptions import VEOAPIError
from utils.quota_display import display_quota
from utils.sidebar import render_sidebar
from datetime import datetime

st.set_page_config(page_title="History", page_icon="📜", layout="wide")

st.title("📜 Generation History")

# Render Sidebar
render_sidebar()

# Check API key
if not st.session_state.get('api_key'):
    st.warning("⚠️ Please enter your API key in the sidebar first!")
    st.stop()

# Display quota
display_quota()

st.markdown("View all your past video generations.")

# Pagination controls
col1, col2, col3 = st.columns([2, 1, 1])

with col1:
    page = st.number_input("Page", min_value=1, value=1, step=1)

with col2:
    page_size = st.selectbox("Items per page", options=[10, 20, 50, 100], index=1)

with col3:
    if st.button("🔄 Refresh History", width='stretch'):
        st.rerun()

# Load history
if st.button("📥 Load History", width='stretch') or 'history_loaded' in st.session_state:
    st.session_state.history_loaded = True

    with st.spinner("Loading history..."):
        try:
            # Initialize VEO client
            client = VEOClient(
                api_key=st.session_state.api_key,
                base_url="https://genaipro.vn/api/v1"
            )

            # Get history
            async def get_history():
                history = await client.get_histories(page=page, page_size=page_size)
                await client.close()
                return history

            history_data = asyncio.run(get_history())

            # Display history
            if history_data and history_data.get('data'):
                items = history_data['data']

                st.success(f"✅ Found {len(items)} generations")

                # Display pagination info
                total_items = history_data.get('total', len(items))
                st.caption(f"Showing page {page} | Total items: {total_items}")

                st.divider()

                # Display each item
                for idx, item in enumerate(items):
                    with st.container():
                        # Create columns for layout
                        col1, col2 = st.columns([3, 1])

                        with col1:
                            st.subheader(f"🎬 Generation #{idx + 1}")

                            # Prompt
                            st.markdown(f"**Prompt:** {item.get('prompt', 'N/A')}")

                            # Status badge
                            status = item.get('status', 'unknown')
                            if status == 'completed':
                                st.success(f"✅ Status: {status.upper()}")
                            elif status == 'processing':
                                st.info(f"⏳ Status: {status.upper()}")
                            elif status == 'failed':
                                st.error(f"❌ Status: {status.upper()}")
                            else:
                                st.warning(f"⚠️ Status: {status.upper()}")

                            # Timestamps
                            created_at = item.get('created_at', '')
                            if created_at:
                                try:
                                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                                    st.caption(f"Created: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
                                except:
                                    st.caption(f"Created: {created_at}")

                        with col2:
                            # Video ID
                            video_id = item.get('id', 'N/A')
                            st.caption(f"ID: {video_id[:16]}..." if len(str(video_id)) > 16 else f"ID: {video_id}")

                            # Action buttons
                            if item.get('file_url'):
                                st.link_button("🔗 View Video", item['file_url'], width='stretch')
                                st.link_button("⬇️ Download", item['file_url'], width='stretch', help="Right-click and 'Save As' to download")

                        # Video preview if available
                        if item.get('file_url'):
                            with st.expander("📺 Preview Video"):
                                st.video(item['file_url'])

                        # Detailed info
                        with st.expander("ℹ️ Details"):
                            st.json(item)

                        st.divider()

                # Pagination navigation
                col1, col2, col3 = st.columns(3)
                with col1:
                    if page > 1:
                        if st.button("⬅️ Previous Page"):
                            st.session_state.page = page - 1
                            st.rerun()

                with col3:
                    if len(items) == page_size:
                        if st.button("Next Page ➡️"):
                            st.session_state.page = page + 1
                            st.rerun()

            else:
                st.info("No generation history found. Start creating videos!")

        except VEOAPIError as e:
            st.error(f"❌ API Error: {str(e)}")

        except Exception as e:
            st.error(f"❌ Error loading history: {str(e)}")

# Help section
with st.expander("❓ About History"):
    st.markdown("""
    **History Features:**
    - View all your past video generations
    - Check status of ongoing generations
    - Access download links for completed videos
    - Review prompts and settings used

    **Status Types:**
    - ✅ **Completed** - Video is ready
    - ⏳ **Processing** - Video is being generated
    - ❌ **Failed** - Generation encountered an error
    - ⚠️ **Other** - Unknown or pending status

    **Tips:**
    - Use pagination to browse through many items
    - Click "View Video" to open in a new tab
    - Expand "Details" to see full generation data
    - Refresh to see updated status of processing videos
    """)
