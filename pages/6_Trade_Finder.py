import datetime

import pandas as pd
import streamlit as st

from config import SLEEPER_USERNAME
from ui import render_league_switcher
from data.sleeper import get_league, get_rosters, get_users, get_all_players, get_my_roster
from data.fantasycalc import get_dynasty_values, infer_fantasycalc_params
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
    compute_trailing_player_scores,
    compute_trailing_defense_scores,
)
from engine.trades import (
    build_team_rosters_with_values,
    build_league_performance_table,
    get_position_slot_counts,
    find_trade_suggestions,
    annotate_starter_impact,
)

st.set_page_config(page_title="Trade Finder", page_icon="🔄", layout="wide")
st.title("🔄 Trade Finder")
st.caption(
    "Dynasty trade value from FantasyCalc, matched against every team in "
    "the league at once, with real starter-lineup impact -- not just "
    "value math -- using the same trailing performance + injury/availability "
    "data as Start/Sit and Free Agents."
)
st.info(
    "This page pulls live from FantasyCalc's API. If it fails to load, "
    "FantasyCalc's service may be temporarily unavailable -- try again shortly.",
    icon="ℹ️",
)

league_cfg = render_league_switcher()

if league_cfg["league_id"] == "REPLACE_WITH_LEAGUE_ID":
    st.error("Set a real league_id for this league in config.py, then reload.")
    st.stop()


@st.cache_data(ttl=3600)
def load_league(league_id: str):
    return get_league(league_id)


@st.cache_data(ttl=1800)
def load_league_context(league_id: str):
    rosters = get_rosters(league_id)
    users = get_users(league_id)
    return rosters, users


@st.cache_data(ttl=3600)
def load_dynasty_values(num_qbs: int, num_teams: int, ppr: float):
    return get_dynasty_values(num_qbs=num_qbs, num_teams=num_teams, ppr=ppr)


league = load_league(league_cfg["league_id"])
my_roster = get_my_roster(league_cfg["league_id"], SLEEPER_USERNAME)
if my_roster is None:
    st.error(
        f"Couldn't find a roster owned by Sleeper username '{SLEEPER_USERNAME}' "
        "in this league. Double check config.SLEEPER_USERNAME."
    )
    st.stop()

fc_params = infer_fantasycalc_params(league)
league_season = int(league.get("season", 2025))
default_season = league_season - 1 if datetime.date.today().month < 9 else league_season

st.caption(
    f"FantasyCalc values for: {'Superflex' if fc_params['numQbs'] == 2 else '1QB'}, "
    f"{fc_params['numTeams']}-team, {fc_params['ppr']} PPR (inferred from this league)."
)

col1, col2, col3, col4 = st.columns(4)
with col1:
    season = st.number_input(
        "Season", min_value=2015, max_value=league_season, value=default_season, step=1
    )
    through_week = st.number_input("Through week", min_value=1, max_value=18, value=3, step=1)
with col2:
    trailing_n = st.number_input("Trailing weeks", min_value=1, max_value=10, value=3, step=1)
    max_package_size = st.number_input("Max players/side", min_value=1, max_value=3, value=2, step=1)
with col3:
    fairness_tolerance_pct = st.slider("Fair tolerance (%)", min_value=5, max_value=30, value=15, step=5)
with col4:
    favor_me_max_pct = st.slider("Max favor-me tilt (%)", min_value=10, max_value=60, value=35, step=5)

weeks = list(range(max(1, through_week - trailing_n + 1), through_week + 1))

with st.spinner("Pulling values, rosters, and performance data..."):
    try:
        dynasty_values = load_dynasty_values(fc_params["numQbs"], fc_params["numTeams"], fc_params["ppr"])
    except Exception as e:
        st.error(
            f"Couldn't load dynasty values from FantasyCalc: {e}. "
            "This depends on an external service that isn't guaranteed to "
            "always be up -- try reloading in a bit."
        )
        st.stop()

    try:
        weekly = get_weekly_stats(season)
        team_defense = get_team_defense_stats(season)
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()

    id_map = get_player_id_map()
    weekly = attach_sleeper_ids(weekly, id_map)

    scored_weekly, _ = compute_points(weekly, league.get("scoring_settings", {}))
    scored_defense, _ = compute_team_defense_points(team_defense, league.get("scoring_settings", {}))

    injuries = get_injury_reports(season)
    injury_lookup = get_latest_injury_status(injuries, id_map, through_week)
    roster_status = get_weekly_roster_status(season)
    availability_lookup = get_availability_reasons(roster_status, injury_lookup, through_week)

    all_players = get_all_players()
    player_lookup = build_player_lookup(all_players)

    player_trailing = compute_trailing_player_scores(scored_weekly, weeks)
    defense_trailing = compute_trailing_defense_scores(scored_defense, weeks)
    performance = build_league_performance_table(
        player_lookup, player_trailing, defense_trailing, availability_lookup
    )

    rosters, users = load_league_context(league_cfg["league_id"])
    team_rosters = build_team_rosters_with_values(rosters, users, player_lookup, dynasty_values)
    position_slot_counts = get_position_slot_counts(league)

    team_name_by_owner = {}
    for u in users:
        team_name_by_owner[u["user_id"]] = (
            (u.get("metadata") or {}).get("team_name") or u.get("display_name") or u.get("user_id")
        )
    my_team_name = team_name_by_owner.get(my_roster.get("owner_id"), "Unknown Team")

if my_team_name not in team_rosters:
    st.error("Couldn't match your roster to a team name -- try reloading.")
    st.stop()

my_team = team_rosters[my_team_name]
my_team_ids = set(my_team["player_id"])

st.divider()
st.markdown(f"### Your team: {my_team_name} — total dynasty value: {int(my_team['dynasty_value'].sum()):,}")
with st.expander("Your full roster with dynasty values"):
    st.dataframe(
        my_team.sort_values("dynasty_value", ascending=False).reset_index(drop=True),
        use_container_width=True,
    )

other_teams = {name: df for name, df in team_rosters.items() if name != my_team_name}
if not other_teams:
    st.warning("No other teams found in this league.")
    st.stop()

with st.spinner(f"Searching for trades across all {len(other_teams)} other teams..."):
    all_suggestions = []
    for opponent_name, their_team in other_teams.items():
        suggestions = find_trade_suggestions(
            my_team,
            their_team,
            max_package_size=max_package_size,
            fairness_tolerance=fairness_tolerance_pct / 100,
            favor_me_max=favor_me_max_pct / 100,
            top_n=10,  # per-opponent cap, kept modest since we combine across all opponents
        )
        if not suggestions.empty:
            suggestions = annotate_starter_impact(suggestions, my_team_ids, performance, position_slot_counts)
            suggestions.insert(0, "opponent", opponent_name)
            all_suggestions.append(suggestions)

if not all_suggestions:
    st.info(
        "No trade packages found across any team in the current fairness "
        "range -- try widening the tolerance sliders or increasing max "
        "players per side."
    )
    st.stop()

combined = pd.concat(all_suggestions, ignore_index=True)

st.divider()
st.markdown("### Suggested trades across the whole league")
st.caption(
    "Sorted by starter lineup impact first, since that's what actually "
    "matters -- a trade that only pads your bench ranks below one that "
    "raises your starting lineup, even if the dynasty value math looks "
    "similar. starter_impact accounts for injury/availability status: an "
    "injured incoming or outgoing player isn't credited or blamed for a "
    "lineup change they can't actually contribute to right now."
)

opponent_filter = st.multiselect(
    "Filter by opponent", options=sorted(other_teams.keys()), default=[]
)
display_df = combined if not opponent_filter else combined[combined["opponent"].isin(opponent_filter)]

display_df = display_df.sort_values("starter_impact", ascending=False)

display_cols = [
    "opponent",
    "you_send",
    "you_receive",
    "starter_impact",
    "value_diff_pct",
    "assessment",
    "you_send_value",
    "you_receive_value",
]
st.dataframe(display_df[display_cols].reset_index(drop=True), use_container_width=True)

with st.expander("Per-position breakdown for the top trade"):
    if not display_df.empty:
        top = display_df.iloc[0]
        st.write(f"**{top['you_send']}** → **{top['you_receive']}** (vs. {top['opponent']})")
        detail_rows = [
            {"position": pos, **vals} for pos, vals in top["starter_impact_detail"].items()
        ]
        if detail_rows:
            st.table(pd.DataFrame(detail_rows))
        else:
            st.caption("No position breakdown available for this trade.")

st.caption(
    "LIMITATIONS: starter_impact compares the sum of your top-K players at "
    "each touched position (K = that position's real starting roster "
    "slots) before vs. after the trade -- it does NOT model FLEX/Superflex/"
    "IDP_FLEX slots, since that requires a full lineup optimizer. A player "
    "who'd only ever occupy a FLEX spot may be undercounted. This is also "
    "pure value + performance math: it doesn't know a manager's contend/"
    "rebuild timeline or whether they'd actually consider the deal."
)
