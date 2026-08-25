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
    get_injury_reports,
    get_latest_injury_status,
    get_weekly_roster_status,
    get_availability_reasons,
)
from engine.scoring import compute_points, compute_team_defense_points
from engine.rankings import (
    build_player_lookup,
    compute_recency_weighted_player_scores,
    compute_recency_weighted_defense_scores,
    rank_roster,
)

st.set_page_config(page_title="Start/Sit", page_icon="🏈", layout="wide")
st.title("🏈 Start/Sit")
st.caption(
    "Your roster, ranked by recency-weighted fantasy points under this "
    "league's real scoring settings -- every game played this season "
    "contributes, weighted toward recent form, with no fixed window to "
    "accidentally miss."
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

# Capped at 18 (real end of regular season) -- the raw max week in the data
# can reach into the low-20s for playoff weeks that only apply to a
# handful of teams, which would badly skew recency decay for everyone else.
try:
    _default_season_weekly = get_weekly_stats(default_season)
    default_as_of_week = min(int(_default_season_weekly["week"].max()), 18)
except Exception:
    default_as_of_week = 18

col1, col2 = st.columns([1, 3])
with col1:
    season = st.number_input(
        "Season", min_value=2015, max_value=league_season, value=default_season, step=1
    )
    as_of_week = st.number_input(
        "As of week", min_value=1, max_value=18, value=default_as_of_week, step=1
    )
    half_life_weeks = st.slider(
        "Recency half-life (weeks)", min_value=1.0, max_value=8.0, value=3.0, step=0.5,
        help="A game this many weeks back counts half as much as the most "
             "recent one. Lower = more reactive to recent form.",
    )

st.caption(
    f"Weighting every game played through week {as_of_week} of {season}, "
    f"with a {half_life_weeks}-week recency half-life."
)

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

    injuries = get_injury_reports(season)
    injury_lookup = get_latest_injury_status(injuries, id_map, as_of_week)
    roster_status = get_weekly_roster_status(season)
    availability_lookup = get_availability_reasons(roster_status, injury_lookup, as_of_week)

    all_players = get_all_players()
    player_lookup = build_player_lookup(all_players)

    player_weighted = compute_recency_weighted_player_scores(scored_weekly, as_of_week, half_life_weeks)
    defense_weighted = compute_recency_weighted_defense_scores(scored_defense, as_of_week, half_life_weeks)

    ranked = rank_roster(roster, player_lookup, player_weighted, defense_weighted, availability_lookup)

if ranked.empty:
    st.warning("No players found on this roster.")
    st.stop()

st.divider()

starters_tab, full_roster_tab = st.tabs(["Starting lineup", "Full roster"])

with starters_tab:
    starters = ranked[ranked["starter"]].sort_values("avg_points", ascending=False)
    st.markdown("### Current starters, ranked by recency-weighted average")
    st.dataframe(
        starters[
            ["name", "position", "team", "avg_points", "games_sampled", "status"]
        ].reset_index(drop=True),
        use_container_width=True,
    )

with full_roster_tab:
    positions = sorted(ranked["position"].dropna().unique().tolist())
    position_filter = st.multiselect("Positions", options=positions, default=positions)
    filtered = ranked[ranked["position"].isin(position_filter)]

    st.markdown("### Full roster by position")
    st.dataframe(
        filtered[
            ["name", "position", "team", "avg_points", "games_sampled", "starter", "status"]
        ].reset_index(drop=True),
        use_container_width=True,
    )
    st.caption(
        "Within each position, bench players ranked above a starter suggest "
        "a lineup change worth considering. A low avg_points with a status "
        "shown means absence (injury, IR, inactive) -- not poor performance. "
        "A blank status with low avg_points means healthy but just not "
        "getting playing time, which is a different kind of problem."
    )
