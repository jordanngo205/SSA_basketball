#!/usr/bin/env python3
"""
Load all scraped SSA JSON files into SQLite.
Usage: python load_ssa_db.py [--data-dir data/raw] [--db data/db/ssa.db]
"""

import argparse
import json
import os
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR  = os.path.join(BASE_DIR, "data", "raw")
DB_PATH  = os.path.join(BASE_DIR, "data", "db", "ssa.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY,
    name TEXT,
    competition_type TEXT,
    sex TEXT,
    game_type TEXT,
    city TEXT,
    country_id TEXT
);

CREATE TABLE IF NOT EXISTS players (
    id TEXT PRIMARY KEY,
    full_name TEXT,
    team_id TEXT,
    position TEXT,
    height REAL,
    jersey_number TEXT,
    nationality TEXT
);

CREATE TABLE IF NOT EXISTS matches (
    id TEXT PRIMARY KEY,
    season_id TEXT,
    season_name TEXT,
    home_team_id TEXT,
    home_team_name TEXT,
    away_team_id TEXT,
    away_team_name TEXT,
    home_score INTEGER,
    away_score INTEGER,
    match_date TEXT
);

CREATE TABLE IF NOT EXISTS team_stats (
    team_id TEXT,
    period TEXT,
    stat_label TEXT,
    total REAL,
    per_game REAL,
    PRIMARY KEY (team_id, period, stat_label)
);

CREATE TABLE IF NOT EXISTS team_play_types (
    team_id TEXT,
    period TEXT,
    side TEXT,
    label TEXT,
    possession REAL,
    points REAL,
    ppp REAL,
    pct REAL,
    PRIMARY KEY (team_id, period, side, label)
);

CREATE TABLE IF NOT EXISTS team_play_types_detail (
    team_id TEXT,
    period TEXT,
    play_type TEXT,
    poss REAL,
    ppp REAL,
    usage REAL,
    ft_m INTEGER,
    ft_a INTEGER,
    two_pt_m INTEGER,
    two_pt_a INTEGER,
    two_pt_pct REAL,
    three_pt_m INTEGER,
    three_pt_a INTEGER,
    three_pt_pct REAL,
    turnovers INTEGER,
    assists REAL,
    PRIMARY KEY (team_id, period, play_type)
);

CREATE TABLE IF NOT EXISTS player_stats (
    player_id TEXT,
    period TEXT,
    stat_label TEXT,
    total REAL,
    per_game REAL,
    PRIMARY KEY (player_id, period, stat_label)
);

CREATE TABLE IF NOT EXISTS player_play_types (
    player_id TEXT,
    period TEXT,
    side TEXT,
    label TEXT,
    possession REAL,
    points REAL,
    ppp REAL,
    pct REAL,
    PRIMARY KEY (player_id, period, side, label)
);

CREATE TABLE IF NOT EXISTS player_play_types_detail (
    player_id TEXT,
    period TEXT,
    play_type TEXT,
    poss REAL,
    ppp REAL,
    usage REAL,
    ft_m INTEGER,
    ft_a INTEGER,
    two_pt_m INTEGER,
    two_pt_a INTEGER,
    two_pt_pct REAL,
    three_pt_m INTEGER,
    three_pt_a INTEGER,
    three_pt_pct REAL,
    turnovers INTEGER,
    assists REAL,
    PRIMARY KEY (player_id, period, play_type)
);

CREATE TABLE IF NOT EXISTS player_tendency_shooting (
    player_id TEXT,
    period TEXT,
    category TEXT,
    hand TEXT,
    short_range_m INTEGER,
    short_range_a INTEGER,
    short_range_pct REAL,
    mid_range_m INTEGER,
    mid_range_a INTEGER,
    mid_range_pct REAL,
    two_pt_m INTEGER,
    two_pt_a INTEGER,
    two_pt_pct REAL,
    PRIMARY KEY (player_id, period, category, hand)
);

CREATE TABLE IF NOT EXISTS player_tendency_dribble (
    player_id TEXT,
    period TEXT,
    play_type TEXT,
    hand TEXT,
    short_range_m INTEGER,
    short_range_a INTEGER,
    short_range_pct REAL,
    mid_range_m INTEGER,
    mid_range_a INTEGER,
    mid_range_pct REAL,
    two_pt_m INTEGER,
    two_pt_a INTEGER,
    two_pt_pct REAL,
    PRIMARY KEY (player_id, period, play_type, hand)
);

CREATE TABLE IF NOT EXISTS player_tendency_finishing (
    player_id TEXT,
    period TEXT,
    shot_type TEXT,
    hand TEXT,
    made INTEGER,
    attempted INTEGER,
    pct REAL,
    PRIMARY KEY (player_id, period, shot_type, hand)
);

CREATE TABLE IF NOT EXISTS player_turnovers (
    player_id TEXT,
    period TEXT,
    play_type TEXT,
    bad_pass INTEGER,
    traveling INTEGER,
    dribble_turnover INTEGER,
    line_violation INTEGER,
    clock_violation INTEGER,
    offensive_foul INTEGER,
    other INTEGER,
    total INTEGER,
    PRIMARY KEY (player_id, period, play_type)
);

CREATE TABLE IF NOT EXISTS player_shot_zones (
    player_id TEXT,
    period TEXT,
    is_dribble INTEGER,
    zone TEXT,
    made INTEGER,
    missed INTEGER,
    total INTEGER,
    pct REAL,
    PRIMARY KEY (player_id, period, is_dribble, zone)
);

CREATE INDEX IF NOT EXISTS idx_player_stats_pid     ON player_stats(player_id, period);
CREATE INDEX IF NOT EXISTS idx_player_zones_pid      ON player_shot_zones(player_id, period, is_dribble);
CREATE INDEX IF NOT EXISTS idx_team_stats_tid         ON team_stats(team_id, period);
"""


def upsert(conn, table, row):
    cols = ", ".join(row.keys())
    placeholders = ", ".join(["?"] * len(row))
    conn.execute(
        f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({placeholders})",
        list(row.values()),
    )


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


def load_team_info(conn, data):
    d = data
    upsert(conn, "teams", {
        "id": d["id"], "name": d.get("name"),
        "competition_type": d.get("competitionType"),
        "sex": d.get("sex"), "game_type": d.get("gameType"),
        "city": d.get("city"), "country_id": d.get("countryId"),
    })


def load_matches(conn, data):
    for m in data:
        upsert(conn, "matches", {
            "id": m.get("id"), "season_id": m.get("seasonId"),
            "season_name": m.get("seasonName"),
            "home_team_id": m.get("homeTeamId"), "home_team_name": m.get("homeTeamName"),
            "away_team_id": m.get("awayTeamId"), "away_team_name": m.get("awayTeamName"),
            "home_score": m.get("homeTeamScore"), "away_score": m.get("awayTeamScore"),
            "match_date": (m.get("matchStartTime") or "")[:10],
        })


def load_stats(conn, table, id_col, entity_id, period, data, competition_type=None):
    for item in data:
        v = item.get("values", {})
        row = {id_col: entity_id, "period": period,
               "stat_label": item["label"],
               "total": v.get("total"), "per_game": v.get("perGame")}
        if competition_type and id_col == "player_id":
            row["competition_type"] = competition_type
        upsert(conn, table, row)


def load_play_types(conn, table, id_col, entity_id, period, side, data, competition_type=None):
    for item in data:
        v = item.get("values", {})
        row = {id_col: entity_id, "period": period, "side": side,
               "label": item["label"],
               "possession": v.get("possession"), "points": v.get("points"),
               "ppp": v.get("pointsPerPossession"), "pct": v.get("possessionPercentage")}
        if competition_type and id_col == "player_id":
            row["competition_type"] = competition_type
        upsert(conn, table, row)


def load_play_types_detail(conn, table, id_col, entity_id, period, data, competition_type=None):
    for item in data:
        v = item.get("values", {})
        row = {id_col: entity_id, "period": period, "play_type": item["label"],
               "poss": v.get("numberOfPossessions"), "ppp": v.get("pointsPerPossession"),
               "usage": v.get("usage"),
               "ft_m": v.get("ftM"), "ft_a": v.get("ftA"),
               "two_pt_m": v.get("twoPtM"), "two_pt_a": v.get("twoPtA"),
               "two_pt_pct": v.get("twoPtPercentage"),
               "three_pt_m": v.get("threePtM"), "three_pt_a": v.get("threePtA"),
               "three_pt_pct": v.get("threePtPercentage"),
               "turnovers": v.get("turnovers"), "assists": v.get("assistance")}
        if competition_type and id_col == "player_id":
            row["competition_type"] = competition_type
        upsert(conn, table, row)


def load_tendency_shooting(conn, player_id, period, data, competition_type=None):
    current_cat = "TOTAL_SHOTS"
    for item in data:
        label, level = item["label"], item["level"]
        if level == 0:
            current_cat, hand = label, "ALL"
        elif level == 1:
            if label.startswith("FROM_"):
                hand = "LEFT" if "LEFT" in label else "RIGHT"
            else:
                current_cat, hand = label, "ALL"
        else:
            hand = "LEFT" if "LEFT" in label else "RIGHT"
        row = {"player_id": player_id, "period": period,
               "category": current_cat, "hand": hand,
               **_shooting_vals(item["values"])}
        if competition_type:
            row["competition_type"] = competition_type
        upsert(conn, "player_tendency_shooting", row)


def load_tendency_dribble(conn, player_id, period, data, competition_type=None):
    current_pt = "ALL"
    for item in data:
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
        row = {"player_id": player_id, "period": period,
               "play_type": current_pt, "hand": hand,
               **_shooting_vals(item["values"])}
        if competition_type:
            row["competition_type"] = competition_type
        upsert(conn, "player_tendency_dribble", row)


def load_tendency_finishing(conn, player_id, period, data, competition_type=None):
    current_shot = "ALL"
    for item in data:
        label, level = item["label"], item["level"]
        v = item["values"]
        if level == 0:
            current_shot, hand = label, "ALL"
        elif level == 1:
            current_shot, hand = label, "ALL"
        else:
            hand = "LEFT" if "LEFT" in label else "RIGHT"
        row = {"player_id": player_id, "period": period,
               "shot_type": current_shot, "hand": hand,
               "made": v.get("made", 0), "attempted": v.get("attempted", 0),
               "pct": v.get("percentage", 0.0)}
        if competition_type:
            row["competition_type"] = competition_type
        upsert(conn, "player_tendency_finishing", row)


def load_turnovers(conn, player_id, period, data, competition_type=None):
    for item in data:
        v = item.get("values", {})
        row = {"player_id": player_id, "period": period, "play_type": item["label"],
               "bad_pass": v.get("BAD_PASS", 0), "traveling": v.get("TRAVELING", 0),
               "dribble_turnover": v.get("DRIBBLE_TURNOVER", 0),
               "line_violation": v.get("LINE_VIOLATION", 0),
               "clock_violation": v.get("CLOCK_VIOLATION", 0),
               "offensive_foul": v.get("OFFENSIVE_FOUL", 0),
               "other": v.get("OTHER", 0), "total": v.get("TOTAL", 0)}
        if competition_type:
            row["competition_type"] = competition_type
        upsert(conn, "player_turnovers", row)


def load_shot_zones(conn, player_id, period, is_dribble, data, competition_type=None):
    for item in data:
        v = item.get("values", {})
        row = {"player_id": player_id, "period": period,
               "is_dribble": 1 if is_dribble else 0,
               "zone": item["label"],
               "made": v.get("made", 0), "missed": v.get("missed", 0),
               "total": v.get("total", 0), "pct": v.get("percentage", 0.0)}
        if competition_type:
            row["competition_type"] = competition_type
        upsert(conn, "player_shot_zones", row)


PERIOD_RE = r"(LAST_\d+|SEASON|ALL)$"
TEAM_ID_RE = r"_team_([a-f0-9-]{36})_"


def process(conn, path, name_to_id, data):
    stem = Path(path).stem

    if re.search(r"_team_[a-f0-9-]+_info$", stem):
        load_team_info(conn, data)
        return "team_info"

    if re.search(r"_team_[a-f0-9-]+_matches$", stem):
        load_matches(conn, data)
        return "matches"

    tm = re.search(TEAM_ID_RE, stem)
    pm = re.search(PERIOD_RE, stem)
    if tm and pm and "_team_" in stem:
        team_id = tm.group(1)
        period  = pm.group(1)
        if "_overall_" in stem and "_offense_" not in stem and "_defense_" not in stem:
            load_stats(conn, "team_stats", "team_id", team_id, period, data)
        elif "_offense_play_types_" in stem:
            load_play_types(conn, "team_play_types", "team_id", team_id, period, "offense", data)
        elif "_defense_play_types_" in stem:
            load_play_types(conn, "team_play_types", "team_id", team_id, period, "defense", data)
        elif "_play_types_detail_" in stem:
            load_play_types_detail(conn, "team_play_types_detail", "team_id", team_id, period, data)
        else:
            return "skip"
        return f"team/{period}"

    if "_player_" in stem and pm:
        period = pm.group(1)
        after  = stem.split("_player_", 1)[1]
        safe_name_and_type = re.sub(rf"_{period}$", "", after)
        data_types = [
            "shot_zones_no_dribble", "shot_zones_dribble",
            "tendency_shooting", "tendency_dribble", "tendency_finishing",
            "play_types_detail", "offense_play_types", "defense_play_types",
            "turnovers", "overall",
        ]
        data_type = next((dt for dt in data_types if safe_name_and_type.endswith(dt)), None)
        if not data_type:
            return "skip"
        safe_name = re.sub(rf"_{data_type}$", "", safe_name_and_type)
        player_id = name_to_id.get(safe_name)
        if not player_id:
            return f"skip (unknown: {safe_name})"

        ct = "NATIONAL_TEAMS"
        if data_type == "overall":
            load_stats(conn, "player_stats", "player_id", player_id, period, data, ct)
        elif data_type == "offense_play_types":
            load_play_types(conn, "player_play_types", "player_id", player_id, period, "offense", data, ct)
        elif data_type == "defense_play_types":
            load_play_types(conn, "player_play_types", "player_id", player_id, period, "defense", data, ct)
        elif data_type == "play_types_detail":
            load_play_types_detail(conn, "player_play_types_detail", "player_id", player_id, period, data, ct)
        elif data_type == "tendency_shooting":
            load_tendency_shooting(conn, player_id, period, data, ct)
        elif data_type == "tendency_dribble":
            load_tendency_dribble(conn, player_id, period, data, ct)
        elif data_type == "tendency_finishing":
            load_tendency_finishing(conn, player_id, period, data, ct)
        elif data_type == "turnovers":
            load_turnovers(conn, player_id, period, data, ct)
        elif data_type == "shot_zones_no_dribble":
            load_shot_zones(conn, player_id, period, False, data, ct)
        elif data_type == "shot_zones_dribble":
            load_shot_zones(conn, player_id, period, True, data, ct)
        return f"player/{safe_name}/{data_type}/{period}"

    return "skip"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=RAW_DIR)
    parser.add_argument("--db", default=DB_PATH)
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.db), exist_ok=True)
    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)

    # Build name→id from DB (populated by discover_players.py before this runs)
    db_players = conn.execute("SELECT id, full_name FROM players").fetchall()
    name_to_id = {row[1].replace(" ", "_"): row[0] for row in db_players}

    files = sorted(Path(args.data_dir).glob("*.json"))
    total = len(files)
    print(f"Loading {total} files...", flush=True)

    def read_file(f):
        with open(f, encoding="utf-8") as fh:
            return str(f), json.load(fh)

    counts: dict[str, int] = {}
    CHUNK = 200
    for i in range(0, total, CHUNK):
        chunk = files[i:i + CHUNK]
        with ThreadPoolExecutor(max_workers=8) as pool:
            loaded = list(pool.map(read_file, chunk))
        for path, data in loaded:
            key = process(conn, path, name_to_id, data)
            counts[key] = counts.get(key, 0) + 1
        conn.commit()
        print(f"  {min(i + CHUNK, total)}/{total}", flush=True)


    print(f"\nLoaded {len(files)} files → {args.db}\n")
    for k, v in sorted(counts.items()):
        mark = "✓" if not k.startswith("skip") else "·"
        print(f"  {mark} {k}: {v}")

    print("\nRow counts:")
    tables = [
        "teams", "players", "matches",
        "team_stats", "team_play_types", "team_play_types_detail",
        "player_stats", "player_play_types", "player_play_types_detail",
        "player_tendency_shooting", "player_tendency_dribble", "player_tendency_finishing",
        "player_turnovers", "player_shot_zones",
    ]
    for t in tables:
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:<35} {n:>5}")
    conn.close()


if __name__ == "__main__":
    main()
