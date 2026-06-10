#!/usr/bin/env python3
"""
The Philosophy League 2026 — World Cup Score Fetcher
Runs hourly via GitHub Actions. Reads MANAGERS config below,
calls API-Football, and writes data.json for index.html.

SETUP: Add your API key as a GitHub Secret named API_FOOTBALL_KEY.
"""

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
CENTRAL_TZ = ZoneInfo("America/Chicago")

STAGE_RANK = {
    "Group Stage": 0,
    "Round of 16": 1,
    "Quarter-finals": 2,
    "Semi-finals": 3,
    "3rd Place": 4,
    "Final": 5,
    "Winner": 6,
}

STAGE_LABEL = {
    "Group Stage": "Group Stage",
    "Round of 16": "Round of 16",
    "Quarter-finals": "Quarterfinals",
    "Semi-finals": "Semifinals",
    "3rd Place": "3rd Place",
    "Final": "Runner-Up",
    "Winner": "Champion 🏆",
}

FINISHED_STATUSES = {"FT", "AET", "PEN"}
NOT_STARTED_STATUSES = {"TBD", "NS"}


def api_get(path, params, key):
    base = "https://v3.football.api-sports.io"
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{base}/{path}?{qs}"
    req = urllib.request.Request(url, headers={"x-apisports-key": key})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def format_central_time(dt_utc):
    local = dt_utc.astimezone(CENTRAL_TZ)
    return local.strftime("%a, %b %d at %I:%M %p CT").replace(" 0", " ")


def parse_fixture_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def get_next_game(fixtures, team_id):
    now = datetime.now(timezone.utc)
    upcoming = []

    for f in fixtures:
        status = f.get("fixture", {}).get("status", {}).get("short")
        fixture_date = parse_fixture_date(f.get("fixture", {}).get("date"))
        if not fixture_date:
            continue

        # Keep future not-started fixtures. Some APIs may use TBD for unscheduled games.
        if status in FINISHED_STATUSES or fixture_date < now:
            continue

        home = f.get("teams", {}).get("home", {})
        away = f.get("teams", {}).get("away", {})
        home_id = home.get("id")
        away_id = away.get("id")

        if team_id not in (home_id, away_id):
            continue

        if home_id == team_id:
            opponent = away.get("name", "TBD")
            home_away = "vs"
        else:
            opponent = home.get("name", "TBD")
            home_away = "at"

        venue = f.get("fixture", {}).get("venue", {}).get("name") or ""
        round_name = f.get("league", {}).get("round") or ""

        upcoming.append({
            "date": fixture_date,
            "opponent": opponent,
            "homeAway": home_away,
            "venue": venue,
            "round": round_name,
        })

    if not upcoming:
        return {
            "opponent": "TBD",
            "homeAway": "",
            "timeCT": "TBD",
            "iso": None,
            "round": "",
            "venue": "",
        }

    next_fixture = sorted(upcoming, key=lambda x: x["date"])[0]
    return {
        "opponent": next_fixture["opponent"],
        "homeAway": next_fixture["homeAway"],
        "timeCT": format_central_time(next_fixture["date"]),
        "iso": next_fixture["date"].isoformat(),
        "round": next_fixture["round"],
        "venue": next_fixture["venue"],
    }


def get_team_data(team_id, key):
    if not team_id:
        return -1, "TBD", 0, 0, get_next_game([], team_id)

    try:
        data = api_get("fixtures", {"league": WORLD_CUP_ID, "team": team_id, "season": SEASON}, key)
        fixtures = data.get("response", [])
    except Exception as e:
        print(f"  Warning: API error for team {team_id}: {e}", file=sys.stderr)
        return -1, "Pending", 0, 0, get_next_game([], team_id)

    if not fixtures:
        return -1, "Pending", 0, 0, get_next_game([], team_id)

    gf_total = 0
    ga_total = 0
    best_stage = -1
    best_label = "Pending"

    for f in fixtures:
        status = f.get("fixture", {}).get("status", {}).get("short")
        if status not in FINISHED_STATUSES:
            continue

        round_name = f.get("league", {}).get("round", "")
        home = f.get("teams", {}).get("home", {})
        away = f.get("teams", {}).get("away", {})
        home_id = home.get("id")
        goals = f.get("goals", {})
        home_goals = goals.get("home") or 0
        away_goals = goals.get("away") or 0

        if home_id == team_id:
            gf_total += home_goals
            ga_total += away_goals
            team_won = home.get("winner")
        else:
            gf_total += away_goals
            ga_total += home_goals
            team_won = away.get("winner")

        for key_stage, rank in STAGE_RANK.items():
            if key_stage.lower() in round_name.lower():
                if key_stage == "Final" and team_won:
                    stage_rank = STAGE_RANK["Winner"]
                    stage_label = STAGE_LABEL["Winner"]
                else:
                    stage_rank = rank
                    stage_label = STAGE_LABEL.get(key_stage, key_stage)

                if stage_rank > best_stage:
                    best_stage = stage_rank
                    best_label = stage_label
                break

    return best_stage, best_label, gf_total, ga_total, get_next_game(fixtures, team_id)


def main():
    api_key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if not api_key:
        print("ERROR: API_FOOTBALL_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching World Cup data for {len(MANAGERS)} teams...")
    results = []

    for m in MANAGERS:
        print(f"  {m['flag']} {m['country']} ({m['manager']})...", end=" ", flush=True)
        stage_val, stage_label, gf, ga, next_game = get_team_data(m["team_id"], api_key)
        print(f"Stage={stage_label}, GF={gf}, GA={ga}, Next={next_game.get('homeAway', '')} {next_game.get('opponent', 'TBD')} {next_game.get('timeCT', '')}")

        results.append({
            "id": f"auto-{m['manager'].lower()}",
            "manager": m["manager"],
            "flag": m["flag"],
            "country": m["country"],
            "team_id": m["team_id"],
            "stage": stage_val,
            "stageLabel": stage_label,
            "gf": gf,
            "ga": ga,
            "gd": gf - ga,
            "nextGame": next_game,
            "draftSlot": None,
        })

    results.sort(key=lambda x: (x["stage"], x["gd"], x["gf"]), reverse=True)

    output = {
        "leagueName": "The Philosophy League 2026",
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "entries": results,
    }

    out_path = os.path.join(os.path.dirname(__file__), "data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {out_path} ({len(results)} entries, updated {output['updatedAt']})")


if __name__ == "__main__":
    main()
