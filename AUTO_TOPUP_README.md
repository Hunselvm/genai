# GenAIPro Auto Top-Up System

Automated quota monitoring and package purchasing for GenAIPro VEO API.

## ⚠️ Important Warnings

**This system is REVERSE ENGINEERED and NOT officially supported by GenAIPro.**

- Your account may be banned if they detect automated purchases
- Cookies expire after ~7 days and need to be re-extracted
- Use at your own risk
- We recommend contacting GenAIPro support for official enterprise/billing solutions

## 🎯 What It Does

1. **Monitors** your VEO quota automatically
2. **Purchases** packages when quota drops below threshold
3. **Alerts** you when balance is low or purchases occur
4. **Prevents** service interruptions for your users

## 📋 Prerequisites

- Python 3.8+
- httpx library (`pip install httpx`)
- python-dotenv (`pip install python-dotenv`)
- Active GenAIPro account with balance
- Chrome or Firefox browser

## 🚀 Quick Start

### Step 1: Install Dependencies

```bash
cd /path/to/genai
pip install httpx python-dotenv
```

### Step 2: Extract Cookies from Browser

```bash
python scripts/get_genaipro_cookies.py
```

Follow the interactive prompts to:
1. Login to https://genaipro.vn
2. Extract cookies from browser DevTools
3. Save cookies to `.env.genaipro` file

### Step 3: Test Connection

```bash
# Check your current status
python scripts/manual_purchase.py --check-only
```

You should see your balance and quota.

### Step 4: Start Monitoring

```bash
# Monitor and auto-purchase when quota < 20
python scripts/monitor_quota.py --threshold 20 --interval 3600
```

## 📖 Detailed Usage

### Cookie Extraction

The system requires 4 cookies from your browser:

1. `__session` - JWT token for authentication
2. `__session_id` - Clerk session ID
3. `__genaipro_session` - Application session
4. `__client_uat` - Client timestamp

**How to extract:**

```bash
python scripts/get_genaipro_cookies.py
```

Or manually:
1. Go to https://genaipro.vn
2. Press F12 → Application → Cookies → https://genaipro.vn
3. Copy the 4 cookie values
4. Save to `.env.genaipro`:

```bash
GENAIPRO_SESSION="eyJhbGci..."
GENAIPRO_SESSION_ID="sess_38OuMQTB5..."
GENAIPRO_APP_SESSION="eyJhbGci..."
GENAIPRO_CLIENT_UAT="1768682891"

VEO_API_KEY="your-veo-api-key-here"
```

**⚠️ Cookie Security:**
- Keep `.env.genaipro` SECRET
- Add to `.gitignore`
- Never commit to repository
- Re-extract every 7 days when expired

### Quota Monitoring

Monitor quota and auto-purchase when low:

```bash
# Basic monitoring (default: threshold=20, interval=1h)
python scripts/monitor_quota.py

# Custom threshold and interval
python scripts/monitor_quota.py --threshold 50 --interval 1800

# Dry run (check only, don't purchase)
python scripts/monitor_quota.py --dry-run

# Check once and exit
python scripts/monitor_quota.py --once
```

**Options:**
- `--threshold INT` - Minimum quota before auto-purchase (default: 20)
- `--interval INT` - Seconds between checks (default: 3600 = 1 hour)
- `--dry-run` - Check quota but don't purchase
- `--once` - Run once and exit

### Manual Purchases

Purchase packages via command line:

```bash
# Check current status
python scripts/manual_purchase.py --check-only

# Purchase 1 package ($1.50 = 100 credits)
python scripts/manual_purchase.py

# Purchase multiple packages
python scripts/manual_purchase.py --count 5
```

### Using in Python Code

```python
import asyncio
from utils.genaipro_auto_topup import GenAIProTopUp

# Load cookies
cookies = {
    "__session": "eyJhbGci...",
    "__session_id": "sess_...",
    "__genaipro_session": "eyJhbGci...",
    "__client_uat": "1768682891",
}

async def example():
    async with GenAIProTopUp(cookies) as client:
        # Check quota
        quota = await client.get_veo_quota()
        print(f"Available: {quota['available_quota']}")

        # Check balance
        user = await client.get_user_info()
        print(f"Balance: ${user['balance']/100.0:.2f}")

        # Auto top-up if needed
        purchased, msg = await client.auto_topup(threshold=20)
        if purchased:
            print(f"Purchased: {msg}")

asyncio.run(example())
```

## 🔧 API Documentation

### GenAIProTopUp Class

Main class for quota monitoring and purchasing.

**Constructor:**
```python
client = GenAIProTopUp(cookies: dict, debug: bool = False)
```

**Methods:**

#### `get_user_info() -> dict`
Get user account information.

Returns:
```python
{
    "balance": 125000,  # Balance in cents ($1250.00)
    "veo_account_id": "uuid",
    "email": "user@example.com",
    "username": "user",
    ...
}
```

#### `get_veo_quota() -> dict`
Get VEO quota information.

Returns:
```python
{
    "total_quota": 100,
    "used_quota": 25,
    "available_quota": 75
}
```

#### `purchase_package(package_id: str) -> dict`
Purchase a specific package.

Args:
- `package_id`: Package UUID

Returns:
```python
{
    "message": "Subscribe veo credits package successfully"
}
```

#### `auto_topup(threshold: int = 20, package_key: str = "veo_100_credits") -> tuple`
Automatically purchase if quota < threshold.

Args:
- `threshold`: Minimum quota
- `package_key`: Package to purchase

Returns:
```python
(purchased: bool, message: str)
```

### Available Packages

```python
GenAIProTopUp.PACKAGES = {
    "veo_100_credits": {
        "id": "33f4871f-efe0-11f0-9608-ce156e002a4d",
        "name": "100 Veo & Banana API",
        "price_usd": 1.50,
        "credits": 100,
        "duration_days": 3
    }
}
```

## 🔍 How It Works

### Architecture

1. **Authentication**: Uses Clerk.com JWT tokens via browser cookies
2. **API Endpoints**:
   - `GET /api/users/me` - User info and balance
   - `GET /api/v1/veo/me` - VEO quota
   - `POST /api/subscriptions/subscribe/veo-credits/{id}` - Purchase package

3. **Flow**:
   ```
   Monitor Loop
   ├─ Check VEO quota (every 1 hour)
   ├─ If quota < threshold:
   │  ├─ Check balance
   │  ├─ Purchase package ($1.50 → 100 credits)
   │  └─ Log success/failure
   └─ Sleep until next check
   ```

### Reverse Engineering Details

**Discovery Method:**
1. Network traffic analysis during manual purchase
2. Identified endpoints and authentication flow
3. Extracted cookie-based auth mechanism
4. Tested and automated

**Key Findings:**
- Uses Clerk.com for authentication
- JWT tokens in `__session` cookie
- Balance in cents (125000 = $1250.00)
- Package IDs are UUIDs

## 🛠️ Troubleshooting

### "Missing required cookies"

**Solution:**
Run cookie extraction again:
```bash
python scripts/get_genaipro_cookies.py
```

Cookies expire after ~7 days.

### "Insufficient balance"

**Solution:**
Top up your GenAIPro balance manually:
1. Go to https://genaipro.vn/payment
2. Add funds via Binance/USDT/PayPal
3. Re-run the script

### "HTTP 401 Unauthorized"

**Solution:**
Your cookies have expired. Re-extract them:
```bash
python scripts/get_genaipro_cookies.py
```

### "HTTP 200 but no purchase"

**Solution:**
Check if package ID changed:
1. Do a manual purchase in browser with DevTools open
2. Check Network tab for the package ID
3. Update `PACKAGES` in `genaipro_auto_topup.py`

## 📊 Monitoring Best Practices

### Recommended Settings

**For production usage:**
```bash
# Check every hour, auto-purchase when < 30 credits
python scripts/monitor_quota.py --threshold 30 --interval 3600
```

**For high-volume usage:**
```bash
# Check every 15 minutes, auto-purchase when < 50 credits
python scripts/monitor_quota.py --threshold 50 --interval 900
```

**For testing:**
```bash
# Dry run - check only
python scripts/monitor_quota.py --dry-run --once
```

### Buffer Strategy

Instead of buying 1 package at a time, buy in bulk:

```python
# Buy 5 packages at once ($7.50 = 500 credits)
python scripts/manual_purchase.py --count 5
```

This reduces API calls and ensures longer runway.

### Alerts

Set up monitoring alerts:

```bash
# Add to your cron or systemd service
*/5 * * * * cd /path/to/genai && python scripts/monitor_quota.py --once >> /var/log/genaipro_monitor.log 2>&1
```

Check logs for warnings:
```bash
tail -f /var/log/genaipro_monitor.log | grep "⚠️"
```

## 🚨 Production Deployment

### Systemd Service (Linux)

Create `/etc/systemd/system/genaipro-monitor.service`:

```ini
[Unit]
Description=GenAIPro Quota Monitor
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/genai
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/python scripts/monitor_quota.py --threshold 30 --interval 3600
Restart=always
RestartSec=60

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable genaipro-monitor
sudo systemctl start genaipro-monitor
sudo systemctl status genaipro-monitor
```

### Docker (Alternative)

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY utils/ ./utils/
COPY scripts/ ./scripts/
COPY .env.genaipro .

CMD ["python", "scripts/monitor_quota.py", "--threshold", "30", "--interval", "3600"]
```

Run:
```bash
docker build -t genaipro-monitor .
docker run -d --name genaipro-monitor --restart=always genaipro-monitor
```

## 🔐 Security Considerations

**DO:**
- Keep cookies SECRET
- Add `.env.genaipro` to `.gitignore`
- Rotate cookies regularly (every 7 days)
- Use environment variables in production
- Monitor logs for unauthorized access

**DON'T:**
- Commit cookies to git
- Share cookies with others
- Use in untrusted environments
- Hardcode cookies in source code

## 📞 Support

**Issues with this automation:**
- Create an issue in this repository
- Check logs: `tail -f genaipro_monitor.log`

**Issues with GenAIPro service:**
- Telegram: https://t.me/genaipro_vn
- Facebook: https://facebook.com/genaipro.vn

## 📜 License & Disclaimer

This automation tool is provided AS-IS with no warranty.

**Disclaimer:**
- Reverse engineered and not officially supported
- May violate GenAIPro Terms of Service
- Your account may be banned
- No guarantees of continued functionality
- Use at your own risk

**Recommendation:**
Contact GenAIPro for official enterprise/reseller programs before using this in production.

---

**Created:** 2026-01-18
**Last Updated:** 2026-01-18
**Status:** Experimental
