#!/usr/bin/env python3
"""
SSA Clubs Scraper — 2026 season, CLUBS competition type.

Phase 1 (--discover): find the clubs season ID and all club team IDs from matches.
Phase 2 (--team <name>): scrape team + players into SQLite for one club team.
Phase 3 (--all): scrape all discovered club teams.

Usage:
    python scrape_clubs.py --discover              # Find season + all clubs teams
    python scrape_clubs.py --team Canada           # Scrape Canada club, SEASON period
    python scrape_clubs.py --team Canada --period LAST_3
    python scrape_clubs.py --all --period SEASON   # Scrape every clubs team

Requires: SSA_USERNAME, SSA_PASSWORD in .env
"""

import argparse, json, os, sys, time, sqlite3, unicodedata
import requests
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
import ssa_functions as sf

BASE_DIR = Path(__file__).parent
DB_PATH  = BASE_DIR / "data" / "db" / "ssa.db"
RAW_DIR  = BASE_DIR / "data" / "raw" / "clubs"
RAW_DIR.mkdir(parents=True, exist_ok=True)

COMP_TYPE = "CLUBS"

DISCOVERY_FILE = BASE_DIR / "data" / "clubs_teams.json"

# Hardcoded rosters for teams where API roster is empty
# Same player IDs as WNT (same players, different comp type)
HARDCODED_ROSTERS: dict[str, list[dict]] = {
    # Canada clubs (ce77b0b3)
    "ce77b0b3-29ec-4f05-98ee-bf6e1f2db8e0": [
        {"id": "f532294f-8e69-4cbb-be69-7fa1cd6189b5", "name": "Katherine Plouffe",       "position": "GUARD",   "height": 183, "jersey": "9"},
        {"id": "d29fd8da-3ead-4c41-aa12-b496fb0debe9", "name": "Paige Crozon",            "position": "GUARD",   "height": 178, "jersey": "6"},
        {"id": "2b6dc75e-dd80-4324-9737-8bc4a0859ce8", "name": "Tara Wallack",            "position": "FORWARD", "height": 185, "jersey": "11"},
        {"id": "68f15832-1965-466d-8d78-4cd1d8c018e5", "name": "Merissah Melanie Russell","position": "GUARD",   "height": 173, "jersey": ""},
        {"id": "826db2c9-b290-4d3e-9991-1ce115aba415", "name": "Cassandra Brown",         "position": "FORWARD", "height": 188, "jersey": ""},
    ],
}

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

class TokenManager:
    """Holds the SSA access token and transparently refreshes it before it expires."""
    REFRESH_AFTER_S = 2700  # refresh proactively at 45 min (token lives 60 min)

    def __init__(self, session, username, password):
        self.session = session
        self.username = username
        self.password = password
        self._refresh_token = None
        self._token = None
        self._acquired_at = 0
        self._login()

    def _login(self):
        self._token, self._refresh_token = sf.get_access_token(self.session, self.username, self.password)
        self._acquired_at = time.time()

    @property
    def token(self):
        if time.time() - self._acquired_at > self.REFRESH_AFTER_S:
            try:
                self._token, self._refresh_token = sf.refresh_access_token(self.session, self._refresh_token)
                self._acquired_at = time.time()
                print("\n  [token refreshed]", flush=True)
            except Exception:
                self._login()
                print("\n  [re-authenticated]", flush=True)
        return self._token


def auth():
    load_dotenv(BASE_DIR / ".env")
    u = os.getenv("SSA_USERNAME"); p = os.getenv("SSA_PASSWORD")
    if not u or not p:
        sys.exit("Set SSA_USERNAME and SSA_PASSWORD in .env")
    session = requests.Session()
    tm = TokenManager(session, u, p)
    return session, tm


def get(session, token, url, params=None):
    r = session.get(url, params=params,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    timeout=30)
    r.raise_for_status()
    return r.json()


def post(session, token, url, body=None):
    r = session.post(url, json=body or {},
                     headers={"Authorization": f"Bearer {token}",
                               "Content-Type": "application/json", "Accept": "application/json"},
                     timeout=30)
    r.raise_for_status()
    return r.json()

# ---------------------------------------------------------------------------
# Phase 1 — discover seasons + clubs teams
# ---------------------------------------------------------------------------

def discover(session, token):
    print("=== Discovering clubs seasons ===")

    # Try to list seasons from API
    seasons_data = {}
    for endpoint in ["/seasons", "/season"]:
        try:
            d = get(session, token, sf.BASE_URL + endpoint)
            if isinstance(d, list) and d:
                seasons_data = {s.get("id"): s for s in d}
                break
            elif isinstance(d, dict) and d.get("content"):
                seasons_data = {s.get("id"): s for s in d["content"]}
                break
        except Exception:
            pass

    if seasons_data:
        print(f"  Found {len(seasons_data)} seasons:")
        for sid, s in seasons_data.items():
            print(f"    {sid}  {s.get('name','?')}  {s.get('year','')}")
    else:
        print("  /seasons endpoint not available — using known season IDs")
        seasons_data = {
            "cba189ee-e4b9-47c1-a650-437e3828160d": {"name": "2026 FIBA CUPS", "year": 2026},
        }

    # Scan matches with competitionType=CLUBS across all season IDs
    print("\n=== Scanning matches for CLUBS teams ===")
    teams: dict[str, dict] = {}   # team_id → {name, season_id}

    for season_id, season_info in seasons_data.items():
        sname = season_info.get("name", season_id[:8])
        page, total_pages = 0, 1
        found_any = False

        while page < total_pages:
            try:
                data = get(session, token, f"{sf.BASE_URL}/matches", params={
                    "seasonId": season_id,
                    "competitionType": COMP_TYPE,
                    "page": page, "size": 100,
                    "sort": "id", "direction": "DESC",
                })
            except Exception as e:
                print(f"  [{sname}] page {page} error: {e}")
                break

            matches   = data.get("content") or (data if isinstance(data, list) else [])
            total_pages = data.get("totalPages", 1) if isinstance(data, dict) else 1

            for m in matches:
                for side in ("home", "away"):
                    tid  = m.get(f"{side}TeamId")
                    name = m.get(f"{side}TeamName", "")
                    sex  = m.get(f"{side}TeamSex", "")
                    if tid and tid not in teams:
                        teams[tid] = {"name": name, "season_id": season_id,
                                      "season_name": sname, "sex": sex}
                        found_any = True

            if not matches:
                break
            page += 1
            time.sleep(0.1)

        if found_any:
            print(f"  [{sname}] → {sum(1 for t in teams.values() if t['season_id']==season_id)} clubs teams found")

    if not teams:
        print("\n  No clubs teams found. The season may use a different ID.")
        print("  Try: check the SSA UI URL when you select 'Clubs' filter and share the season UUID.")
        return

    print(f"\n  Total clubs teams found: {len(teams)}")
    for tid, info in sorted(teams.items(), key=lambda x: x[1]["name"]):
        print(f"    {info['name']:<35} {tid}  [{info['season_name']}]")

    DISCOVERY_FILE.write_text(json.dumps(teams, indent=2))
    print(f"\n  Saved → {DISCOVERY_FILE}")

# ---------------------------------------------------------------------------
# Phase 2 — scrape one team (team stats + all players)
# ---------------------------------------------------------------------------

def _safe(fn, label, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception as e:
        print(f"    [{label}] {e}")
        return None


def _upsert(conn, table, row):
    cols = ", ".join(row.keys())
    phs  = ", ".join(["?"] * len(row))
    conn.execute(
        f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({phs})",
        list(row.values())
    )


def _insert_stats(conn, pid, period, data):
    for item in (data or []):
        v = item.get("values", {})
        _upsert(conn, "player_stats", {
            "player_id": pid, "period": period,
            "stat_label": item["label"], "competition_type": COMP_TYPE,
            "total": v.get("total"), "per_game": v.get("perGame"),
        })


def _insert_play_types(conn, pid, period, side, data):
    for item in (data or []):
        v = item.get("values", {})
        _upsert(conn, "player_play_types", {
            "player_id": pid, "period": period, "side": side,
            "label": item["label"], "competition_type": COMP_TYPE,
            "possession": v.get("possession"), "points": v.get("points"),
            "ppp": v.get("pointsPerPossession"), "pct": v.get("possessionPercentage"),
        })


def _insert_play_types_detail(conn, pid, period, data):
    for item in (data or []):
        v = item.get("values", {})
        _upsert(conn, "player_play_types_detail", {
            "player_id": pid, "period": period, "play_type": item["label"],
            "competition_type": COMP_TYPE,
            "poss": v.get("numberOfPossessions"), "ppp": v.get("pointsPerPossession"),
            "usage": v.get("usage"),
            "ft_m": v.get("ftM"), "ft_a": v.get("ftA"),
            "two_pt_m": v.get("twoPtM"), "two_pt_a": v.get("twoPtA"),
            "two_pt_pct": v.get("twoPtPercentage"),
            "three_pt_m": v.get("threePtM"), "three_pt_a": v.get("threePtA"),
            "three_pt_pct": v.get("threePtPercentage"),
            "turnovers": v.get("turnovers"), "assists": v.get("assistance"),
        })


def _shooting_vals(values):
    v = values[0] if isinstance(values, list) and values else (values or {})
    return {
        "short_range_m":   v.get("shortRangeM", 0),
        "short_range_a":   v.get("shortRangeA", 0),
        "short_range_pct": v.get("shortRangePercentage", 0.0),
        "mid_range_m":     v.get("midRangeM", 0),
        "mid_range_a":     v.get("midRangeA", 0),
        "mid_range_pct":   v.get("midRangePercentage", 0.0),
        "two_pt_m":        v.get("threePtM", 0),
        "two_pt_a":        v.get("threePtA", 0),
        "two_pt_pct":      v.get("threePtPercentage", 0.0),
    }


def _insert_tendency_shooting(conn, pid, period, data):
    current_cat = "TOTAL_SHOTS"
    for item in (data or []):
        label, level = item["label"], item["level"]
        if level == 0:
            current_cat, hand = label, "ALL"
        elif level == 1:
            hand = ("LEFT" if "LEFT" in label else "RIGHT") if label.startswith("FROM_") else "ALL"
            if not label.startswith("FROM_"): current_cat = label
        else:
            hand = "LEFT" if "LEFT" in label else "RIGHT"
        _upsert(conn, "player_tendency_shooting", {
            "player_id": pid, "period": period,
            "category": current_cat, "hand": hand, "competition_type": COMP_TYPE,
            **_shooting_vals(item["values"]),
        })


def _insert_tendency_finishing(conn, pid, period, data):
    current_shot = "ALL"
    for item in (data or []):
        label, level = item["label"], item["level"]
        v = item["values"]
        if level in (0, 1): current_shot, hand = label, "ALL"
        else: hand = "LEFT" if "LEFT" in label else "RIGHT"
        _upsert(conn, "player_tendency_finishing", {
            "player_id": pid, "period": period,
            "shot_type": current_shot, "hand": hand, "competition_type": COMP_TYPE,
            "made": v.get("made", 0), "attempted": v.get("attempted", 0),
            "pct": v.get("percentage", 0.0),
        })


def _insert_tendency_dribble(conn, pid, period, data):
    current_pt = "ALL"
    for item in (data or []):
        label, level = item["label"], item["level"]
        if level == 0:
            current_pt, hand = "ALL", "ALL"
        elif level == 1:
            if label.startswith("FROM_"):
                hand = "LEFT" if "LEFT" in label else "RIGHT"
                current_pt = "ALL"
            else:
                current_pt, hand = label, "ALL"
        else:
            hand = "LEFT" if "LEFT" in label else "RIGHT"
        _upsert(conn, "player_tendency_dribble", {
            "player_id": pid, "period": period,
            "play_type": current_pt, "hand": hand, "competition_type": COMP_TYPE,
            **_shooting_vals(item["values"]),
        })


def _insert_turnovers(conn, pid, period, data):
    for item in (data or []):
        v = item.get("values", {})
        _upsert(conn, "player_turnovers", {
            "player_id": pid, "period": period, "play_type": item["label"],
            "competition_type": COMP_TYPE,
            "bad_pass": v.get("BAD_PASS", 0), "traveling": v.get("TRAVELING", 0),
            "dribble_turnover": v.get("DRIBBLE_TURNOVER", 0),
            "line_violation": v.get("LINE_VIOLATION", 0),
            "clock_violation": v.get("CLOCK_VIOLATION", 0),
            "offensive_foul": v.get("OFFENSIVE_FOUL", 0),
            "other": v.get("OTHER", 0), "total": v.get("TOTAL", 0),
        })


def _insert_shot_zones(conn, pid, period, is_dribble, data):
    for item in (data or []):
        v = item.get("values", {})
        _upsert(conn, "player_shot_zones", {
            "player_id": pid, "period": period,
            "is_dribble": 1 if is_dribble else 0,
            "zone": item["label"], "competition_type": COMP_TYPE,
            "made": v.get("made", 0), "missed": v.get("missed", 0),
            "total": v.get("total", 0), "pct": v.get("percentage", 0.0),
        })


def _insert_team_play_types(conn, team_id, period, side, data):
    for item in (data or []):
        v = item.get("values", {})
        _upsert(conn, "team_play_types", {
            "team_id": team_id, "period": period, "side": side,
            "label": item["label"],
            "possession": v.get("possession"), "points": v.get("points"),
            "ppp": v.get("pointsPerPossession"), "pct": v.get("possessionPercentage"),
        })


def _insert_team_play_types_detail(conn, team_id, period, data):
    for item in (data or []):
        v = item.get("values", {})
        _upsert(conn, "team_play_types_detail", {
            "team_id": team_id, "period": period, "play_type": item["label"],
            "poss": v.get("numberOfPossessions"), "ppp": v.get("pointsPerPossession"),
            "usage": v.get("usage"),
            "ft_m": v.get("ftM"), "ft_a": v.get("ftA"),
            "two_pt_m": v.get("twoPtM"), "two_pt_a": v.get("twoPtA"),
            "two_pt_pct": v.get("twoPtPercentage"),
            "three_pt_m": v.get("threePtM"), "three_pt_a": v.get("threePtA"),
            "three_pt_pct": v.get("threePtPercentage"),
            "turnovers": v.get("turnovers"), "assists": v.get("assistance"),
        })


def scrape_player_into_db(session, tm, conn, pid, name, season_id, period):
    results = []
    calls = [
        ("overall",    sf.get_player_overall,
         lambda d: _insert_stats(conn, pid, period, d)),
        ("add_off",    sf.get_player_additional_offense,
         lambda d: _insert_stats(conn, pid, period, d)),
        ("off_pt",     sf.get_player_offense_play_types,
         lambda d: _insert_play_types(conn, pid, period, "offense", d)),
        ("def_pt",     sf.get_player_defense_play_types,
         lambda d: _insert_play_types(conn, pid, period, "defense", d)),
        ("pt_detail",  sf.get_player_play_types,
         lambda d: _insert_play_types_detail(conn, pid, period, d)),
        ("shooting",   sf.get_player_shooting_tendency,
         lambda d: _insert_tendency_shooting(conn, pid, period, d)),
        ("dribble",    sf.get_player_shooting_tendency_dribble,
         lambda d: _insert_tendency_dribble(conn, pid, period, d)),
        ("finishing",  sf.get_player_shooting_tendency_finishing,
         lambda d: _insert_tendency_finishing(conn, pid, period, d)),
        ("turnovers",  sf.get_player_turnovers,
         lambda d: _insert_turnovers(conn, pid, period, d)),
    ]
    for label, fn, insert_fn in calls:
        try:
            data = fn(session, tm.token, pid, season_id, period, COMP_TYPE)
            insert_fn(data)
            results.append("✓")
        except Exception as e:
            results.append("✗")
        time.sleep(0.15)

    for is_dribble in (False, True):
        try:
            data = sf.get_player_shot_zones(session, tm.token, pid, season_id, is_dribble, period, COMP_TYPE)
            _insert_shot_zones(conn, pid, period, is_dribble, data)
            results.append("✓")
        except Exception:
            results.append("✗")
        time.sleep(0.15)

    conn.commit()
    print(f"    {''.join(results)}", flush=True)


def build_clubs_roster_map(session, tm, sex_filter=None) -> dict[str, list[dict]]:
    """
    Build {clubs_team_id: [player_dict]} by:
      1. Paging the full player list (fast, but clubs=[] in paginated response)
      2. Fetching individual records for each matched player (has clubs populated)

    sex_filter: "FEMALE", "MALE", or None for all
    """
    print("Step 1: collecting player IDs from paginated list...")
    player_ids: list[tuple[str, str]] = []   # (id, sex)
    page, total_pages = 0, 1

    while page < total_pages:
        r = session.get(f"{sf.BASE_URL}/players",
                        params={"size": 100, "page": page},
                        headers=sf._headers(tm.token), timeout=30)
        r.raise_for_status()
        data = r.json()
        total_pages = data.get("totalPages", 1)
        for p in data.get("content", []):
            pid = p.get("id")
            sex = (p.get("sex") or "").upper()
            if pid and (sex_filter is None or sex == sex_filter.upper()):
                player_ids.append((pid, sex))
        page += 1
        print(f"  page {page}/{total_pages}  matched={len(player_ids)}", end="\r")
        time.sleep(0.05)

    print(f"\n  {len(player_ids)} players to fetch individually")

    print("Step 2: fetching individual records to get clubs...")
    roster_map: dict[str, list[dict]] = {}

    for i, (pid, sex) in enumerate(player_ids):
        try:
            r = session.get(f"{sf.BASE_URL}/players/{pid}",
                            headers=sf._headers(tm.token), timeout=30)
            r.raise_for_status()
            p = r.json()
            name = f"{(p.get('firstName') or '').strip()} {(p.get('lastName') or '').strip()}".strip()
            rec = {
                "id":       pid,
                "name":     name,
                "position": p.get("position"),
                "height":   p.get("height"),
                "jersey":   p.get("favouriteJerseyNumber") or "",
                "sex":      sex,
            }
            for club in (p.get("clubs") or []):
                tid = club.get("id")
                if tid:
                    roster_map.setdefault(tid, []).append(rec)
        except Exception as e:
            pass

        if (i + 1) % 50 == 0 or i == len(player_ids) - 1:
            print(f"  {i+1}/{len(player_ids)} fetched  teams_so_far={len(roster_map)}", end="\r")
        time.sleep(0.07)

    total_links = sum(len(v) for v in roster_map.values())
    print(f"\nRoster map complete: {len(roster_map)} clubs teams, {total_links} player slots")
    return roster_map


def _insert_team_stats(conn, team_id, period, data):
    for item in (data or []):
        v = item.get("values", {})
        conn.execute(
            "INSERT OR REPLACE INTO team_stats (team_id, period, stat_label, total, per_game) "
            "VALUES (?,?,?,?,?)",
            (team_id, period, item["label"], v.get("total"), v.get("perGame"))
        )


def scrape_team(session, tm, team_id, team_name, season_id, period, conn, roster=None):
    print(f"\n  Team: {team_name}  ({team_id[:8]}...)")

    conn.execute(
        "INSERT OR IGNORE INTO teams (id, name, competition_type) VALUES (?,?,?)",
        (team_id, team_name, COMP_TYPE)
    )

    # Ensure team_stats table exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS team_stats (
            team_id TEXT, period TEXT, stat_label TEXT,
            total REAL, per_game REAL,
            PRIMARY KEY (team_id, period, stat_label)
        )""")
    conn.commit()

    # Matches (period-independent, only fetch once for SEASON)
    if period == "SEASON":
        try:
            matches = sf.get_all_team_matches(session, tm.token, team_id, season_id)
            for m in (matches or []):
                _upsert(conn, "matches", {
                    "id": m.get("id"), "season_id": m.get("seasonId"),
                    "season_name": m.get("seasonName"),
                    "home_team_id": m.get("homeTeamId"), "home_team_name": m.get("homeTeamName"),
                    "away_team_id": m.get("awayTeamId"), "away_team_name": m.get("awayTeamName"),
                    "home_score": m.get("homeTeamScore"), "away_score": m.get("awayTeamScore"),
                    "match_date": (m.get("matchStartTime") or "")[:10],
                })
        except Exception:
            pass
        time.sleep(0.1)

    # Team-level stats
    print("  Team stats: ", end="", flush=True)
    results = []
    try:
        data = sf.get_team_overall(session, tm.token, team_id, season_id, period, COMP_TYPE)
        _insert_team_stats(conn, team_id, period, data)
        results.append("✓")
    except Exception:
        results.append("✗")
    time.sleep(0.1)
    try:
        data = sf.get_team_additional_offense(session, tm.token, team_id, season_id, period, COMP_TYPE)
        _insert_team_play_types(conn, team_id, period, "offense", data)
        results.append("✓")
    except Exception:
        results.append("✗")
    time.sleep(0.1)
    try:
        data = sf.get_team_additional_defense(session, tm.token, team_id, season_id, period, COMP_TYPE)
        _insert_team_play_types(conn, team_id, period, "defense", data)
        results.append("✓")
    except Exception:
        results.append("✗")
    time.sleep(0.1)
    try:
        data = sf.get_team_play_types(session, tm.token, team_id, season_id, period, COMP_TYPE)
        _insert_team_play_types_detail(conn, team_id, period, data)
        results.append("✓")
    except Exception:
        results.append("✗")
    time.sleep(0.1)
    print("".join(results))
    conn.commit()

    if not roster:
        print("  No roster — skipping player scraping")
        return

    for p in roster:
        pid  = p.get("id") or p.get("playerId")
        name = (p.get("name") or
                f"{p.get('firstName','')} {p.get('lastName','')}".strip() or
                p.get("playerName") or pid)
        pos  = p.get("position")
        ht   = p.get("height")
        num  = (p.get("jersey") or p.get("favouriteJerseyNumber") or
                p.get("shirtNumber") or p.get("number") or "")

        if not pid:
            continue

        conn.execute(
            "INSERT OR REPLACE INTO players (id, full_name, team_id, position, height, jersey_number) "
            "VALUES (?,?,?,?,?,?)",
            (pid, name, team_id, pos, ht, str(num))
        )
        conn.commit()

        print(f"  [{name}]  ", end="", flush=True)
        scrape_player_into_db(session, tm, conn, pid, name, season_id, period)
        time.sleep(0.2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

ALL_PERIODS = ["SEASON", "LAST_1", "LAST_3", "LAST_5"]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--discover", action="store_true",
                        help="Scan matches to find all clubs teams + season ID")
    parser.add_argument("--team",   default=None,
                        help="Team name to scrape (partial match, e.g. Canada)")
    parser.add_argument("--all",         action="store_true",
                        help="Scrape all discovered clubs teams")
    parser.add_argument("--all-women",   action="store_true",
                        help="Scrape all women's clubs teams (sex=FEMALE in match data)")
    parser.add_argument("--period", default="SEASON",
                        choices=["LAST_1","LAST_3","LAST_5","LAST_10","SEASON"])
    parser.add_argument("--all-periods", action="store_true",
                        help=f"Scrape all periods: {ALL_PERIODS}")
    args = parser.parse_args()

    session, tm = auth()

    if args.discover:
        discover(session, tm.token)
        return

    # Load discovered teams
    if not DISCOVERY_FILE.exists():
        print("No discovery file found. Run: python scrape_clubs.py --discover")
        sys.exit(1)
    teams = json.loads(DISCOVERY_FILE.read_text())

    # Pick target teams
    if args.team:
        q = args.team.lower()
        targets = {tid: info for tid, info in teams.items()
                   if q in info["name"].lower()}
        if not targets:
            print(f"No clubs team matching '{args.team}'. Available:")
            for info in sorted(teams.values(), key=lambda x: x["name"]):
                print(f"  {info['name']}")
            sys.exit(1)
    elif args.all_women:
        # Filter to women's teams using sex field stored in discovery
        targets = {tid: info for tid, info in teams.items()
                   if info.get("sex","").upper() == "FEMALE"}
        if not targets:
            print("No sex field in discovery data — re-running discover with sex tagging...")
            # Fallback: include all and let the scraper handle it
            targets = teams
        print(f"Women's clubs teams: {len(targets)}")
    elif args.all:
        targets = teams
    else:
        parser.print_help()
        sys.exit(0)

    # Open DB
    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row

    # Ensure teams table has competition_type column
    cols = [r[1] for r in conn.execute("PRAGMA table_info(teams)").fetchall()]
    if "competition_type" not in cols:
        conn.execute("ALTER TABLE teams ADD COLUMN competition_type TEXT")
        conn.commit()

    sex_filter = "FEMALE" if args.all_women else None
    roster_map = build_clubs_roster_map(session, tm, sex_filter=sex_filter)

    periods = ALL_PERIODS if args.all_periods else [args.period]
    sorted_targets = sorted(targets.items(), key=lambda x: x[1]["name"])

    print(f"\nScraping {len(targets)} club team(s) | periods={periods}")
    for period in periods:
        print(f"\n{'='*60}")
        print(f"PERIOD: {period}")
        print(f"{'='*60}")
        done = 0
        for tid, info in sorted_targets:
            roster = roster_map.get(tid, [])
            print(f"[{done+1}/{len(targets)}] {info['name']}  ({len(roster)} players)")
            scrape_team(session, tm, tid, info["name"],
                        info["season_id"], period, conn, roster=roster)
            done += 1

    conn.close()
    print("\n✅ Done")


if __name__ == "__main__":
    main()
