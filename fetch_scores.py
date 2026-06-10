#!/usr/bin/env python3
"""
Philosophy League 2026 — World Cup Score Fetcher
Uses football-data.org (free tier covers the World Cup).

SETUP:
  1. Register free at https://www.football-data.org/client/register
  2. Copy your API token from the dashboard
  3. In your GitHub repo → Settings → Secrets → Actions → New secret:
       Name:  FOOTBALL_DATA_TOKEN
       Value: your token

This script fetches ALL World Cup matches in one API call, aggregates
goals and furthest stage reached per team, then writes data.json.
"""

import json, os, sys, urllib.request
from datetime import datetime, timezone

# ══════════════════════════════════════════════════════════════════════════════
#  ★  EDIT THIS — your 12 managers and their World Cup picks  ★
#
#  team_id = the football-data.org numeric team ID.
#  Run the helper at the bottom of this file to look up IDs, or see the
#  cheat-sheet below.
#
#  Common 2026 World Cup team IDs (football-data.org v4):
#  🇦🇷 Argentina  = 3    🇧🇷 Brazil      = 6    🇫🇷 France      = 773
#  🇩🇪 Germany   = 759  🇪🇸 Spain       = 760  🇵🇹 Portugal    = 765
#  🏴󠁧󠁢󠁥󠁮󠁧󠁿 England   = 66   🇳🇱 Netherlands = 770  🇧🇪 Belgium     = 805
#  🇺🇸 USA        = 762  🇲🇽 Mexico      = 764  🇯🇵 Japan       = 827
#  🇭🇷 Croatia   = 799  🇺🇾 Uruguay     = 776  🇨🇴 Colombia    = 779
#  🇲🇦 Morocco   = 1013 🇸🇳 Senegal     = 907  🇦🇺 Australia   = 790
#  🇰🇷 S. Korea  = 732  🇨🇦 Canada      = 786  🇨🇭 Switzerland = 788
# ══════════════════════════════════════════════════════════════════════════════

MANAGERS = [
    {"manager": "Example Manager 1",  "country": "Argentina",   "flag": "🇦🇷", "team_id": 3},
    {"manager": "Example Manager 2",  "country": "Brazil",      "flag": "🇧🇷", "team_id": 6},
    {"manager": "Example Manager 3",  "country": "France",      "flag": "🇫🇷", "team_id": 773},
    {"manager": "Example Manager 4",  "country": "Germany",     "flag": "🇩🇪", "team_id": 759},
    {"manager": "Example Manager 5",  "country": "Spain",       "flag": "🇪🇸", "team_id": 760},
    {"manager": "Example Manager 6",  "country": "Portugal",    "flag": "🇵🇹", "team_id": 765},
    {"manager": "Example Manager 7",  "country": "England",     "flag": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "team_id": 66},
    {"manager": "Example Manager 8",  "country": "Netherlands", "flag": "🇳🇱", "team_id": 770},
    {"manager": "Example Manager 9",  "country": "USA",         "flag": "🇺🇸", "team_id": 762},
    {"manager": "Example Manager 10", "country": "Mexico",      "flag": "🇲🇽", "team_id": 764},
    {"manager": "Example Manager 11", "country": "Japan",       "flag": "🇯🇵", "team_id": 827},
    {"manager": "Example Manager 12", "country": "Morocco",     "flag": "🇲🇦", "team_id": 1013},
]

# ── STAGE MAPPINGS ────────────────────────────────────────────────────────────
# football-data.org v4 stage strings → our numeric rank (higher = further)
STAGE_RANK = {
    "GROUP_STAGE":    0,
    "ROUND_OF_16":    1,
    "QUARTER_FINALS": 2,
    "SEMI_FINALS":    3,
    "THIRD_PLACE":    4,   # 3rd place play-off
    "FINAL":          5,   # runner-up (loser of final)
    # "FINAL" winner gets bumped to 6 separately
}

STAGE_DISPLAY = {
    -1: "Pending",
    0:  "Group Stage",
    1:  "Round of 16",
    2:  "Quarterfinals",
    3:  "Semifinals",
    4:  "3rd Place",
    5:  "Runner-Up",
    6:  "Champion 🏆",
}

# ── API HELPER ────────────────────────────────────────────────────────────────

def api_get(path, token, params=None):
    base = "https://api.football-data.org/v4"
    url  = f"{base}/{path}"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(url, headers={"X-Auth-Token": token})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    token = os.environ.get("FOOTBALL_DATA_TOKEN", "").strip()
    if not token:
        print("ERROR: FOOTBALL_DATA_TOKEN environment variable not set.", file=sys.stderr)
        print("Get a free token at https://www.football-data.org/client/register", file=sys.stderr)
        sys.exit(1)

    # Build lookup: team_id → manager config
    team_lookup = {m["team_id"]: m for m in MANAGERS}

    # Per-team accumulators
    stats = {
        m["team_id"]: {"gf": 0, "ga": 0, "best_stage": -1}
        for m in MANAGERS
    }

    print("Fetching all World Cup 2026 matches from football-data.org…")
    try:
        data = api_get("competitions/WC/matches", token)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"HTTP {e.code}: {body}", file=sys.stderr)
        sys.exit(1)

    matches = data.get("matches", [])
    print(f"  Total matches in response: {len(matches)}")

    finished = 0
    for m in matches:
        if m.get("status") != "FINISHED":
            continue
        finished += 1

        home_id   = m["homeTeam"]["id"]
        away_id   = m["awayTeam"]["id"]
        home_goals = (m["score"]["fullTime"].get("home") or 0)
        away_goals = (m["score"]["fullTime"].get("away") or 0)
        stage_str  = m.get("stage", "GROUP_STAGE")
        winner     = m["score"].get("winner")  # "HOME_TEAM", "AWAY_TEAM", "DRAW", None

        # Map stage string to numeric rank
        stage_rank = STAGE_RANK.get(stage_str, 0)

        for team_id, is_home in [(home_id, True), (away_id, False)]:
            if team_id not in stats:
                continue   # not one of our managers' teams

            s = stats[team_id]
            if is_home:
                s["gf"] += home_goals
                s["ga"] += away_goals
                team_won = (winner == "HOME_TEAM")
            else:
                s["gf"] += away_goals
                s["ga"] += home_goals
                team_won = (winner == "AWAY_TEAM")

            # For the Final specifically: winner gets stage 6, loser stays 5
            if stage_str == "FINAL":
                effective_stage = 6 if team_won else 5
            else:
                effective_stage = stage_rank

            if effective_stage > s["best_stage"]:
                s["best_stage"] = effective_stage

    print(f"  Finished matches processed: {finished}")

    # Build output entries
    results = []
    for m in MANAGERS:
        tid  = m["team_id"]
        s    = stats[tid]
        stage_val = s["best_stage"]

        print(
            f"  {m['flag']} {m['country']:14s} ({m['manager']}) → "
            f"Stage: {STAGE_DISPLAY.get(stage_val, '?')}, "
            f"GF={s['gf']}, GA={s['ga']}, GD={s['gf']-s['ga']:+d}"
        )

        results.append({
            "id":         f"team-{tid}",
            "manager":    m["manager"],
            "flag":       m["flag"],
            "country":    m["country"],
            "team_id":    tid,
            "stage":      stage_val,
            "gf":         s["gf"],
            "ga":         s["ga"],
            "draftSlot":  None,   # managed manually in the browser
        })

    output = {
        "updatedAt": datetime.now(timezone.utc).strftime("%b %d %Y, %H:%M UTC"),
        "entries":   results,
    }

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n✓ data.json written — {len(results)} entries, updated {output['updatedAt']}")


# ── TEAM ID LOOKUP HELPER ─────────────────────────────────────────────────────
# Run:  FOOTBALL_DATA_TOKEN=yourtoken python fetch_scores.py --lookup "Spain"
# to find the correct team ID for any country.

def lookup_team(token, query):
    print(f"Looking up team IDs for: '{query}'")
    try:
        data = api_get("competitions/WC/teams", token)
        teams = data.get("teams", [])
        query_lower = query.lower()
        matches = [t for t in teams if query_lower in t.get("name","").lower()
                   or query_lower in t.get("shortName","").lower()
                   or query_lower in t.get("tla","").lower()]
        if matches:
            for t in matches:
                print(f"  ID={t['id']:6d}  {t['name']}  ({t.get('tla','?')})")
        else:
            print(f"  No match found. All teams:")
            for t in teams:
                print(f"  ID={t['id']:6d}  {t['name']}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "--lookup":
        token = os.environ.get("FOOTBALL_DATA_TOKEN", "").strip()
        if not token:
            print("Set FOOTBALL_DATA_TOKEN env var first.")
        else:
            lookup_team(token, sys.argv[2])
    else:
        main()
