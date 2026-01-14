"""Shared authentication utility for password protection across all pages."""

import streamlit as st


def check_password():
    """Returns `True` if the user had the correct password.

    This function should be called at the top of every page after set_page_config.
    If it returns False, the page should call st.stop() to prevent rendering.
    """

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if st.session_state["password"] == st.secrets.get("app_password", "changeme123"):
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    # First run, show input for password
    if "password_correct" not in st.session_state:
        st.markdown("## 🔐 VEO Video Generation - Login Required")
        st.text_input(
            "Password", type="password", on_change=password_entered, key="password"
        )
        st.info("💡 This app is password protected. Contact the administrator for access.")
        return False
    # Password not correct, show input + error
    elif not st.session_state["password_correct"]:
        st.markdown("## 🔐 VEO Video Generation - Login Required")
        st.text_input(
            "Password", type="password", on_change=password_entered, key="password"
        )
        st.error("😕 Password incorrect")
        return False
    else:
        # Password correct
        return True


def require_password():
    """Convenience function that checks password and stops page if not authenticated.

    Usage at the top of each page file (after set_page_config):
        from utils.auth import require_password
        require_password()
    """
    if not check_password():
        st.stop()
