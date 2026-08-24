"""
Thin wrapper around the public Sleeper API (no auth required, read-only).

Docs: https://docs.sleeper.com/

Sleeper's own guidance is to cache the /players endpoint locally and refresh
at most once a day -- it's a multi-MB payload of every NFL player and doesn't
change often. Everything else (league settings, rosters, users) is small and
cheap to pull live, so we don't bother caching those beyond Streamlit's own
st.cache_data.
"""

import json
import os
import time
from datetime import datetime, timedelta

import requests

from config import (
    SLEEPER_API_BASE,
    CACHE_DIR,
    PLAYERS_CACHE_PATH,
    PLAYERS_CACHE_TTL_HOURS,
)


def _get(path: str) -> dict | list:
    url = f"{SLEEPER_API_BASE}{path}"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_league(league_id: str) -> dict:
    """Full league object: scoring_settings, roster_positions, season, etc."""
    return _get(f"/league/{league_id}")


def get_rosters(league_id: str) -> list[dict]:
    """One entry per team: owner_id, players (list of player_ids), starters, etc."""
    return _get(f"/league/{league_id}/rosters")


def get_users(league_id: str) -> list[dict]:
    """League members: user_id, display_name, team name metadata."""
    return _get(f"/league/{league_id}/users")


def get_transactions(league_id: str, week: int) -> list[dict]:
    """Trades/waivers/free-agent moves for a given week (1-18)."""
    return _get(f"/league/{league_id}/transactions/{week}")


def get_all_players(force_refresh: bool = False) -> dict:
    """
    Full NFL player DB, keyed by player_id. This is a large payload --
    Sleeper asks that it be cached and refreshed at most daily.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)

    if not force_refresh and os.path.exists(PLAYERS_CACHE_PATH):
        age = datetime.now() - datetime.fromtimestamp(
            os.path.getmtime(PLAYERS_CACHE_PATH)
        )
        if age < timedelta(hours=PLAYERS_CACHE_TTL_HOURS):
            with open(PLAYERS_CACHE_PATH) as f:
                return json.load(f)

    players = _get("/players/nfl")
    with open(PLAYERS_CACHE_PATH, "w") as f:
        json.dump(players, f)
    return players


def get_rostered_player_ids(league_id: str) -> set[str]:
    """Every player_id currently on any roster in the league."""
    rosters = get_rosters(league_id)
    rostered = set()
    for r in rosters:
        if r.get("players"):
            rostered.update(r["players"])
    return rostered


def get_free_agents(league_id: str, all_players: dict | None = None) -> dict:
    """
    Players in the Sleeper NFL player DB not currently on any roster in this
    league. Returns a dict keyed by player_id, same shape as get_all_players.
    Filters out non-active/retired entries and non-fantasy-relevant positions.
    """
    if all_players is None:
        all_players = get_all_players()

    rostered = get_rostered_player_ids(league_id)
    relevant_positions = {"QB", "RB", "WR", "TE", "LB", "DB", "DL"}

    free_agents = {
        pid: p
        for pid, p in all_players.items()
        if pid not in rostered
        and p.get("position") in relevant_positions
        and p.get("team") is not None  # drop players with no current NFL team
    }
    return free_agents


def parse_scoring_settings(league: dict) -> dict:
    """
    Sleeper returns scoring_settings as a flat dict of stat_key -> points.
    This just groups them into readable buckets so a settings page can
    render "what actually scores points" without you eyeballing raw keys.
    """
    scoring = league.get("scoring_settings", {})

    groups = {
        "passing": {},
        "rushing": {},
        "receiving": {},
        "idp_tackling": {},
        "idp_pass_rush": {},
        "idp_coverage": {},
        "kicking": {},
        "misc": {},
    }

    prefix_map = {
        "pass_": "passing",
        "rush_": "rushing",
        "rec_": "receiving",
        "idp_tkl": "idp_tackling",
        "tkl": "idp_tackling",
        "sack": "idp_pass_rush",
        "qb_hit": "idp_pass_rush",
        "int": "idp_coverage",
        "pass_def": "idp_coverage",
        "ff": "idp_tackling",
        "fum_rec": "idp_tackling",
        "fg_": "kicking",
        "xp_": "kicking",
    }

    for key, points in scoring.items():
        bucket = "misc"
        for prefix, group_name in prefix_map.items():
            if key.startswith(prefix):
                bucket = group_name
                break
        groups[bucket][key] = points

    return groups


def get_roster_construction(league: dict) -> dict:
    """
    Tally roster_positions into a simple count per slot type, e.g.
    {"LB": 4, "DB": 2, "IDP_FLEX": 2, "WR": 3, ...}
    """
    positions = league.get("roster_positions", [])
    counts: dict[str, int] = {}
    for pos in positions:
        if pos == "BN":
            continue
        counts[pos] = counts.get(pos, 0) + 1
    return counts
