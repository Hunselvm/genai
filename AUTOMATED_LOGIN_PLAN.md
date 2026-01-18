# Automated GenAIPro Login & Cookie Management

## Overview

Automate the GenAIPro login flow using email+password authentication to eliminate manual cookie extraction. The system will handle:
- Automated browser login via Playwright
- Interactive email verification code entry (one-time)
- Automatic cookie extraction and storage
- Cookie expiration detection and auto-refresh

**User Requirements:**
- ✅ Already has email+password account on GenAIPro
- ✅ Manual email verification code entry (acceptable)
- ✅ 100% automation after initial setup

## Current State

**Existing System:** `/Users/max/My Drive (selviocommerce@gmail.com)/8 App/genai/`
- Cookie-based authentication (4 cookies required)
- Manual cookie extraction every 7 days
- Working auto-topup system with correct balance calculations

**Current Files:**
- `utils/genaipro_auto_topup.py` - Main automation logic
- `scripts/get_genaipro_cookies.py` - Manual cookie extraction tool
- `scripts/monitor_quota.py` - Quota monitoring daemon
- `.env.genaipro` - Cookie storage

## Implementation Plan

### Phase 1: Browser Automation Setup

**New Dependencies:**
```txt
# Add to requirements.txt or requirements_auto_topup.txt
playwright==1.42.0
```

**Installation:**
```bash
pip install playwright
playwright install chromium  # Install browser binary
```

### Phase 2: Create Automated Login Module

**New File:** `utils/genaipro_auth.py`

**Key Functions:**

1. **`async def automated_login(email: str, password: str) -> dict`**
   - Launch headless Chromium browser via Playwright
   - Navigate to https://genaipro.vn
   - Fill email and password fields
   - Submit login form
   - **Pause for user to enter email verification code** (interactive prompt)
   - Wait for successful authentication
   - Extract all 4 required cookies
   - Return cookie dictionary

2. **`async def extract_cookies_from_browser(page: Page) -> dict`**
   - Get cookies from Playwright browser context
   - Map to required format:
     ```python
     {
         "__session": "...",
         "__session_id": "...",
         "__genaipro_session": "...",
         "__client_uat": "..."
     }
     ```

3. **`def save_cookies_to_env(cookies: dict, filepath: str = ".env.genaipro")`**
   - Save cookies to `.env.genaipro` file
   - Include expiration timestamp for 7-day refresh tracking

4. **`def cookies_expired(filepath: str = ".env.genaipro") -> bool`**
   - Check if cookies are older than 7 days
   - Return True if refresh needed

**Playwright Selectors (to be discovered):**
- Email input field: `input[name="identifier"]` or `input[type="email"]`
- Password input field: `input[name="password"]` or `input[type="password"]`
- Submit button: `button[type="submit"]` or specific Clerk button class
- Verification code input: `input[name="code"]` (after login)

**Implementation Details:**

```python
async def automated_login(email: str, password: str) -> dict:
    """
    Automate GenAIPro login and extract cookies.

    Flow:
    1. Launch Playwright browser
    2. Navigate to https://genaipro.vn
    3. Click login/sign-in button
    4. Fill email and password
    5. Submit form
    6. WAIT for user to manually enter email verification code
    7. Extract cookies after successful login
    8. Close browser
    9. Return cookies
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        # Launch browser (headless=False for interactive code entry)
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        # Navigate to GenAIPro
        await page.goto("https://genaipro.vn")

        # Click sign-in (discover exact selector)
        await page.click("text=Sign in")  # Or Clerk button

        # Fill credentials
        await page.fill("input[name='identifier']", email)
        await page.fill("input[name='password']", password)
        await page.click("button:has-text('Continue')")

        # Wait for email verification page
        print("\n⚠️  CHECK YOUR EMAIL for verification code")
        print("Enter the code in the browser window...")

        # Wait for successful login (check for redirect or dashboard)
        await page.wait_for_url("**/veo**", timeout=120000)  # 2 min timeout

        # Extract cookies
        cookies = await extract_cookies_from_browser(page)

        await browser.close()
        return cookies
```

### Phase 3: Modify Existing Scripts

**Update: `utils/genaipro_auto_topup.py`**

Add automatic cookie refresh logic:

```python
class GenAIProTopUp:
    def __init__(
        self,
        cookies: Optional[Dict[str, str]] = None,
        email: Optional[str] = None,
        password: Optional[str] = None,
        debug: bool = False
    ):
        """
        Initialize with either:
        - cookies: Pre-extracted cookies (existing flow)
        - email+password: Trigger automated login if cookies missing/expired
        """
        if cookies is None:
            # Try loading from .env.genaipro
            cookies = self._load_cookies_from_env()

            # If cookies expired or missing, do automated login
            if cookies_expired() or not cookies:
                if email and password:
                    print("🔄 Cookies expired, performing automated login...")
                    cookies = asyncio.run(automated_login(email, password))
                    save_cookies_to_env(cookies)
                else:
                    raise ValueError("Cookies expired and no email+password provided")

        # Rest of existing __init__ code...
```

**Add: Cookie refresh wrapper**

```python
async def _ensure_valid_cookies(self):
    """Check and refresh cookies before API calls."""
    if cookies_expired():
        if self.email and self.password:
            print("🔄 Auto-refreshing expired cookies...")
            new_cookies = await automated_login(self.email, self.password)
            save_cookies_to_env(new_cookies)
            self.cookies = new_cookies
        else:
            raise ValueError("Cookies expired - please login again")
```

### Phase 4: Create Setup Script

**New File:** `scripts/setup_automated_auth.py`

Interactive setup wizard:

```python
#!/usr/bin/env python3
"""
Setup automated GenAIPro authentication.

This script:
1. Prompts for email+password
2. Performs first-time login with browser automation
3. Extracts and saves cookies
4. Configures .env.genaipro file
"""

import asyncio
from utils.genaipro_auth import automated_login, save_cookies_to_env

async def main():
    print("╔════════════════════════════════════════════╗")
    print("║  GenAIPro Automated Authentication Setup  ║")
    print("╚════════════════════════════════════════════╝\n")

    email = input("Enter your GenAIPro email: ").strip()
    password = input("Enter your GenAIPro password: ").strip()

    print("\n🚀 Starting automated login...")
    print("📧 You will need to enter the email verification code in the browser\n")

    cookies = await automated_login(email, password)

    save_cookies_to_env(cookies)

    # Save credentials for auto-refresh
    with open(".env.genaipro", "a") as f:
        f.write(f"\n# Auto-refresh credentials\n")
        f.write(f"GENAIPRO_EMAIL=\"{email}\"\n")
        f.write(f"GENAIPRO_PASSWORD=\"{password}\"\n")

    print("\n✅ Setup complete!")
    print("   Cookies saved to .env.genaipro")
    print("   Auto-refresh enabled for 7-day cycle\n")

if __name__ == "__main__":
    asyncio.run(main())
```

### Phase 5: Update Monitoring Scripts

**Modify: `scripts/monitor_quota.py`**

```python
def load_cookies_and_credentials() -> tuple:
    """Load cookies and optional email+password for auto-refresh."""
    env_file = project_root / ".env.genaipro"
    if env_file.exists():
        load_dotenv(env_file)

    cookies = {
        "__session": os.getenv("GENAIPRO_SESSION"),
        "__session_id": os.getenv("GENAIPRO_SESSION_ID"),
        "__genaipro_session": os.getenv("GENAIPRO_APP_SESSION"),
        "__client_uat": os.getenv("GENAIPRO_CLIENT_UAT"),
    }

    # Optional credentials for auto-refresh
    email = os.getenv("GENAIPRO_EMAIL")
    password = os.getenv("GENAIPRO_PASSWORD")

    return cookies, email, password

# In monitor loop:
cookies, email, password = load_cookies_and_credentials()
async with GenAIProTopUp(cookies=cookies, email=email, password=password) as client:
    # Auto-refresh will happen automatically if cookies expire
    await client.auto_topup(threshold=threshold)
```

## Critical Files to Modify

1. **NEW:** `utils/genaipro_auth.py` - Browser automation and cookie extraction
2. **NEW:** `scripts/setup_automated_auth.py` - One-time setup wizard
3. **MODIFY:** `utils/genaipro_auto_topup.py` - Add auto-refresh logic
4. **MODIFY:** `scripts/monitor_quota.py` - Load email+password for auto-refresh
5. **MODIFY:** `scripts/manual_purchase.py` - Same auto-refresh support
6. **UPDATE:** `.gitignore` - Ensure `.env.genaipro` is excluded (already done)
7. **UPDATE:** `requirements.txt` - Add `playwright==1.42.0`

## Playwright Selector Discovery

Before implementation, need to discover exact selectors by inspecting GenAIPro:

1. Visit https://genaipro.vn
2. Inspect login form elements
3. Identify:
   - Sign-in button selector
   - Email input field name/id
   - Password input field name/id
   - Submit button selector
   - Verification code input (if separate page)
   - Success redirect URL pattern

## Security Considerations

**Storing Credentials:**
- Passwords stored in `.env.genaipro` (plain text)
- **Risk:** If file is compromised, attacker has full access
- **Mitigation:**
  - Ensure `.env.genaipro` is in `.gitignore`
  - File permissions: `chmod 600 .env.genaipro`
  - Consider encryption at rest (optional)

**Browser Automation Detection:**
- Clerk.com may detect Playwright/Selenium
- **Mitigation:**
  - Use stealth plugins if needed
  - Mimic human behavior (delays, mouse movements)
  - Use `headless=False` initially to verify flow

## Implementation Steps

### Step 1: Install Dependencies
```bash
cd "/Users/max/My Drive (selviocommerce@gmail.com)/8 App/genai"
pip install playwright
playwright install chromium
```

### Step 2: Discover Selectors
- Manually inspect GenAIPro login flow
- Document exact Clerk.com form selectors
- Test Playwright navigation in Python REPL

### Step 3: Implement `utils/genaipro_auth.py`
- Start with manual browser (`headless=False`)
- Implement login automation
- Add interactive verification code prompt
- Test cookie extraction

### Step 4: Create Setup Script
- Build `scripts/setup_automated_auth.py`
- Test full flow with real account
- Verify cookies work with existing auto-topup

### Step 5: Add Auto-Refresh
- Modify `GenAIProTopUp.__init__()`
- Add `_ensure_valid_cookies()` method
- Update all scripts to load credentials

### Step 6: Testing
- Test initial setup flow
- Verify 7-day cookie expiration detection
- Test automatic refresh when cookies expire
- Ensure all existing functionality still works

## Verification Plan

**Test 1: Initial Setup**
```bash
python scripts/setup_automated_auth.py
# Verify: .env.genaipro contains all cookies + credentials
```

**Test 2: Manual Cookie Check**
```bash
python scripts/manual_purchase.py --check-only
# Should show correct balance without manual cookie extraction
```

**Test 3: Simulate Expired Cookies**
```bash
# Modify cookie timestamp to be 8 days old
python scripts/monitor_quota.py --once
# Should auto-refresh cookies via browser automation
```

**Test 4: 24-Hour Monitoring**
```bash
python scripts/monitor_quota.py --threshold 50 --interval 3600
# Should run for 24h without manual intervention
```

## Fallback Strategy

If browser automation fails or is detected:
1. Fall back to manual cookie extraction (current method)
2. Show clear error message with instructions
3. Log failure reason for debugging

**Error Handling:**
```python
try:
    cookies = await automated_login(email, password)
except PlaywrightError as e:
    logger.error(f"Automated login failed: {e}")
    logger.info("Please extract cookies manually: python scripts/get_genaipro_cookies.py")
    raise
```

## Timeline Estimate

- **Selector Discovery:** 30 minutes
- **Core Implementation:** 2-3 hours
- **Testing & Debugging:** 1-2 hours
- **Documentation:** 30 minutes
- **Total:** ~4-6 hours

## Success Criteria

✅ Setup script successfully logs in and extracts cookies
✅ Cookies work with existing auto-topup system
✅ Auto-refresh triggers when cookies expire
✅ System runs for 7+ days without manual intervention
✅ Email verification code can be entered interactively
✅ Fallback to manual extraction if automation fails

## Trade-offs & Risks

**Benefits:**
- ✅ Eliminates weekly manual cookie extraction
- ✅ Fully automated after initial setup
- ✅ Graceful handling of cookie expiration

**Risks:**
- ⚠️ Playwright detection by Clerk.com
- ⚠️ Changes to GenAIPro login UI break automation
- ⚠️ Credentials stored in plaintext in .env file
- ⚠️ Browser automation adds ~200MB dependency (Chromium)

**Recommendation:**
Proceed with implementation. The benefits outweigh the risks for a personal automation tool. The fallback to manual extraction ensures resilience.
