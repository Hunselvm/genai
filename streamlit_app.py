"""VEO API Video Generation - Streamlit Application (Password Protected)"""

import streamlit as st
from pathlib import Path

# Page configuration
st.set_page_config(
    page_title="VEO Video Generation",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Password Protection
def check_password():
    """Returns `True` if the user had the correct password."""

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if st.session_state["password"] == st.secrets.get("app_password", "changeme123"):
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    # First run, show input for password
    if "password_correct" not in st.session_state:
        st.markdown("## 🔐 VEO Video Generation - Login Required")
        st.text_input(
            "Password", type="password", on_change=password_entered, key="password"
        )
        st.info("💡 This app is password protected. Contact the administrator for access.")
        return False
    # Password not correct, show input + error
    elif not st.session_state["password_correct"]:
        st.markdown("## 🔐 VEO Video Generation - Login Required")
        st.text_input(
            "Password", type="password", on_change=password_entered, key="password"
        )
        st.error("😕 Password incorrect")
        return False
    else:
        # Password correct
        return True

if not check_password():
    st.stop()

# Rest of the app (same as streamlit_app.py)
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
from utils.sidebar import render_sidebar
render_sidebar()

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
st.caption("🔐 Password Protected | Powered by GenAIPro VEO API | Built with Streamlit")
