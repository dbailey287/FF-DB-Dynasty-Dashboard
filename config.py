"""
League configuration.

Fill in the real Sleeper league IDs below. You can find a league's ID in the
URL when viewing it on sleeper.com: sleeper.com/leagues/<LEAGUE_ID>/team
or in the app under League > Settings (scroll to the bottom).

league_type should be "idp" or "redraft_style" (no IDP) -- this just controls
which pages/logic apply, actual scoring is always pulled live from the API.
"""

LEAGUES = {
    "sensitivity_training": {
        "display_name": "Sensitivity Training",
        "league_id": "REPLACE_WITH_LEAGUE_ID",
        "league_type": "idp",  # LB/DB + 2 flex-D spots, tackle-heavy, .5 PPR
    },
    "queen_city_kings": {
        "display_name": "Queen City Kings",
        "league_id": "REPLACE_WITH_LEAGUE_ID",
        "league_type": "offense_only",  # 1 PPR, no IDP
    },
}

SLEEPER_API_BASE = "https://api.sleeper.app/v1"

# Local cache locations
CACHE_DIR = "data/cache"
PLAYERS_CACHE_PATH = f"{CACHE_DIR}/players.json"
PLAYERS_CACHE_TTL_HOURS = 24
