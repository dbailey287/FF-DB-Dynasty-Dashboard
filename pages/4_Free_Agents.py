import datetime

import pandas as pd
import streamlit as st

from config import SLEEPER_USERNAME
from ui import render_league_switcher
from data.sleeper import get_league, get_my_roster, get_all_players, get_free_agents
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
    rank_free_agents,
    find_upgrades,
)

st.set_page_config(page_title="Free Agents", page_icon="🔍", layout="wide")
st.title("🔍 Free Agents")
st.caption(
    "Everyone available in this league, ranked by the same trailing-average "
    "scoring as Start/Sit, with upgrades over your weakest rostered players "
    "flagged automatically."
)

league_cfg = render_league_switcher()

if league_cfg["league_id"] == "REPLACE_WITH_LEAGUE_ID":
    st.error("Set a real league_id for this league in config.py, then reload.")
    st.stop()


@st.cache_data(ttl=3600)
def load_league(league_id: str):
    return get_league(league_id)


@st.cache_data(ttl=1800)  # shorter TTL -- rosters/free agents change during the week
def load_my_roster(league_id: str, username: str):
    return get_my_roster(league_id, username)


@st.cache_data(ttl=1800)
def load_free_agents(league_id: str, _all_players: dict):
    return get_free_agents(league_id, _all_players)


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
    min_games = st.number_input(
        "Min games played (filters small samples)", min_value=1, max_value=10, value=2, step=1
    )

weeks = list(range(max(1, through_week - trailing_n + 1), through_week + 1))
st.caption(f"Averaging weeks {weeks[0]}–{weeks[-1]} of {season}")

with st.spinner("Pulling stats and scoring free agents..."):
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
    free_agents = load_free_agents(league_cfg["league_id"], all_players)

    player_trailing = compute_trailing_player_scores(scored_weekly, weeks)
    defense_trailing = compute_trailing_defense_scores(scored_defense, weeks)

    my_roster_ranked = rank_roster(roster, player_lookup, player_trailing, defense_trailing)
    fa_ranked = rank_free_agents(free_agents, player_lookup, player_trailing, defense_trailing, min_games)
    upgrades, skipped_positions = find_upgrades(my_roster_ranked, fa_ranked, min_games)

st.divider()

upgrades_tab, browse_tab = st.tabs(["🚀 Suggested upgrades", "Browse free agents"])

with upgrades_tab:
    if skipped_positions:
        st.warning(
            f"Skipped comparing at: {', '.join(sorted(set(skipped_positions)))} -- "
            f"every rostered player there has fewer than {min_games} games in this "
            "window (injured/IR, bye, or just acquired), so there's no meaningful "
            "'worst performer' to compare free agents against. A 0.0 average from "
            "zero games isn't a real performance floor."
        )

    if upgrades.empty:
        st.info(
            "No free agent currently beats your worst *eligible* rostered player "
            "at any position in this window -- try a different trailing window, "
            "or your bench depth may just be solid right now."
        )
    else:
        st.markdown(
            "### Free agents outscoring your weakest rostered player at their position"
        )
        st.caption(
            "Compared against your worst rostered player per position (not your "
            "best) -- most real value is in replacing weak depth, not unseating "
            "a clear starter."
        )
        st.dataframe(upgrades, use_container_width=True)

with browse_tab:
    if fa_ranked.empty:
        st.warning("No free agents found matching the current filters.")
    else:
        positions = sorted(fa_ranked["position"].dropna().unique().tolist())
        default_positions = (
            ["LB", "DB"] if league_cfg["league_type"] == "idp" else ["QB", "RB", "WR", "TE"]
        )
        position_filter = st.multiselect(
            "Positions", options=positions, default=[p for p in default_positions if p in positions]
        )
        filtered = fa_ranked[fa_ranked["position"].isin(position_filter)]
        top = filtered.sort_values("avg_points", ascending=False).head(30)

        st.markdown(f"### Top free agents — {', '.join(position_filter)}")
        st.dataframe(
            top[["name", "position", "team", "avg_points", "games_sampled"]].reset_index(drop=True),
            use_container_width=True,
        )
