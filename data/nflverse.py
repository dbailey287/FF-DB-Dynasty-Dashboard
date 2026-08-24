"""
Wrapper around nflreadpy (the actively-maintained nflverse Python client).

NOTE: we deliberately use nflreadpy, not the older `nfl_data_py` package.
nfl_data_py pins pandas<2.0, which has no prebuilt wheels for Python 3.13+
and fails to build from source in most environments. nflreadpy is the
nflverse team's own successor, has no such pin, and returns Polars
DataFrames (converted to pandas at the edges here so the rest of the app
can stay pandas-only for simplicity).

The other reason we use nflreadpy specifically: load_ff_playerids() returns
a crosswalk table with a `sleeper_id` column, which is the only clean way
to join Sleeper roster data to nflverse stats (they use totally different
ID schemes -- Sleeper's own IDs vs. nflverse's gsis_id).
"""

import os

import nflreadpy as nfl
import pandas as pd

from config import CACHE_DIR

WEEKLY_STATS_CACHE_PATH = f"{CACHE_DIR}/weekly_stats_{{season}}.parquet"
PLAYER_ID_MAP_CACHE_PATH = f"{CACHE_DIR}/player_id_map.parquet"


def get_weekly_stats(season: int, force_refresh: bool = False) -> pd.DataFrame:
    """
    Weekly player-level stats for a season: passing/rushing/receiving
    volume+efficiency, plus IDP tackling/pass-rush/coverage stats, plus
    Sleeper/nflverse's own fantasy_points and fantasy_points_ppr (we won't
    use those directly since we recompute points from each league's own
    scoring_settings, but they're handy for sanity-checking).

    Cached locally as parquet since this covers a whole season and only
    changes after games are played (weekly refresh is plenty in-season).

    Raises FileNotFoundError with a clear message if nflverse has no data
    published for this season yet (e.g. requesting the upcoming season
    before Week 1 has been played).
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = WEEKLY_STATS_CACHE_PATH.format(season=season)

    if not force_refresh and os.path.exists(cache_path):
        return pd.read_parquet(cache_path)

    try:
        stats = nfl.load_player_stats(seasons=[season]).to_pandas()
    except Exception as e:
        raise FileNotFoundError(
            f"nflverse has no weekly stats published for {season} yet "
            f"(likely because that season hasn't started or completed any "
            f"games). Try an earlier season. Original error: {e}"
        ) from e

    stats.to_parquet(cache_path, index=False)
    return stats


def get_player_id_map(force_refresh: bool = False) -> pd.DataFrame:
    """
    Crosswalk table joining sleeper_id <-> gsis_id (nflverse's player_id)
    <-> name/position/team, plus draft capital (draft_year/round/pick) which
    is useful later for the breakout detector (production vs. draft capital).

    This changes slowly (new players added weekly at most) -- cache daily.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)

    if not force_refresh and os.path.exists(PLAYER_ID_MAP_CACHE_PATH):
        return pd.read_parquet(PLAYER_ID_MAP_CACHE_PATH)

    ids = nfl.load_ff_playerids().to_pandas()
    ids.to_parquet(PLAYER_ID_MAP_CACHE_PATH, index=False)
    return ids


def attach_sleeper_ids(weekly_stats: pd.DataFrame, id_map: pd.DataFrame) -> pd.DataFrame:
    """
    Joins nflverse weekly stats (keyed on player_id == gsis_id) to Sleeper
    IDs via the crosswalk, so the rest of the app can look players up by
    Sleeper's own ID (what rosters/free-agents use).

    Sleeper's API returns player_id as a plain string (e.g. "4046"), but
    the crosswalk's sleeper_id column comes through as float64 (because of
    NaNs for players with no Sleeper ID) -- left as-is, "4046" would never
    match 4046.0 when joining against real roster data. Normalized to a
    clean string here so downstream lookups actually match.
    """
    slim_map = id_map[["gsis_id", "sleeper_id", "name", "position", "team"]].dropna(
        subset=["gsis_id"]
    ).copy()
    slim_map["sleeper_id"] = slim_map["sleeper_id"].apply(
        lambda x: str(int(x)) if pd.notna(x) else None
    )
    merged = weekly_stats.merge(
        slim_map,
        left_on="player_id",
        right_on="gsis_id",
        how="left",
        suffixes=("", "_idmap"),
    )
    return merged


def get_team_defense_stats(season: int, force_refresh: bool = False) -> pd.DataFrame:
    """
    Team-level defense/special-teams box score stats (sacks, INTs, fumble
    recoveries, def/return TDs, safeties, blocked kicks) -- this is what a
    standard-league team DEF/D-ST roster slot scores off of, as opposed to
    individual IDP players. Joined with schedule data to add each team's
    points allowed that week (needed for pts_allow_X scoring tiers), since
    "points allowed" is really the opponent's score in that game.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = f"{CACHE_DIR}/team_defense_{season}.parquet"

    if not force_refresh and os.path.exists(cache_path):
        return pd.read_parquet(cache_path)

    team_stats = nfl.load_team_stats(seasons=[season]).to_pandas()
    schedules = nfl.load_schedules(seasons=[season]).to_pandas()

    home = schedules[["season", "week", "home_team", "away_score"]].rename(
        columns={"home_team": "team", "away_score": "points_allowed"}
    )
    away = schedules[["season", "week", "away_team", "home_score"]].rename(
        columns={"away_team": "team", "home_score": "points_allowed"}
    )
    points_allowed = pd.concat([home, away], ignore_index=True)

    merged = team_stats.merge(points_allowed, on=["season", "week", "team"], how="left")
    merged.to_parquet(cache_path, index=False)
    return merged


def get_injury_reports(season: int, force_refresh: bool = False) -> pd.DataFrame:
    """
    Weekly injury report data: report_status (Out/Doubtful/Questionable) and
    the actual injury (e.g. "Knee") per player per week. Used to explain
    WHY a player shows few/zero games in a trailing window -- a 0.0 average
    from zero games means "didn't play," and this says whether that's
    injury, and what kind, rather than leaving it looking like missing data.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = f"{CACHE_DIR}/injuries_{season}.parquet"

    if not force_refresh and os.path.exists(cache_path):
        return pd.read_parquet(cache_path)

    injuries = nfl.load_injuries(seasons=[season]).to_pandas()
    injuries.to_parquet(cache_path, index=False)
    return injuries


def get_latest_injury_status(
    injuries: pd.DataFrame, id_map: pd.DataFrame, through_week: int
) -> dict:
    """
    Reduces the weekly injury report table to one row per player: their
    most recent report_status/injury as of through_week. Returns
    {sleeper_id: {"status": ..., "injury": ...}}. Players with no report
    at all (never appeared on an injury report) are simply absent from
    this dict -- callers should treat that as "no designation," not "Out".
    """
    slim_map = id_map[["gsis_id", "sleeper_id"]].dropna(subset=["gsis_id"]).copy()
    slim_map["sleeper_id"] = slim_map["sleeper_id"].apply(
        lambda x: str(int(x)) if pd.notna(x) else None
    )

    subset = injuries[
        (injuries["week"] <= through_week) & injuries["report_status"].notna()
    ].merge(slim_map, on="gsis_id", how="left")
    subset = subset.dropna(subset=["sleeper_id"])

    if subset.empty:
        return {}

    latest = subset.sort_values("week").groupby("sleeper_id").tail(1)
    return {
        row["sleeper_id"]: {
            "status": row["report_status"],
            "injury": row.get("report_primary_injury"),
        }
        for _, row in latest.iterrows()
    }


def get_weekly_roster_status(season: int, force_refresh: bool = False) -> pd.DataFrame:
    """
    Weekly roster status per player (ACT/RES/INA/DEV/CUT/RET/TRD/EXE) --
    already keyed by sleeper_id directly, no crosswalk needed. This is what
    distinguishes a healthy player simply not getting playing time (ACT,
    zero snaps) from one on injured reserve (RES) or a practice-squad call-
    up (DEV), which the injury report alone can't fully capture -- a benched
    healthy backup never appears on an injury report at all.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = f"{CACHE_DIR}/roster_status_{season}.parquet"

    if not force_refresh and os.path.exists(cache_path):
        return pd.read_parquet(cache_path)

    roster_status = nfl.load_rosters_weekly(seasons=[season]).to_pandas()
    roster_status.to_parquet(cache_path, index=False)
    return roster_status


_STATUS_LABELS = {
    "RES": "Injured Reserve",
    "DEV": "Practice Squad",
    "CUT": "Released",
    "RET": "Retired",
    "TRD": "Traded",
    "TRC": "Traded (Cond.)",
    "EXE": "Exempt",
}


def get_availability_reasons(
    roster_status: pd.DataFrame,
    injury_lookup: dict,
    through_week: int,
) -> dict:
    """
    Combines weekly roster status with the injury report into one clear
    "why isn't this player producing" label per sleeper_id:
      - RES/DEV/CUT/RET/TRD/EXE -> that roster status (e.g. "Injured Reserve")
      - ACT/INA + an injury report entry -> "{report_status} - {injury}"
        (e.g. "Out - Knee")
      - INA with no injury report entry -> "Inactive (healthy scratch/coach's decision)"
      - ACT with no injury report entry -> "" (genuinely just not getting
        playing time -- this is the "benched, not injured" case)
    """
    subset = roster_status[roster_status["week"] <= through_week].dropna(subset=["sleeper_id"])
    if subset.empty:
        return {}

    subset = subset.copy()
    subset["sleeper_id"] = subset["sleeper_id"].apply(
        lambda x: str(int(x)) if pd.notna(x) else None
    )
    latest = subset.sort_values("week").groupby("sleeper_id").tail(1)

    reasons = {}
    for _, row in latest.iterrows():
        pid = row["sleeper_id"]
        status = row["status"]
        injury_info = injury_lookup.get(pid)

        if status in _STATUS_LABELS:
            reasons[pid] = _STATUS_LABELS[status]
        elif injury_info:
            reasons[pid] = f"{injury_info['status']} - {injury_info['injury']}"
        elif status == "INA":
            reasons[pid] = "Inactive (healthy scratch/coach's decision)"
        else:
            reasons[pid] = ""  # ACT with no injury report -- healthy, just not playing

    return reasons
