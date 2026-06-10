#!/usr/bin/env python3

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

MANAGERS = [
    {"manager": "Alex",    "country": "England",     "flag": "🇬🇧", "team_id": 10},
    {"manager": "Toiv",    "country": "France",      "flag": "🇫🇷", "team_id": 2},
    {"manager": "Miles",   "country": "Spain",       "flag": "🇪🇸", "team_id": 9},
    {"manager": "Alec",    "country": "Argentina",   "flag": "🇦🇷", "team_id": 26},
    {"manager": "Nate",    "country": "USA",         "flag": "🇺🇸", "team_id": 2384},
    {"manager": "Tom",     "country": "Brazil",      "flag": "🇧🇷", "team_id": 6},
    {"manager": "Charlie", "country": "Portugal",    "flag": "🇵🇹", "team_id": 27},
    {"manager": "Dane",    "country": "Germany",     "flag": "🇩🇪", "team_id": 25},
    {"manager": "Tik",     "country": "Netherlands", "flag": "🇳🇱", "team_id": 1114},
    {"manager": "Hunter",  "country": "Norway",      "flag": "🇳🇴", "team_id": 1098},
    {"manager": "Jonah",   "country": "Mexico",      "flag": "🇲🇽", "team_id": 16},
    {"manager": "Aaron",   "country": "Belgium",     "flag": "🇧🇪", "team_id": 1},
]

WORLD_CUP_ID = 1
SEASON = 2026


def api_get(path, params, key):
    base = "https://v3.football.api-sports.io"
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{base}/{path}?{qs}"

    print(f"\nCalling: {url}")

    req = urllib.request.Request(url, headers={"x-apisports-key": key})

    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def main():
    api_key = os.environ.get("API_FOOTBALL_KEY", "").strip()

    if not api_key:
        print("ERROR: API_FOOTBALL_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    print("=== API-FOOTBALL DEBUG TEST ===")

    print("\nTesting World Cup teams endpoint...")

    teams_data = api_get(
        "teams",
        {
            "league": WORLD_CUP_ID,
            "season": SEASON,
        },
        api_key,
    )

    print("\nRAW TEAMS RESPONSE:")
    print(json.dumps(teams_data, indent=2, ensure_ascii=False)[:3000])

    teams = teams_data.get("response", [])
    print(f"\nWorld Cup teams found: {len(teams)}")

    print("\nFirst 20 teams returned:")
    for item in teams[:20]:
        team = item.get("team", {})
        print(f"{team.get('id')} - {team.get('name')}")

    print("\nTesting World Cup fixtures endpoint...")

    fixtures_data = api_get(
        "fixtures",
        {
            "league": WORLD_CUP_ID,
            "season": SEASON,
        },
        api_key,
    )

    print("\nRAW FIXTURES RESPONSE:")
    print(json.dumps(fixtures_data, indent=2, ensure_ascii=False)[:3000])

    fixtures = fixtures_data.get("response", [])
    print(f"\nWorld Cup fixtures found: {len(fixtures)}")

    print("\nFirst 5 fixtures returned:")
    for f in fixtures[:5]:
        fixture = f.get("fixture", {})
        league = f.get("league", {})
        teams_obj = f.get("teams", {})
        home = teams_obj.get("home", {})
        away = teams_obj.get("away", {})

        print(
            f"{fixture.get('date')} | {league.get('round')} | "
            f"{home.get('id')} {home.get('name')} vs {away.get('id')} {away.get('name')}"
        )

    print("\n=== DEBUG TEST COMPLETE ===")


if __name__ == "__main__":
    main()