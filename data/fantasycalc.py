"""
FantasyCalc dynasty trade value connector.

FantasyCalc has no official published developer API, but they do run a
free, public, unauthenticated JSON endpoint that their own site uses --
confirmed live (fetched real current data while building this):

    https://api.fantasycalc.com/values/current
        ?isDynasty=true&numQbs=<1|2>&numTeams=<10|12|14>&ppr=<0|0.5|1>

Each entry includes player.sleeperId directly, so no ID crosswalk is
needed to join this to Sleeper roster data -- a real advantage over the
nflverse-based sources elsewhere in this app.

NOTE: this endpoint could not be exercised end-to-end from the sandbox
this was built in (network there is locked to package registries only).
The parsing logic below is tested against a saved real response sample
(data/fixtures/fantasycalc_sample.json) rather than a live call. The live
HTTP request itself should be verified once running locally, where normal
internet access applies.
"""

import os

import pandas as pd
import requests

from config import CACHE_DIR

FANTASYCALC_BASE = "https://api.fantasycalc.com/values/current"
VALID_NUM_TEAMS = (8, 10, 12, 14, 16)
VALID_PPR = (0, 0.5, 1)


def _round_to_nearest(value: float, options: tuple) -> float:
    return min(options, key=lambda x: abs(x - value))


def infer_fantasycalc_params(league: dict) -> dict:
    """
    Derives FantasyCalc's required query params from a league's real
    Sleeper settings, rather than hardcoding them:
      - numQbs: 2 if the league starts multiple QB-eligible slots
        (Superflex/2QB), else 1
      - numTeams: from total_rosters, rounded to FantasyCalc's supported
        team-count buckets
      - ppr: from the 'rec' scoring key, rounded to 0 / 0.5 / 1
    """
    roster_positions = league.get("roster_positions", [])
    qb_eligible_slots = sum(
        1 for p in roster_positions if p in ("QB", "SUPER_FLEX", "SUPERFLEX")
    )
    num_qbs = 2 if qb_eligible_slots >= 2 else 1

    total_rosters = league.get("total_rosters", 12)
    num_teams = _round_to_nearest(total_rosters, VALID_NUM_TEAMS)

    rec_points = (league.get("scoring_settings") or {}).get("rec", 0.5)
    ppr = _round_to_nearest(rec_points, VALID_PPR)

    return {"numQbs": num_qbs, "numTeams": num_teams, "ppr": ppr}


def get_dynasty_values(
    num_qbs: int = 1, num_teams: int = 12, ppr: float = 1, force_refresh: bool = False
) -> pd.DataFrame:
    """
    Current dynasty trade values for every player FantasyCalc tracks,
    already keyed by sleeper_id. Cached locally (values move daily, so a
    same-day cache is fine; refreshed automatically once stale).
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = f"{CACHE_DIR}/fantasycalc_{num_qbs}qb_{num_teams}tm_{ppr}ppr.parquet"

    if not force_refresh and os.path.exists(cache_path):
        return pd.read_parquet(cache_path)

    resp = requests.get(
        FANTASYCALC_BASE,
        params={"isDynasty": "true", "numQbs": num_qbs, "numTeams": num_teams, "ppr": ppr},
        timeout=20,
    )
    resp.raise_for_status()
    df = _parse_fantasycalc_response(resp.json())
    df.to_parquet(cache_path, index=False)
    return df


def _parse_fantasycalc_response(data: list[dict]) -> pd.DataFrame:
    """Separated from get_dynasty_values() so the parsing logic can be unit tested offline."""
    rows = []
    for entry in data:
        p = entry.get("player", {})
        sleeper_id = p.get("sleeperId")
        if not sleeper_id:
            continue
        rows.append(
            {
                "sleeper_id": str(sleeper_id),
                "name": p.get("name"),
                "position": p.get("position"),
                "nfl_team": p.get("maybeTeam"),
                "age": p.get("maybeAge"),
                "dynasty_value": entry.get("value"),
                "overall_rank": entry.get("overallRank"),
                "position_rank": entry.get("positionRank"),
                "trend_30day": entry.get("trend30Day"),
            }
        )
    return pd.DataFrame(rows)
