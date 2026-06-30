#!/usr/bin/env python3
"""
Philosophy League 2026 — World Cup Score Fetcher
Uses football-data.org free tier (covers 2026 World Cup).

SETUP:
  1. Register free at https://www.football-data.org/client/register
  2. Copy your API token
  3. GitHub repo → Settings → Secrets → Actions → New secret:
       Name:  FOOTBALL_DATA_TOKEN
       Value: your token

HOW IT WORKS:
  - Reads fixtures.json for pre-loaded schedule (next match times, venues)
  - Calls football-data.org for live/finished match scores
  - Merges both into data.json which index.html reads automatically
  - Run manually: FOOTBALL_DATA_TOKEN=yourtoken python fetch_scores.py
  - GitHub Actions runs this every hour automatically
"""

import json, os, sys, urllib.request, urllib.error
from datetime import datetime, timezone

# ══════════════════════════════════════════════════════════════════════════════
#  ★  YOUR 12 MANAGERS  ★
#
#  team_id = football-data.org numeric ID for the country.
#  To look up any team: FOOTBALL_DATA_TOKEN=xxx python fetch_scores.py --lookup "Norway"
# ══════════════════════════════════════════════════════════════════════════════

MANAGERS = [
    {"manager": "Alex",    "country": "England",     "flag": "🇬🇧", "team_id": 770},
    {"manager": "Toiv",    "country": "France",      "flag": "🇫🇷", "team_id": 773},
    {"manager": "Miles",   "country": "Spain",       "flag": "🇪🇸", "team_id": 760},
    {"manager": "Alec",    "country": "Argentina",   "flag": "🇦🇷", "team_id": 762},
    {"manager": "Nate",    "country": "USA",         "flag": "🇺🇸", "team_id": 771},
    {"manager": "Tom",     "country": "Brazil",      "flag": "🇧🇷", "team_id": 764},
    {"manager": "Charlie", "country": "Portugal",    "flag": "🇵🇹", "team_id": 765},
    {"manager": "Dane",    "country": "Germany",     "flag": "🇩🇪", "team_id": 759},
    {"manager": "Tik",     "country": "Netherlands", "flag": "🇳🇱", "team_id": 8601},
    {"manager": "Hunter",  "country": "Norway",      "flag": "🇳🇴", "team_id": 8872},
    {"manager": "Jonah",   "country": "Mexico",      "flag": "🇲🇽", "team_id": 769},
    {"manager": "Aaron",   "country": "Belgium",     "flag": "🇧🇪", "team_id": 805},
]

# ── STAGE MAPPINGS ────────────────────────────────────────────────────────────
# football-data.org v4 stage strings → our numeric rank (higher = further)
STAGE_RANK = {
    "GROUP_STAGE":    0,
    "ROUND_OF_32":    1,   # new for the 48-team 2026 format — was missing, causing every
    "ROUND_OF_16":    2,   # R32 match to silently fall back to "Group Stage" (rank 0)
    "QUARTER_FINALS": 3,
    "SEMI_FINALS":    4,
    "THIRD_PLACE":    5,
    # FINAL: winner → 7, loser → 6 (handled separately below)
}

STAGE_DISPLAY = {
    -1: "Pending",
    0:  "Group Stage",
    1:  "Round of 32",
    2:  "Round of 16",
    3:  "Quarterfinals",
    4:  "Semifinals",
    5:  "3rd Place",
    6:  "Runner-Up",
    7:  "Champion 🏆",
}

# ── HELPERS ───────────────────────────────────────────────────────────────────

def api_get(path, token, params=None):
    url = f"https://api.football-data.org/v4/{path}"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(url, headers={"X-Auth-Token": token})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def load_fixtures():
    """Load the pre-built fixtures.json schedule."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures.json")
    if not os.path.exists(path):
        print("  WARNING: fixtures.json not found — next match data will be empty.")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_next_game(country, fixtures_by_country, eliminated=False):
    """Return the next upcoming (or soonest past) game for a country."""
    games = fixtures_by_country.get(country, [])
    if not games:
        return {"opponent": "TBD", "homeAway": "", "timeCT": "TBD", "iso": None, "round": "", "venue": ""}

    if eliminated:
        return {"opponent": "TBD", "homeAway": "", "timeCT": "Eliminated", "iso": None, "round": "", "venue": ""}

    now = datetime.now(timezone.utc)

    # Find the first game that hasn't finished yet
    for g in games:
        if g.get("iso"):
            try:
                game_time = datetime.fromisoformat(g["iso"])
                # Keep as upcoming if within 3 hours (might still be in progress)
                if game_time.timestamp() > now.timestamp() - 10800:
                    return g
            except ValueError:
                pass
        else:
            return g  # no ISO, just return it

    # All games are in the past and the team is presumably still alive (no API
    # token, or fixtures.json hasn't been extended to the next round yet) —
    # return the last known game rather than inventing one.
    return games[-1]


ROUND_LABEL = {
    "GROUP_STAGE":    "Group Stage",
    "ROUND_OF_32":    "Round of 32",
    "ROUND_OF_16":    "Round of 16",
    "QUARTER_FINALS": "Quarterfinals",
    "SEMI_FINALS":    "Semifinals",
    "THIRD_PLACE":    "3rd Place Match",
    "FINAL":          "Final",
}

def utc_iso_to_ct(utc_date_str):
    """football-data.org returns UTC ISO timestamps. Convert to a CT-labeled
    display string. WC games run June–July, which is CDT (UTC-5)."""
    try:
        dt_utc = datetime.fromisoformat(utc_date_str.replace("Z", "+00:00"))
    except ValueError:
        return utc_date_str, None
    from datetime import timedelta
    dt_ct = dt_utc - timedelta(hours=5)
    label = dt_ct.strftime("%a, %b %-d at %-I:%M %p CT")
    iso_ct = dt_ct.strftime("%Y-%m-%dT%H:%M:%S-05:00")
    return label, iso_ct


def build_next_match_from_api(team_id, matches):
    """Find this team's earliest non-finished match directly from the live
    API schedule. Once a bracket slot resolves (e.g. 'Winner of R32 Match 4'
    becomes 'Portugal'), football-data.org fills in the real team — so this
    keeps next-round matchups, dates, and venues current automatically with
    zero manual fixture editing."""
    candidates = []
    for m in matches:
        if m.get("status") in ("FINISHED", "CANCELLED", "POSTPONED"):
            continue
        home = m.get("homeTeam") or {}
        away = m.get("awayTeam") or {}
        is_home = home.get("id") == team_id
        is_away = away.get("id") == team_id
        if not (is_home or is_away):
            continue
        candidates.append((m, is_home, home, away))

    if not candidates:
        return None

    candidates.sort(key=lambda c: c[0].get("utcDate") or "9999")
    m, is_home, home, away = candidates[0]
    opp = away if is_home else home
    opp_name = opp.get("name") or "TBD"
    time_ct, iso_ct = utc_iso_to_ct(m.get("utcDate", "")) if m.get("utcDate") else ("TBD", None)

    return {
        "opponent": opp_name,
        "homeAway": "vs" if is_home else "at",
        "timeCT":   time_ct,
        "iso":      iso_ct,
        "round":    ROUND_LABEL.get(m.get("stage", ""), m.get("stage", "")),
        "venue":    (m.get("venue") or ""),
    }


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    token = os.environ.get("FOOTBALL_DATA_TOKEN", "").strip()

    # Build accumulators for live scores
    team_ids   = {m["team_id"] for m in MANAGERS}
    stats      = {m["team_id"]: {"gf": 0, "ga": 0, "best_stage": -1, "eliminated": False} for m in MANAGERS}
    fixtures_db = load_fixtures()
    all_matches = []   # populated from API if token present; used for live next-match lookup

    if token:
        print("Fetching live World Cup scores from football-data.org…")
        try:
            data    = api_get("competitions/WC/matches", token)
            matches = data.get("matches", [])
            all_matches = matches
            print(f"  {len(matches)} total matches in API response")

            finished = 0
            for m in matches:
                if m.get("status") != "FINISHED":
                    continue
                finished += 1

                home_id    = m["homeTeam"]["id"]
                away_id    = m["awayTeam"]["id"]
                home_goals = m["score"]["fullTime"].get("home") or 0
                away_goals = m["score"]["fullTime"].get("away") or 0
                stage_str  = m.get("stage", "GROUP_STAGE")
                winner     = m["score"].get("winner")

                for team_id, is_home in [(home_id, True), (away_id, False)]:
                    if team_id not in team_ids:
                        continue
                    s = stats[team_id]
                    if is_home:
                        s["gf"] += home_goals
                        s["ga"] += away_goals
                        team_won = (winner == "HOME_TEAM")
                    else:
                        s["gf"] += away_goals
                        s["ga"] += home_goals
                        team_won = (winner == "AWAY_TEAM")

                    if stage_str == "FINAL":
                        effective = 7 if team_won else 6
                    else:
                        effective = STAGE_RANK.get(stage_str, 0)

                    if effective > s["best_stage"]:
                        s["best_stage"] = effective

                    # A knockout match (anything past Group Stage) that wasn't won
                    # eliminates the team — including a Final loss (Runner-Up).
                    if stage_str != "GROUP_STAGE" and not team_won:
                        s["eliminated"] = True
                    elif team_won:
                        # Winning a later match un-sets a stale elimination flag
                        # (shouldn't normally happen, but keeps state consistent).
                        s["eliminated"] = False

            print(f"  {finished} finished matches processed")

        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"  API error {e.code}: {body}", file=sys.stderr)
            print("  Continuing with static data only.")
        except Exception as e:
            print(f"  Unexpected error: {e}", file=sys.stderr)
            print("  Continuing with static data only.")
    else:
        print("No FOOTBALL_DATA_TOKEN set — using static fixtures only (scores will show as Pending).")

    # Build output
    results = []
    for m in MANAGERS:
        tid       = m["team_id"]
        s         = stats[tid]
        stage_val = s["best_stage"]

        # Prefer the live API schedule (auto-resolves real opponents as the
        # bracket fills in); fall back to the static fixtures.json (mainly
        # useful for the group stage, or when running without a token).
        next_game = None
        if not s["eliminated"] and all_matches:
            next_game = build_next_match_from_api(tid, all_matches)
        if next_game is None:
            next_game = get_next_game(m["country"], fixtures_db, eliminated=s["eliminated"])

        print(
            f"  {m['flag']} {m['country']:14s} ({m['manager']:8s}) → "
            f"Stage: {STAGE_DISPLAY.get(stage_val, '?'):12s} "
            f"{'[ELIMINATED] ' if s['eliminated'] else ''}"
            f"GF={s['gf']} GA={s['ga']} | "
            f"Next: {next_game.get('homeAway','')} {next_game.get('opponent','TBD')} "
            f"({next_game.get('timeCT','TBD')})"
        )

        results.append({
            "id":         f"team-{tid}",
            "manager":    m["manager"],
            "flag":       m["flag"],
            "country":    m["country"],
            "team_id":    tid,
            "stage":      stage_val,
            "eliminated": s["eliminated"],
            "gf":         s["gf"],
            "ga":         s["ga"],
            "nextGame":   next_game,
            "draftSlot":  None,   # managed in the browser
        })

    output = {
        "updatedAt": datetime.now(timezone.utc).strftime("%b %d %Y, %H:%M UTC"),
        "entries":   results,
    }

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n✓ data.json written — {len(results)} entries, {output['updatedAt']}")


# ── TEAM LOOKUP HELPER ────────────────────────────────────────────────────────
# Usage: FOOTBALL_DATA_TOKEN=xxx python fetch_scores.py --lookup "Norway"

def lookup_team(token, query):
    print(f"Searching for team: '{query}'")
    try:
        data  = api_get("competitions/WC/teams", token)
        teams = data.get("teams", [])
        ql    = query.lower()
        hits  = [t for t in teams if ql in t.get("name","").lower()
                 or ql in t.get("shortName","").lower()
                 or ql in t.get("tla","").lower()]
        if hits:
            for t in hits:
                print(f"  ID={t['id']:6d}  {t['name']}  ({t.get('tla','?')})")
        else:
            print("  No exact match. All teams in the World Cup:")
            for t in sorted(teams, key=lambda t: t["name"]):
                print(f"  ID={t['id']:6d}  {t['name']}")
    except Exception as e:
        print(f"  Error: {e}")


def verify_ids(token):
    """Cross-check all MANAGER team_ids against the WC team list from the API."""
    print("Verifying team IDs against football-data.org World Cup team list...\n")
    try:
        data  = api_get("competitions/WC/teams", token)
        teams = data.get("teams", [])
    except Exception as e:
        print(f"Error fetching teams: {e}")
        return

    api_ids = {t["id"]: t["name"] for t in teams}

    all_ok = True
    for m in MANAGERS:
        tid  = m["team_id"]
        name = api_ids.get(tid)
        if name:
            match = "✅" if m["country"].lower() in name.lower() or name.lower() in m["country"].lower() else "⚠️  NAME MISMATCH"
            print(f"  {match}  {m['manager']:8s} → {m['country']:14s} id={tid} → API says: '{name}'")
            if "⚠️" in match:
                all_ok = False
        else:
            all_ok = False
            # Find closest match by name
            guesses = [t for t in teams if m["country"].lower() in t["name"].lower()
                       or t["name"].lower() in m["country"].lower()]
            if guesses:
                suggestions = ", ".join(f"'{t['name']}' (id={t['id']})" for t in guesses)
                print(f"  ❌  {m['manager']:8s} → {m['country']:14s} id={tid} NOT FOUND — did you mean: {suggestions}?")
            else:
                print(f"  ❌  {m['manager']:8s} → {m['country']:14s} id={tid} NOT FOUND in WC team list")

    print()
    if all_ok:
        print("All team IDs verified ✅")
    else:
        print("Fix the IDs marked ❌ or ⚠️ above, then re-run.")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--lookup":
        tok = os.environ.get("FOOTBALL_DATA_TOKEN", "").strip()
        if not tok:
            print("Set FOOTBALL_DATA_TOKEN env var first.")
        else:
            lookup_team(tok, sys.argv[2])
    elif len(sys.argv) >= 2 and sys.argv[1] == "--verify":
        tok = os.environ.get("FOOTBALL_DATA_TOKEN", "").strip()
        if not tok:
            print("Set FOOTBALL_DATA_TOKEN env var first.")
        else:
            verify_ids(tok)
    else:
        main()
