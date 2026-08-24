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

## Next steps (not built yet)

- Breakout detector (the "Puka Nacua" signal -- efficiency/usage trending
  up faster than draft capital/dynasty value)
- Trade finder using dynasty value data (FantasyCalc/KTC)
- Scheduled data pulls (GitHub Action -> committed parquet/CSV) for
  slow-changing data: league settings, nflverse stats, dynasty values as an
  append-only time series
