"""Shared sidebar component for all pages."""

import streamlit as st
import asyncio
from utils.veo_client import VEOClient

def render_sidebar():
    """Render the standard sidebar with API key config and tools."""
    with st.sidebar:
        st.image("https://via.placeholder.com/150x50/667eea/ffffff?text=VEO+API", use_container_width=True)
        st.title("⚙️ Configuration")

        # Initialize session state for API key if not exists
        if 'api_key' not in st.session_state:
            st.session_state.api_key = ""
        if 'quota_info' not in st.session_state:
            st.session_state.quota_info = None

        # API Key Input
        api_key = st.text_input(
            "GenAIPro API Key",
            value=st.session_state.api_key,
            type="password",
            help="Enter your GenAIPro JWT token. Get it from https://genaipro.vn/docs-api"
        )

        if api_key != st.session_state.api_key:
            st.session_state.api_key = api_key
            st.session_state.quota_info = None

        # Check API Key button
        if st.button("🔍 Check Quota", use_container_width=True):
            if not st.session_state.api_key:
                st.error("Please enter your API key first!")
            else:
                with st.spinner("Checking quota..."):
                    try:
                        client = VEOClient(
                            api_key=st.session_state.api_key,
                            base_url="https://genaipro.vn/api/v1"
                        )

                        # Get quota
                        quota = asyncio.run(client.get_quota())
                        st.session_state.quota_info = quota
                        asyncio.run(client.close())

                        st.success("✅ API key is valid!")

                    except Exception as e:
                        # Ignore harmless transport errors as requested
                        if "TCPTransport closed" in str(e) or "handler is closed" in str(e):
                            pass
                        else:
                            st.error(f"❌ Error: {str(e)}")

        # Display quota if available
        if st.session_state.quota_info:
            st.divider()
            st.subheader("📊 Quota Information")

            quota = st.session_state.quota_info
            col1, col2 = st.columns(2)

            with col1:
                st.metric("Available", quota.get('available_quota', 0))
            with col2:
                st.metric("Total", quota.get('total_quota', 0))

            used = quota.get('used_quota', 0)
            st.caption(f"Used: {used}")

        st.divider()

        # Logout button
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.password_correct = False
            st.rerun()

        # Help section
        with st.expander("❓ Help & Info"):
            st.markdown("""
            **How to use:**
            1. Enter your GenAIPro API key above
            2. Click "Check Quota" to verify
            3. Navigate to different pages using the sidebar
            4. Generate videos with various methods

            **Get API Key:**
            Visit [GenAIPro Docs](https://genaipro.vn/docs-api)

            **Support:**
            - Telegram: [@genaipro_vn](https://t.me/genaipro_vn)
            - Facebook: [genaipro.vn](https://www.facebook.com/genaipro.vn)
            """)
