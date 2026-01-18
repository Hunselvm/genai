#!/bin/bash
# GenAIPro Auto Top-Up Setup Script

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║        GenAIPro Auto Top-Up Setup                            ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.8+."
    exit 1
fi

echo "✅ Python found: $(python3 --version)"

# Check venv
if [ ! -d "venv" ]; then
    echo ""
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
echo "🔌 Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo ""
echo "📥 Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet httpx python-dotenv

echo "✅ Dependencies installed"

# Make scripts executable
echo ""
echo "🔧 Making scripts executable..."
chmod +x scripts/*.py

# Run cookie extraction
echo ""
echo "🍪 Running cookie extraction..."
echo ""
python3 scripts/get_genaipro_cookies.py

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                    Setup Complete!                           ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "📖 Next Steps:"
echo ""
echo "1. Test connection:"
echo "   python scripts/manual_purchase.py --check-only"
echo ""
echo "2. Start monitoring:"
echo "   python scripts/monitor_quota.py --threshold 20 --interval 3600"
echo ""
echo "3. Read full documentation:"
echo "   cat AUTO_TOPUP_README.md"
echo ""
