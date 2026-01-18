#!/usr/bin/env python3
"""
GenAIPro Manual Package Purchase
=================================

Manually purchase VEO packages via command line.

Usage:
    python scripts/manual_purchase.py [--package veo_100_credits] [--count 1]

Options:
    --package STR    Package to purchase (default: veo_100_credits)
    --count INT      Number of packages to purchase (default: 1)
    --check-only     Only check balance/quota, don't purchase
"""

import asyncio
import argparse
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.genaipro_auto_topup import GenAIProTopUp
from dotenv import load_dotenv
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


def load_cookies() -> dict:
    """Load cookies from environment."""

    env_file = project_root / ".env.genaipro"
    if env_file.exists():
        load_dotenv(env_file)

    cookies = {
        "__session": os.getenv("GENAIPRO_SESSION"),
        "__session_id": os.getenv("GENAIPRO_SESSION_ID"),
        "__genaipro_session": os.getenv("GENAIPRO_APP_SESSION"),
        "__client_uat": os.getenv("GENAIPRO_CLIENT_UAT"),
    }

    if not all(cookies.values()):
        logger.error("❌ Missing required cookies!")
        logger.error("   Run: python scripts/get_genaipro_cookies.py")
        sys.exit(1)

    return cookies


async def check_status(cookies: dict):
    """Check current balance and quota."""

    async with GenAIProTopUp(cookies) as client:
        quota = await client.get_veo_quota()
        user = await client.get_user_info()

        available = quota.get("available_quota", 0)
        total = quota.get("total_quota", 0)
        used = quota.get("used_quota", 0)
        balance_usd = user["balance"] / 25000.0

        print("\n" + "="*60)
        print("📊 CURRENT STATUS")
        print("="*60)
        print(f"💰 Balance:      ${balance_usd:.2f}")
        print(f"📈 VEO Quota:    {available}/{total} ({used} used)")
        print(f"📧 Email:        {user.get('email')}")
        print(f"👤 Username:     {user.get('username')}")
        print("="*60 + "\n")

        return balance_usd, available


async def purchase_packages(cookies: dict, package_key: str, count: int):
    """Purchase one or more packages."""

    async with GenAIProTopUp(cookies, debug=True) as client:
        # Get package info
        package = GenAIProTopUp.PACKAGES.get(package_key)
        if not package:
            logger.error(f"❌ Unknown package: {package_key}")
            logger.error(f"   Available: {list(GenAIProTopUp.PACKAGES.keys())}")
            sys.exit(1)

        # Check balance
        balance_usd, current_quota = await check_status(cookies)

        total_cost = package["price_usd"] * count
        total_credits = package["credits"] * count

        print(f"📦 Package: {package['name']}")
        print(f"💵 Price:   ${package['price_usd']} per package")
        print(f"🔢 Count:   {count}")
        print(f"💰 Total:   ${total_cost:.2f}\n")

        if balance_usd < total_cost:
            logger.error(f"❌ Insufficient balance!")
            logger.error(f"   Have: ${balance_usd:.2f}")
            logger.error(f"   Need: ${total_cost:.2f}")
            return

        # Confirm
        print(f"This will purchase {count}x '{package['name']}' for ${total_cost:.2f}")
        print(f"You will receive {total_credits} credits.")
        confirm = input("\n⚠️  Confirm purchase? (yes/no): ").strip().lower()

        if confirm != "yes":
            logger.info("❌ Purchase cancelled")
            return

        # Purchase
        print(f"\n🛒 Purchasing {count} package(s)...")

        for i in range(count):
            try:
                result = await client.purchase_package(package["id"])
                logger.info(f"   ✅ Package {i+1}/{count}: {result.get('message')}")

                # Small delay between purchases
                if i < count - 1:
                    await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"   ❌ Package {i+1}/{count} failed: {e}")
                break

        # Show updated status
        print("\n📊 Updated status:")
        await check_status(cookies)


def main():
    """Main entry point."""

    parser = argparse.ArgumentParser(description="Manually purchase GenAIPro packages")
    parser.add_argument("--package", default="veo_100_credits", help="Package to purchase")
    parser.add_argument("--count", type=int, default=1, help="Number of packages")
    parser.add_argument("--check-only", action="store_true", help="Only check status")

    args = parser.parse_args()

    # Load cookies
    cookies = load_cookies()

    # Run
    if args.check_only:
        asyncio.run(check_status(cookies))
    else:
        asyncio.run(purchase_packages(cookies, args.package, args.count))


if __name__ == "__main__":
    main()
