#!/usr/bin/env python3
"""
GenAIPro Quota Monitor
======================

Continuously monitors VEO quota and automatically purchases packages when needed.

Usage:
    python scripts/monitor_quota.py [--threshold 20] [--interval 3600]

Options:
    --threshold INT    Minimum quota before auto-purchase (default: 20)
    --interval INT     Seconds between checks (default: 3600 = 1 hour)
    --dry-run         Check quota but don't purchase
    --once            Run once and exit (don't loop)
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
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('genaipro_monitor.log')
    ]
)
logger = logging.getLogger(__name__)


def load_cookies() -> dict:
    """Load cookies from environment."""

    # Try to load from .env.genaipro first
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


async def check_once(cookies: dict, threshold: int, dry_run: bool = False):
    """Check quota once and optionally purchase."""

    async with GenAIProTopUp(cookies, debug=False) as client:
        try:
            # Get current status
            quota = await client.get_veo_quota()
            user = await client.get_user_info()

            available = quota.get("available_quota", 0)
            total = quota.get("total_quota", 0)
            balance_usd = user["balance"] / 25000.0

            logger.info(f"📊 Status: Quota={available}/{total}, Balance=${balance_usd:.2f}")

            # Check if we need to top up
            if available >= threshold:
                logger.info(f"✅ Quota sufficient ({available} >= {threshold})")
                return False

            logger.warning(f"⚠️  Low quota! {available} < {threshold}")

            if dry_run:
                logger.info("🔍 Dry run mode - skipping purchase")
                return False

            # Auto purchase
            purchased, msg = await client.auto_topup(threshold=threshold)

            if purchased:
                logger.info(f"📦 {msg}")
                return True
            else:
                logger.warning(f"⚠️  {msg}")
                return False

        except Exception as e:
            logger.error(f"❌ Error: {e}", exc_info=True)
            return False


async def monitor_loop(cookies: dict, threshold: int, interval: int, dry_run: bool = False):
    """Monitor quota in a loop."""

    logger.info("🚀 Starting quota monitoring...")
    logger.info(f"   Threshold: {threshold} credits")
    logger.info(f"   Check interval: {interval}s ({interval/3600:.1f}h)")
    logger.info(f"   Dry run: {dry_run}")

    while True:
        try:
            await check_once(cookies, threshold, dry_run)

            # Wait before next check
            logger.info(f"⏱️  Next check in {interval}s...")
            await asyncio.sleep(interval)

        except KeyboardInterrupt:
            logger.info("⏹️  Monitoring stopped by user")
            break
        except Exception as e:
            logger.error(f"❌ Loop error: {e}", exc_info=True)
            await asyncio.sleep(60)  # Short wait before retry


def main():
    """Main entry point."""

    parser = argparse.ArgumentParser(description="Monitor GenAIPro VEO quota")
    parser.add_argument("--threshold", type=int, default=20, help="Minimum quota before auto-purchase")
    parser.add_argument("--interval", type=int, default=3600, help="Seconds between checks")
    parser.add_argument("--dry-run", action="store_true", help="Check quota but don't purchase")
    parser.add_argument("--once", action="store_true", help="Run once and exit")

    args = parser.parse_args()

    # Load cookies
    cookies = load_cookies()

    # Run
    if args.once:
        asyncio.run(check_once(cookies, args.threshold, args.dry_run))
    else:
        asyncio.run(monitor_loop(cookies, args.threshold, args.interval, args.dry_run))


if __name__ == "__main__":
    main()
