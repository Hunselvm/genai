# Auto Top-Up Integration Guide

## Quick Integration

### Option 1: Single Video Generation (Simple Check)

In any Streamlit page, add **after the sidebar** but **before video generation**:

```python
# Example: pages/1a_📝_Text_to_Video.py

from utils.auto_topup_check import check_and_topup

st.title("📝 Text to Video Generation")
render_sidebar()

# 👇 ADD THESE 2 LINES 👇
success, msg = check_and_topup()
if not success and "failed" in msg.lower():
    st.warning(msg)  # Optional: show warning if it failed

# Rest of your page...
```

### Option 2: Batch Operations (Show Warning First)

For batch operations (A-Roll, B-Roll, Auto Generator), show a **preview warning**:

```python
# Example: pages/3_🎬_A-ROLL_Footage.py

from utils.auto_topup_check import show_topup_warning, check_and_topup

st.title("🎬 A-Roll Batch Generation")
render_sidebar()

# Form with number of videos
with st.form("aroll_form"):
    num_videos = st.number_input("Number of videos", min_value=1, max_value=100)
    submit = st.form_submit_button("Generate")

# 👇 SHOW WARNING BEFORE GENERATION 👇
if submit:
    # Show warning if this will trigger auto top-up
    show_topup_warning(num_videos)

    # Then do the auto top-up check
    check_and_topup()

    # Continue with generation...
    st.info(f"Generating {num_videos} videos...")
```

That's it! The system will now:
- ✅ Check quota before video generation
- ✅ Auto-purchase if quota < 30
- ✅ Cache result for 5 minutes (no repeated checks)
- ✅ Never block the UI (fails silently if needed)

---

## Configuration

Add to your `.env.genaipro`:

```bash
# Auto top-up settings
AUTO_TOPUP_ENABLED=true          # Set to false to disable
AUTO_TOPUP_THRESHOLD=30          # Auto-purchase when quota < 30
```

---

## ON/OFF Switch

**To disable globally:**
```bash
# In .env.genaipro
AUTO_TOPUP_ENABLED=false
```

**To disable for a specific page:**
```python
# Just don't call check_and_topup() on that page
```

---

## Replace in Future

When you want to switch to a different provider:

**Option 1: Disable auto top-up**
```bash
AUTO_TOPUP_ENABLED=false
```

**Option 2: Replace the function**
Edit `utils/auto_topup_check.py` and point to your new provider:
```python
def check_and_topup():
    # Call your new provider's API instead
    return new_provider.auto_topup()
```

**Option 3: Remove completely**
Just delete the 2-line calls from your pages. Done!

---

## Where To Add It

**Recommended pages:**
- ✅ `pages/1a_📝_Text_to_Video.py` - Text to video
- ✅ `pages/1b_🖼️_Frames_to_Video.py` - Frames to video
- ✅ `pages/1c_🎨_Ingredients_to_Video.py` - Ingredients to video
- ✅ `pages/3_🎬_A-ROLL_Footage.py` - Batch A-roll
- ✅ `pages/5_🎥_B-ROLL_Footage.py` - Batch B-roll
- ✅ `pages/6_🤖_Auto_Generator.py` - Auto generator (most important!)

**Don't add to:**
- ❌ `pages/2_📜_History.py` - Just viewing history
- ❌ `pages/1d_🎨_Create_Image.py` - Images use different quota

---

## Example: Full Integration

```python
"""pages/1a_📝_Text_to_Video.py"""

import streamlit as st
from utils.sidebar import render_sidebar
from utils.auto_topup_check import check_and_topup
from utils.veo_client import VEOClient

st.set_page_config(page_title="Text to Video", page_icon="📝")

# Password protection
from utils.auth import require_password
require_password()

st.title("📝 Text to Video Generation")

# Render sidebar
render_sidebar()

# 👇 AUTO TOP-UP CHECK 👇
success, msg = check_and_topup()
if not success and "failed" in msg.lower():
    st.warning(f"⚠️ {msg}")
# 👆 END AUTO TOP-UP 👆

# Check API key
if not st.session_state.get('api_key'):
    st.warning("⚠️ Please enter your API key in the sidebar first!")
    st.stop()

# Rest of your video generation code...
with st.form("text_to_video_form"):
    prompt = st.text_area("Video Prompt", ...)
    submit_button = st.form_submit_button("🎬 Generate Video")

if submit_button:
    # Generate video...
    pass
```

---

## Testing

**Test 1: Check it works**
```python
# In Python console
from utils.auto_topup_check import check_and_topup
success, msg = check_and_topup()
print(msg)
```

**Test 2: Check quota is monitored**
- Use your Streamlit app normally
- Check `genaipro_monitor.log` after 5 minutes
- Should see quota checks happening

**Test 3: Disable and verify**
```bash
# .env.genaipro
AUTO_TOPUP_ENABLED=false
```
Run app → should not auto-purchase anymore

---

## Troubleshooting

**"Auto top-up: cookies not configured"**
- Run: `python scripts/get_genaipro_cookies.py`
- Or check that `.env.genaipro` has all 4 cookies

**"Auto top-up check failed"**
- Check cookies haven't expired (7 days)
- Re-extract cookies if needed

**It's not auto-purchasing**
- Check `AUTO_TOPUP_ENABLED=true` in `.env.genaipro`
- Check `AUTO_TOPUP_THRESHOLD` is set correctly
- Verify your quota is actually below threshold

**I want to see what's happening**
```python
# Add debug output
success, msg = check_and_topup()
st.info(f"Debug: {msg}")  # Temporarily show the message
```

---

## Cost Estimation

With threshold=30 and average usage:
- **Low usage** (50 videos/day): ~$1.50 every 2 days = **$22.50/month**
- **Medium usage** (200 videos/day): ~$1.50 daily = **$45/month**
- **High usage** (500 videos/day): ~$3-4 daily = **$90-120/month**

Each purchase = $1.50 for 100 credits

---

## Migration Path (Future)

When switching providers:

1. Set `AUTO_TOPUP_ENABLED=false`
2. Let current credits run out
3. Switch to new provider
4. Remove `check_and_topup()` calls
5. Delete `utils/auto_topup_check.py` if not needed

Clean, modular, easy to remove!
