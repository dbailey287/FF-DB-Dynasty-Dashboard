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

## Next steps (not built yet)

- Scoring engine (`engine/scoring.py`) — apply each league's actual
  scoring_settings to nflverse stats to produce projected points
- Start/Sit rankings page
- Free agent comparison against your roster
- Breakout/trend detector (the "Puka Nacua" signal)
- Trade finder using dynasty value data (FantasyCalc/KTC)
- Scheduled data pulls (GitHub Action -> committed parquet/CSV) for
  slow-changing data: league settings, nflverse stats, dynasty values as an
  append-only time series
