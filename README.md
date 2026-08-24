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

## Next steps (not built yet)

- Start/Sit rankings page (built on top of the scoring engine)
- Free agent comparison against your roster
- Breakout/trend detector (the "Puka Nacua" signal)
- Trade finder using dynasty value data (FantasyCalc/KTC)
- Scheduled data pulls (GitHub Action -> committed parquet/CSV) for
  slow-changing data: league settings, nflverse stats, dynasty values as an
  append-only time series
