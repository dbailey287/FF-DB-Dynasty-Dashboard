import datetime

import pandas as pd
import streamlit as st

from ui import render_league_switcher
from data.sleeper import get_league
from data.nflverse import (
    get_weekly_stats,
    get_player_id_map,
    attach_sleeper_ids,
    get_team_defense_stats,
)
from engine.scoring import compute_points, compute_team_defense_points, summarize_unmapped

st.set_page_config(page_title="Scoring Engine Test", page_icon="🧮", layout="wide")
st.title("🧮 Scoring Engine Test")
st.caption(
    "Sanity-check step: apply this league's real scoring_settings to nflverse "
    "stats and confirm nothing important is falling through the cracks before "
    "we build Start/Sit rankings on top of this."
)

league_cfg = render_league_switcher()

if league_cfg["league_id"] == "REPLACE_WITH_LEAGUE_ID":
    st.error("Set a real league_id for this league in config.py, then reload.")
    st.stop()


@st.cache_data(ttl=3600)
def load_league(league_id: str):
    return get_league(league_id)


league = load_league(league_cfg["league_id"])
scoring_settings = league.get("scoring_settings", {})

# The league's own "season" field points at the upcoming/current season,
# which may not have any games played yet (no nflverse data published for
# it in that case). Default to last year instead and let the user override.
league_season = int(league.get("season", 2025))
default_season = league_season - 1 if datetime.date.today().month < 9 else league_season

col1, col2 = st.columns([1, 3])
with col1:
    season = st.number_input(
        "Season", min_value=2015, max_value=league_season, value=default_season, step=1
    )
    week = st.number_input("Week", min_value=1, max_value=18, value=1, step=1)

with st.spinner("Pulling nflverse weekly stats and Sleeper ID crosswalk..."):
    try:
        weekly = get_weekly_stats(season)
        team_defense = get_team_defense_stats(season)
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()
    id_map = get_player_id_map()
    weekly = attach_sleeper_ids(weekly, id_map)

week_stats = weekly[weekly["week"] == week].copy()
week_defense = team_defense[team_defense["week"] == week].copy()

scored, unmapped_player = compute_points(week_stats, scoring_settings)
scored_defense, unmapped_defense = compute_team_defense_points(week_defense, scoring_settings)

# A key might legitimately be handled by one path and not the other (e.g.
# pts_allow_X only makes sense for team defense) -- only flag a key as
# truly unmapped if BOTH paths failed to place it.
truly_unmapped = sorted(set(unmapped_player) & set(unmapped_defense))

if truly_unmapped:
    st.warning(
        f"{len(truly_unmapped)} scoring_settings key(s) carry point value but "
        "aren't mapped anywhere yet -- points from these are NOT included "
        "below. Send these over so the mapping can be extended:"
    )
    st.table(summarize_unmapped(scoring_settings, truly_unmapped))
else:
    st.success("Every scoring_settings key with a non-zero value is mapped somewhere.")

with st.expander(
    f"Individual-player-only keys not used here ({len(unmapped_player) - len(truly_unmapped)}) "
    "-- expected, these are team-DEF-only keys like pts_allow_X"
):
    st.table(summarize_unmapped(scoring_settings, sorted(set(unmapped_player) - set(truly_unmapped))))

st.divider()

tab1, tab2 = st.tabs(["Individual players", "Team defense (DEF/D-ST)"])

with tab1:
    position_filter = st.multiselect(
        "Positions",
        options=sorted(scored["position"].dropna().unique().tolist()),
        default=["LB", "DB"] if league_cfg["league_type"] == "idp" else ["QB", "RB", "WR", "TE"],
    )

    display_cols = [
        "player_display_name",
        "position",
        "team",
        "opponent_team",
        "league_points",
    ]

    filtered = scored[scored["position"].isin(position_filter)]
    top = filtered.sort_values("league_points", ascending=False).head(25)

    st.markdown(f"### Top scorers — Week {week} ({', '.join(position_filter)})")
    st.dataframe(top[display_cols].reset_index(drop=True), use_container_width=True)

with tab2:
    st.markdown(f"### Team defense scoring — Week {week}")
    defense_cols = ["team", "opponent_team", "points_allowed", "def_sacks", "def_interceptions", "league_points"]
    top_defense = scored_defense.sort_values("league_points", ascending=False)
    st.dataframe(top_defense[defense_cols].reset_index(drop=True), use_container_width=True)

with st.expander("Raw scoring_settings (for reference)"):
    st.json(scoring_settings)
