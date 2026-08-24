"""
Applies a league's real scoring_settings (pulled live from Sleeper) to
nflverse weekly stats to compute actual fantasy points per player per week.

IMPORTANT CAVEAT: Sleeper doesn't publish an official list of every
scoring_settings key name, so STAT_KEY_MAP below is built from the commonly
documented/observed keys, not a guaranteed-complete spec. compute_points()
returns both the computed points AND a list of any scoring_settings keys
that had a non-zero point value but no mapping found -- check that list
against the raw JSON on the League Settings page. Any key that shows up
there means real scoring is happening that this engine is currently
missing, and STAT_KEY_MAP needs a new entry for it.
"""

import pandas as pd

# Maps a Sleeper scoring_settings key -> the corresponding nflverse column
# in the weekly stats table. Only keys present here get scored; anything
# else surfaces in the "unmapped" list from compute_points().
STAT_KEY_MAP: dict[str, str] = {
    # Passing
    "pass_yd": "passing_yards",
    "pass_td": "passing_tds",
    "pass_int": "passing_interceptions",
    "pass_2pt": "passing_2pt_conversions",
    "pass_cmp": "completions",
    "pass_inc": None,  # needs (attempts - completions), handled specially
    # Kicking (individual kicker, present in weekly player stats)
    "fgm_0_19": "fg_made_0_19",
    "fgm_20_29": "fg_made_20_29",
    "fgm_30_39": "fg_made_30_39",
    "fgm_40_49": "fg_made_40_49",
    "fgm_50p": None,  # fg_made_50_59 + fg_made_60_, handled specially
    "fgmiss_0_19": "fg_missed_0_19",
    "fgmiss_20_29": "fg_missed_20_29",
    "fgmiss_30_39": "fg_missed_30_39",
    "fgmiss_40_49": "fg_missed_40_49",
    "fgmiss": "fg_missed",  # flat (non-tiered) miss penalty
    "xpm": "pat_made",
    "xpmiss": "pat_missed",
    # Rushing
    "rush_yd": "rushing_yards",
    "rush_td": "rushing_tds",
    "rush_2pt": "rushing_2pt_conversions",
    # Receiving
    "rec": "receptions",
    "rec_yd": "receiving_yards",
    "rec_td": "receiving_tds",
    "rec_2pt": "receiving_2pt_conversions",
    # Fumbles (offense)
    "fum_lost": "fumbles_lost_total",
    # IDP tackling (Sleeper does NOT use an "idp_" prefix on these keys --
    # confirmed against real league scoring_settings output)
    "tkl_solo": "def_tackles_solo",
    "tkl_ast": "def_tackles_with_assist",
    "tkl_loss": "def_tackles_for_loss",
    "tkl": "def_tackles_solo",  # some leagues use a single combined "tkl" key
    # IDP pass rush
    "sack": "def_sacks",
    "qb_hit": "def_qb_hits",
    # IDP coverage / turnovers / general defensive
    "int": "def_interceptions",
    "pass_def": "def_pass_defended",
    "ff": "def_fumbles_forced",
    "fum_rec": "fumble_recovery_opp",
    "fum_rec_td": "fumble_recovery_tds",
    "def_td": "def_tds",
    "safe": "def_safeties",
    "blk_kick": None,  # handled specially: sum of punt/PAT/FG blocks
    # Special-teams variants of forced fumble / recovery / TD (kick/punt
    # return plays specifically, distinct from generic ff/fum_rec/def_td)
    "def_st_ff": "def_fumbles_forced",
    "def_st_fum_rec": "fumble_recovery_opp",
    "def_st_td": "special_teams_tds",
}

# nflverse splits blocked kicks by type (punt/PAT/FG) rather than one
# combined column -- summed together when scoring blk_kick.
BLOCKED_KICK_COLUMNS = ["def_punt_blocks", "def_pat_blocks", "def_fg_blocks"]



def compute_points(
    weekly_stats: pd.DataFrame, scoring_settings: dict
) -> tuple[pd.DataFrame, list[str]]:
    """
    Adds a 'league_points' column to weekly_stats computed from the league's
    actual scoring_settings. Returns (scored_df, unmapped_keys) where
    unmapped_keys lists any scoring_settings entries with a non-zero point
    value that couldn't be applied because no matching nflverse column is
    known -- always check this list before trusting the output.
    """
    df = weekly_stats.copy()
    df["league_points"] = 0.0
    unmapped: list[str] = []

    for key, points_per_unit in scoring_settings.items():
        if not points_per_unit:
            continue  # zero-value settings don't affect anything

        if key == "pass_inc":
            if {"attempts", "completions"}.issubset(df.columns):
                df["league_points"] += (
                    df["attempts"] - df["completions"]
                ) * points_per_unit
            else:
                unmapped.append(key)
            continue

        if key == "blk_kick":
            available = [c for c in BLOCKED_KICK_COLUMNS if c in df.columns]
            if available:
                df["league_points"] += df[available].sum(axis=1) * points_per_unit
            else:
                unmapped.append(key)
            continue

        if key == "fgm_50p":
            fifty_plus_cols = [c for c in ("fg_made_50_59", "fg_made_60_") if c in df.columns]
            if fifty_plus_cols:
                df["league_points"] += df[fifty_plus_cols].sum(axis=1) * points_per_unit
            else:
                unmapped.append(key)
            continue

        column = STAT_KEY_MAP.get(key)
        if column is None or column not in df.columns:
            unmapped.append(key)
            continue

        df["league_points"] += df[column].fillna(0) * points_per_unit

    return df, sorted(set(unmapped))


# Maps a team-DEF scoring key to the corresponding column in
# get_team_defense_stats()'s output (team-level, not individual IDP).
TEAM_DEFENSE_KEY_MAP: dict[str, str] = {
    "sack": "def_sacks",
    "int": "def_interceptions",
    "ff": "def_fumbles_forced",
    "fum_rec": "fumble_recovery_opp",
    "fum_rec_td": "fumble_recovery_tds",
    "def_td": "def_tds",
    "safe": "def_safeties",
    "def_st_td": "special_teams_tds",
}


def _parse_pts_allow_key(key: str) -> tuple[int, int | None] | None:
    """
    Parses Sleeper's pts_allow_X scoring key into a (low, high) point range.
    "pts_allow_0" -> (0, 0); "pts_allow_1_6" -> (1, 6);
    "pts_allow_35p" -> (35, None) meaning 35 or more.
    Returns None if the key doesn't parse as a pts_allow bracket.
    """
    if not key.startswith("pts_allow_"):
        return None
    remainder = key[len("pts_allow_"):]
    parts = remainder.split("_")
    try:
        if len(parts) == 1:
            token = parts[0]
            if token.endswith("p"):
                return int(token[:-1]), None
            val = int(token)
            return val, val
        elif len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except ValueError:
        return None
    return None


def _points_for_bracket(points_allowed: float, brackets: list[tuple[int, int | None, float]]) -> float:
    if pd.isna(points_allowed):
        return 0.0
    for low, high, value in brackets:
        if high is None:
            if points_allowed >= low:
                return value
        elif low <= points_allowed <= high:
            return value
    return 0.0


def compute_team_defense_points(
    team_defense_stats: pd.DataFrame, scoring_settings: dict
) -> tuple[pd.DataFrame, list[str]]:
    """
    Same idea as compute_points(), but for a team DEF/D-ST roster slot
    using team_defense_stats from data.nflverse.get_team_defense_stats().
    Handles the pts_allow_X bracket keys specially since only one bracket
    applies per team per game (not a per-unit multiply like other stats).
    """
    df = team_defense_stats.copy()
    df["league_points"] = 0.0
    unmapped: list[str] = []

    pts_allow_brackets = []

    for key, points_value in scoring_settings.items():
        if not points_value:
            continue

        bracket = _parse_pts_allow_key(key)
        if bracket is not None:
            pts_allow_brackets.append((bracket[0], bracket[1], points_value))
            continue

        if key == "blk_kick":
            available = [c for c in BLOCKED_KICK_COLUMNS if c in df.columns]
            if available:
                df["league_points"] += df[available].sum(axis=1) * points_value
            else:
                unmapped.append(key)
            continue

        column = TEAM_DEFENSE_KEY_MAP.get(key)
        if column is None or column not in df.columns:
            unmapped.append(key)
            continue

        df["league_points"] += df[column].fillna(0) * points_value

    if pts_allow_brackets and "points_allowed" in df.columns:
        df["league_points"] += df["points_allowed"].apply(
            lambda pa: _points_for_bracket(pa, pts_allow_brackets)
        )

    return df, sorted(set(unmapped))


def summarize_unmapped(scoring_settings: dict, unmapped_keys: list[str]) -> pd.DataFrame:
    """Small table for display: unmapped key + the point value it carries."""
    return pd.DataFrame(
        {
            "scoring_settings key": unmapped_keys,
            "point value": [scoring_settings.get(k) for k in unmapped_keys],
        }
    )
