"""
Trade finder: uses FantasyCalc dynasty values to compute each team's total
roster value, then proposes 1-for-1 and 2-for-1 trade packages between your
team and another team where the value gap falls within a chosen "fairness"
band -- either genuinely even, or tilted toward you by a configurable margin.
"""

import itertools

import pandas as pd


def build_team_rosters_with_values(
    rosters: list[dict],
    users: list[dict],
    player_lookup: dict,
    dynasty_values: pd.DataFrame,
) -> dict:
    """
    Returns {team_name: DataFrame of that team's players with dynasty
    value, name, position}. Players FantasyCalc doesn't track (e.g. a
    team DEF, or someone too deep to have a value) show dynasty_value 0
    rather than being dropped, so roster totals aren't silently short.
    """
    value_by_sleeper_id = dynasty_values.set_index("sleeper_id")["dynasty_value"].to_dict()

    team_name_by_owner = {}
    for u in users:
        team_name_by_owner[u["user_id"]] = (
            (u.get("metadata") or {}).get("team_name") or u.get("display_name") or u.get("user_id")
        )

    team_rosters = {}
    for r in rosters:
        team_name = team_name_by_owner.get(r.get("owner_id"), "Unknown Team")
        rows = []
        for pid in r.get("players") or []:
            info = player_lookup.get(pid, {"name": pid, "position": "UNK"})
            rows.append(
                {
                    "player_id": pid,
                    "name": info["name"],
                    "position": info["position"],
                    "dynasty_value": value_by_sleeper_id.get(pid, 0) or 0,
                }
            )
        team_rosters[team_name] = pd.DataFrame(rows)

    return team_rosters


def find_trade_suggestions(
    my_team: pd.DataFrame,
    their_team: pd.DataFrame,
    max_package_size: int = 2,
    fairness_tolerance: float = 0.15,
    favor_me_max: float = 0.35,
    top_n: int = 15,
) -> pd.DataFrame:
    """
    Generates candidate trades of up to max_package_size players per side,
    swapping from my_team to their_team and vice versa, keeping only trades
    where the value gap is within fairness_tolerance (a genuinely fair
    trade) OR tilted in your favor by up to favor_me_max (you gain more
    value than you give, but not so much it's an obvious lopsided ask
    unlikely to be accepted).

    Only single-direction packages are built (N of my players for M of
    theirs, not multi-piece both ways) to keep the combinatorics sane --
    real trade talks usually start from a simple package anyway.

    Returns a DataFrame sorted by "fairness" first (closest to even) then
    by how favorable it is to you, so the top rows are the trades most
    likely to actually get accepted.
    """
    if my_team.empty or their_team.empty:
        return pd.DataFrame()

    my_team = my_team[my_team["dynasty_value"] > 0]
    their_team = their_team[their_team["dynasty_value"] > 0]

    results = []

    for my_size in range(1, max_package_size + 1):
        for their_size in range(1, max_package_size + 1):
            # Skip 1-for-1 combos already covered and avoid huge blowup
            # (e.g. 2-for-2 from large rosters) -- cap combinations checked
            my_combos = list(itertools.combinations(my_team.itertuples(), my_size))
            their_combos = list(itertools.combinations(their_team.itertuples(), their_size))

            for my_group in my_combos:
                my_value = sum(p.dynasty_value for p in my_group)
                for their_group in their_combos:
                    their_value = sum(p.dynasty_value for p in their_group)
                    if my_value == 0 or their_value == 0:
                        continue

                    # Ratio of what you'd receive vs. what you'd give
                    ratio = their_value / my_value
                    gap_pct = abs(ratio - 1)

                    is_fair = gap_pct <= fairness_tolerance
                    is_favor_me = 1 < ratio <= 1 + favor_me_max

                    if not (is_fair or is_favor_me):
                        continue

                    results.append(
                        {
                            "you_send": ", ".join(p.name for p in my_group),
                            "you_send_value": round(my_value),
                            "you_receive": ", ".join(p.name for p in their_group),
                            "you_receive_value": round(their_value),
                            "value_diff_pct": round((ratio - 1) * 100, 1),
                            "assessment": "Favors you" if ratio > 1 + fairness_tolerance else "Fair",
                        }
                    )

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results).drop_duplicates(subset=["you_send", "you_receive"])
    # Rank by closeness to a truly even trade first -- a near-0% diff is
    # the most plausible/acceptable deal; larger favor-me percentages rank
    # lower even though they're still "allowed," since a leaguemate is far
    # more likely to accept something close to fair than a trade sitting
    # at the edge of the configured favor_me_max.
    df["_abs_diff"] = df["value_diff_pct"].abs()
    df = df.sort_values("_abs_diff").drop(columns="_abs_diff").head(top_n).reset_index(drop=True)
    return df
