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
    Counts each position's dedicated (non-flex) starting slots from
    roster_positions, e.g. {"QB": 1, "RB": 2, "WR": 2, "TE": 1}.
    """
    counts: dict[str, int] = {}
    exact_positions = {"QB", "RB", "WR", "TE", "LB", "DB", "DL", "K", "DEF"}
    for slot in league.get("roster_positions", []):
        if slot in exact_positions:
            counts[slot] = counts.get(slot, 0) + 1
    return counts


# Known Sleeper flex slot names -> the set of positions eligible to fill them.
FLEX_SLOT_ELIGIBILITY = {
    "FLEX": {"RB", "WR", "TE"},
    "WR_RB_FLEX": {"RB", "WR"},
    "WR_TE_FLEX": {"WR", "TE"},
    "REC_FLEX": {"WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
    "IDP_FLEX": {"LB", "DB", "DL"},
}


def get_position_groups(league: dict) -> tuple[list[dict], list[str]]:
    """
    Merges positions that share a FLEX-type slot into one group, since a
    player is only really "irreplaceable" relative to everyone eligible
    for the same slots -- not just same-labeled positions. Without this,
    an RB3 who's actually starting via FLEX (because he outproduces the
    team's WR/TE options) looks fully replaceable in isolation, when in
    practice removing him drops a real starter.

    Returns (groups, unrecognized_flex_slots):
      - groups: list of {"positions": set(...), "slots": int}, e.g. a
        standard roster with RB/RB/WR/WR/TE/FLEX(RB/WR/TE) becomes one
        group {"positions": {"RB","WR","TE"}, "slots": 6}, while QB (no
        flex sharing) stays its own group {"positions":{"QB"},"slots":1}.
      - unrecognized_flex_slots: any roster_positions entry that LOOKS
        like a flex-type slot (contains "FLEX") but isn't in
        FLEX_SLOT_ELIGIBILITY. Sleeper doesn't publish a complete list of
        every possible slot name, so a league with an unusual flex slot
        (a second FLEX variant, a differently-named IDP flex, etc.) could
        exist that this mapping hasn't seen yet. Rather than silently
        dropping that slot's capacity, the caller should surface this list
        so it's obvious the starter-impact numbers may be undercounting
        for that league until the mapping is extended -- same pattern as
        the "unmapped scoring keys" warning elsewhere in this app.
    """
    slot_counts = get_position_slot_counts(league)
    positions = set(slot_counts.keys())

    parent = {p: p for p in positions}

    def find(p):
        while parent[p] != p:
            p = parent[p]
        return p

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    flex_slot_list = []
    unrecognized_flex_slots = []
    seen_unrecognized = set()
    for slot in league.get("roster_positions", []):
        if slot in FLEX_SLOT_ELIGIBILITY:
            eligible = FLEX_SLOT_ELIGIBILITY[slot]
            eligible_present = eligible & positions
            if eligible_present:
                flex_slot_list.append((slot, eligible_present))
                eligible_list = list(eligible_present)
                for other in eligible_list[1:]:
                    union(eligible_list[0], other)
        elif "FLEX" in slot.upper() and slot not in seen_unrecognized:
            unrecognized_flex_slots.append(slot)
            seen_unrecognized.add(slot)

    groups: dict[str, dict] = {}
    for p in positions:
        root = find(p)
        groups.setdefault(root, {"positions": set(), "slots": 0})
        groups[root]["positions"].add(p)
        groups[root]["slots"] += slot_counts[p]

    for slot_name, eligible_present in flex_slot_list:
        representative = next(iter(eligible_present))
        root = find(representative)
        groups[root]["slots"] += 1

    return list(groups.values()), unrecognized_flex_slots


def _top_k_sum(
    performance: pd.DataFrame, player_ids: set, positions: set, k: int
) -> float:
    """Sum of the top-k eligible players' trailing avg_points across a set of positions."""
    pool = performance[
        performance["sleeper_id"].isin(player_ids)
        & performance["position"].isin(positions)
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
    position_groups: list[dict] | None = None,
) -> tuple[float, dict]:
    """
    For every position GROUP touched by the trade (a group merges positions
    that share a FLEX/SUPER_FLEX/IDP_FLEX slot -- see get_position_groups),
    compares the sum of your top-K eligible options across that whole group
    before vs. after the deal, where K is the group's total real starting
    capacity (exact slots + shared flex slots).

    This correctly credits/debits a player who starts via FLEX rather than
    a dedicated slot -- e.g. an RB3 who's actually your flex starter shows
    up properly when traded away, because he's evaluated against the
    combined RB/WR/TE pool sized to its true total slot count, not just
    counted (and likely dismissed) against a too-small "RB slots only" pool.

    If position_groups is not provided, falls back to one slot per exact
    position (no flex modeling) for backward compatibility.

    Returns (net_impact, per_group_breakdown) where breakdown keys are a
    "/"-joined label of the group's positions (e.g. "RB/WR/TE").
    """
    if position_groups is None:
        exact_positions = performance["position"].unique()
        position_groups = [{"positions": {p}, "slots": 1} for p in exact_positions]

    touched_positions = set(
        performance[performance["sleeper_id"].isin(send_ids + receive_ids)]["position"]
    )

    after_ids = (my_team_ids - set(send_ids)) | set(receive_ids)

    breakdown = {}
    net_impact = 0.0
    for group in position_groups:
        if not (group["positions"] & touched_positions):
            continue
        label = "/".join(sorted(group["positions"]))
        k = group["slots"]
        before = _top_k_sum(performance, my_team_ids, group["positions"], k)
        after = _top_k_sum(performance, after_ids, group["positions"], k)
        delta = after - before
        breakdown[label] = {"before": round(before, 2), "after": round(after, 2), "delta": round(delta, 2)}
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
    position_groups: list[dict] | None = None,
) -> pd.DataFrame:
    """Adds starter_impact (net points) and starter_impact_detail (per-group dict) columns."""
    if suggestions.empty:
        return suggestions

    impacts = []
    details = []
    for _, row in suggestions.iterrows():
        net, breakdown = compute_starter_impact(
            my_team_ids, row["you_send_ids"], row["you_receive_ids"], performance, position_groups
        )
        impacts.append(net)
        details.append(breakdown)

    suggestions = suggestions.copy()
    suggestions["starter_impact"] = impacts
    suggestions["starter_impact_detail"] = details
    return suggestions
