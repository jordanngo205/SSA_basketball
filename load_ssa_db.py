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
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR  = os.path.join(BASE_DIR, "data", "raw")
DB_PATH  = os.path.join(BASE_DIR, "data", "db", "ssa.db")

CANADA_WNT_ID = "4f9b83f2-8209-4e04-a9bb-6fcd0a03f739"

PLAYER_NAME_TO_ID = {
    "Paige_Crozon":       "d29fd8da-3ead-4c41-aa12-b496fb0debe9",
    "Katherine_Plouffe":  "f532294f-8e69-4cbb-be69-7fa1cd6189b5",
    "Kacie_Bosch":        "d9c544b9-cb4d-4280-9bef-6b1102fc7b2a",
    "Saicha_Grant-Allen": "9f9a4068-97fb-4bd2-a865-0c354c533f4d",
    "Tara_Wallack":       "2b6dc75e-dd80-4324-9737-8bc4a0859ce8",
}

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


def load_team_info(conn, path):
    d = json.load(open(path))
    upsert(conn, "teams", {
        "id": d["id"], "name": d.get("name"),
        "competition_type": d.get("competitionType"),
        "sex": d.get("sex"), "game_type": d.get("gameType"),
        "city": d.get("city"), "country_id": d.get("countryId"),
    })


def load_matches(conn, path):
    for m in json.load(open(path)):
        upsert(conn, "matches", {
            "id": m.get("id"), "season_id": m.get("seasonId"),
            "season_name": m.get("seasonName"),
            "home_team_id": m.get("homeTeamId"), "home_team_name": m.get("homeTeamName"),
            "away_team_id": m.get("awayTeamId"), "away_team_name": m.get("awayTeamName"),
            "home_score": m.get("homeTeamScore"), "away_score": m.get("awayTeamScore"),
            "match_date": (m.get("matchStartTime") or "")[:10],
        })


def load_stats(conn, table, id_col, entity_id, period, path):
    for item in json.load(open(path)):
        v = item.get("values", {})
        upsert(conn, table, {
            id_col: entity_id, "period": period,
            "stat_label": item["label"],
            "total": v.get("total"), "per_game": v.get("perGame"),
        })


def load_play_types(conn, table, id_col, entity_id, period, side, path):
    for item in json.load(open(path)):
        v = item.get("values", {})
        upsert(conn, table, {
            id_col: entity_id, "period": period, "side": side,
            "label": item["label"],
            "possession": v.get("possession"), "points": v.get("points"),
            "ppp": v.get("pointsPerPossession"), "pct": v.get("possessionPercentage"),
        })


def load_play_types_detail(conn, table, id_col, entity_id, period, path):
    for item in json.load(open(path)):
        v = item.get("values", {})
        upsert(conn, table, {
            id_col: entity_id, "period": period, "play_type": item["label"],
            "poss": v.get("numberOfPossessions"), "ppp": v.get("pointsPerPossession"),
            "usage": v.get("usage"),
            "ft_m": v.get("ftM"), "ft_a": v.get("ftA"),
            "two_pt_m": v.get("twoPtM"), "two_pt_a": v.get("twoPtA"),
            "two_pt_pct": v.get("twoPtPercentage"),
            "three_pt_m": v.get("threePtM"), "three_pt_a": v.get("threePtA"),
            "three_pt_pct": v.get("threePtPercentage"),
            "turnovers": v.get("turnovers"), "assists": v.get("assistance"),
        })


def load_tendency_shooting(conn, player_id, period, path):
    """
    [0] TOTAL_SHOTS → category=TOTAL_SHOTS, hand=ALL
      [1] DRIBBLE_JUMPER → category=DRIBBLE_JUMPER, hand=ALL
        [2] FROM_LEFT/RIGHT_HAND → hand=LEFT/RIGHT
      [1] NO_DRIBBLE_JUMPER → category=NO_DRIBBLE_JUMPER, hand=ALL
    """
    data = json.load(open(path))
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
        upsert(conn, "player_tendency_shooting", {
            "player_id": player_id, "period": period,
            "category": current_cat, "hand": hand,
            **_shooting_vals(item["values"]),
        })


def load_tendency_dribble(conn, player_id, period, path):
    """
    [0] ALL → play_type=ALL, hand=ALL
      [1] FROM_LEFT/RIGHT → play_type=ALL, hand=LEFT/RIGHT
      [1] PICK_AND_ROLL → play_type=PICK_AND_ROLL, hand=ALL
        [2] FROM_LEFT/RIGHT → play_type=PICK_AND_ROLL, hand=LEFT/RIGHT
      ...
    """
    data = json.load(open(path))
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
        upsert(conn, "player_tendency_dribble", {
            "player_id": player_id, "period": period,
            "play_type": current_pt, "hand": hand,
            **_shooting_vals(item["values"]),
        })


def load_tendency_finishing(conn, player_id, period, path):
    """
    [0] ALL
      [1] LAYUP / FLOATER_OR_RUNNER / HOOK_SHOT / DUNK / TIP_SHOT / JUMPER
        [2] FROM_LEFT/RIGHT_HAND
    """
    data = json.load(open(path))
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
        upsert(conn, "player_tendency_finishing", {
            "player_id": player_id, "period": period,
            "shot_type": current_shot, "hand": hand,
            "made": v.get("made", 0), "attempted": v.get("attempted", 0),
            "pct": v.get("percentage", 0.0),
        })


def load_turnovers(conn, player_id, period, path):
    for item in json.load(open(path)):
        v = item.get("values", {})
        upsert(conn, "player_turnovers", {
            "player_id": player_id, "period": period, "play_type": item["label"],
            "bad_pass": v.get("BAD_PASS", 0), "traveling": v.get("TRAVELING", 0),
            "dribble_turnover": v.get("DRIBBLE_TURNOVER", 0),
            "line_violation": v.get("LINE_VIOLATION", 0),
            "clock_violation": v.get("CLOCK_VIOLATION", 0),
            "offensive_foul": v.get("OFFENSIVE_FOUL", 0),
            "other": v.get("OTHER", 0), "total": v.get("TOTAL", 0),
        })


def load_shot_zones(conn, player_id, period, is_dribble, path):
    for item in json.load(open(path)):
        v = item.get("values", {})
        upsert(conn, "player_shot_zones", {
            "player_id": player_id, "period": period,
            "is_dribble": 1 if is_dribble else 0,
            "zone": item["label"],
            "made": v.get("made", 0), "missed": v.get("missed", 0),
            "total": v.get("total", 0), "pct": v.get("percentage", 0.0),
        })


def seed_static(conn):
    upsert(conn, "teams", {
        "id": CANADA_WNT_ID, "name": "Canada WNT",
        "competition_type": "NATIONAL_TEAMS", "sex": "FEMALE",
        "game_type": "THREE_X_THREE", "city": "Ottawa", "country_id": "CA",
    })
    for safe_name, pid in PLAYER_NAME_TO_ID.items():
        pos_map = {"Paige_Crozon": "GUARD", "Katherine_Plouffe": "FORWARD",
                   "Kacie_Bosch": "GUARD", "Saicha_Grant-Allen": "FORWARD",
                   "Tara_Wallack": "GUARD"}
        jersey_map = {"Paige_Crozon": "7", "Katherine_Plouffe": "2"}
        height_map = {"Paige_Crozon": 185, "Katherine_Plouffe": 192}
        upsert(conn, "players", {
            "id": pid, "full_name": safe_name.replace("_", " "),
            "team_id": CANADA_WNT_ID,
            "position": pos_map.get(safe_name),
            "height": height_map.get(safe_name),
            "jersey_number": jersey_map.get(safe_name, ""),
            "nationality": "CA",
        })


PERIOD_RE = r"(LAST_\d+|SEASON|ALL)$"
TEAM_ID_RE = r"_team_([a-f0-9-]{36})_"


def process(conn, path):
    stem = Path(path).stem

    # team info
    if re.search(r"_team_[a-f0-9-]+_info$", stem):
        load_team_info(conn, path)
        return "team_info"

    # matches
    if re.search(r"_team_[a-f0-9-]+_matches$", stem):
        load_matches(conn, path)
        return "matches"

    # team data with period
    tm = re.search(TEAM_ID_RE, stem)
    pm = re.search(PERIOD_RE, stem)
    if tm and pm and "_team_" in stem:
        team_id = tm.group(1)
        period  = pm.group(1)
        if "_overall_" in stem and "_offense_" not in stem and "_defense_" not in stem:
            load_stats(conn, "team_stats", "team_id", team_id, period, path)
        elif "_offense_play_types_" in stem:
            load_play_types(conn, "team_play_types", "team_id", team_id, period, "offense", path)
        elif "_defense_play_types_" in stem:
            load_play_types(conn, "team_play_types", "team_id", team_id, period, "defense", path)
        elif "_play_types_detail_" in stem:
            load_play_types_detail(conn, "team_play_types_detail", "team_id", team_id, period, path)
        else:
            return "skip"
        return f"team/{period}"

    # player data with period
    if "_player_" in stem and pm:
        period = pm.group(1)
        after  = stem.split("_player_", 1)[1]
        # strip period suffix
        safe_name_and_type = re.sub(rf"_{period}$", "", after)
        # identify data type suffix
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
        player_id = PLAYER_NAME_TO_ID.get(safe_name)
        if not player_id:
            return f"skip (unknown: {safe_name})"

        if data_type == "overall":
            load_stats(conn, "player_stats", "player_id", player_id, period, path)
        elif data_type == "offense_play_types":
            load_play_types(conn, "player_play_types", "player_id", player_id, period, "offense", path)
        elif data_type == "defense_play_types":
            load_play_types(conn, "player_play_types", "player_id", player_id, period, "defense", path)
        elif data_type == "play_types_detail":
            load_play_types_detail(conn, "player_play_types_detail", "player_id", player_id, period, path)
        elif data_type == "tendency_shooting":
            load_tendency_shooting(conn, player_id, period, path)
        elif data_type == "tendency_dribble":
            load_tendency_dribble(conn, player_id, period, path)
        elif data_type == "tendency_finishing":
            load_tendency_finishing(conn, player_id, period, path)
        elif data_type == "turnovers":
            load_turnovers(conn, player_id, period, path)
        elif data_type == "shot_zones_no_dribble":
            load_shot_zones(conn, player_id, period, False, path)
        elif data_type == "shot_zones_dribble":
            load_shot_zones(conn, player_id, period, True, path)
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
    seed_static(conn)

    files = sorted(Path(args.data_dir).glob("*.json"))
    counts: dict[str, int] = {}
    for f in files:
        key = process(conn, str(f))
        counts[key] = counts.get(key, 0) + 1

    conn.commit()

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
