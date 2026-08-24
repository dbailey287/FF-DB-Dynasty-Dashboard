"""
Breakout candidate detector -- the "Puka Nacua signal": players whose
underlying opportunity/efficiency is trending up faster than their draft
capital or dynasty market value would suggest, before that shift is fully
priced in.

This first version is built entirely from data we already have (no
external dynasty-value API): nflverse's weekly WOPR (weighted opportunity
rating -- combines target share and air yards share into one number, a
strong proxy for "how much this player's offense is funneled through him")
and the player ID crosswalk's draft capital (round/pick/year) and age.

The core idea: split the trailing window into an early half and a recent
half, and flag players whose opportunity rose meaningfully between the two
AND who came from Day 2/3 draft capital (or went undrafted) or are still
early in their career -- since that's the actual Puka Nacua pattern (low
investment, rising role, market hasn't caught up yet).
"""

import pandas as pd


def find_breakout_candidates(
    weekly_stats: pd.DataFrame,
    id_map: pd.DataFrame,
    weeks: list[int],
    positions: tuple[str, ...] = ("WR", "RB", "TE"),
    min_games: int = 3,
    max_draft_round: float = 3.0,
    max_years_since_draft: int = 3,
    season: int | None = None,
    top_n: int = 25,
) -> pd.DataFrame:
    """
    Returns up to top_n candidates sorted by opportunity trend (rising
    fastest first). A player qualifies as "low investment" if EITHER:
      - they have no draft_round on file (likely undrafted), OR
      - draft_round > max_draft_round (Day 3), OR
      - season - draft_year <= max_years_since_draft (still early-career,
        even if drafted higher -- covers a good Day 2 rookie/sophomore
        breaking out, not just deep-round afterthoughts)

    Needs at least 2 distinct weeks in `weeks` to compute a trend; returns
    an empty DataFrame with a clear reason otherwise (surfaced by the
    caller, not raised, since this is a normal "not enough data yet" case
    early in a season).
    """
    if len(set(weeks)) < 2:
        return pd.DataFrame()

    sorted_weeks = sorted(set(weeks))
    midpoint = len(sorted_weeks) // 2
    early_weeks = sorted_weeks[:midpoint] or sorted_weeks[:1]
    recent_weeks = sorted_weeks[midpoint:] or sorted_weeks[-1:]

    subset = weekly_stats[
        weekly_stats["week"].isin(sorted_weeks)
        & weekly_stats["position"].isin(positions)
        & weekly_stats["sleeper_id"].notna()
    ].copy()

    if subset.empty:
        return pd.DataFrame()

    games = subset.groupby("sleeper_id")["week"].count().rename("games")

    early = (
        subset[subset["week"].isin(early_weeks)]
        .groupby("sleeper_id")["wopr"]
        .mean()
        .rename("wopr_early")
    )
    recent = (
        subset[subset["week"].isin(recent_weeks)]
        .groupby("sleeper_id")["wopr"]
        .mean()
        .rename("wopr_recent")
    )
    overall_target_share = (
        subset.groupby("sleeper_id")["target_share"].mean().rename("avg_target_share")
    )

    combined = pd.concat([games, early, recent, overall_target_share], axis=1).reset_index()
    combined = combined[combined["games"] >= min_games]
    combined["wopr_trend"] = combined["wopr_recent"] - combined["wopr_early"]

    # Attach name/position/team/draft capital via the id_map crosswalk
    id_slim = id_map[
        ["sleeper_id", "name", "position", "team", "draft_round", "draft_pick", "draft_year", "age"]
    ].dropna(subset=["sleeper_id"]).copy()
    id_slim["sleeper_id"] = id_slim["sleeper_id"].apply(
        lambda x: str(int(x)) if pd.notna(x) else None
    )

    merged = combined.merge(id_slim, on="sleeper_id", how="left")

    if season is not None:
        merged["years_since_draft"] = season - merged["draft_year"]
    else:
        merged["years_since_draft"] = None

    def is_low_investment(row) -> bool:
        if pd.isna(row.get("draft_round")):
            return True  # undrafted
        if row["draft_round"] > max_draft_round:
            return True
        if row.get("years_since_draft") is not None and pd.notna(row["years_since_draft"]):
            if row["years_since_draft"] <= max_years_since_draft:
                return True
        return False

    merged["low_investment"] = merged.apply(is_low_investment, axis=1)
    candidates = merged[merged["low_investment"] & merged["wopr_trend"].notna()]

    candidates = candidates.sort_values("wopr_trend", ascending=False).head(top_n)

    display_cols = [
        "sleeper_id",
        "name",
        "position",
        "team",
        "wopr_early",
        "wopr_recent",
        "wopr_trend",
        "avg_target_share",
        "draft_round",
        "draft_pick",
        "draft_year",
        "age",
        "games",
    ]
    return candidates[display_cols].round(3).reset_index(drop=True)
