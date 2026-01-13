# Quick Start Guide

## 🚀 Get Running in 2 Minutes

### Step 1: Run the App

Choose your preferred method:

#### Option A: Use the Helper Script (Easiest)
```bash
./run_streamlit.sh
```

#### Option B: Manual Start
```bash
# Activate virtual environment
source venv/bin/activate

# Install Streamlit (first time only)
pip install streamlit

# Run the app
streamlit run streamlit_app.py
```

### Step 2: Open Your Browser

The app will automatically open at: `http://localhost:8501`

If it doesn't open automatically, manually go to that URL.

### Step 3: Enter Your API Key

1. Look at the **left sidebar**
2. Find the "GenAIPro API Key" text input
3. Paste your API key (get it from https://genaipro.vn/docs-api)
4. Click "Check Quota" to verify it works

### Step 4: Generate Your First Video!

1. Click **"Text to Video"** in the sidebar
2. Enter a prompt like: `"A cat playing with a ball in a sunny garden"`
3. Choose **Landscape** aspect ratio
4. Click **"Generate Video"**
5. Watch the progress bar fill up!
6. Your video will appear when ready

---

## 📱 Share with Others

### For Local Network (Home/Office):

1. **Find your IP address:**
   ```bash
   # On Mac/Linux
   ifconfig | grep "inet "

   # On Windows
   ipconfig
   ```

2. **Share the URL:**
   - Share: `http://YOUR-IP:8501`
   - Example: `http://192.168.1.100:8501`

3. **Each user enters their own API key** in the sidebar

### For Internet Access:

**Option 1: Deploy to Streamlit Cloud (Free)**
- Push code to GitHub
- Go to [share.streamlit.io](https://share.streamlit.io)
- Connect your repo and deploy
- Get a public URL like: `https://your-app.streamlit.app`

**Option 2: Use Your Home Server**
- Run with Docker: `docker-compose up -d`
- Setup port forwarding on your router (port 8501)
- Share your public IP: `http://YOUR-PUBLIC-IP:8501`
- (Recommended: Use a reverse proxy with HTTPS)

---

## 🔧 Common Commands

```bash
# Start the app
streamlit run streamlit_app.py

# Start with custom port
streamlit run streamlit_app.py --server.port=8502

# Start with Docker
docker-compose up -d

# View Docker logs
docker-compose logs -f

# Stop Docker
docker-compose down

# Update dependencies
pip install -r requirements_streamlit.txt
```

---

## ❓ Quick Troubleshooting

### "Command not found: streamlit"
```bash
pip install streamlit
```

### "Module not found: utils"
Make sure you're in the `genai` directory:
```bash
cd "/Users/max/My Drive (selviocommerce@gmail.com)/8 App/genai"
```

### "Port 8501 already in use"
```bash
# Kill the process using the port
lsof -ti:8501 | xargs kill -9

# Or use a different port
streamlit run streamlit_app.py --server.port=8502
```

### "API key invalid"
1. Check you copied the entire key
2. Remove any spaces before/after
3. Get a fresh key from https://genaipro.vn/docs-api

---

## 📚 Next Steps

- Read the full [README_STREAMLIT.md](README_STREAMLIT.md) for deployment options
- Check out all four generation modes in the sidebar
- View your generation history
- Monitor your quota usage

**Need Help?**
- GenAIPro Support: https://t.me/genaipro_vn
- Check logs in terminal for errors

---

**Enjoy generating amazing videos! 🎬**
