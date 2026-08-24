"""
Turns per-week scored stats (from engine.scoring) into a Start/Sit view for
a specific roster: a trailing average of league_points per player over the
last N played weeks, split starters vs. bench and grouped by position.

Handles one Sleeper quirk: a team DEF/D-ST roster slot is represented in
Sleeper's player IDs as the team's abbreviation itself (e.g. "SEA", "DEN")
rather than a normal player_id -- so those get looked up against team
defense scores instead of individual player scores.
"""

import pandas as pd


def build_player_lookup(all_players: dict) -> dict:
    """
    Sleeper's full player DB -> {player_id: {"name", "position", "team"}}.
    Team DEF entries in Sleeper's player DB are keyed by team abbreviation
    and have position == "DEF".
    """
    lookup = {}
    for pid, p in all_players.items():
        if p.get("position") == "DEF":
            name = p.get("first_name") or pid  # Sleeper stores team name oddly here
        else:
            name = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
        lookup[pid] = {
            "name": name or pid,
            "position": p.get("position"),
            "team": p.get("team"),
        }
    return lookup


def compute_trailing_player_scores(
    scored_weekly: pd.DataFrame, weeks: list[int]
) -> pd.DataFrame:
    """
    Average league_points per sleeper_id over the given weeks (individual
    offense + IDP players). Returns columns: sleeper_id, avg_points, games.
    """
    subset = scored_weekly[
        scored_weekly["week"].isin(weeks) & scored_weekly["sleeper_id"].notna()
    ]
    grouped = (
        subset.groupby("sleeper_id")["league_points"]
        .agg(avg_points="mean", games="count")
        .reset_index()
    )
    return grouped


def compute_trailing_defense_scores(
    scored_defense: pd.DataFrame, weeks: list[int]
) -> pd.DataFrame:
    """
    Same idea for team DEF/D-ST, keyed by team abbreviation (which doubles
    as the Sleeper player_id for a team defense).
    """
    subset = scored_defense[scored_defense["week"].isin(weeks)]
    grouped = (
        subset.groupby("team")["league_points"]
        .agg(avg_points="mean", games="count")
        .reset_index()
        .rename(columns={"team": "sleeper_id"})
    )
    return grouped


def rank_roster(
    roster: dict,
    player_lookup: dict,
    player_trailing: pd.DataFrame,
    defense_trailing: pd.DataFrame,
) -> pd.DataFrame:
    """
    Builds the Start/Sit table for one roster: every rostered player_id
    joined to their trailing average score, name, position, and whether
    they're currently a starter, sorted by position then avg_points desc.
    """
    player_ids = roster.get("players") or []
    starters = set(roster.get("starters") or [])

    combined_trailing = pd.concat([player_trailing, defense_trailing], ignore_index=True)
    trailing_map = combined_trailing.set_index("sleeper_id")[["avg_points", "games"]].to_dict("index")

    rows = []
    for pid in player_ids:
        info = player_lookup.get(pid, {"name": pid, "position": "UNK", "team": None})
        trailing = trailing_map.get(pid, {"avg_points": 0.0, "games": 0})
        rows.append(
            {
                "player_id": pid,
                "name": info["name"],
                "position": info["position"],
                "team": info["team"],
                "avg_points": round(trailing["avg_points"], 2),
                "games_sampled": trailing["games"],
                "starter": pid in starters,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values(["position", "avg_points"], ascending=[True, False]).reset_index(drop=True)
