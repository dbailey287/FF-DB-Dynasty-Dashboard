"""
Shared UI helper so every page (not just app.py) can switch leagues.
Call render_league_switcher() near the top of each page.
"""

import streamlit as st

from config import LEAGUES


def render_league_switcher() -> dict:
    """
    Renders a league selector in the sidebar. Persists the choice in
    session_state under 'active_league_key' so it's shared across pages.
    Returns the active league's config dict.
    """
    if "active_league_key" not in st.session_state:
        st.session_state["active_league_key"] = list(LEAGUES.keys())[0]

    with st.sidebar:
        st.selectbox(
            "Active league",
            options=list(LEAGUES.keys()),
            format_func=lambda k: LEAGUES[k]["display_name"],
            key="active_league_key",
        )

    return LEAGUES[st.session_state["active_league_key"]]
