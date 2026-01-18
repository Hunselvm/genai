"""
Auto Top-Up Integration for Streamlit
======================================

Simple utility to auto-purchase VEO credits when quota is low.
Can be easily disabled or replaced in the future.
"""

import asyncio
import os
import streamlit as st
from typing import Tuple, Optional
from pathlib import Path
from dotenv import load_dotenv


def is_enabled() -> bool:
    """Check if auto top-up is enabled. Easy on/off switch."""
    # Set to False to disable auto top-up globally
    return os.getenv("AUTO_TOPUP_ENABLED", "true").lower() == "true"


def get_threshold() -> int:
    """Get the quota threshold for auto-purchase."""
    return int(os.getenv("AUTO_TOPUP_THRESHOLD", "5"))


@st.cache_data(ttl=300)  # Cache for 5 minutes
def check_and_topup() -> Tuple[bool, str]:
    """
    Check quota and auto top-up if needed.

    Returns:
        (success: bool, message: str)

    Usage in Streamlit pages:
        success, msg = check_and_topup()
        if not success:
            st.warning(msg)
    """
    if not is_enabled():
        return True, "Auto top-up disabled"

    try:
        # Import here to avoid circular dependencies
        from .genaipro_auto_topup import GenAIProTopUp

        # Load cookies
        env_file = Path(__file__).parent.parent / ".env.genaipro"
        if env_file.exists():
            load_dotenv(env_file)

        cookies = {
            "__session": os.getenv("GENAIPRO_SESSION"),
            "__session_id": os.getenv("GENAIPRO_SESSION_ID"),
            "__genaipro_session": os.getenv("GENAIPRO_APP_SESSION"),
            "__client_uat": os.getenv("GENAIPRO_CLIENT_UAT"),
        }

        if not all(cookies.values()):
            return True, "Auto top-up: cookies not configured (skipping)"

        # Async check and purchase
        async def _check():
            async with GenAIProTopUp(cookies, debug=False) as client:
                threshold = get_threshold()
                purchased, msg = await client.auto_topup(threshold=threshold)
                return purchased, msg

        purchased, msg = asyncio.run(_check())
        return True, msg

    except Exception as e:
        # Don't fail the whole page if auto top-up fails
        return True, f"Auto top-up check failed (continuing anyway): {str(e)}"


# Optional: Silent version (no return value, just runs in background)
def silent_check():
    """Run auto top-up check silently without blocking UI."""
    if is_enabled():
        try:
            check_and_topup()
        except:
            pass  # Fail silently


def will_trigger_topup(credits_needed: int) -> Tuple[bool, Optional[dict]]:
    """
    Check if a batch operation will trigger auto top-up.

    Args:
        credits_needed: Number of credits the operation will use

    Returns:
        (will_trigger: bool, quota_info: dict or None)
        quota_info contains: available, total, balance_usd

    Usage:
        will_trigger, info = will_trigger_topup(50)  # For 50 videos
        if will_trigger:
            st.warning(f"⚠️ This will trigger auto top-up ($1.50)")
    """
    if not is_enabled():
        return False, None

    try:
        from .genaipro_auto_topup import GenAIProTopUp

        env_file = Path(__file__).parent.parent / ".env.genaipro"
        if env_file.exists():
            load_dotenv(env_file)

        cookies = {
            "__session": os.getenv("GENAIPRO_SESSION"),
            "__session_id": os.getenv("GENAIPRO_SESSION_ID"),
            "__genaipro_session": os.getenv("GENAIPRO_APP_SESSION"),
            "__client_uat": os.getenv("GENAIPRO_CLIENT_UAT"),
        }

        if not all(cookies.values()):
            return False, None

        async def _check():
            async with GenAIProTopUp(cookies, debug=False) as client:
                quota = await client.get_veo_quota()
                user = await client.get_user_info()

                available = quota.get("available_quota", 0)
                total = quota.get("total_quota", 0)
                balance_usd = user["balance"] / 25000.0

                quota_info = {
                    "available": available,
                    "total": total,
                    "balance_usd": balance_usd,
                    "after_operation": available - credits_needed
                }

                threshold = get_threshold()
                will_trigger = (available - credits_needed) < threshold

                return will_trigger, quota_info

        will_trigger, quota_info = asyncio.run(_check())
        return will_trigger, quota_info

    except Exception:
        return False, None


def show_topup_warning(credits_needed: int):
    """
    Show Streamlit warning if operation will trigger auto top-up.

    Args:
        credits_needed: Number of credits the operation will use

    Usage (in Streamlit page):
        # Before batch operation
        show_topup_warning(number_of_videos)
    """
    will_trigger, info = will_trigger_topup(credits_needed)

    if will_trigger and info:
        st.warning(
            f"⚠️ **Auto Top-Up Alert**\n\n"
            f"This operation will use **{credits_needed} credits**.\n\n"
            f"Current quota: **{info['available']}/{info['total']}**\n\n"
            f"After operation: **{info['after_operation']}** (below threshold of {get_threshold()})\n\n"
            f"💳 This will trigger **automatic purchase** of 100 credits for **$1.50**\n\n"
            f"Current balance: **${info['balance_usd']:.2f}**"
        )
    elif info:
        st.info(
            f"ℹ️ This operation will use **{credits_needed}** credits. "
            f"Current quota: **{info['available']}/{info['total']}** "
            f"(sufficient, no top-up needed)"
        )
