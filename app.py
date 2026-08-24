import streamlit as st

from config import LEAGUES

st.set_page_config(page_title="Dynasty Dashboard", page_icon="🏈", layout="wide")

st.title("🏈 Dynasty Dashboard")
st.caption("Sensitivity Training & Queen City Kings — start/sit, free agents, trades, breakouts")

# League switcher lives in session_state so every page can read it
if "active_league_key" not in st.session_state:
    st.session_state["active_league_key"] = list(LEAGUES.keys())[0]

league_key = st.selectbox(
    "Active league",
    options=list(LEAGUES.keys()),
    format_func=lambda k: LEAGUES[k]["display_name"],
    key="active_league_key",
)

league_cfg = LEAGUES[league_key]

st.markdown(
    f"""
    **Selected:** {league_cfg['display_name']}
    **Type:** {"IDP (LB/DB-heavy)" if league_cfg['league_type'] == 'idp' else "Offense only, 1 PPR"}
    """
)

if league_cfg["league_id"] == "REPLACE_WITH_LEAGUE_ID":
    st.warning(
        "This league's ID hasn't been set yet in config.py. "
        "Add the real Sleeper league ID to see live data."
    )
else:
    st.success("League ID configured — head to **League Settings** in the sidebar to confirm scoring.")

st.divider()
st.markdown(
    """
    #### Pages
    - **League Settings** — pulls live scoring & roster construction from Sleeper to confirm how each league actually scores
    - *(Start/Sit, Free Agents, Breakouts, Trade Finder — coming next)*
    """
)
