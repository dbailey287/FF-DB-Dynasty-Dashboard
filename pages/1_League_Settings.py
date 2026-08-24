import streamlit as st

from ui import render_league_switcher
from data.sleeper import get_league, parse_scoring_settings, get_roster_construction

st.set_page_config(page_title="League Settings", page_icon="⚙️", layout="wide")
st.title("⚙️ League Settings")

league_cfg = render_league_switcher()
st.subheader(league_cfg["display_name"])

if league_cfg["league_id"] == "REPLACE_WITH_LEAGUE_ID":
    st.error("Set a real league_id for this league in config.py, then reload.")
    st.stop()


@st.cache_data(ttl=3600)
def load_league(league_id: str):
    return get_league(league_id)


league = load_league(league_cfg["league_id"])

col1, col2 = st.columns(2)

with col1:
    st.markdown("### Roster Construction")
    construction = get_roster_construction(league)
    st.table(
        {"Slot": list(construction.keys()), "Count": list(construction.values())}
    )

with col2:
    st.markdown("### Scoring Settings (grouped)")
    grouped = parse_scoring_settings(league)

    for group_name, stats in grouped.items():
        if not stats:
            continue
        with st.expander(group_name.replace("_", " ").title(), expanded=(group_name == "idp_tackling")):
            st.table({"Stat": list(stats.keys()), "Points": list(stats.values())})

st.divider()

if league_cfg["league_type"] == "idp":
    st.markdown("### 🔍 Tackle-weight check")
    grouped = parse_scoring_settings(league)
    tackling = grouped.get("idp_tackling", {})
    coverage = grouped.get("idp_coverage", {})

    tkl_points = sum(v for k, v in tackling.items() if "tkl" in k)
    cov_points = sum(v for v in coverage.values())

    st.write(
        f"Total tackle-related point value found: **{tkl_points}** "
        f"vs. coverage/turnover-related: **{cov_points}**"
    )
    st.caption(
        "If tackle points clearly outweigh coverage/turnover points, that confirms "
        "LBs (high tackle volume) should rank above DBs (coverage-dependent, lower "
        "tackle volume) in this league's IDP rankings — the engine will use these "
        "exact weights rather than a hardcoded assumption."
    )

with st.expander("Raw scoring_settings (debug)"):
    st.json(league.get("scoring_settings", {}))
