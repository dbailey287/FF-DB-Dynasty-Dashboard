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
    compute_recency_weighted_player_scores,
    compute_recency_weighted_defense_scores,
)
from engine.trades import (
    build_team_rosters_with_values,
    build_league_performance_table,
    get_position_groups,
    find_trade_suggestions,
    annotate_starter_impact,
)

st.set_page_config(page_title="Trade Finder", page_icon="🔄", layout="wide")
st.title("🔄 Trade Finder")
st.caption(
    "Dynasty trade value from FantasyCalc, matched against every team in "
    "the league at once, with real starter-lineup impact using recency-"
    "weighted performance + injury/availability data."
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

# Capped at 18 (real end of regular season) rather than the raw max week in
# the data, which can reach into the low-20s for playoff weeks that only
# apply to a handful of teams -- using that as the reference point would
# badly skew recency decay for everyone else.
try:
    _default_season_weekly = get_weekly_stats(default_season)
    default_as_of_week = min(int(_default_season_weekly["week"].max()), 18)
except Exception:
    default_as_of_week = 18

st.caption(
    f"FantasyCalc values for: {'Superflex' if fc_params['numQbs'] == 2 else '1QB'}, "
    f"{fc_params['numTeams']}-team, {fc_params['ppr']} PPR (inferred from this league)."
)

col1, col2, col3, col4 = st.columns(4)
with col1:
    season = st.number_input(
        "Season", min_value=2015, max_value=league_season, value=default_season, step=1
    )
    as_of_week = st.number_input(
        "As of week", min_value=1, max_value=18, value=default_as_of_week, step=1
    )
with col2:
    half_life_weeks = st.slider(
        "Recency half-life (weeks)", min_value=1.0, max_value=8.0, value=3.0, step=0.5,
        help="How fast older games fade. A game this many weeks back counts "
             "half as much as the most recent one. Lower = more reactive to "
             "recent form; higher = smoother, weighs the whole season more.",
    )
    max_package_size = st.number_input("Max players/side", min_value=1, max_value=3, value=2, step=1)
with col3:
    fairness_tolerance_pct = st.slider("Fair tolerance (%)", min_value=5, max_value=30, value=15, step=5)
with col4:
    favor_me_max_pct = st.slider("Max favor-me tilt (%)", min_value=10, max_value=60, value=35, step=5)

st.caption(
    "Uses every game a player has played this season, weighted by recency "
    "(no fixed window to accidentally miss) -- a player who was great for "
    "16 weeks then missed the last 2 still shows meaningfully strong, just "
    "gently discounted, rather than vanishing or being judged on a too-thin "
    "recent slice alone."
)

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
    injury_lookup = get_latest_injury_status(injuries, id_map, as_of_week)
    roster_status = get_weekly_roster_status(season)
    availability_lookup = get_availability_reasons(roster_status, injury_lookup, as_of_week)

    all_players = get_all_players()
    player_lookup = build_player_lookup(all_players)

    player_weighted = compute_recency_weighted_player_scores(scored_weekly, as_of_week, half_life_weeks)
    defense_weighted = compute_recency_weighted_defense_scores(scored_defense, as_of_week, half_life_weeks)
    performance = build_league_performance_table(
        player_lookup, player_weighted, defense_weighted, availability_lookup
    )

    rosters, users = load_league_context(league_cfg["league_id"])
    team_rosters = build_team_rosters_with_values(rosters, users, player_lookup, dynasty_values)
    position_groups, unrecognized_flex_slots = get_position_groups(league)

    team_name_by_owner = {}
    for u in users:
        team_name_by_owner[u["user_id"]] = (
            (u.get("metadata") or {}).get("team_name") or u.get("display_name") or u.get("user_id")
        )
    my_team_name = team_name_by_owner.get(my_roster.get("owner_id"), "Unknown Team")

if my_team_name not in team_rosters:
    st.error("Couldn't match your roster to a team name -- try reloading.")
    st.stop()

if unrecognized_flex_slots:
    st.warning(
        f"This league has a flex-type slot not yet mapped: "
        f"{', '.join(unrecognized_flex_slots)}. That slot's capacity is NOT "
        f"being counted in starter_impact below, which likely undercounts "
        f"players who start via it -- please share this exact slot name so "
        f"the mapping can be extended."
    )

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
            suggestions = annotate_starter_impact(suggestions, my_team_ids, performance, position_groups)
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
            {"position group": label, **vals} for label, vals in top["starter_impact_detail"].items()
        ]
        if detail_rows:
            st.table(pd.DataFrame(detail_rows))
        else:
            st.caption("No position breakdown available for this trade.")

st.caption(
    "starter_impact fills each position's own dedicated slots with players "
    "of that exact position first (a TE slot can't be filled by an RB, no "
    "matter how deep your RB room is), then lets only the leftover players "
    "compete for shared FLEX/Superflex/IDP_FLEX slots -- so losing your only "
    "good player at a scarce position is never masked by gaining depth at a "
    "different, FLEX-sharing position. This is still pure value + "
    "performance math on top of that: it doesn't know a manager's contend/"
    "rebuild timeline, whether they'd actually consider the deal, or "
    "long-term talent beyond recent performance -- a hot recent stretch "
    "from a lesser-regarded player can outscore a slumping/injured star in "
    "this metric even when dynasty consensus would strongly disagree."
)
