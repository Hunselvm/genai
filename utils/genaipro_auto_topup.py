"""
GenAIPro Auto Top-Up System
============================

This module provides automated quota monitoring and package purchasing for GenAIPro VEO API.

⚠️ IMPORTANT: This is reverse-engineered and not officially supported by GenAIPro.
Use at your own risk. Your account may be banned if they detect automated purchases.

Authentication:
- GenAIPro uses Clerk.com for authentication with JWT tokens
- Requires browser cookies: __session, __session_id, __genaipro_session, __client_uat
- Cookies expire after ~7 days

Usage:
    1. Extract cookies from browser (see get_cookies_from_browser.py)
    2. Set cookies in environment or pass to functions
    3. Run monitor or purchase functions
"""

import httpx
import asyncio
import json
import os
from typing import Dict, Optional, Tuple
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class GenAIProTopUp:
    """Handles automated quota monitoring and package purchasing for GenAIPro."""

    # Base URLs
    BASE_URL = "https://genaipro.vn/api"

    # Package IDs (reverse engineered from network traffic)
    PACKAGES = {
        "veo_100_credits": {
            "id": "33f4871f-efe0-11f0-9608-ce156e002a4d",
            "name": "100 Veo & Banana API",
            "price_usd": 1.50,
            "credits": 100,
            "duration_days": 3
        }
    }

    def __init__(self, cookies: Dict[str, str], debug: bool = False):
        """
        Initialize the GenAIPro auto top-up client.

        Args:
            cookies: Dictionary with required cookies:
                - __session
                - __session_id
                - __genaipro_session
                - __client_uat
            debug: Enable debug logging
        """
        self.cookies = cookies
        self.debug = debug

        # Validate required cookies
        required = ["__session", "__session_id", "__genaipro_session", "__client_uat"]
        missing = [c for c in required if c not in cookies]
        if missing:
            raise ValueError(f"Missing required cookies: {missing}")

        # Create HTTP client
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "application/json",
                "Referer": "https://genaipro.vn/",
            }
        )

        if debug:
            logger.setLevel(logging.DEBUG)

    async def get_user_info(self) -> Dict:
        """
        Get current user information including balance and VEO quota.

        Returns:
            Dict with user info:
                - balance: Balance in 1/25000 USD units (e.g., 87500 = $3.50)
                - veo_account_id: VEO account UUID
                - veo_subscription_end_date: Expiration date
                - email, username, etc.

        Raises:
            httpx.HTTPStatusError: If request fails
        """
        url = f"{self.BASE_URL}/users/me"

        response = await self.client.get(url, cookies=self.cookies)
        response.raise_for_status()

        data = response.json()

        if self.debug:
            logger.debug(f"User info: {json.dumps(data, indent=2)}")

        return data

    async def get_veo_quota(self) -> Dict:
        """
        Get VEO quota information via the VEO API.

        Note: This uses your VEO_API_KEY from environment, not cookies.

        Returns:
            Dict with quota info:
                - total_quota: Total quota
                - used_quota: Used quota
                - available_quota: Remaining quota
        """
        api_key = os.getenv("VEO_API_KEY")
        if not api_key:
            raise ValueError("VEO_API_KEY not set in environment")

        url = "https://genaipro.vn/api/v1/veo/me"
        headers = {"Authorization": f"Bearer {api_key}"}

        response = await self.client.get(url, headers=headers)
        response.raise_for_status()

        return response.json()

    async def purchase_package(self, package_id: str) -> Dict:
        """
        Purchase a VEO credits package.

        Args:
            package_id: Package UUID (use PACKAGES constant)

        Returns:
            Dict with purchase result:
                - message: Success message

        Raises:
            httpx.HTTPStatusError: If purchase fails (e.g., insufficient balance)
        """
        url = f"{self.BASE_URL}/subscriptions/subscribe/veo-credits/{package_id}"

        if self.debug:
            logger.debug(f"Purchasing package: {package_id}")

        response = await self.client.post(url, cookies=self.cookies)
        response.raise_for_status()

        data = response.json()

        if self.debug:
            logger.debug(f"Purchase result: {json.dumps(data, indent=2)}")

        return data

    async def auto_topup(
        self,
        threshold: int = 20,
        package_key: str = "veo_100_credits"
    ) -> Tuple[bool, str]:
        """
        Automatically purchase a package if quota is below threshold.

        Args:
            threshold: Minimum quota before triggering purchase
            package_key: Package to purchase (key from PACKAGES)

        Returns:
            Tuple of (purchased: bool, message: str)
        """
        try:
            # Check current quota
            quota_info = await self.get_veo_quota()
            available = quota_info.get("available_quota", 0)

            logger.info(f"Current quota: {available}/{quota_info.get('total_quota')}")

            # Check if we need to top up
            if available >= threshold:
                return False, f"Quota sufficient: {available} >= {threshold}"

            # Check balance
            user_info = await self.get_user_info()
            balance_cents = user_info.get("balance", 0)
            balance_usd = balance_cents / 25000.0

            package = self.PACKAGES[package_key]

            if balance_usd < package["price_usd"]:
                msg = f"Insufficient balance: ${balance_usd:.2f} < ${package['price_usd']}"
                logger.warning(msg)
                return False, msg

            # Purchase package
            logger.info(f"Purchasing {package['name']} for ${package['price_usd']}")
            result = await self.purchase_package(package["id"])

            msg = f"✅ Purchased {package['name']}: {result.get('message')}"
            logger.info(msg)

            return True, msg

        except Exception as e:
            msg = f"❌ Auto top-up failed: {str(e)}"
            logger.error(msg, exc_info=True)
            return False, msg

    async def monitor_and_topup(
        self,
        threshold: int = 20,
        check_interval: int = 3600,
        package_key: str = "veo_100_credits"
    ):
        """
        Continuously monitor quota and auto-purchase when needed.

        Args:
            threshold: Minimum quota before triggering purchase
            check_interval: Seconds between checks (default: 1 hour)
            package_key: Package to purchase
        """
        logger.info(f"Starting quota monitoring (threshold={threshold}, interval={check_interval}s)")

        while True:
            try:
                purchased, message = await self.auto_topup(threshold, package_key)

                if purchased:
                    logger.info(f"📦 {message}")
                    # Wait longer after purchase to let quota update
                    await asyncio.sleep(60)

                # Wait before next check
                await asyncio.sleep(check_interval)

            except KeyboardInterrupt:
                logger.info("Monitoring stopped by user")
                break
            except Exception as e:
                logger.error(f"Monitoring error: {e}", exc_info=True)
                await asyncio.sleep(60)  # Short wait before retry

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


# Helper functions

async def check_quota_and_alert(cookies: Dict[str, str]) -> Dict:
    """
    Check current quota and return status info.

    Args:
        cookies: Browser cookies dict

    Returns:
        Dict with quota status
    """
    async with GenAIProTopUp(cookies) as client:
        quota = await client.get_veo_quota()
        user = await client.get_user_info()

        return {
            "quota": quota,
            "balance_usd": user["balance"] / 25000.0,
            "timestamp": datetime.now().isoformat()
        }


async def purchase_single_package(cookies: Dict[str, str], package_key: str = "veo_100_credits") -> Dict:
    """
    Purchase a single package.

    Args:
        cookies: Browser cookies dict
        package_key: Package to purchase

    Returns:
        Purchase result dict
    """
    async with GenAIProTopUp(cookies) as client:
        package = GenAIProTopUp.PACKAGES[package_key]
        result = await client.purchase_package(package["id"])
        return result


# Example usage
if __name__ == "__main__":
    import sys

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Load cookies from environment
    cookies = {
        "__session": os.getenv("GENAIPRO_SESSION"),
        "__session_id": os.getenv("GENAIPRO_SESSION_ID"),
        "__genaipro_session": os.getenv("GENAIPRO_APP_SESSION"),
        "__client_uat": os.getenv("GENAIPRO_CLIENT_UAT"),
    }

    if not all(cookies.values()):
        print("❌ Missing required cookies in environment variables:")
        print("   GENAIPRO_SESSION, GENAIPRO_SESSION_ID, GENAIPRO_APP_SESSION, GENAIPRO_CLIENT_UAT")
        sys.exit(1)

    async def main():
        async with GenAIProTopUp(cookies, debug=True) as client:
            # Check current status
            print("\n📊 Checking current status...")
            quota = await client.get_veo_quota()
            user = await client.get_user_info()

            print(f"   Balance: ${user['balance']/100.0:.2f}")
            print(f"   VEO Quota: {quota['available_quota']}/{quota['total_quota']}")

            # Auto top-up once
            print("\n🔄 Running auto top-up check...")
            purchased, msg = await client.auto_topup(threshold=20)
            print(f"   {msg}")

    asyncio.run(main())
