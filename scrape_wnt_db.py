#!/usr/bin/env python3
"""
WNT direct-to-DB scraper — mirrors scrape_clubs.py architecture.
Reads roster from DB (players already discovered), scrapes all endpoints
for all periods, writes directly to SQLite with competition_type='NATIONAL_TEAMS'.

Usage:
    python scrape_wnt_db.py --all-periods          # All WNT teams, all 4 periods
    python scrape_wnt_db.py --team "Canada WNT"    # Single team, all periods
    python scrape_wnt_db.py --period LAST_3        # All teams, one period
"""
import argparse, os, sys, time, sqlite3
import requests
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
import ssa_functions as sf

BASE_DIR  = Path(__file__).parent
DB_PATH   = BASE_DIR / "data" / "db" / "ssa.db"
COMP_TYPE = "NATIONAL_TEAMS"
SEASON_ID = "cba189ee-e4b9-47c1-a650-437e3828160d"
ALL_PERIODS = ["SEASON", "LAST_1", "LAST_3", "LAST_5"]


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


def _upsert(conn, table, row):
    cols = ", ".join(row.keys())
    phs  = ", ".join(["?"] * len(row))
    conn.execute(f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({phs})", list(row.values()))


# ── Player stat inserts (all tagged competition_type=NATIONAL_TEAMS) ──────────

def _insert_stats(conn, pid, period, data):
    for item in (data or []):
        v = item.get("values", {})
        _upsert(conn, "player_stats", {
            "player_id": pid, "period": period, "stat_label": item["label"],
            "competition_type": COMP_TYPE,
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


def scrape_player(session, tm, conn, pid, name, period):
    results = []
    calls = [
        ("overall",   sf.get_player_overall,
         lambda d: _insert_stats(conn, pid, period, d)),
        ("add_off",   sf.get_player_additional_offense,
         lambda d: _insert_stats(conn, pid, period, d)),
        ("off_pt",    sf.get_player_offense_play_types,
         lambda d: _insert_play_types(conn, pid, period, "offense", d)),
        ("def_pt",    sf.get_player_defense_play_types,
         lambda d: _insert_play_types(conn, pid, period, "defense", d)),
        ("pt_detail", sf.get_player_play_types,
         lambda d: _insert_play_types_detail(conn, pid, period, d)),
        ("shooting",  sf.get_player_shooting_tendency,
         lambda d: _insert_tendency_shooting(conn, pid, period, d)),
        ("dribble",   sf.get_player_shooting_tendency_dribble,
         lambda d: _insert_tendency_dribble(conn, pid, period, d)),
        ("finishing", sf.get_player_shooting_tendency_finishing,
         lambda d: _insert_tendency_finishing(conn, pid, period, d)),
        ("turnovers", sf.get_player_turnovers,
         lambda d: _insert_turnovers(conn, pid, period, d)),
    ]
    for label, fn, insert_fn in calls:
        try:
            data = fn(session, tm.token, pid, SEASON_ID, period, COMP_TYPE)
            insert_fn(data)
            results.append("✓")
        except Exception:
            results.append("✗")
        time.sleep(0.15)

    for is_dribble in (False, True):
        try:
            data = sf.get_player_shot_zones(session, tm.token, pid, SEASON_ID, is_dribble, period, COMP_TYPE)
            _insert_shot_zones(conn, pid, period, is_dribble, data)
            results.append("✓")
        except Exception:
            results.append("✗")
        time.sleep(0.15)

    conn.commit()
    print("".join(results), flush=True)


def _upsert_matches(conn, matches):
    for m in (matches or []):
        _upsert(conn, "matches", {
            "id": m.get("id"), "season_id": m.get("seasonId"),
            "season_name": m.get("seasonName"),
            "home_team_id": m.get("homeTeamId"), "home_team_name": m.get("homeTeamName"),
            "away_team_id": m.get("awayTeamId"), "away_team_name": m.get("awayTeamName"),
            "home_score": m.get("homeTeamScore"), "away_score": m.get("awayTeamScore"),
            "match_date": (m.get("matchStartTime") or "")[:10],
        })


def scrape_team(session, tm, conn, team_id, team_name, players, period):
    print(f"\n  Team: {team_name}  ({team_id[:8]}...)")

    # Matches — period-independent, fetch once
    if period == "SEASON":
        try:
            matches = sf.get_all_team_matches(session, tm.token, team_id, SEASON_ID)
            _upsert_matches(conn, matches)
        except Exception:
            pass
        time.sleep(0.1)

    results = []
    for label, fn, insert_fn in [
        ("overall",  sf.get_team_overall,
         lambda d: _upsert_team_stats(conn, team_id, period, d)),
        ("off_pt",   sf.get_team_additional_offense,
         lambda d: _insert_team_play_types(conn, team_id, period, "offense", d)),
        ("def_pt",   sf.get_team_additional_defense,
         lambda d: _insert_team_play_types(conn, team_id, period, "defense", d)),
        ("pt_detail",sf.get_team_play_types,
         lambda d: _insert_team_play_types_detail(conn, team_id, period, d)),
    ]:
        try:
            data = fn(session, tm.token, team_id, SEASON_ID, period, COMP_TYPE)
            insert_fn(data)
            results.append("✓")
        except Exception:
            results.append("✗")
        time.sleep(0.1)
    print(f"  Team stats: {''.join(results)}")
    conn.commit()

    for p in players:
        print(f"  [{p['full_name']}]  ", end="", flush=True)
        scrape_player(session, tm, conn, p["id"], p["full_name"], period)
        time.sleep(0.2)


def _upsert_team_stats(conn, team_id, period, data):
    for item in (data or []):
        v = item.get("values", {})
        _upsert(conn, "team_stats", {
            "team_id": team_id, "period": period,
            "stat_label": item["label"],
            "total": v.get("total"), "per_game": v.get("perGame"),
        })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--team", default=None, help="Team name (partial match)")
    parser.add_argument("--period", default="SEASON",
                        choices=["LAST_1", "LAST_3", "LAST_5", "SEASON"])
    parser.add_argument("--all-periods", action="store_true",
                        help=f"Scrape all periods: {ALL_PERIODS}")
    args = parser.parse_args()

    session, tm = auth()
    print("SSA authenticated.")

    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row

    # Load WNT team names from DB
    wnt_team_names = dict(conn.execute(
        "SELECT id, name FROM teams WHERE competition_type='NATIONAL_TEAMS'"
    ).fetchall())

    # Load rosters from rosters.json (authoritative SSA source).
    # Players may be stored in DB under a clubs team_id, so we can't rely
    # on the players.team_id join — use the pre-built roster file instead.
    rosters_path = BASE_DIR / "data" / "rosters.json"
    rosters_json: dict = {}
    if rosters_path.exists():
        import json
        rosters_json = json.loads(rosters_path.read_text())

    teams: dict[str, dict] = {}
    for tid, tname in wnt_team_names.items():
        roster = rosters_json.get(tid, [])
        teams[tid] = {
            "name": tname,
            "players": [{"id": p["id"], "full_name": p["name"]} for p in roster],
        }

    if args.team:
        q = args.team.lower()
        teams = {tid: info for tid, info in teams.items() if q in info["name"].lower()}
        if not teams:
            print(f"No WNT team matching '{args.team}'")
            sys.exit(1)

    periods = ALL_PERIODS if args.all_periods else [args.period]
    print(f"\n{len(teams)} WNT teams | periods={periods}")

    for period in periods:
        print(f"\n{'='*60}")
        print(f"PERIOD: {period}")
        print(f"{'='*60}")
        done = 0
        for tid, info in sorted(teams.items(), key=lambda x: x[1]["name"]):
            print(f"[{done+1}/{len(teams)}] {info['name']}  ({len(info['players'])} players)")
            scrape_team(session, tm, conn, tid, info["name"], info["players"], period)
            done += 1

    conn.close()
    print("\n✅ Done")


if __name__ == "__main__":
    main()
