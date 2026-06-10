#!/usr/bin/env python3
"""
Philosophy League 2026 — World Cup Score Fetcher
Runs hourly via GitHub Actions. Reads MANAGERS config below,
calls API-Football, writes data.json which index.html reads.

SETUP: Add your API key as a GitHub Secret named API_FOOTBALL_KEY
Get a free key at: https://dashboard.api-football.com (100 calls/day free)
"""

import json, os, sys, urllib.request
from datetime import datetime, timezone

MANAGERS = [
    {"manager": "Alex",    "country": "England",   "flag": "🇬🇧", "team_id": 10},
    {"manager": "Toiv",    "country": "France",    "flag": "🇫🇷", "team_id": 2},
    {"manager": "Miles",   "country": "Spain",     "flag": "🇪🇸", "team_id": 9},
    {"manager": "Alec",    "country": "Argentina", "flag": "🇦🇷", "team_id": 26},
    {"manager": "Nate",    "country": "",          "flag": "",    "team_id": 0},
    {"manager": "Tom",     "country": "",          "flag": "",    "team_id": 0},
    {"manager": "Charlie", "country": "",          "flag": "",    "team_id": 0},
    {"manager": "Dane",    "country": "",          "flag": "",    "team_id": 0},
    {"manager": "Tik",     "country": "",          "flag": "",    "team_id": 0},
    {"manager": "Hunter",  "country": "",          "flag": "",    "team_id": 0},
    {"manager": "Jonah",   "country": "",          "flag": "",    "team_id": 0},
    {"manager": "Aaron",   "country": "",          "flag": "",    "team_id": 0},
]

WORLD_CUP_ID = 1

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


def api_get(path, params, key):
    base = "https://v3.football.api-sports.io"
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{base}/{path}?{qs}"
    req = urllib.request.Request(url, headers={"x-apisports-key": key})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def get_team_stats(team_id, key):
    if not team_id:
        return -1, "TBD", 0, 0

    try:
        data = api_get("fixtures", {"league": WORLD_CUP_ID, "team": team_id, "season": 2026}, key)
        fixtures = data.get("response", [])
    except Exception as e:
        print(f"  Warning: API error for team {team_id}: {e}", file=sys.stderr)
        return -1, "Pending", 0, 0

    if not fixtures:
        return -1, "Pending", 0, 0

    gf_total = 0
    ga_total = 0
    best_stage = -1
    best_label = "Pending"

    for f in fixtures:
        status = f["fixture"]["status"]["short"]
        if status not in ("FT", "AET", "PEN"):
            continue

        round_name = f["league"]["round"]
        home_id = f["teams"]["home"]["id"]
        home_goals = f["goals"]["home"] or 0
        away_goals = f["goals"]["away"] or 0

        if home_id == team_id:
            gf_total += home_goals
            ga_total += away_goals
            team_won = f["teams"]["home"]["winner"]
        else:
            gf_total += away_goals
            ga_total += home_goals
            team_won = f["teams"]["away"]["winner"]

        for key_stage, rank in STAGE_RANK.items():
            if key_stage.lower() in round_name.lower():
                if key_stage == "Final":
                    if team_won:
                        stage_rank = STAGE_RANK["Winner"]
                        stage_label = STAGE_LABEL["Winner"]
                    else:
                        stage_rank = STAGE_RANK["Final"]
                        stage_label = STAGE_LABEL["Final"]
                else:
                    stage_rank = rank
                    stage_label = STAGE_LABEL.get(key_stage, key_stage)

                if stage_rank > best_stage:
                    best_stage = stage_rank
                    best_label = stage_label
                break

    return best_stage, best_label, gf_total, ga_total


def main():
    api_key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if not api_key:
        print("ERROR: API_FOOTBALL_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching World Cup scores for {len(MANAGERS)} teams...")
    results = []

    for m in MANAGERS:
        print(f"  {m['flag']} {m['country']} ({m['manager']})...", end=" ", flush=True)
        stage_val, stage_label, gf, ga = get_team_stats(m["team_id"], api_key)
        print(f"Stage={stage_label}, GF={gf}, GA={ga}")

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
            "draftSlot": None,
        })

    results.sort(
        key=lambda x: (
            x["stage"],
            x["gd"],
            x["gf"],
        ),
        reverse=True,
    )

    output = {
        "leagueName": "Philosophy League 2026",
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "entries": results,
    }

    out_path = os.path.join(os.path.dirname(__file__), "data.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {out_path} ({len(results)} entries, updated {output['updatedAt']})")


if __name__ == "__main__":
    main()
