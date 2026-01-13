"""Reusable quota display component for all pages."""

import streamlit as st
import asyncio
from utils.veo_client import VEOClient


def display_quota():
    """Display quota information with refresh button."""
    if st.session_state.get('quota_info'):
        quota = st.session_state.quota_info
        available = quota.get('available_quota', 0)
        total = quota.get('total_quota', 0)
        
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            if available == 0:
                st.error(f"⚠️ **Quota Exhausted!** You have 0 credits remaining.")
            elif available < 5:
                st.warning(f"⚠️ **Low Quota:** {available}/{total} credits remaining")
            else:
                st.info(f"📊 **Quota:** {available}/{total} credits available")
        with col2:
            if st.button("🔄 Refresh Quota"):
                try:
                    if not st.session_state.get('api_key'):
                        st.error("Please enter API key first")
                        return
                    
                    client = VEOClient(
                        api_key=st.session_state.api_key,
                        base_url="https://genaipro.vn/api/v1"
                    )
                    quota = asyncio.run(client.get_quota())
                    st.session_state.quota_info = quota
                    asyncio.run(client.close())
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to refresh: {str(e)}")
        
        st.divider()
    else:
        # Suggest checking quota
        if st.session_state.get('api_key'):
            st.info("💡 Click 'Check Quota' in the sidebar to see your available credits")
            st.divider()
