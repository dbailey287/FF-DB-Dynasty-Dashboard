import streamlit as st

from config import SLEEPER_USERNAME
from ui import render_league_switcher
from data.sleeper import get_league, get_rosters, get_users, get_all_players, get_my_roster
from data.fantasycalc import get_dynasty_values, infer_fantasycalc_params
from engine.rankings import build_player_lookup
from engine.trades import build_team_rosters_with_values, find_trade_suggestions

st.set_page_config(page_title="Trade Finder", page_icon="🔄", layout="wide")
st.title("🔄 Trade Finder")
st.caption(
    "Dynasty trade value from FantasyCalc, matched against each team's real "
    "roster, to suggest fair (or team-favorable) trade packages."
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
st.caption(
    f"Using FantasyCalc values for: {'Superflex' if fc_params['numQbs'] == 2 else '1QB'}, "
    f"{fc_params['numTeams']}-team, {fc_params['ppr']} PPR "
    "(inferred from this league's real roster/scoring settings)."
)

col1, col2, col3 = st.columns(3)
with col1:
    max_package_size = st.number_input(
        "Max players per side", min_value=1, max_value=3, value=2, step=1
    )
with col2:
    fairness_tolerance_pct = st.slider(
        "Fair trade tolerance (%)", min_value=5, max_value=30, value=15, step=5
    )
with col3:
    favor_me_max_pct = st.slider(
        "Max favor-me tilt (%)", min_value=10, max_value=60, value=35, step=5
    )

with st.spinner("Pulling dynasty values and rosters..."):
    try:
        dynasty_values = load_dynasty_values(fc_params["numQbs"], fc_params["numTeams"], fc_params["ppr"])
    except Exception as e:
        st.error(
            f"Couldn't load dynasty values from FantasyCalc: {e}. "
            "This page depends on an external service that isn't guaranteed to "
            "always be up -- try reloading in a bit."
        )
        st.stop()

    rosters, users = load_league_context(league_cfg["league_id"])
    all_players = get_all_players()
    player_lookup = build_player_lookup(all_players)

    team_rosters = build_team_rosters_with_values(rosters, users, player_lookup, dynasty_values)

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

st.divider()

st.markdown(f"### Your team: {my_team_name} — total value: {int(my_team['dynasty_value'].sum()):,}")
with st.expander("Your full roster with dynasty values"):
    st.dataframe(
        my_team.sort_values("dynasty_value", ascending=False).reset_index(drop=True),
        use_container_width=True,
    )

other_teams = {name: df for name, df in team_rosters.items() if name != my_team_name}
if not other_teams:
    st.warning("No other teams found in this league.")
    st.stop()

opponent = st.selectbox("Find trades with", options=sorted(other_teams.keys()))
their_team = other_teams[opponent]

st.markdown(f"#### {opponent} — total value: {int(their_team['dynasty_value'].sum()):,}")

with st.spinner("Searching for trade packages..."):
    suggestions = find_trade_suggestions(
        my_team,
        their_team,
        max_package_size=max_package_size,
        fairness_tolerance=fairness_tolerance_pct / 100,
        favor_me_max=favor_me_max_pct / 100,
    )

if suggestions.empty:
    st.info(
        "No trade packages found in the current fairness range -- try "
        "widening the tolerance sliders or increasing max players per side."
    )
else:
    st.markdown("### Suggested trades")
    st.dataframe(suggestions, use_container_width=True)
    st.caption(
        "value_diff_pct is how much more value you'd receive than you send "
        "(negative means you'd be giving up more). Sorted closest-to-even "
        "first -- those are the most likely to actually get accepted. "
        "This is pure value math: it doesn't know positional needs, roster "
        "construction limits, or whether a manager is rebuilding vs. "
        "contending -- sanity-check any suggestion against that context."
    )
