# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VEO API Video Generation - A Python web application for generating AI videos using the GenAIPro VEO API. The app provides both a FastAPI backend and a Streamlit frontend with password protection, supporting multiple video generation methods: text-to-video, frames-to-video, ingredients-to-video, and batch processing.

## Common Commands

### Running the Application

**Streamlit Frontend (Primary Interface):**
```bash
# Quick start (recommended)
./run_streamlit.sh

# Manual start
source venv/bin/activate
streamlit run streamlit_app.py

# With custom port
streamlit run streamlit_app.py --server.port=8502

# Kill existing Streamlit process
lsof -ti:8501 | xargs kill -9
```

**FastAPI Backend (Legacy):**
```bash
source venv/bin/activate
python run.py
```

**Docker:**
```bash
docker-compose up -d
docker-compose logs -f
docker-compose down
```

### Development

```bash
# Setup
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt  # For FastAPI
pip install -r requirements_streamlit.txt  # For Streamlit

# Configuration
cp .env.example .env
# Edit .env and add your VEO_API_KEY
```

## Architecture

### Application Structure

The codebase uses a **dual-application architecture**:

1. **FastAPI Backend** (`app/` directory) - Legacy API server with SSE streaming
2. **Streamlit Frontend** (`streamlit_app.py` + `pages/`) - Primary user interface with password protection

Both interfaces share common utilities in the `utils/` directory.

### Key Components

**VEO API Client (`utils/veo_client.py`)**
- Async HTTP client wrapper for GenAIPro VEO API using httpx
- Implements retry logic with exponential backoff for transient errors
- Handles SSE streaming via context managers (`text_to_video_stream`, `frames_to_video_stream`, etc.)
- Error handling detects HTML maintenance pages and converts them to user-friendly messages
- Rate limiting: 429 errors trigger automatic retry after specified delay
- Connection pooling configured with keepalive (5 connections, 30s expiry)

**SSE Stream Handler (`utils/sse_handler.py`)**
- Parses Server-Sent Events from VEO API responses
- Handles both dictionary (progress updates) and array (completion) formats
- Detects `event:error` types and raises `VideoGenerationError`
- Auto-completes array responses by injecting `status: 'completed'`
- Timeout protection: raises error if no events received for 30 seconds

**Streamlit Pages Architecture**
- `streamlit_app.py` - Main entry point with password protection (uses `utils/auth.py`)
- `pages/` directory contains numbered pages that appear in sidebar:
  - `0_🎯_Solo_Generation.py` - Introduction to solo generation modes
  - `1a_📝_Text_to_Video.py` - Text prompt → video
  - `1b_🖼️_Frames_to_Video.py` - Start/end frame interpolation
  - `1c_🎨_Ingredients_to_Video.py` - Multiple reference images → video
  - `1d_🎨_Create_Image.py` - Image generation
  - `2_📜_History.py` - View past generations
  - `3_🎬_A-ROLL_Footage.py` - Parallel A-roll video generation (single frame + multiple prompts)
  - `4_📦_B-ROLL_Images.py` - Batch image generation with prompts
  - `5_🎥_B-ROLL_Footage.py` - Parallel B-roll video generation (multiple frames matched to prompts)

**Shared Sidebar (`utils/sidebar.py`)**
- Standard component rendered across all Streamlit pages
- API key input (stored in `st.session_state.api_key`)
- Quota checking with live display
- Logout functionality (clears `password_correct` session state)
- Suppresses benign "TCPTransport closed" errors during quota checks

### Critical Implementation Details

**Error Suppression**
The codebase intentionally suppresses specific httpx errors that occur during cleanup:
- "TCPTransport closed" errors in `utils/sidebar.py:52-53`
- These errors are harmless and occur after successful API calls when the client closes

**Batch A-Roll Processing (`pages/7_🎬_Batch_ARoll.py`)**
- Accepts `.txt` files with multi-line prompts separated by blank lines
- Accepts `.csv` files with per-prompt control (ID, prompt, aspect_ratio, etc.)
- Generates multiple videos in parallel from a single reference frame
- Uses UUID-based unique IDs for UI widgets to avoid Streamlit key collisions
- Results are collected and offered as zip download

**Configuration (`app/config.py`)**
- Uses Pydantic Settings to load from `.env` file
- Settings are case-insensitive (`case_sensitive=False`)
- Extra environment variables are ignored (`extra="ignore"`)

**Custom Exceptions (`utils/exceptions.py`)**
- `VEOAPIError` - Base exception for all API errors
- `AuthenticationError` - 401 errors (invalid API key)
- `QuotaExceededError` - 402 errors (insufficient quota)
- `NetworkError` - Connection/timeout failures
- `VideoGenerationError` - Video generation failures
- `StreamInterruptedError` - SSE stream disconnections

### API Endpoints (VEO API)

```
POST /veo/text-to-video          - Generate video from text (SSE stream)
POST /veo/frames-to-video        - Generate video from frames (SSE stream)
POST /veo/ingredients-to-video   - Generate video from images (SSE stream)
POST /veo/create-image           - Generate images (SSE stream)
GET  /veo/me                     - Get quota information
GET  /veo/histories              - Get generation history (paginated)
```

All POST endpoints return SSE streams with format:
```
data: {"status": "processing", "process_percentage": 45}
data: {"status": "completed", "file_url": "https://...", "id": "..."}
```

Or as completion array:
```
data: [{"file_url": "https://...", "id": "...", ...}]
```

### Aspect Ratios

**Video:**
- `VIDEO_ASPECT_RATIO_LANDSCAPE` - Default for most videos
- `VIDEO_ASPECT_RATIO_PORTRAIT` - Mobile/vertical videos

**Image:**
- `IMAGE_ASPECT_RATIO_LANDSCAPE`
- `IMAGE_ASPECT_RATIO_PORTRAIT`
- `IMAGE_ASPECT_RATIO_SQUARE`

## Development Notes

### File Paths
- Uploads: `uploads/` directory (temporary storage)
- Database: `data/batch_queue.db` (batch processing queue)
- Static files: `static/css/`, `static/js/`
- Templates: `templates/` (FastAPI Jinja2 templates)

### Session State (Streamlit)
Key session state variables:
- `api_key` - User's GenAIPro JWT token
- `quota_info` - Cached quota data
- `password_correct` - Password authentication status

### Async Patterns
- Always use `asyncio.run()` when calling async VEO client methods from Streamlit
- Always close the client: `await client.close()` or use context managers
- SSE streams must be consumed fully or closed properly to avoid hanging connections

### Password Protection
- Password is stored in `.streamlit/secrets.toml` as `app_password`
- Default fallback: `"changeme123"`
- Shared authentication utility: `utils/auth.py` provides `require_password()` function
- All pages call `require_password()` after `set_page_config()` to enforce authentication
- Session state `st.session_state.password_correct` tracks authentication across all pages
- Logout clears `st.session_state.password_correct` and triggers rerun
- Users cannot bypass authentication by directly accessing page URLs

### Debugging
- Enable debug mode in VEOClient constructor: `debug=True`
- Use StreamlitLogger for structured logging in Streamlit pages
- SSE handler logs all events when logger is provided
- Check sidebar debug mode checkbox for detailed API logs

## Support Resources

- GenAIPro API Docs: https://genaipro.vn/docs-api
- Telegram Support: https://t.me/genaipro_vn
- Facebook: https://www.facebook.com/genaipro.vn
