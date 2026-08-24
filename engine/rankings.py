"""
Turns per-week scored stats (from engine.scoring) into player-level trailing
averages, used by both the Start/Sit page (your roster) and the Free Agents
page (everyone available). A trailing average of league_points per player
over the last N played weeks.

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


def _combined_trailing_map(
    player_trailing: pd.DataFrame, defense_trailing: pd.DataFrame
) -> dict:
    combined = pd.concat([player_trailing, defense_trailing], ignore_index=True)
    return combined.set_index("sleeper_id")[["avg_points", "games"]].to_dict("index")


def build_player_table(
    player_ids: list[str],
    player_lookup: dict,
    player_trailing: pd.DataFrame,
    defense_trailing: pd.DataFrame,
    starters: set[str] | None = None,
) -> pd.DataFrame:
    """
    Core table builder shared by rank_roster() and rank_free_agents(): every
    player_id joined to name/position/team and trailing avg_points, sorted
    by position then avg_points desc. If starters is provided, adds a
    'starter' bool column.
    """
    trailing_map = _combined_trailing_map(player_trailing, defense_trailing)

    rows = []
    for pid in player_ids:
        info = player_lookup.get(pid, {"name": pid, "position": "UNK", "team": None})
        trailing = trailing_map.get(pid, {"avg_points": 0.0, "games": 0})
        row = {
            "player_id": pid,
            "name": info["name"],
            "position": info["position"],
            "team": info["team"],
            "avg_points": round(trailing["avg_points"], 2),
            "games_sampled": trailing["games"],
        }
        if starters is not None:
            row["starter"] = pid in starters
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values(["position", "avg_points"], ascending=[True, False]).reset_index(drop=True)


def rank_roster(
    roster: dict,
    player_lookup: dict,
    player_trailing: pd.DataFrame,
    defense_trailing: pd.DataFrame,
) -> pd.DataFrame:
    """Start/Sit table for one roster: every rostered player + starter flag."""
    player_ids = roster.get("players") or []
    starters = set(roster.get("starters") or [])
    return build_player_table(player_ids, player_lookup, player_trailing, defense_trailing, starters)


def rank_free_agents(
    free_agents: dict,
    player_lookup: dict,
    player_trailing: pd.DataFrame,
    defense_trailing: pd.DataFrame,
    min_games: int = 1,
) -> pd.DataFrame:
    """
    Trailing-average table for every free agent in the league. min_games
    filters out players with too little recent data to be a meaningful
    signal (e.g. someone who just returned from injury this week).
    """
    player_ids = list(free_agents.keys())
    table = build_player_table(player_ids, player_lookup, player_trailing, defense_trailing)
    if table.empty:
        return table
    return table[table["games_sampled"] >= min_games].reset_index(drop=True)


def find_upgrades(
    my_roster_ranked: pd.DataFrame, free_agents_ranked: pd.DataFrame, min_games: int = 2
) -> pd.DataFrame:
    """
    For each position, compares your rostered players to available free
    agents and flags any free agent outscoring your WORST rostered player
    at that position (i.e. someone you could add outright, or at minimum
    a real bench upgrade). Returns one row per suggested upgrade, sorted by
    point differential descending -- the most clear-cut upgrades first.

    Deliberately compares against your worst rostered player rather than
    your best, since "beats my best starter" is a much higher and less
    useful bar -- most real value gets found in replacing weak bench/depth
    pieces, not unseating a clear starter.
    """
    if my_roster_ranked.empty or free_agents_ranked.empty:
        return pd.DataFrame()

    rows = []
    for position in my_roster_ranked["position"].unique():
        my_players = my_roster_ranked[my_roster_ranked["position"] == position]
        worst_rostered = my_players["avg_points"].min()
        worst_rostered_name = my_players.loc[my_players["avg_points"].idxmin(), "name"]

        candidates = free_agents_ranked[
            (free_agents_ranked["position"] == position)
            & (free_agents_ranked["games_sampled"] >= min_games)
            & (free_agents_ranked["avg_points"] > worst_rostered)
        ]

        for _, fa in candidates.iterrows():
            rows.append(
                {
                    "position": position,
                    "free_agent": fa["name"],
                    "fa_avg_points": fa["avg_points"],
                    "replaces": worst_rostered_name,
                    "replaces_avg_points": round(worst_rostered, 2),
                    "point_diff": round(fa["avg_points"] - worst_rostered, 2),
                }
            )

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values("point_diff", ascending=False).reset_index(drop=True)
