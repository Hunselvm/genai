# VEO API Video Generation

A Python web application for generating videos using the GenAIPro VEO API. Features a simple web interface for text-to-video, frames-to-video, and ingredients-to-video generation with batch processing support.

## Features

- **Text-to-Video Generation**: Create videos from text prompts
- **Frames-to-Video**: Generate videos from start/end frame images
- **Ingredients-to-Video**: Create videos using multiple reference images
- **Batch Processing**: Queue multiple video generation jobs
- **Real-time Progress**: Live updates during video generation via SSE
- **Generation History**: View past video generations
- **Quota Tracking**: Monitor your API usage

## Requirements

- Python 3.8+
- GenAIPro API key (JWT token)

## Installation

1. **Clone or navigate to the project directory**:
   ```bash
   cd /path/to/genai
   ```

2. **Create a virtual environment**:
   ```bash
   python -m venv venv
   ```

3. **Activate the virtual environment**:
   - On macOS/Linux:
     ```bash
     source venv/bin/activate
     ```
   - On Windows:
     ```bash
     venv\Scripts\activate
     ```

4. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

5. **Create .env file**:
   ```bash
   cp .env.example .env
   ```

6. **Edit .env file and add your API key**:
   ```bash
   VEO_API_KEY=your_jwt_token_here
   ```

## Usage

1. **Start the application**:
   ```bash
   python run.py
   ```

2. **Open your browser**:
   Navigate to `http://127.0.0.1:8000`

3. **Generate videos**:
   - **Text to Video**: Enter a prompt and click "Generate Video"
   - **Check Quota**: Click "Check Quota" to see your remaining credits
   - **View History**: Switch to the "History" tab to see past generations

## Project Structure

```
genai/
├── app/                    # Application code
│   ├── main.py            # FastAPI application
│   ├── config.py          # Configuration
│   ├── models.py          # Pydantic models
│   ├── services/          # Business logic
│   │   ├── veo_client.py  # VEO API client
│   │   └── sse_handler.py # SSE stream handler
│   └── utils/             # Utilities
│       └── exceptions.py  # Custom exceptions
├── static/                # Static files
│   ├── css/              # Stylesheets
│   └── js/               # JavaScript
├── templates/            # HTML templates
├── uploads/              # Temporary file storage
├── data/                 # Database files
├── .env                  # Environment variables
├── requirements.txt      # Python dependencies
├── run.py               # Application launcher
└── README.md            # This file
```

## API Endpoints

- `GET /` - Main dashboard
- `GET /api/quota` - Get quota information
- `POST /api/video/text-to-video` - Generate video from text (SSE stream)
- `GET /api/history` - Get generation history
- `GET /health` - Health check

## Configuration

Edit `.env` file to customize settings:

```bash
# API Configuration
VEO_API_KEY=your_jwt_token_here
VEO_BASE_URL=https://genaipro.vn/api/v1

# Application Settings
APP_HOST=127.0.0.1
APP_PORT=8000
DEBUG=true

# File Settings
UPLOAD_DIR=uploads
MAX_UPLOAD_SIZE_MB=50

# Batch Processing
MAX_CONCURRENT_JOBS=1
BATCH_DB_PATH=data/batch_queue.db
```

## Development Status

### ✅ Phase 1 Complete: Core Infrastructure
- Project structure
- VEO API client
- SSE stream handling
- Basic text-to-video generation
- Web UI with real-time progress

### 🚧 Coming Soon:
- Frames-to-video generation
- Ingredients-to-video generation
- Batch processing queue
- Directory scanning for images
- WebSocket real-time updates

## Troubleshooting

### API Key Error
If you get an authentication error, check that:
1. Your `.env` file exists and contains `VEO_API_KEY`
2. The API key is valid and not expired
3. You have sufficient quota

### Connection Error
If the application fails to connect:
1. Check your internet connection
2. Verify the VEO API is accessible
3. Check firewall settings

### Module Not Found
If you get import errors:
1. Ensure virtual environment is activated
2. Reinstall dependencies: `pip install -r requirements.txt`

## Support

For issues with the GenAIPro VEO API, visit: https://genaipro.vn/docs-api

## License

This project is for personal use with the GenAIPro API.
