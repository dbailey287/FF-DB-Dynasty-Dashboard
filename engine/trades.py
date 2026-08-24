"""
Trade finder: uses FantasyCalc dynasty values to compute each team's total
roster value, then proposes 1-for-1 and 2-for-2 (configurable) trade
packages between your team and another team where the value gap falls
within a chosen "fairness" band -- either genuinely even, or tilted toward
you by a configurable margin.

Also computes real STARTER LINEUP IMPACT for each suggestion: for every
position touched by a trade, compares your best available (healthy,
actually playing) option at that position before vs. after the deal,
using the same trailing-average performance + availability data as
Start/Sit and Free Agents. This is the part that answers "does this
actually make my starting lineup better, not just richer on paper."
"""

import itertools

import pandas as pd

# Statuses that disqualify a player from counting as a viable starter
# option right now -- matches the exclusion logic used elsewhere (Free
# Agents' find_upgrades) for consistency. A blank status (healthy, just
# not playing) is NOT in this list -- that player is still a real option.
UNAVAILABLE_STATUS_KEYWORDS = ("Out", "Doubtful", "Injured Reserve", "Practice Squad")


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


def build_league_performance_table(
    player_lookup: dict,
    player_trailing: pd.DataFrame,
    defense_trailing: pd.DataFrame,
    availability_lookup: dict,
) -> pd.DataFrame:
    """
    One row per player league-wide (not just your roster) with trailing
    avg_points, games_sampled, status, and whether they're currently a
    viable starter option (eligible). This lets starter-impact math look
    up ANY player's performance regardless of who currently owns them --
    needed since a trade target comes from an opponent's roster, not yours.
    """
    combined = pd.concat([player_trailing, defense_trailing], ignore_index=True)
    combined = combined.rename(columns={"games": "games_sampled"})

    rows = []
    for _, row in combined.iterrows():
        pid = row["sleeper_id"]
        info = player_lookup.get(pid, {"name": pid, "position": "UNK"})
        status = availability_lookup.get(pid, "")
        eligible = row["games_sampled"] > 0 and not (
            status and any(kw in status for kw in UNAVAILABLE_STATUS_KEYWORDS)
        )
        rows.append(
            {
                "sleeper_id": pid,
                "name": info["name"],
                "position": info["position"],
                "avg_points": row["avg_points"],
                "games_sampled": row["games_sampled"],
                "status": status,
                "eligible": eligible,
            }
        )
    return pd.DataFrame(rows)


def get_position_slot_counts(league: dict) -> dict:
    """
    Counts each position's dedicated starting slots from roster_positions
    (e.g. {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "LB": 3, "DB": 2}).
    Deliberately excludes FLEX/SUPER_FLEX/IDP_FLEX/BN -- those are shared
    across multiple positions and correctly modeling them requires a full
    lineup optimizer, which is out of scope here. This means the resulting
    counts are a lower bound on true starting capacity at flex-eligible
    positions, not the exact number -- see the note in compute_starter_impact.
    """
    counts: dict[str, int] = {}
    exact_positions = {"QB", "RB", "WR", "TE", "LB", "DB", "DL", "K", "DEF"}
    for slot in league.get("roster_positions", []):
        if slot in exact_positions:
            counts[slot] = counts.get(slot, 0) + 1
    return counts


def _top_k_sum_at_position(
    performance: pd.DataFrame, player_ids: set, position: str, k: int
) -> float:
    """Sum of the top-k eligible players' trailing avg_points at a position (0 if none/fewer than k)."""
    pool = performance[
        performance["sleeper_id"].isin(player_ids)
        & (performance["position"] == position)
        & performance["eligible"]
    ]
    if pool.empty:
        return 0.0
    top_k = pool.nlargest(k, "avg_points")
    return top_k["avg_points"].sum()


def compute_starter_impact(
    my_team_ids: set,
    send_ids: list,
    receive_ids: list,
    performance: pd.DataFrame,
    position_slot_counts: dict | None = None,
) -> tuple[float, dict]:
    """
    For every position touched by the trade, compares the sum of your top-K
    eligible options at that position before vs. after the deal, where K is
    that position's actual number of starting roster slots (from
    get_position_slot_counts). This correctly credits upgrading a weak
    starter (e.g. WR2) even when your WR1 is untouched -- comparing only
    the single best player per position (an earlier version of this) missed
    exactly that case.

    LIMITATION: FLEX/SUPER_FLEX/IDP_FLEX slots aren't modeled (see
    get_position_slot_counts) -- a trade that improves a player who'd only
    ever play in a FLEX spot may be undercounted. If position_slot_counts
    is not provided, defaults to 1 per position (same as comparing only
    the single best, for backward compatibility).

    Returns (net_impact, per_position_breakdown).
    """
    if position_slot_counts is None:
        position_slot_counts = {}

    touched_positions = performance[
        performance["sleeper_id"].isin(send_ids + receive_ids)
    ]["position"].unique()

    after_ids = (my_team_ids - set(send_ids)) | set(receive_ids)

    breakdown = {}
    net_impact = 0.0
    for position in touched_positions:
        k = position_slot_counts.get(position, 1)
        before = _top_k_sum_at_position(performance, my_team_ids, position, k)
        after = _top_k_sum_at_position(performance, after_ids, position, k)
        delta = after - before
        breakdown[position] = {"before": round(before, 2), "after": round(after, 2), "delta": round(delta, 2)}
        net_impact += delta

    return round(net_impact, 2), breakdown


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
    trade) OR tilted in your favor by up to favor_me_max.

    Only single-direction packages are built (N of my players for M of
    theirs) to keep the combinatorics sane.

    Returns a DataFrame including send_ids/receive_ids (for starter-impact
    lookup downstream) sorted by closeness to a truly even trade first.
    """
    if my_team.empty or their_team.empty:
        return pd.DataFrame()

    my_team = my_team[my_team["dynasty_value"] > 0]
    their_team = their_team[their_team["dynasty_value"] > 0]

    results = []

    for my_size in range(1, max_package_size + 1):
        for their_size in range(1, max_package_size + 1):
            my_combos = list(itertools.combinations(my_team.itertuples(), my_size))
            their_combos = list(itertools.combinations(their_team.itertuples(), their_size))

            for my_group in my_combos:
                my_value = sum(p.dynasty_value for p in my_group)
                for their_group in their_combos:
                    their_value = sum(p.dynasty_value for p in their_group)
                    if my_value == 0 or their_value == 0:
                        continue

                    ratio = their_value / my_value
                    gap_pct = abs(ratio - 1)

                    is_fair = gap_pct <= fairness_tolerance
                    is_favor_me = 1 < ratio <= 1 + favor_me_max

                    if not (is_fair or is_favor_me):
                        continue

                    results.append(
                        {
                            "you_send": ", ".join(p.name for p in my_group),
                            "you_send_ids": [p.player_id for p in my_group],
                            "you_send_value": round(my_value),
                            "you_receive": ", ".join(p.name for p in their_group),
                            "you_receive_ids": [p.player_id for p in their_group],
                            "you_receive_value": round(their_value),
                            "value_diff_pct": round((ratio - 1) * 100, 1),
                            "assessment": "Favors you" if ratio > 1 + fairness_tolerance else "Fair",
                        }
                    )

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results).drop_duplicates(subset=["you_send", "you_receive"])
    df["_abs_diff"] = df["value_diff_pct"].abs()
    df = df.sort_values("_abs_diff").drop(columns="_abs_diff").head(top_n).reset_index(drop=True)
    return df


def annotate_starter_impact(
    suggestions: pd.DataFrame,
    my_team_ids: set,
    performance: pd.DataFrame,
    position_slot_counts: dict | None = None,
) -> pd.DataFrame:
    """Adds starter_impact (net points) and starter_impact_detail (per-position dict) columns."""
    if suggestions.empty:
        return suggestions

    impacts = []
    details = []
    for _, row in suggestions.iterrows():
        net, breakdown = compute_starter_impact(
            my_team_ids, row["you_send_ids"], row["you_receive_ids"], performance, position_slot_counts
        )
        impacts.append(net)
        details.append(breakdown)

    suggestions = suggestions.copy()
    suggestions["starter_impact"] = impacts
    suggestions["starter_impact_detail"] = details
    return suggestions
