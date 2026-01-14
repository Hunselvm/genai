"""Solo Generation - Introduction Page"""

import streamlit as st
from utils.sidebar import render_sidebar

st.set_page_config(page_title="Solo Generation", page_icon="🎯", layout="wide")

# Password protection
from utils.auth import require_password
require_password()

# Render Sidebar
render_sidebar()

st.title("🎯 Solo Generation")

st.markdown("""
Welcome to **Solo Generation** - create individual videos and images one at a time with full control over each generation.

## Available Solo Generation Modes

### 📝 Text to Video
Generate videos from text descriptions alone. Perfect for creating simple video clips from your imagination.

**Use Cases:**
- Quick video mockups
- Concept visualization
- Simple animations

---

### 🖼️ Frames to Video
Create videos by interpolating between a start frame and optional end frame. The AI smoothly transitions between your images.

**Use Cases:**
- Morphing effects
- Smooth transitions
- Image animation

---

### 🎨 Ingredients to Video
Generate videos using multiple reference images to guide the style and content.

**Use Cases:**
- Style-guided videos
- Multi-reference compositions
- Complex scene creation

---

### 🎨 Create Image
Generate still images from text prompts with optional reference images.

**Use Cases:**
- Concept art
- Visual references
- Storyboarding

---

## Getting Started

1. **Enter your API key** in the Configuration section (left sidebar)
2. **Check your quota** to see available credits
3. **Select a mode** from the sidebar pages (1a-1d)
4. **Generate your content** and download results

## Need Multiple Generations?

For batch processing and parallel generation, check out:
- **A-ROLL Footage** - Multiple videos from one reference frame
- **B-ROLL Images** - Batch image generation
- **B-ROLL Footage** - Multiple videos with different reference frames

---

👈 **Select a solo generation mode from the sidebar to get started!**
""")

# Tips section
with st.expander("💡 Tips for Solo Generation"):
    st.markdown("""
    **API Usage:**
    - Each generation consumes quota credits
    - Check quota before generating
    - Solo modes are perfect for testing prompts

    **Quality Tips:**
    - Be specific in your prompts
    - Use high-quality reference images
    - Experiment with different aspect ratios

    **Workflow:**
    - Start with Text to Video for quick tests
    - Use Frames/Ingredients for more control
    - Create images for storyboarding first
    """)
