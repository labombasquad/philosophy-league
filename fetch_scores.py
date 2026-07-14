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
from zoneinfo import ZoneInfo

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
# NOTE: football-data.org's documented stage enum (GROUP_STAGE, ROUND_OF_16,
# QUARTER_FINALS, SEMI_FINALS, FINAL) predates the 2026 48-team format and the
# new Round of 32. Rather than guess the literal string they use for it (a
# previous version guessed "ROUND_OF_32" and it didn't match the live data),
# stage ranking is now built DYNAMICALLY each run from whatever stage values
# actually appear in the API response, ordered by each stage's earliest match
# date. This self-corrects no matter what football-data.org calls the round.
# Known display names are still used when a stage string matches one of the
# common ones; anything unrecognized falls back to a prettified version of
# the raw string (e.g. "ROUND_OF_32" -> "Round Of 32") so it never blanks out.

KNOWN_STAGE_LABELS = {
    "GROUP_STAGE":    "Group Stage",
    "ROUND_OF_32":    "Round of 32",
    "LAST_32":        "Round of 32",   # confirmed: this is what football-data.org actually returns
    "ROUND_OF_16":    "Round of 16",
    "LAST_16":        "Round of 16",   # defensive alias, in case they use the same LAST_X convention
    "QUARTER_FINALS": "Quarterfinals",
    "SEMI_FINALS":    "Semifinals",
    "THIRD_PLACE":    "3rd Place",
    "FINAL":          "Final",
}

SHORT_STAGE_LABELS = {
    "GROUP_STAGE":    "Groups",
    "ROUND_OF_32":    "R32",
    "LAST_32":        "R32",
    "ROUND_OF_16":    "R16",
    "LAST_16":        "R16",
    "QUARTER_FINALS": "QF",
    "SEMI_FINALS":    "SF",
    "THIRD_PLACE":    "3rd Place",
    "FINAL":          "Final",
}

def prettify_stage_short(stage_str):
    return SHORT_STAGE_LABELS.get(stage_str, prettify_stage(stage_str))

def prettify_stage(stage_str):
    return KNOWN_STAGE_LABELS.get(stage_str, stage_str.replace("_", " ").title())


def build_dynamic_stage_rank(matches):
    """Order every distinct stage string by its earliest scheduled date.
    GROUP_STAGE is forced to rank 0 regardless (it's always first). The
    FINAL stage (last chronologically) is excluded here and handled
    separately by the caller so winner/loser can be split into two ranks."""
    earliest = {}
    for m in matches:
        stage = m.get("stage")
        date  = m.get("utcDate")
        if not stage or not date:
            continue
        if stage not in earliest or date < earliest[stage]:
            earliest[stage] = date

    if "GROUP_STAGE" not in earliest:
        earliest["GROUP_STAGE"] = "0000-01-01"  # ensure it always sorts first

    ordered = sorted(earliest.keys(), key=lambda s: earliest[s])
    # GROUP_STAGE must be rank 0 no matter where it sorted (defensive)
    ordered = ["GROUP_STAGE"] + [s for s in ordered if s != "GROUP_STAGE"]

    rank = {stage: i for i, stage in enumerate(ordered)}
    final_stage = ordered[-1] if len(ordered) > 1 else None
    return rank, final_stage


# Built once live data is available; see main(). Empty dict / None until then.
STAGE_RANK  = {}
FINAL_STAGE = None

STAGE_DISPLAY = {-1: "Pending"}  # populated dynamically alongside STAGE_RANK

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


# ── BRACKET FALLBACKS ─────────────────────────────────────────────────────────
# football-data.org is the source of truth when it has a real opponent attached.
# These fallbacks are only used when the API has not resolved a future bracket
# slot yet, such as "Portugal vs TBD" after Portugal wins the Round of 32.
#
# Times are Central Time.

def norm_name(value):
    return str(value or "").lower().replace("&", "and").replace("-", " ").strip()


def name_in(country, names):
    c = norm_name(country)
    return any(c == norm_name(n) for n in names)


def make_fallback(opponent, home_away, time_ct, iso, round_name, venue=""):
    return {
        "opponent": opponent,
        "homeAway": home_away,
        "timeCT": time_ct,
        "iso": iso,
        "round": round_name,
        "venue": venue
    }


R32_WINNER_FALLBACKS = [
    # Round of 32 winners -> Round of 16
    ({"South Africa", "Canada"}, "Winner of Netherlands/Morocco", "vs", "Sat, Jul 4 at 12:00 PM CT", "2026-07-04T12:00:00-05:00"),
    ({"Netherlands", "Morocco"}, "Winner of Canada/South Africa", "vs", "Sat, Jul 4 at 12:00 PM CT", "2026-07-04T12:00:00-05:00"),

    ({"Germany", "Paraguay"}, "Winner of France/Sweden", "vs", "Sat, Jul 4 at 4:00 PM CT", "2026-07-04T16:00:00-05:00"),
    ({"France", "Sweden"}, "Winner of Germany/Paraguay", "vs", "Sat, Jul 4 at 4:00 PM CT", "2026-07-04T16:00:00-05:00"),

    ({"Brazil", "Japan"}, "Winner of Ivory Coast/Norway", "vs", "Sun, Jul 5 at 3:00 PM CT", "2026-07-05T15:00:00-05:00"),
    ({"Ivory Coast", "Norway"}, "Winner of Brazil/Japan", "vs", "Sun, Jul 5 at 3:00 PM CT", "2026-07-05T15:00:00-05:00"),

    ({"Mexico", "Ecuador"}, "Winner of England/DR Congo", "vs", "Sun, Jul 5 at 7:00 PM CT", "2026-07-05T19:00:00-05:00"),
    ({"England", "Congo DR", "DR Congo"}, "Winner of Mexico/Ecuador", "vs", "Sun, Jul 5 at 7:00 PM CT", "2026-07-05T19:00:00-05:00"),

    ({"Portugal", "Croatia"}, "Winner of Spain/Austria", "vs", "Mon, Jul 6 at 2:00 PM CT", "2026-07-06T14:00:00-05:00"),
    ({"Spain", "Austria"}, "Winner of Portugal/Croatia", "vs", "Mon, Jul 6 at 2:00 PM CT", "2026-07-06T14:00:00-05:00"),

    ({"United States", "USA", "Bosnia and Herzegovina", "Bosnia-Herzegovina"}, "Winner of Belgium/Senegal", "vs", "Mon, Jul 6 at 7:00 PM CT", "2026-07-06T19:00:00-05:00"),
    ({"Belgium", "Senegal"}, "Winner of USA/Bosnia-Herzegovina", "vs", "Mon, Jul 6 at 7:00 PM CT", "2026-07-06T19:00:00-05:00"),

    ({"Australia", "Egypt"}, "Winner of Argentina/Cape Verde", "vs", "Tue, Jul 7 at 11:00 AM CT", "2026-07-07T11:00:00-05:00"),
    ({"Argentina", "Cape Verde", "Cape Verde Islands"}, "Winner of Australia/Egypt", "vs", "Tue, Jul 7 at 11:00 AM CT", "2026-07-07T11:00:00-05:00"),

    ({"Switzerland", "Algeria"}, "Winner of Colombia/Ghana", "vs", "Tue, Jul 7 at 3:00 PM CT", "2026-07-07T15:00:00-05:00"),
    ({"Colombia", "Ghana"}, "Winner of Switzerland/Algeria", "vs", "Tue, Jul 7 at 3:00 PM CT", "2026-07-07T15:00:00-05:00"),
]


QF_FALLBACKS = [
    # Round of 16 winners -> Quarterfinals
    ({"Canada", "South Africa", "Morocco", "Netherlands"}, "Winner of Paraguay/France/Sweden", "vs", "Thu, Jul 9 at 3:00 PM CT", "2026-07-09T15:00:00-05:00"),
    ({"Germany", "Paraguay", "France", "Sweden"}, "Winner of Canada/Morocco", "vs", "Thu, Jul 9 at 3:00 PM CT", "2026-07-09T15:00:00-05:00"),

    ({"Portugal", "Croatia", "Spain", "Austria"}, "Winner of USA/Belgium/Senegal", "vs", "Fri, Jul 10 at 2:00 PM CT", "2026-07-10T14:00:00-05:00"),
    ({"United States", "USA", "Bosnia and Herzegovina", "Bosnia-Herzegovina", "Belgium", "Senegal"}, "Winner of Portugal/Spain", "vs", "Fri, Jul 10 at 2:00 PM CT", "2026-07-10T14:00:00-05:00"),

    ({"Brazil", "Japan", "Ivory Coast", "Norway"}, "Winner of Mexico/England/Ecuador/DR Congo", "vs", "Sat, Jul 11 at 4:00 PM CT", "2026-07-11T16:00:00-05:00"),
    ({"Mexico", "Ecuador", "England", "Congo DR", "DR Congo"}, "Winner of Brazil/Norway", "vs", "Sat, Jul 11 at 4:00 PM CT", "2026-07-11T16:00:00-05:00"),

    ({"Argentina", "Cape Verde", "Cape Verde Islands", "Australia", "Egypt"}, "Switzerland", "vs", "Sat, Jul 11 at 8:00 PM CT", "2026-07-11T20:00:00-05:00"),
    ({"Switzerland", "Algeria", "Colombia", "Ghana"}, "Argentina", "vs", "Sat, Jul 11 at 8:00 PM CT", "2026-07-11T20:00:00-05:00"),
]


SF_FALLBACKS = [
    # Quarterfinal winners -> Semifinals
    ({"Canada", "South Africa", "Morocco", "Netherlands", "Germany", "Paraguay", "France", "Sweden"}, "Winner of Portugal/Spain/USA/Belgium", "vs", "Tue, Jul 14 at 2:00 PM CT", "2026-07-14T14:00:00-05:00"),
    ({"Portugal", "Croatia", "Spain", "Austria", "United States", "USA", "Bosnia and Herzegovina", "Bosnia-Herzegovina", "Belgium", "Senegal"}, "Winner of Canada/Morocco/France/Paraguay", "vs", "Tue, Jul 14 at 2:00 PM CT", "2026-07-14T14:00:00-05:00"),

    ({"Brazil", "Japan", "Ivory Coast", "Norway", "Mexico", "Ecuador", "England", "Congo DR", "DR Congo"}, "Winner of Argentina/Australia/Colombia/Ghana", "vs", "Wed, Jul 15 at 2:00 PM CT", "2026-07-15T14:00:00-05:00"),
    ({"Argentina", "Cape Verde", "Cape Verde Islands", "Australia", "Egypt", "Switzerland", "Algeria", "Colombia", "Ghana"}, "Winner of Brazil/Mexico/England/Norway", "vs", "Wed, Jul 15 at 2:00 PM CT", "2026-07-15T14:00:00-05:00"),
]


POST_SF_FALLBACKS = [
    # Semifinal winners -> Final; semifinal losers -> 3rd Place playoff.
    ({"France", "Spain"}, "Winner of England/Argentina", "vs", "Sun, Jul 19 at 2:00 PM CT", "2026-07-19T14:00:00-05:00", "Final"),
]

THIRD_PLACE_FALLBACKS = [
    ({"France", "Spain"}, "Loser of England/Argentina", "vs", "Sat, Jul 18 at 4:00 PM CT", "2026-07-18T16:00:00-05:00", "3rd Place"),
]


def get_bracket_fallback(country, stage_val):
    """Return a bracket-path fallback for teams that have advanced but whose
    next opponent has not resolved in football-data.org yet."""
    r16_rank = STAGE_RANK.get("ROUND_OF_16", STAGE_RANK.get("LAST_16", 2))
    qf_rank = STAGE_RANK.get("QUARTER_FINALS", 3)
    sf_rank = STAGE_RANK.get("SEMI_FINALS", 4)
    third_rank = STAGE_RANK.get("THIRD_PLACE")
    final_rank = STAGE_RANK.get("FINAL")

    if stage_val == r16_rank:
        for names, opponent, ha, time_ct, iso in R32_WINNER_FALLBACKS:
            if name_in(country, names):
                return make_fallback(opponent, ha, time_ct, iso, "Round of 16")

    if stage_val == qf_rank:
        for names, opponent, ha, time_ct, iso in QF_FALLBACKS:
            if name_in(country, names):
                return make_fallback(opponent, ha, time_ct, iso, "Quarterfinals")

    if stage_val == sf_rank:
        for names, opponent, ha, time_ct, iso in SF_FALLBACKS:
            if name_in(country, names):
                return make_fallback(opponent, ha, time_ct, iso, "Semifinals")

    if final_rank is not None and stage_val == final_rank:
        for names, opponent, ha, time_ct, iso, round_name in POST_SF_FALLBACKS:
            if name_in(country, names):
                return make_fallback(opponent, ha, time_ct, iso, round_name)

    if third_rank is not None and stage_val == third_rank:
        for names, opponent, ha, time_ct, iso, round_name in THIRD_PLACE_FALLBACKS:
            if name_in(country, names):
                return make_fallback(opponent, ha, time_ct, iso, round_name)

    return None


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


def build_next_match_from_api(team_id, matches, country=None):
    """Find this team's earliest non-finished match directly from the live
    API schedule. Uses team ID first, then falls back to country/name matching
    for future bracket slots where the API may resolve a displayed team name
    before attaching the numeric team id."""
    candidates = []
    country_norm = norm_name(country) if country else ""

    for m in matches:
        if m.get("status") in ("FINISHED", "CANCELLED", "POSTPONED"):
            continue

        home = m.get("homeTeam") or {}
        away = m.get("awayTeam") or {}

        home_id = home.get("id")
        away_id = away.get("id")
        home_name = home.get("name") or home.get("shortName") or ""
        away_name = away.get("name") or away.get("shortName") or ""

        is_home = home_id == team_id
        is_away = away_id == team_id

        # Defensive fallback: some unresolved/partly-resolved knockout matches
        # may have the real country name but no team id yet.
        if not (is_home or is_away) and country_norm:
            is_home = country_norm in norm_name(home_name) or norm_name(home_name) in country_norm
            is_away = country_norm in norm_name(away_name) or norm_name(away_name) in country_norm

        if not (is_home or is_away):
            continue

        candidates.append((m, is_home, home, away))

    if not candidates:
        return None

    candidates.sort(key=lambda c: c[0].get("utcDate") or "9999")
    m, is_home, home, away = candidates[0]
    opp = away if is_home else home
    opp_name = opp.get("name") or opp.get("shortName") or "TBD"
    time_ct, iso_ct = utc_iso_to_ct(m.get("utcDate", "")) if m.get("utcDate") else ("TBD", None)

    return {
        "opponent": opp_name,
        "homeAway": "vs" if is_home else "at",
        "timeCT":   time_ct,
        "iso":      iso_ct,
        "round":    prettify_stage(m.get("stage", "")),
        "_stageRaw": m.get("stage", ""),
        "venue":    (m.get("venue") or ""),
    }


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    token = os.environ.get("FOOTBALL_DATA_TOKEN", "").strip()

    # Build accumulators for live scores
    team_ids   = {m["team_id"] for m in MANAGERS}
    stats      = {m["team_id"]: {"gf": 0, "ga": 0, "best_stage": -1, "eliminated": False, "eliminated_stage": None} for m in MANAGERS}
    fixtures_db = load_fixtures()
    all_matches = []   # populated from API if token present; used for live next-match lookup

    if token:
        print("Fetching live World Cup scores from football-data.org…")
        try:
            data    = api_get("competitions/WC/matches", token)
            matches = data.get("matches", [])
            all_matches = matches
            print(f"  {len(matches)} total matches in API response")

            global STAGE_RANK, FINAL_STAGE, STAGE_DISPLAY
            STAGE_RANK, FINAL_STAGE = build_dynamic_stage_rank(matches)
            # Reserve final's loser/winner as the top two ranks beyond what
            # build_dynamic_stage_rank assigned everything else.
            top_rank = max(STAGE_RANK.values()) if STAGE_RANK else 0
            STAGE_DISPLAY = {-1: "Pending"}
            for stage, rnk in STAGE_RANK.items():
                if stage == FINAL_STAGE:
                    continue  # handled below as runner-up/champion
                STAGE_DISPLAY[rnk] = prettify_stage(stage)
            if FINAL_STAGE:
                STAGE_DISPLAY[top_rank]     = "Runner-Up"
                STAGE_DISPLAY[top_rank + 1] = "Champion 🏆"
            print(f"  Detected stages (chronological): {list(STAGE_RANK.keys())}"
                  + (f", final stage = '{FINAL_STAGE}'" if FINAL_STAGE else ""))

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

                    if FINAL_STAGE and stage_str == FINAL_STAGE:
                        # Final winner = champion, final loser = runner-up.
                        effective = top_rank + 1 if team_won else top_rank
                    elif stage_str == "SEMI_FINALS":
                        # The semifinal branches: winners advance to the Final,
                        # while losers advance to the 3rd Place playoff. A plain
                        # +1 rank is incorrect because THIRD_PLACE is scheduled
                        # before FINAL and sits between them chronologically.
                        if team_won:
                            effective = STAGE_RANK.get("FINAL", top_rank)
                        else:
                            effective = STAGE_RANK.get("THIRD_PLACE", STAGE_RANK.get(stage_str, 0))
                    else:
                        current_round_rank = STAGE_RANK.get(stage_str, 0)

                        # In knockout play, a win means the team has reached
                        # the next stage. Example: winning LAST_32 means the
                        # team is now in the Round of 16.
                        if stage_str != "GROUP_STAGE" and team_won:
                            effective = min(current_round_rank + 1, top_rank)
                        else:
                            effective = current_round_rank

                    if effective > s["best_stage"]:
                        s["best_stage"] = effective

                    # A semifinal loser is still alive in the 3rd Place playoff.
                    # Other knockout losses eliminate the team, including a
                    # Final or 3rd Place loss once that match is complete.
                    if stage_str != "GROUP_STAGE" and not team_won and stage_str != "SEMI_FINALS":
                        s["eliminated"] = True
                        s["eliminated_stage"] = stage_str
                    elif stage_str == "SEMI_FINALS" and not team_won:
                        s["eliminated"] = False
                        s["eliminated_stage"] = None
                    elif team_won:
                        # Winning a later match un-sets a stale elimination flag
                        # (shouldn't normally happen, but keeps state consistent).
                        s["eliminated"] = False
                        s["eliminated_stage"] = None

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
        # bracket fills in); fall back to the bracket map/static fixtures.
        #
        # Important: eliminated teams should never show a stale future/pending
        # match. Once eliminated, force the next-match cell to "Eliminated."
        next_game = None
        if s["eliminated"]:
            next_game = get_next_game(m["country"], fixtures_db, eliminated=True)
        else:
            if all_matches:
                next_game = build_next_match_from_api(tid, all_matches, m["country"])

            # If the API has the future match but not the opponent yet, prefer
            # the known bracket path over a plain TBD.
            api_opponent_unresolved = (
                next_game is not None and
                (not next_game.get("opponent") or "TBD" in str(next_game.get("opponent", "")).upper())
            )
            if api_opponent_unresolved:
                fb = get_bracket_fallback(m["country"], stage_val)
                if fb:
                    next_game = fb

            if next_game is None:
                fb = get_bracket_fallback(m["country"], stage_val)
                next_game = fb or get_next_game(m["country"], fixtures_db, eliminated=False)

            # If fallback/static data points to a past match after the team has
            # advanced, try the bracket fallback again. This avoids stale entries
            # like Brazil still showing Japan after Brazil won the R32 match.
            if next_game and next_game.get("iso"):
                try:
                    ng_time = datetime.fromisoformat(next_game["iso"])
                    if ng_time.timestamp() < datetime.now(timezone.utc).timestamp() - 10800:
                        fb = get_bracket_fallback(m["country"], stage_val)
                        if fb:
                            next_game = fb
                except ValueError:
                    pass

        # A team that has QUALIFIED for a later round but hasn't played it yet
        # would otherwise still show "Group Stage" (best_stage only advances on
        # FINISHED matches). Bump the displayed stage to match their scheduled
        # next match so the UI reflects "Round of 32" etc. as soon as they're
        # through, not just once they've actually played it.
        stage_raw_next = next_game.pop("_stageRaw", None) if isinstance(next_game, dict) else None
        pending_rank = STAGE_RANK.get(stage_raw_next) if stage_raw_next else None
        is_pending = False
        if (not s["eliminated"]) and pending_rank is not None and pending_rank > stage_val:
            stage_val  = pending_rank
            is_pending = True

        top_rank = max(STAGE_RANK.values()) if STAGE_RANK else None

        if s["eliminated"]:
            stage_label = f"Eliminated – {prettify_stage_short(s.get('eliminated_stage', ''))}"
        elif isinstance(next_game, dict) and next_game.get("round") == "Final":
            stage_label = "Championship Game"
        elif isinstance(next_game, dict) and next_game.get("round") == "3rd Place":
            stage_label = "3rd Place Game"
        elif FINAL_STAGE and top_rank is not None and stage_val == top_rank and is_pending:
            stage_label = "Championship Game"
        else:
            stage_label = STAGE_DISPLAY.get(stage_val) or prettify_stage(stage_raw_next or "")

        print(
            f"  {m['flag']} {m['country']:14s} ({m['manager']:8s}) → "
            f"Stage: {stage_label:18s} "
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
            "stageLabel": stage_label,
            "eliminated": s["eliminated"],
            "gf":         s["gf"],
            "ga":         s["ga"],
            "nextGame":   next_game,
            "draftSlot":  None,   # managed in the browser
        })

    results.sort(
        key=lambda x: (
            x["stage"],
            x["gf"] - x["ga"],
            x["gf"],
        ),
        reverse=True,
    )

    central = datetime.now(ZoneInfo("America/Chicago"))

    output = {
        "updatedAt": central.strftime("%b %d %Y, %I:%M %p %Z"),
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
