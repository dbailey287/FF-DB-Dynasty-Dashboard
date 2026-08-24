import datetime

import pandas as pd
import streamlit as st

from config import SLEEPER_USERNAME
from ui import render_league_switcher
from data.sleeper import get_league, get_my_roster, get_all_players
from data.nflverse import (
    get_weekly_stats,
    get_player_id_map,
    attach_sleeper_ids,
    get_team_defense_stats,
)
from engine.scoring import compute_points, compute_team_defense_points
from engine.rankings import (
    build_player_lookup,
    compute_trailing_player_scores,
    compute_trailing_defense_scores,
    rank_roster,
)

st.set_page_config(page_title="Start/Sit", page_icon="🏈", layout="wide")
st.title("🏈 Start/Sit")
st.caption(
    "Your roster, ranked by trailing average fantasy points under this "
    "league's real scoring settings."
)

league_cfg = render_league_switcher()

if league_cfg["league_id"] == "REPLACE_WITH_LEAGUE_ID":
    st.error("Set a real league_id for this league in config.py, then reload.")
    st.stop()


@st.cache_data(ttl=3600)
def load_league(league_id: str):
    return get_league(league_id)


@st.cache_data(ttl=3600)
def load_my_roster(league_id: str, username: str):
    return get_my_roster(league_id, username)


league = load_league(league_cfg["league_id"])
scoring_settings = league.get("scoring_settings", {})

roster = load_my_roster(league_cfg["league_id"], SLEEPER_USERNAME)
if roster is None:
    st.error(
        f"Couldn't find a roster owned by Sleeper username '{SLEEPER_USERNAME}' "
        "in this league. Double check config.SLEEPER_USERNAME."
    )
    st.stop()

league_season = int(league.get("season", 2025))
default_season = league_season - 1 if datetime.date.today().month < 9 else league_season

col1, col2 = st.columns([1, 3])
with col1:
    season = st.number_input(
        "Season", min_value=2015, max_value=league_season, value=default_season, step=1
    )
    through_week = st.number_input("Through week", min_value=1, max_value=18, value=3, step=1)
    trailing_n = st.number_input("Trailing weeks to average", min_value=1, max_value=10, value=3, step=1)

weeks = list(range(max(1, through_week - trailing_n + 1), through_week + 1))
st.caption(f"Averaging weeks {weeks[0]}–{weeks[-1]} of {season}")

with st.spinner("Pulling stats and scoring your roster..."):
    try:
        weekly = get_weekly_stats(season)
        team_defense = get_team_defense_stats(season)
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()

    id_map = get_player_id_map()
    weekly = attach_sleeper_ids(weekly, id_map)

    scored_weekly, _ = compute_points(weekly, scoring_settings)
    scored_defense, _ = compute_team_defense_points(team_defense, scoring_settings)

    all_players = get_all_players()
    player_lookup = build_player_lookup(all_players)

    player_trailing = compute_trailing_player_scores(scored_weekly, weeks)
    defense_trailing = compute_trailing_defense_scores(scored_defense, weeks)

    ranked = rank_roster(roster, player_lookup, player_trailing, defense_trailing)

if ranked.empty:
    st.warning("No players found on this roster.")
    st.stop()

st.divider()

starters_tab, full_roster_tab = st.tabs(["Starting lineup", "Full roster"])

with starters_tab:
    starters = ranked[ranked["starter"]].sort_values("avg_points", ascending=False)
    st.markdown("### Current starters, ranked by trailing average")
    st.dataframe(
        starters[["name", "position", "team", "avg_points", "games_sampled"]].reset_index(drop=True),
        use_container_width=True,
    )

with full_roster_tab:
    positions = sorted(ranked["position"].dropna().unique().tolist())
    position_filter = st.multiselect("Positions", options=positions, default=positions)
    filtered = ranked[ranked["position"].isin(position_filter)]

    st.markdown("### Full roster by position")
    st.dataframe(
        filtered[["name", "position", "team", "avg_points", "games_sampled", "starter"]].reset_index(
            drop=True
        ),
        use_container_width=True,
    )
    st.caption(
        "Within each position, bench players ranked above a starter suggest "
        "a lineup change worth considering -- weighed against matchup, "
        "injury status, and bye weeks, which this view doesn't account for yet."
    )
