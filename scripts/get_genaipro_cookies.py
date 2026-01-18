#!/usr/bin/env python3
"""
GenAIPro Cookie Extractor
==========================

This script helps you extract cookies from your browser for use with the auto top-up system.

Usage:
    1. Login to genaipro.vn in your browser
    2. Run this script
    3. Follow the instructions to copy cookies
"""

import os
import json


def print_instructions():
    """Print step-by-step instructions to extract cookies."""

    print("""
╔══════════════════════════════════════════════════════════════╗
║         GenAIPro Cookie Extraction Instructions              ║
╚══════════════════════════════════════════════════════════════╝

📋 STEP 1: Open GenAIPro in Chrome
   • Go to: https://genaipro.vn
   • Make sure you're logged in

📋 STEP 2: Open Developer Tools
   • Press F12 (Windows) or Cmd+Option+I (Mac)
   • Click on "Application" tab at the top

📋 STEP 3: View Cookies
   • In left sidebar: Storage → Cookies → https://genaipro.vn
   • You should see a list of cookies

📋 STEP 4: Copy Cookie Values
   • Find these 4 cookies and copy their VALUES:

   1️⃣  __session
      → Look for: Long string starting with "eyJhbGci..."

   2️⃣  __session_id
      → Look for: String like "sess_38OuMQTB5LlJn8DxVKeAwhtI1Ix"

   3️⃣  __genaipro_session
      → Look for: Long string starting with "eyJhbGci..."

   4️⃣  __client_uat
      → Look for: Number like "1768682891"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📝 STEP 5: Enter Cookie Values Below
    """)


def get_cookie_input() -> dict:
    """Interactive prompt to get cookie values from user."""

    print("\n🔐 Enter cookie values (paste and press Enter):\n")

    cookies = {}

    cookies["__session"] = input("1. __session: ").strip()
    cookies["__session_id"] = input("2. __session_id: ").strip()
    cookies["__genaipro_session"] = input("3. __genaipro_session: ").strip()
    cookies["__client_uat"] = input("4. __client_uat: ").strip()

    return cookies


def validate_cookies(cookies: dict) -> bool:
    """Validate that cookies look correct."""

    if not all(cookies.values()):
        print("\n❌ Error: All cookies are required!")
        return False

    # Basic validation
    if not cookies["__session"].startswith("eyJ"):
        print("\n⚠️  Warning: __session should start with 'eyJ' (JWT token)")

    if not cookies["__session_id"].startswith("sess_"):
        print("\n⚠️  Warning: __session_id should start with 'sess_'")

    if not cookies["__client_uat"].isdigit():
        print("\n⚠️  Warning: __client_uat should be a number")

    return True


def save_to_env_file(cookies: dict, filepath: str = ".env.genaipro"):
    """Save cookies to .env file."""

    env_content = f"""# GenAIPro Auto Top-Up Cookies
# Generated: {__import__('datetime').datetime.now().isoformat()}
# ⚠️  Keep this file SECRET! Do not commit to git!

GENAIPRO_SESSION="{cookies['__session']}"
GENAIPRO_SESSION_ID="{cookies['__session_id']}"
GENAIPRO_APP_SESSION="{cookies['__genaipro_session']}"
GENAIPRO_CLIENT_UAT="{cookies['__client_uat']}"

# Your VEO API key (from https://genaipro.vn/docs-api)
VEO_API_KEY="your-api-key-here"
"""

    with open(filepath, "w") as f:
        f.write(env_content)

    print(f"\n✅ Cookies saved to: {filepath}")
    print(f"   Make sure to add this to .gitignore!")


def save_to_python_dict(cookies: dict, filepath: str = "genaipro_cookies.py"):
    """Save cookies as Python dictionary."""

    python_content = f'''"""
GenAIPro Cookies
Generated: {__import__('datetime').datetime.now().isoformat()}

⚠️  KEEP THIS FILE SECRET! Do not commit to git!
"""

GENAIPRO_COOKIES = {{
    "__session": "{cookies['__session']}",
    "__session_id": "{cookies['__session_id']}",
    "__genaipro_session": "{cookies['__genaipro_session']}",
    "__client_uat": "{cookies['__client_uat']}",
}}
'''

    with open(filepath, "w") as f:
        f.write(python_content)

    print(f"✅ Cookies saved to: {filepath}")


def main():
    """Main entry point."""

    print_instructions()

    # Get cookies from user
    cookies = get_cookie_input()

    # Validate
    if not validate_cookies(cookies):
        print("\n❌ Please try again with correct cookie values")
        return

    # Ask where to save
    print("\n💾 Where do you want to save the cookies?")
    print("   1. .env file (recommended)")
    print("   2. Python file")
    print("   3. Both")
    print("   4. Just show me (don't save)")

    choice = input("\nEnter choice (1-4): ").strip()

    if choice == "1" or choice == "3":
        save_to_env_file(cookies)

    if choice == "2" or choice == "3":
        save_to_python_dict(cookies)

    if choice == "4":
        print("\n📋 Your cookies:\n")
        print(json.dumps(cookies, indent=2))

    # Print usage instructions
    print("\n" + "="*60)
    print("🎉 Setup Complete!")
    print("="*60)
    print("\n📖 Next Steps:\n")
    print("1. Test the connection:")
    print("   python utils/genaipro_auto_topup.py")
    print("\n2. Start monitoring:")
    print("   python scripts/monitor_quota.py")
    print("\n3. Manual purchase:")
    print("   python scripts/manual_purchase.py")
    print("\n⚠️  Remember: Cookies expire after ~7 days!")
    print("   You'll need to re-extract them when they expire.\n")


if __name__ == "__main__":
    main()
