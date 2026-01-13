#!/bin/bash

# VEO API Video Generation - Streamlit Runner
# This script helps you run the Streamlit app easily

echo "🎬 VEO API Video Generation - Streamlit"
echo "========================================"
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Install/update dependencies
echo "📥 Installing dependencies..."
pip install -q -r requirements_streamlit.txt

# Create uploads directory if it doesn't exist
mkdir -p uploads

echo ""
echo "✅ Setup complete!"
echo ""
echo "🚀 Starting Streamlit app..."
echo "   Access at: http://localhost:8501"
echo "   Press Ctrl+C to stop"
echo ""

# Run Streamlit
streamlit run streamlit_app.py
