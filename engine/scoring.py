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
    # IDP tackling
    "idp_tkl_solo": "def_tackles_solo",
    "idp_tkl_ast": "def_tackles_with_assist",
    "idp_tkl_loss": "def_tackles_for_loss",
    # IDP pass rush
    "idp_sack": "def_sacks",
    "idp_qb_hit": "def_qb_hits",
    # IDP coverage / turnovers
    "idp_int": "def_interceptions",
    "idp_pass_def": "def_pass_defended",
    "idp_ff": "def_fumbles_forced",
    "idp_fum_rec": "def_fumbles",
    "idp_def_td": "def_tds",
    "idp_safe": "def_safeties",
}


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

        column = STAT_KEY_MAP.get(key)
        if column is None or column not in df.columns:
            unmapped.append(key)
            continue

        df["league_points"] += df[column].fillna(0) * points_per_unit

    return df, sorted(set(unmapped))


def summarize_unmapped(scoring_settings: dict, unmapped_keys: list[str]) -> pd.DataFrame:
    """Small table for display: unmapped key + the point value it carries."""
    return pd.DataFrame(
        {
            "scoring_settings key": unmapped_keys,
            "point value": [scoring_settings.get(k) for k in unmapped_keys],
        }
    )
