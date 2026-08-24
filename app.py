import streamlit as st

from ui import render_league_switcher

st.set_page_config(page_title="Dynasty Dashboard", page_icon="🏈", layout="wide")

st.title("🏈 Dynasty Dashboard")
st.caption("Sensitivity Training & Queen City Kings — start/sit, free agents, trades, breakouts")

league_cfg = render_league_switcher()

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
