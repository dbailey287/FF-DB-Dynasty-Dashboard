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
  `sleeper_id` crosswalk table needed to join Sleeper rosters to nflverse
  stats. Both cached locally as parquet.
- `engine/scoring.py` — applies a league's real `scoring_settings` to those
  stats to compute actual weekly fantasy points. `STAT_KEY_MAP` maps known
  Sleeper scoring keys to nflverse columns; any scoring key with a non-zero
  point value that isn't mapped gets flagged rather than silently dropped.
- `pages/2_Scoring_Engine_Test.py` — sanity-check page: pick a week, see
  top scorers by the league's real scoring, and see any unmapped scoring
  keys that need `STAT_KEY_MAP` extended. **Run this before trusting the
  numbers** — check the "unmapped keys" warning against each league's real
  scoring_settings.

## Next steps (not built yet)

- Start/Sit rankings page (built on top of the scoring engine)
- Free agent comparison against your roster
- Breakout/trend detector (the "Puka Nacua" signal)
- Trade finder using dynasty value data (FantasyCalc/KTC)
- Scheduled data pulls (GitHub Action -> committed parquet/CSV) for
  slow-changing data: league settings, nflverse stats, dynasty values as an
  append-only time series
