"""
Shared Streamlit session state helpers.

All pages access the SessionStore through these helpers so the store
instance and active session ID live in st.session_state consistently.
"""

from __future__ import annotations

import streamlit as st

from pfile.session.store import SessionStore


def get_store() -> SessionStore:
    if "store" not in st.session_state:
        st.session_state["store"] = SessionStore()
    return st.session_state["store"]


def set_active(session_id: str) -> None:
    st.session_state["active_session_id"] = session_id


def get_active_id() -> str | None:
    return st.session_state.get("active_session_id")


def clear_active() -> None:
    st.session_state.pop("active_session_id", None)
