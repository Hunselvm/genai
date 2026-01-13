# VEO API Video Generation - Streamlit App

A beautiful, user-friendly web application for generating videos using the GenAIPro VEO API. Built with Streamlit for easy deployment and sharing.

## ✨ Features

- **🔐 Secure API Key Management** - Each user enters their own API key
- **📝 Text to Video** - Generate videos from text prompts with real-time progress
- **🖼️ Frames to Video** - Create videos by interpolating between images
- **🎨 Ingredients to Video** - Use multiple reference images for video generation
- **📜 History** - View all your past generations
- **📊 Quota Tracking** - Monitor your API usage
- **🎨 Beautiful UI** - Clean, modern interface with gradient themes

## 🚀 Quick Start

### Option 1: Run Locally (Simplest)

1. **Install dependencies:**
   ```bash
   pip install -r requirements_streamlit.txt
   ```

2. **Run the app:**
   ```bash
   streamlit run streamlit_app.py
   ```

3. **Open your browser:**
   - Streamlit will automatically open `http://localhost:8501`
   - Enter your GenAIPro API key in the sidebar
   - Start generating videos!

### Option 2: Docker (Recommended for Home Server)

1. **Build and run with Docker Compose:**
   ```bash
   docker-compose up -d
   ```

2. **Access the app:**
   - Open `http://localhost:8501` or `http://your-server-ip:8501`

3. **Stop the app:**
   ```bash
   docker-compose down
   ```

### Option 3: Deploy to Streamlit Cloud (Free Hosting)

1. **Push to GitHub:**
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin your-github-repo-url
   git push -u origin main
   ```

2. **Deploy:**
   - Go to [share.streamlit.io](https://share.streamlit.io)
   - Click "New app"
   - Select your repository
   - Set main file: `streamlit_app.py`
   - Click "Deploy"

3. **Share the URL:**
   - You'll get a public URL like `https://your-app.streamlit.app`
   - Share this with your team/clients
   - Each user enters their own API key

## 📁 Project Structure

```
genai/
├── streamlit_app.py          # Main application
├── pages/                    # Multi-page app
│   ├── 1_📝_Text_to_Video.py
│   ├── 2_🖼️_Frames_to_Video.py
│   ├── 3_🎨_Ingredients_to_Video.py
│   └── 4_📜_History.py
├── utils/                    # Reusable utilities
│   ├── veo_client.py        # VEO API client
│   ├── sse_handler.py       # SSE stream parser
│   └── exceptions.py        # Custom exceptions
├── .streamlit/
│   └── config.toml          # Streamlit configuration
├── Dockerfile               # Docker image definition
├── docker-compose.yml       # Docker Compose config
└── requirements_streamlit.txt  # Python dependencies
```

## 🔑 Getting Your API Key

1. Visit [GenAIPro API Docs](https://genaipro.vn/docs-api)
2. Log in or create an account
3. Navigate to "API Key Management" section
4. Copy your JWT token
5. Enter it in the Streamlit app sidebar

## 🎬 How to Use

### Text to Video
1. Click "Text to Video" in sidebar
2. Enter a descriptive prompt
3. Choose aspect ratio (Landscape/Portrait)
4. Select number of videos (1-4)
5. Click "Generate Video"
6. Watch real-time progress
7. View and download your video!

### Frames to Video
1. Click "Frames to Video" in sidebar
2. Upload a start frame image (required)
3. Upload an end frame image (optional)
4. Enter a prompt describing the transition
5. Click "Generate Video from Frames"
6. Watch progress and get your result!

### Ingredients to Video
1. Click "Ingredients to Video" in sidebar
2. Upload multiple reference images (2-6 recommended)
3. Enter a prompt describing how to use them
4. Click "Generate Video from Ingredients"
5. Get your AI-generated video!

### History
1. Click "History" in sidebar
2. Click "Load History"
3. Browse your past generations
4. Click "View Video" to watch again
5. Use pagination for many items

## 🏠 Deploy to Your Home Server

### Requirements:
- Docker and Docker Compose installed
- Port 8501 available
- (Optional) Reverse proxy for HTTPS (nginx/Caddy)

### Steps:

1. **Clone/copy files to server:**
   ```bash
   scp -r genai/ user@your-server:/path/to/deploy
   ```

2. **SSH into server:**
   ```bash
   ssh user@your-server
   cd /path/to/deploy/genai
   ```

3. **Run with Docker:**
   ```bash
   docker-compose up -d
   ```

4. **Access locally or via IP:**
   - Local: `http://localhost:8501`
   - Network: `http://your-server-ip:8501`

### Optional: Setup HTTPS with nginx

1. **Install nginx:**
   ```bash
   sudo apt install nginx certbot python3-certbot-nginx
   ```

2. **Create nginx config** (`/etc/nginx/sites-available/veo-app`):
   ```nginx
   server {
       listen 80;
       server_name your-domain.com;

       location / {
           proxy_pass http://localhost:8501;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
       }
   }
   ```

3. **Enable and get SSL:**
   ```bash
   sudo ln -s /etc/nginx/sites-available/veo-app /etc/nginx/sites-enabled/
   sudo certbot --nginx -d your-domain.com
   sudo systemctl restart nginx
   ```

4. **Access via HTTPS:**
   - `https://your-domain.com`

## 💡 Tips for Users

### For Best Video Results:
- **Prompts**: Be specific and descriptive
- **Aspect Ratio**: Choose based on intended use (social media, website, etc.)
- **Images**: Use high-quality, clear images
- **Reference Images**: Keep them thematically consistent

### For Administrators:
- **API Keys**: Never share your API key - each user should use their own
- **Costs**: Each user's generations count against their own quota
- **Updates**: Pull latest changes and rebuild Docker image
- **Monitoring**: Check logs with `docker-compose logs -f`

## 🐛 Troubleshooting

### App Won't Start
```bash
# Check if port 8501 is in use
lsof -i :8501

# View Docker logs
docker-compose logs

# Rebuild Docker image
docker-compose build --no-cache
docker-compose up -d
```

### API Key Not Working
- Verify key is correct (copy from GenAIPro dashboard)
- Check quota hasn't been exceeded
- Ensure no extra spaces in key

### Video Generation Fails
- Check internet connection
- Verify API key has remaining quota
- Ensure uploaded images are valid formats
- Try a simpler prompt first

### Can't Access on Network
```bash
# Check firewall
sudo ufw allow 8501

# Verify Docker is running
docker ps

# Check if service is listening
netstat -tulpn | grep 8501
```

## 📊 Deployment Options Comparison

| Option | Difficulty | Cost | Best For |
|--------|-----------|------|----------|
| **Local Run** | Easy | Free | Testing, personal use |
| **Home Server** | Medium | Free | Small team, have server |
| **Streamlit Cloud** | Easy | Free | Team/clients, public access |
| **VPS (DigitalOcean, etc.)** | Medium | $5-10/mo | Professional deployment |

## 🔄 Updating the App

### Local Installation:
```bash
git pull
pip install -r requirements_streamlit.txt
streamlit run streamlit_app.py
```

### Docker:
```bash
git pull
docker-compose down
docker-compose build
docker-compose up -d
```

### Streamlit Cloud:
- Push changes to GitHub
- Streamlit Cloud auto-deploys

## 📞 Support

- **GenAIPro API**: [https://genaipro.vn/docs-api](https://genaipro.vn/docs-api)
- **Telegram**: [@genaipro_vn](https://t.me/genaipro_vn)
- **Facebook**: [genaipro.vn](https://www.facebook.com/genaipro.vn)

## 📝 License

This project is for use with the GenAIPro API. Each user is responsible for their own API usage and costs.

---

**Built with ❤️ using Streamlit and GenAIPro VEO API**
