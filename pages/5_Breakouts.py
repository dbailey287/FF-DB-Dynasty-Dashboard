import datetime

import streamlit as st

from ui import render_league_switcher
from data.sleeper import get_league, get_player_ownership_map
from data.nflverse import get_weekly_stats, get_player_id_map, attach_sleeper_ids
from engine.breakouts import find_breakout_candidates

st.set_page_config(page_title="Breakouts", page_icon="📈", layout="wide")
st.title("📈 Breakout Candidates")
st.caption(
    "Players whose target share / opportunity (WOPR) is rising fastest, "
    "filtered to those with low draft capital or still early in their "
    "career -- the Puka Nacua pattern: production climbing before the "
    "market has caught up."
)

league_cfg = render_league_switcher()

if league_cfg["league_id"] == "REPLACE_WITH_LEAGUE_ID":
    st.error("Set a real league_id for this league in config.py, then reload.")
    st.stop()


@st.cache_data(ttl=3600)
def load_league(league_id: str):
    return get_league(league_id)


@st.cache_data(ttl=1800)  # shorter TTL -- rosters change during the week
def load_ownership(league_id: str):
    return get_player_ownership_map(league_id)


league = load_league(league_cfg["league_id"])
league_season = int(league.get("season", 2025))
default_season = league_season - 1 if datetime.date.today().month < 9 else league_season

col1, col2, col3 = st.columns(3)
with col1:
    season = st.number_input(
        "Season", min_value=2015, max_value=league_season, value=default_season, step=1
    )
    through_week = st.number_input("Through week", min_value=2, max_value=18, value=14, step=1)
with col2:
    window_size = st.number_input(
        "Weeks to analyze (split early/recent)", min_value=4, max_value=18, value=7, step=1
    )
    min_games = st.number_input("Min games played", min_value=2, max_value=10, value=4, step=1)
with col3:
    max_draft_round = st.number_input(
        "Max draft round to qualify as 'low investment'", min_value=1, max_value=7, value=3, step=1
    )
    max_years_since_draft = st.number_input(
        "Or years since draft <=", min_value=1, max_value=10, value=3, step=1
    )

positions = st.multiselect("Positions", options=["WR", "RB", "TE"], default=["WR", "RB", "TE"])
availability_filter = st.radio(
    "Show",
    options=["All players", "Free agents only", "Rostered only"],
    horizontal=True,
)

weeks = list(range(max(1, through_week - window_size + 1), through_week + 1))
st.caption(
    f"Comparing weeks {weeks[0]}–{weeks[len(weeks)//2 - 1] if len(weeks) > 1 else weeks[0]} "
    f"(early) vs. weeks {weeks[len(weeks)//2]}–{weeks[-1]} (recent) of {season}"
)

with st.spinner("Pulling stats and scanning for breakout patterns..."):
    try:
        weekly = get_weekly_stats(season)
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()

    id_map = get_player_id_map()
    weekly = attach_sleeper_ids(weekly, id_map)
    ownership = load_ownership(league_cfg["league_id"])

    candidates = find_breakout_candidates(
        weekly,
        id_map,
        weeks,
        positions=tuple(positions),
        min_games=min_games,
        max_draft_round=max_draft_round,
        max_years_since_draft=max_years_since_draft,
        season=season,
    )

    if not candidates.empty:
        candidates["fantasy_team"] = candidates["sleeper_id"].map(ownership).fillna("Free Agent")

        if availability_filter == "Free agents only":
            candidates = candidates[candidates["fantasy_team"] == "Free Agent"]
        elif availability_filter == "Rostered only":
            candidates = candidates[candidates["fantasy_team"] != "Free Agent"]

        candidates = candidates.drop(columns=["sleeper_id"]).rename(columns={"team": "nfl_team"})
        # Put fantasy_team right after name/position so it's immediately visible
        cols = candidates.columns.tolist()
        cols.insert(cols.index("nfl_team") + 1, cols.pop(cols.index("fantasy_team")))
        candidates = candidates[cols].reset_index(drop=True)

st.divider()

if candidates.empty:
    st.info(
        "No candidates found -- try widening the week window (need at least "
        "2 distinct weeks to compute a trend), lowering min games, or "
        "relaxing the draft capital filters."
    )
else:
    st.markdown("### Rising opportunity, low investment")
    st.dataframe(candidates, use_container_width=True)
    st.caption(
        "wopr_trend is the change in Weighted Opportunity Rating (combines "
        "target share + air yards share) between the early and recent half "
        "of the window -- higher means their role is growing fastest. This "
        "flags a changing role, not a guaranteed future star; always sanity-"
        "check against depth chart/injury news before trading for someone."
    )
