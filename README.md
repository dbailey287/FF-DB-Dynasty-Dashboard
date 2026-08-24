# Dynasty Dashboard

Streamlit dashboard covering two Sleeper dynasty leagues: **Sensitivity Training**
(IDP, LB/DB + 2 flex-D, tackle-heavy scoring, .5 PPR) and **Queen City Kings**
(offense only, 1 PPR).

## Setup

1. `pip install -r requirements.txt`
2. Open `config.py` and replace `REPLACE_WITH_LEAGUE_ID` for both leagues with
   the real Sleeper league IDs. Find these in the URL when viewing a league
   on sleeper.com (`sleeper.com/leagues/<LEAGUE_ID>/team`) or in the app under
   League > Settings.
3. `streamlit run app.py`

## What's built so far (Step 1)

- `data/sleeper.py` — connector for Sleeper's public read-only API: league
  settings, rosters, users, free agents, the full player DB (cached locally,
  refreshed at most daily per Sleeper's guidance).
- `app.py` — landing page with a league switcher (stored in session state so
  every other page reads the same active league).
- `pages/1_League_Settings.py` — pulls live scoring_settings and
  roster_positions for the active league, groups them into readable buckets
  (passing/rushing/receiving/IDP tackling/IDP pass rush/IDP coverage/kicking),
  and for the IDP league specifically sums tackle-related vs.
  coverage/turnover-related point values to confirm the tackle-heavy,
  LB > DB scoring dynamic directly from the API rather than assuming it.

## Step 2 — Scoring engine (built)

- `data/nflverse.py` — pulls weekly player stats (offense + IDP tackling/
  pass-rush/coverage) via `nflreadpy` (NOT the older `nfl_data_py`, which
  pins pandas<2.0 and fails to build on Python 3.13+). Also pulls the
  `sleeper_id` crosswalk table (joins Sleeper rosters to nflverse stats),
  and team-level defense/special-teams stats + schedule scores (for a
  standard team DEF/D-ST roster slot, joined to points-allowed). All
  cached locally as parquet.
- `engine/scoring.py` — two scoring paths:
  - `compute_points()` — individual players (offense + IDP), using
    `STAT_KEY_MAP`. Confirmed against real Sleeper scoring_settings: Sleeper
    does NOT prefix IDP keys with "idp_" (e.g. it's `tkl_solo`, `sack`,
    `int`, `ff`, `fum_rec` — not `idp_tkl_solo` etc.).
  - `compute_team_defense_points()` — team DEF/D-ST slot, using
    `TEAM_DEFENSE_KEY_MAP` plus special handling for `pts_allow_X` bracket
    keys (only one bracket applies per team per game) and `blk_kick`
    (summed across punt/PAT/FG blocks, since nflverse splits these).
  - Any scoring key with a non-zero point value not handled by *either*
    path gets flagged rather than silently dropped.
- `pages/2_Scoring_Engine_Test.py` — sanity-check page with tabs for
  individual players and team defense. Pick a season/week, see top
  scorers, and see any truly-unmapped scoring keys. **Run this before
  trusting the numbers** for each league.

## Step 3 — Start/Sit rankings (built)

- `config.py` — added `SLEEPER_USERNAME` so the app knows which roster in
  each league is yours.
- `data/sleeper.py` — `get_user()` and `get_my_roster()` find your roster
  by matching your username's Sleeper user_id against each league's
  roster owner_ids.
- `data/nflverse.py` — fixed a real dtype bug in `attach_sleeper_ids()`:
  the crosswalk's `sleeper_id` column comes through as float64 (due to
  NaNs), which would silently fail to match Sleeper's actual string player
  IDs from roster data. Normalized to clean strings.
- `engine/rankings.py` — builds a name/position/team lookup from Sleeper's
  player DB (handling team DEF entries, which Sleeper keys by team
  abbreviation rather than a normal player_id), computes each rostered
  player's trailing average `league_points` over a chosen window of
  recent weeks, and ranks the roster by position.
- `pages/3_Start_Sit.py` — pick season/week/trailing-window, see your
  current starters ranked by trailing average, plus a full-roster view by
  position to spot bench players outscoring a starter.

**Known limitation:** this ranks by *trailing average performance*, not a
true forward-looking projection (nflverse doesn't publish projections) —
it doesn't yet account for opponent matchup, injury status, or bye weeks.
Good enough to flag "who's been producing," not yet a full projection
system.

## Step 4 — Free Agents (built)

- `data/sleeper.py` — `get_free_agents()` now also includes K and DEF
  (was missing these -- Queen City Kings clearly rosters both).
- `engine/rankings.py` — refactored around a shared `build_player_table()`
  so the same trailing-average logic powers both Start/Sit and Free
  Agents. Added `rank_free_agents()` and `find_upgrades()`.
- `pages/4_Free_Agents.py` — two views:
  - **Suggested upgrades** — for each position, compares available free
    agents to your *worst* rostered player at that position (deliberately
    not your best -- most real value is in replacing weak depth, not
    unseating a clear starter) and flags any free agent who'd be an
    improvement.
  - **Browse free agents** — full ranked list by position, same trailing-
    average scoring as everywhere else, with a min-games filter to screen
    out tiny endorsements from a single spot start.

## Root-cause fix: injury awareness (built)

Answers "can we tell WHY a player shows 0 games instead of just guessing
from the number?" -- yes, via `nflreadpy.load_injuries()`.

- `data/nflverse.py` — `get_injury_reports()` pulls weekly injury report
  data (report_status: Out/Doubtful/Questionable + the actual injury type).
  `get_latest_injury_status()` reduces that to one current status per
  player as of a given week, keyed by sleeper_id.
- `engine/rankings.py` — `build_player_table()` (and therefore
  `rank_roster()`/`rank_free_agents()`) now optionally adds
  `injury_status`/`injury` columns, so a 0.0 average shows *why* (e.g.
  "Out - Knee") instead of looking like a data gap. `find_upgrades()` now
  also excludes free agents currently listed Out/Doubtful/IR from being
  recommended -- symmetric fix to the rostered-player-baseline bug, since
  recommending an injured free agent as an "upgrade" would be the same
  root problem in the other direction.
- Both `pages/3_Start_Sit.py` and `pages/4_Free_Agents.py` now display
  injury status/type alongside every player's trailing average.

Note: `games_sampled` itself was already a reasonable proxy for "games
missed" (nflverse's weekly stats only include a row for players who
actually played), so the earlier min_games fix already addressed the
core bug -- this adds the *explanation* on top, and additionally protects
the free-agent side of the recommendation.

## Benched vs. injured distinction (built)

Direct answer to "how do we tell a benched player from an injured one":
nflverse's weekly roster status (`load_rosters_weekly`) has real status
codes -- ACT/RES/INA/DEV/CUT/RET/TRD/EXE -- combined with the injury
report from the previous round.

- `data/nflverse.py` — `get_weekly_roster_status()` pulls this (already
  keyed by sleeper_id directly, no crosswalk needed).
  `get_availability_reasons()` combines it with the injury report into one
  clear label per player:
  - `RES` -> "Injured Reserve", `DEV` -> "Practice Squad", etc.
  - Has an injury report entry -> "Out - Knee" / "Questionable - Ankle" / etc.
  - `INA` with no injury report -> "Inactive (healthy scratch/coach's decision)"
  - `ACT` with no injury report -> **blank** -- this is the genuinely
    healthy-but-benched case, now distinguishable from injury for the
    first time.
- `engine/rankings.py` — `injury_lookup` renamed to `availability_lookup`
  throughout; tables now show one `status` column instead of two separate
  injury columns. `find_upgrades()`'s exclusion logic now matches on
  keywords within the combined status string (Out/Doubtful/Injured
  Reserve) rather than an exact status code, since the string is now
  richer (e.g. "Out - Knee") -- a blank status (healthy, benched) is
  never excluded.
- Both Start/Sit and Free Agents pages display the single `status` column.

## Step 5 — Breakout detector (built)

The "Puka Nacua signal" -- built entirely from data already on hand, no
external dynasty-value API needed for this first pass.

- `engine/breakouts.py` — `find_breakout_candidates()` splits a week window
  into early/recent halves, computes the change in WOPR (Weighted
  Opportunity Rating -- nflverse's combined target-share + air-yards-share
  metric) between them, and filters to players who are either undrafted,
  Day 3 picks, or still within N years of being drafted (covers a good
  Day 2 rookie/sophomore breaking out, not just deep-round afterthoughts).
  Sorted by rising-opportunity-fastest.
- `pages/5_Breakouts.py` — configurable week window, min games, and draft-
  capital thresholds; WR/RB/TE only (WOPR is a receiving-opportunity
  metric, not meaningful for IDP).
- **Validated against real 2025 data**: Puka Nacua himself appears in the
  candidate list (5th-round pick, rising WOPR) -- a solid sanity check
  that the detector catches the exact pattern it's designed for.

**Known limitation:** this flags a *changing role*, not a guaranteed
future star, and doesn't yet cross-reference an actual dynasty market
value (FantasyCalc/KeepTradeCut) to confirm the market hasn't already
priced the change in -- that's a natural next enhancement once the trade
finder (which needs that same value data) is built.

- `data/sleeper.py` — `get_player_ownership_map()` maps every rostered
  player_id in the league to their fantasy team's name (or "Free Agent"
  if unrostered).
- `pages/5_Breakouts.py` — added a Show toggle (All / Free agents only /
  Rostered only) and a `fantasy_team` column, so a breakout candidate
  sitting on another manager's bench (a buy-low trade target) is now
  distinguishable from one actually available on waivers.

## Step 6 — Trade Finder (built)

Uses FantasyCalc dynasty values -- a free, public, unauthenticated API
(no key needed) confirmed live during development. Each player entry
includes `sleeperId` directly, so no ID crosswalk is needed for this
source (unlike the nflverse-based data elsewhere in the app).

- `data/fantasycalc.py` — `get_dynasty_values()` pulls current dynasty
  trade values. `infer_fantasycalc_params()` derives the required query
  params (numQbs/numTeams/ppr) from each league's REAL Sleeper settings
  rather than hardcoding them -- e.g. Sensitivity Training correctly comes
  back as 1QB/10-team/.5PPR.
  **Caveat:** this sandbox's network is locked to package registries, so
  the live HTTP call itself couldn't be tested end-to-end here -- verified
  the endpoint works via a direct fetch during development, and the
  parsing logic is tested against a saved real response
  (`data/fixtures/fantasycalc_sample.json`), but the actual `requests.get`
  call needs confirming once running locally with normal internet access.
- `engine/trades.py` — computes each team's total dynasty value from real
  rosters, then searches 1-for-1 and 2-for-2 (configurable) combinations
  between your team and a chosen opponent, keeping only trades within a
  fairness tolerance or tilted your way up to a configurable max. Ranked
  closest-to-even first (most likely to be accepted), not most lopsided.
  **Also computes real starter lineup impact**: for every position touched
  by a trade, compares the sum of your top-K eligible players at that
  position (K = that position's actual starting roster slot count) before
  vs. after the deal -- correctly credits upgrading a weak starter (e.g.
  WR2) even when a stronger WR1 is untouched, and correctly excludes
  injured/IR/practice-squad players from counting as a real lineup option
  either lost or gained.
- `pages/6_Trade_Finder.py` — shows suggested trades across **every**
  opponent at once (was previously one-team-at-a-time via a selectbox),
  sorted by starter lineup impact first since that's what actually
  matters, with dynasty value shown as secondary context.

**Known limitations:**
- pure value + performance math -- doesn't know a manager's contend/
  rebuild timeline or whether a proposed player is actually droppable

### Fix: FLEX slots weren't modeled, causing a bad recommendation

Reported real-world bug: the tool suggested trading away Cam Skattebo (a
real flex starter) + a backup TE for two backup QBs, and showed it as a
**positive** starter impact -- because the original logic only measured
capacity per exact position label ("RB" slots specifically), so a player
who earns his start via FLEX rather than a dedicated slot looked fully
replaceable in isolation.

- `engine/trades.py` — replaced exact-position-only slot counting with
  `get_position_groups()`, which merges positions that share a FLEX/
  Superflex/IDP_FLEX slot into one group (e.g. a standard RB/RB/WR/WR/TE/
  FLEX roster becomes one merged {RB, WR, TE} group sized 6, not three
  separate pools of 2/2/1). `compute_starter_impact()` now compares top-K
  sums across the whole merged group, correctly capturing a FLEX starter's
  real value. Verified against the exact reported scenario -- now
  correctly shows a real downgrade instead of a false positive.
- Also fixed: `pages/6_Trade_Finder.py`'s default "through week" was
  hardcoded to week 3, badly understating any player (especially a
  rookie) whose role emerged later in the season -- now defaults to the
  most recent week with real data available (capped at 18, since
  nflverse's week numbering extends into playoffs up to ~22, which would
  have exceeded the widget's bounds and crashed).

## Next steps (not built yet)

- Scheduled data pulls (GitHub Action -> committed parquet/CSV) for
  slow-changing data: league settings, nflverse stats, dynasty values as an
  append-only time series
