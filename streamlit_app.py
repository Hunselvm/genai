"""VEO API Video Generation - Streamlit Application"""

import streamlit as st
from pathlib import Path

# Page configuration
st.set_page_config(
    page_title="VEO Video Generation",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 3rem;
        font-weight: bold;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-align: center;
        padding: 1rem 0;
    }
    .stProgress > div > div > div > div {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
    }
    .success-box {
        padding: 1rem;
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        border-radius: 0.5rem;
        color: #155724;
    }
    .error-box {
        padding: 1rem;
        background-color: #f8d7da;
        border: 1px solid #f5c6cb;
        border-radius: 0.5rem;
        color: #721c24;
    }
    .info-box {
        padding: 1rem;
        background-color: #d1ecf1;
        border: 1px solid #bee5eb;
        border-radius: 0.5rem;
        color: #0c5460;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'api_key' not in st.session_state:
    st.session_state.api_key = ""
if 'quota_info' not in st.session_state:
    st.session_state.quota_info = None

# Sidebar - API Key Configuration
with st.sidebar:
    st.image("https://via.placeholder.com/150x50/667eea/ffffff?text=VEO+API", use_container_width=True)
    st.title("⚙️ Configuration")

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
                    from utils.veo_client import VEOClient
                    import asyncio

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

# Main content
st.markdown('<h1 class="main-header">🎬 VEO Video Generation</h1>', unsafe_allow_html=True)

st.markdown("""
<div class="info-box">
    <strong>Welcome to VEO Video Generation!</strong><br>
    Generate amazing videos using AI with multiple methods:
    <ul>
        <li><strong>Text to Video</strong> - Create videos from text descriptions</li>
        <li><strong>Frames to Video</strong> - Interpolate between start and end frames</li>
        <li><strong>Ingredients to Video</strong> - Use multiple reference images</li>
        <li><strong>History</strong> - View your past generations</li>
    </ul>
    👈 <strong>Select a page from the sidebar to get started!</strong>
</div>
""", unsafe_allow_html=True)

# API Key check
if not st.session_state.api_key:
    st.warning("⚠️ Please enter your API key in the sidebar to get started.")
else:
    st.success("✅ API key configured. Select a page from the sidebar to generate videos!")

# Footer
st.divider()
st.caption("Powered by GenAIPro VEO API | Built with Streamlit")
