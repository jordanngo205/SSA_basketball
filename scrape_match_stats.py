#!/usr/bin/env python3
"""
Scrape per-match team stats for all matches where both teams are in the DB.

For each match, calls the SSA API with matchIds=[match_id] to get stats
filtered to exactly that game, for both home and away teams.

Usage:
    python scrape_match_stats.py                   # scrape all missing matches
    python scrape_match_stats.py --match <id>      # scrape a specific match
    python scrape_match_stats.py --overwrite        # re-scrape already stored matches
    python scrape_match_stats.py --status           # just print what's stored

Requires: SSA_USERNAME, SSA_PASSWORD in .env
"""

import argparse, os, sys, time, sqlite3
import requests
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
import ssa_functions as sf

BASE_DIR = Path(__file__).parent
DB_PATH  = BASE_DIR / "data" / "db" / "ssa.db"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class TokenManager:
    REFRESH_AFTER_S = 2700

    def __init__(self, session, username, password):
        self.session  = session
        self.username = username
        self.password = password
        self._refresh_token = None
        self._token         = None
        self._acquired_at   = 0
        self._login()

    def _login(self):
        self._token, self._refresh_token = sf.get_access_token(
            self.session, self.username, self.password)
        self._acquired_at = time.time()

    @property
    def token(self):
        if time.time() - self._acquired_at > self.REFRESH_AFTER_S:
            try:
                self._token, self._refresh_token = sf.refresh_access_token(
                    self.session, self._refresh_token)
                self._acquired_at = time.time()
                print("\n  [token refreshed]", flush=True)
            except Exception:
                self._login()
                print("\n  [re-authenticated]", flush=True)
        return self._token


def auth():
    load_dotenv(BASE_DIR / ".env")
    u = os.getenv("SSA_USERNAME")
    p = os.getenv("SSA_PASSWORD")
    if not u or not p:
        sys.exit("Set SSA_USERNAME and SSA_PASSWORD in .env")
    session = requests.Session()
    tm = TokenManager(session, u, p)
    return session, tm


# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS match_team_stats (
    match_id   TEXT NOT NULL,
    team_id    TEXT NOT NULL,
    stat_label TEXT NOT NULL,
    total      REAL,
    per_game   REAL,
    PRIMARY KEY (match_id, team_id, stat_label)
);

CREATE TABLE IF NOT EXISTS match_team_play_types (
    match_id   TEXT NOT NULL,
    team_id    TEXT NOT NULL,
    side       TEXT NOT NULL,
    label      TEXT NOT NULL,
    possession REAL,
    points     REAL,
    ppp        REAL,
    pct        REAL,
    PRIMARY KEY (match_id, team_id, side, label)
);

CREATE TABLE IF NOT EXISTS match_team_play_types_detail (
    match_id     TEXT NOT NULL,
    team_id      TEXT NOT NULL,
    play_type    TEXT NOT NULL,
    poss         REAL,
    ppp          REAL,
    usage        REAL,
    ft_m         REAL,
    ft_a         REAL,
    two_pt_m     REAL,
    two_pt_a     REAL,
    two_pt_pct   REAL,
    three_pt_m   REAL,
    three_pt_a   REAL,
    three_pt_pct REAL,
    turnovers    REAL,
    assists      REAL,
    PRIMARY KEY (match_id, team_id, play_type)
);

CREATE TABLE IF NOT EXISTS match_team_turnovers (
    match_id         TEXT NOT NULL,
    team_id          TEXT NOT NULL,
    play_type        TEXT NOT NULL,
    bad_pass         INTEGER,
    traveling        INTEGER,
    dribble_turnover INTEGER,
    line_violation   INTEGER,
    clock_violation  INTEGER,
    offensive_foul   INTEGER,
    other            INTEGER,
    total            INTEGER,
    PRIMARY KEY (match_id, team_id, play_type)
);

CREATE TABLE IF NOT EXISTS match_player_stats (
    match_id   TEXT NOT NULL,
    team_id    TEXT NOT NULL,
    player_id  TEXT NOT NULL,
    stat_label TEXT NOT NULL,
    per_game   REAL,
    PRIMARY KEY (match_id, player_id, stat_label)
);
"""


def ensure_tables(conn):
    for stmt in CREATE_TABLES.split(";"):
        s = stmt.strip()
        if s:
            conn.execute(s)
    conn.commit()


def upsert(conn, table, row):
    cols = ", ".join(row.keys())
    phs  = ", ".join(["?"] * len(row))
    conn.execute(
        f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({phs})",
        list(row.values()),
    )


# ---------------------------------------------------------------------------
# Insert helpers
# ---------------------------------------------------------------------------

def insert_overall(conn, match_id, team_id, data):
    for item in (data or []):
        v = item.get("values", {})
        upsert(conn, "match_team_stats", {
            "match_id":   match_id,
            "team_id":    team_id,
            "stat_label": item["label"],
            "total":      v.get("total"),
            "per_game":   v.get("perGame"),
        })


def insert_play_types(conn, match_id, team_id, side, data):
    for item in (data or []):
        v = item.get("values", {})
        upsert(conn, "match_team_play_types", {
            "match_id":   match_id,
            "team_id":    team_id,
            "side":       side,
            "label":      item["label"],
            "possession": v.get("possession"),
            "points":     v.get("points"),
            "ppp":        v.get("pointsPerPossession"),
            "pct":        v.get("possessionPercentage"),
        })


def insert_play_types_detail(conn, match_id, team_id, data):
    for item in (data or []):
        v = item.get("values", {})
        upsert(conn, "match_team_play_types_detail", {
            "match_id":     match_id,
            "team_id":      team_id,
            "play_type":    item["label"],
            "poss":         v.get("numberOfPossessions"),
            "ppp":          v.get("pointsPerPossession"),
            "usage":        v.get("usage"),
            "ft_m":         v.get("ftM"),
            "ft_a":         v.get("ftA"),
            "two_pt_m":     v.get("twoPtM"),
            "two_pt_a":     v.get("twoPtA"),
            "two_pt_pct":   v.get("twoPtPercentage"),
            "three_pt_m":   v.get("threePtM"),
            "three_pt_a":   v.get("threePtA"),
            "three_pt_pct": v.get("threePtPercentage"),
            "turnovers":    v.get("turnovers"),
            "assists":      v.get("assistance"),
        })


def insert_turnovers(conn, match_id, team_id, data):
    for item in (data or []):
        v = item.get("values", {})
        upsert(conn, "match_team_turnovers", {
            "match_id":         match_id,
            "team_id":          team_id,
            "play_type":        item["label"],
            "bad_pass":         v.get("BAD_PASS"),
            "traveling":        v.get("TRAVELING"),
            "dribble_turnover": v.get("DRIBBLE_TURNOVER"),
            "line_violation":   v.get("LINE_VIOLATION"),
            "clock_violation":  v.get("CLOCK_VIOLATION"),
            "offensive_foul":   v.get("OFFENSIVE_FOUL"),
            "other":            v.get("OTHER"),
            "total":            v.get("TOTAL"),
        })


def insert_player_overall(conn, match_id, team_id, player_id, data):
    for item in (data or []):
        v = item.get("values", {})
        pg = v.get("perGame")
        if pg is None:
            continue
        upsert(conn, "match_player_stats", {
            "match_id":   match_id,
            "team_id":    team_id,
            "player_id":  player_id,
            "stat_label": item["label"],
            "per_game":   round(pg, 4),
        })


# ---------------------------------------------------------------------------
# Scrape one team for one match
# ---------------------------------------------------------------------------

def _turnovers_url(team_id, period, comp_type):
    return f"{sf.BASE_URL}/reporting/team/{team_id}/turnovers/{period}/{comp_type}"


def scrape_team_match(session, tm, conn, match_id, team_id, season_id, comp_type):
    results = []
    mids = [match_id]

    calls = [
        ("overall",    sf.get_team_overall,
         lambda d: insert_overall(conn, match_id, team_id, d)),
        ("add_off",    sf.get_team_additional_offense,
         lambda d: insert_play_types(conn, match_id, team_id, "offense", d)),
        ("add_def",    sf.get_team_additional_defense,
         lambda d: insert_play_types(conn, match_id, team_id, "defense", d)),
        ("pt_detail",  sf.get_team_play_types,
         lambda d: insert_play_types_detail(conn, match_id, team_id, d)),
    ]

    for label, fn, insert_fn in calls:
        try:
            # period=CUSTOM + matchIds: perGame = stats for that exact match only
            data = fn(session, tm.token, team_id, season_id,
                      period="CUSTOM", competition_type=comp_type, match_ids=mids)
            insert_fn(data)
            results.append("✓")
        except Exception as e:
            results.append(f"✗")
        time.sleep(0.15)

    # Turnovers breakdown by play type
    try:
        url = _turnovers_url(team_id, "CUSTOM", comp_type)
        data = sf._report_post(session, tm.token, url, season_id, mids)
        insert_turnovers(conn, match_id, team_id, data)
        results.append("✓")
    except Exception:
        results.append("✗")
    time.sleep(0.15)

    conn.commit()
    return "".join(results)


def scrape_player_match(session, tm, conn, match_id, team_id, player_id, season_id, comp_type):
    mids = [match_id]
    try:
        data = sf.get_player_overall(session, tm.token, player_id, season_id,
                                     period="CUSTOM", competition_type=comp_type, match_ids=mids)
        insert_player_overall(conn, match_id, team_id, player_id, data)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Load matches from DB
# ---------------------------------------------------------------------------

def load_matches(conn, match_id_filter=None):
    q = """
        SELECT m.id, m.season_id,
               m.home_team_id, ht.competition_type as h_ct,
               m.away_team_id, at.competition_type as a_ct,
               m.home_team_name, m.away_team_name,
               m.home_score, m.away_score, m.match_date
        FROM matches m
        JOIN teams ht ON ht.id = m.home_team_id
        JOIN teams at ON at.id = m.away_team_id
        WHERE (COALESCE(m.home_score,0)+COALESCE(m.away_score,0)) > 0
          AND ht.sex='FEMALE' AND at.sex='FEMALE'
    """
    params = []
    if match_id_filter:
        q += " AND m.id=?"
        params.append(match_id_filter)
    q += " ORDER BY m.match_date DESC"
    return conn.execute(q, params).fetchall()


def already_scraped(conn, match_id, team_id):
    r = conn.execute(
        "SELECT COUNT(*) FROM match_team_stats WHERE match_id=? AND team_id=?",
        (match_id, team_id)
    ).fetchone()
    return (r[0] or 0) > 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--match",     default=None, help="Scrape a specific match ID only")
    parser.add_argument("--overwrite", action="store_true", help="Re-scrape matches already in DB")
    parser.add_argument("--status",    action="store_true", help="Print what is already stored and exit")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH, timeout=30)
    ensure_tables(conn)

    if args.status:
        rows = conn.execute("""
            SELECT m.home_team_name, m.away_team_name, m.match_date, m.home_score, m.away_score,
                   (SELECT COUNT(*) FROM match_team_stats WHERE match_id=m.id) as stat_rows
            FROM matches m
            JOIN teams ht ON ht.id = m.home_team_id
            JOIN teams at ON at.id = m.away_team_id
            WHERE stat_rows > 0
            ORDER BY m.match_date DESC
        """).fetchall()
        total = conn.execute("SELECT COUNT(DISTINCT match_id) FROM match_team_stats").fetchone()[0]
        print(f"Matches with data: {total}")
        for r in rows:
            print(f"  {r[2]}  {r[0]} {r[3]}-{r[4]} {r[1]}  ({r[5]} stat rows)")
        conn.close()
        return

    session, tm = auth()

    matches = load_matches(conn, args.match)
    print(f"Found {len(matches)} match(es) to process")

    done, skipped, errors = 0, 0, 0

    for i, row in enumerate(matches):
        (match_id, season_id, home_id, h_ct, away_id, a_ct,
         h_name, a_name, h_score, a_score, mdate) = row

        label = f"{mdate}  {h_name} {h_score}-{a_score} {a_name}"
        print(f"\n[{i+1}/{len(matches)}] {label}")

        for team_id, ct, side in [(home_id, h_ct, "home"), (away_id, a_ct, "away")]:
            if not args.overwrite and already_scraped(conn, match_id, team_id):
                print(f"  {side} ({team_id[:8]}) — already done, skipping")
                skipped += 1
                continue

            result = scrape_team_match(session, tm, conn, match_id, team_id, season_id, ct)

            # Scrape per-player stats — only players with at least 1 confirmed game played
            players = conn.execute("""
                SELECT DISTINCT p.id FROM players p
                JOIN player_stats ps ON ps.player_id = p.id
                WHERE p.team_id = ? AND ps.stat_label = 'GAMES_PLAYED' AND ps.per_game >= 1
            """, (team_id,)).fetchall()
            p_done = p_skip = 0
            for (pid,) in players:
                already = conn.execute(
                    "SELECT COUNT(*) FROM match_player_stats WHERE match_id=? AND player_id=?",
                    (match_id, pid)
                ).fetchone()[0]
                if already and not args.overwrite:
                    p_skip += 1
                    continue
                ok = scrape_player_match(session, tm, conn, match_id, team_id, pid, season_id, ct)
                p_done += 1
                time.sleep(0.12)
            conn.commit()

            p_summary = f" | {p_done} players" if p_done else (f" | {p_skip} pl skipped" if p_skip else "")
            print(f"  {side} ({team_id[:8]}) — {result}{p_summary}")
            done += 1

    conn.close()
    print(f"\nDone. Scraped: {done}  Skipped: {skipped}  Errors: {errors}")


if __name__ == "__main__":
    main()
