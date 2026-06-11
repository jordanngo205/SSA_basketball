#!/usr/bin/env python3
"""
Load SSA scraped JSON files into SQLite.
Mirrors the pattern of load_synergy_player_offense_summary.py.

Creates three tables:
  - ssa_team_stats       (overall + additional offense + defensive)
  - ssa_player_stats     (overall + additional offense + defensive per player)
  - ssa_player_play_types (play type breakdown per player)

Usage:
    python load_ssa_db.py                      # Load latest files in data/raw/
    python load_ssa_db.py --raw-dir ./data/raw # Custom raw dir
    python load_ssa_db.py --db ./data/db/ssa.db
"""

import argparse
import glob
import json
import os
import sqlite3
import sys
from datetime import datetime

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "raw")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "db", "ssa.db")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        -- Team-level aggregated stats
        CREATE TABLE IF NOT EXISTS ssa_team_stats (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            scrape_date     TEXT NOT NULL,
            team_id         TEXT NOT NULL,
            season_id       TEXT NOT NULL,
            period          TEXT NOT NULL,
            stat_type       TEXT NOT NULL,   -- 'overall' | 'additional_offense' | 'defensive'
            label           TEXT NOT NULL,
            value_total     REAL,
            value_per_game  REAL,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(scrape_date, team_id, season_id, period, stat_type, label)
        );

        -- Player-level aggregated stats (overall + additional_offense + defensive)
        CREATE TABLE IF NOT EXISTS ssa_player_stats (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            scrape_date     TEXT NOT NULL,
            player_id       TEXT NOT NULL,
            player_name     TEXT,
            team_id         TEXT NOT NULL,
            season_id       TEXT NOT NULL,
            period          TEXT NOT NULL,
            stat_type       TEXT NOT NULL,
            label           TEXT NOT NULL,
            value_total     REAL,
            value_per_game  REAL,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(scrape_date, player_id, team_id, season_id, period, stat_type, label)
        );

        -- Player play type breakdown
        CREATE TABLE IF NOT EXISTS ssa_player_play_types (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            scrape_date     TEXT NOT NULL,
            player_id       TEXT NOT NULL,
            player_name     TEXT,
            team_id         TEXT NOT NULL,
            season_id       TEXT NOT NULL,
            period          TEXT NOT NULL,
            play_type       TEXT NOT NULL,
            label           TEXT NOT NULL,
            value_total     REAL,
            value_per_game  REAL,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(scrape_date, player_id, team_id, season_id, period, play_type, label)
        );

        -- Match results
        CREATE TABLE IF NOT EXISTS ssa_matches (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id        TEXT NOT NULL UNIQUE,
            season_id       TEXT,
            season_name     TEXT,
            competition_name TEXT,
            home_team_id    TEXT,
            home_team_name  TEXT,
            home_score      INTEGER,
            away_team_id    TEXT,
            away_team_name  TEXT,
            away_score      INTEGER,
            match_date      TEXT,
            match_type      TEXT,
            match_status    TEXT,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_ssa_team_stats_team   ON ssa_team_stats(team_id, period);
        CREATE INDEX IF NOT EXISTS idx_ssa_player_stats_player ON ssa_player_stats(player_id, period);
        CREATE INDEX IF NOT EXISTS idx_ssa_matches_season    ON ssa_matches(season_id);
    """)
    conn.commit()
    print("Tables created/verified.")


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _parse_filename(path: str) -> dict:
    """
    Extract date, entity_type, entity_id, stat_type, period from filename.
    Pattern: {date}_team_{id}_{stat_type}_{period}.json
             {date}_player_{name}_{stat_type}_{period}.json
             {date}_team_{id}_matches.json
    """
    name = os.path.basename(path).replace(".json", "")
    parts = name.split("_")
    return {
        "raw_name": name,
        "date": parts[0] if parts else "",
    }


def load_stats_file(
    conn: sqlite3.Connection,
    path: str,
    entity_type: str,   # 'team' or 'player'
    entity_id: str,
    entity_name: str,
    team_id: str,
    season_id: str,
    period: str,
    stat_type: str,
    scrape_date: str,
) -> int:
    """Load a flat stats JSON file (list of {label, values} dicts) into DB."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        print(f"  Skipping {path} — unexpected format (not a list)")
        return 0

    table = "ssa_team_stats" if entity_type == "team" else "ssa_player_stats"
    inserted = 0

    for item in data:
        if not isinstance(item, dict) or "label" not in item:
            continue
        label      = item["label"]
        values     = item.get("values", {})
        val_total  = values.get("total")
        val_game   = values.get("perGame")

        if entity_type == "team":
            conn.execute(f"""
                INSERT OR REPLACE INTO {table}
                    (scrape_date, team_id, season_id, period, stat_type, label, value_total, value_per_game)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (scrape_date, entity_id, season_id, period, stat_type, label, val_total, val_game))
        else:
            conn.execute(f"""
                INSERT OR REPLACE INTO {table}
                    (scrape_date, player_id, player_name, team_id, season_id, period, stat_type, label, value_total, value_per_game)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (scrape_date, entity_id, entity_name, team_id, season_id, period, stat_type, label, val_total, val_game))

        inserted += 1

    conn.commit()
    return inserted


def load_play_types_file(
    conn: sqlite3.Connection,
    path: str,
    player_id: str,
    player_name: str,
    team_id: str,
    season_id: str,
    period: str,
    scrape_date: str,
) -> int:
    """Load a play-types JSON file into ssa_player_play_types."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        return 0

    inserted = 0
    # Expected structure: [{play_type: "SET_PLAY", stats: [{label, values}]}, ...]
    # OR flat list if SSA returns differently — handle both
    for item in data:
        if not isinstance(item, dict):
            continue

        play_type = (
            item.get("playType")
            or item.get("play_type")
            or item.get("label")
            or "UNKNOWN"
        )
        stats = item.get("stats") or item.get("values") or []

        if isinstance(stats, list):
            for stat in stats:
                if not isinstance(stat, dict) or "label" not in stat:
                    continue
                values = stat.get("values", {})
                conn.execute("""
                    INSERT OR REPLACE INTO ssa_player_play_types
                        (scrape_date, player_id, player_name, team_id, season_id, period, play_type, label, value_total, value_per_game)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    scrape_date, player_id, player_name, team_id, season_id, period,
                    play_type, stat["label"],
                    values.get("total"), values.get("perGame"),
                ))
                inserted += 1
        elif isinstance(item.get("values"), dict):
            # Flat item is itself a stat row, play_type = item.label
            values = item.get("values", {})
            conn.execute("""
                INSERT OR REPLACE INTO ssa_player_play_types
                    (scrape_date, player_id, player_name, team_id, season_id, period, play_type, label, value_total, value_per_game)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                scrape_date, player_id, player_name, team_id, season_id, period,
                play_type, play_type,
                values.get("total"), values.get("perGame"),
            ))
            inserted += 1

    conn.commit()
    return inserted


def load_matches_file(conn: sqlite3.Connection, path: str) -> int:
    """Load a matches JSON file into ssa_matches."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        return 0

    inserted = 0
    for m in data:
        if not isinstance(m, dict):
            continue
        try:
            conn.execute("""
                INSERT OR IGNORE INTO ssa_matches
                    (match_id, season_id, season_name, competition_name,
                     home_team_id, home_team_name, home_score,
                     away_team_id, away_team_name, away_score,
                     match_date, match_type, match_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                m.get("id"), m.get("seasonId"), m.get("seasonName"),
                m.get("competitionName"),
                m.get("homeTeamId"), m.get("homeTeamName"), m.get("homeTeamScore"),
                m.get("awayTeamId"), m.get("awayTeamName"), m.get("awayTeamScore"),
                m.get("matchStartTime"), m.get("matchType"), m.get("matchStatus"),
            ))
            inserted += 1
        except Exception as e:
            print(f"  Error inserting match {m.get('id')}: {e}")

    conn.commit()
    return inserted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Load SSA JSON files into SQLite")
    parser.add_argument("--raw-dir", default=RAW_DIR, help="Directory with JSON files")
    parser.add_argument("--db", default=DB_PATH, help="SQLite database path")
    parser.add_argument(
        "--team-id", default="4f9b83f2-8209-4e04-a9bb-6fcd0a03f739",
        help="Team UUID (used when loading player files)"
    )
    parser.add_argument(
        "--season-id", default="cba189ee-e4b9-47c1-a650-437e3828160d",
        help="Season UUID"
    )
    args = parser.parse_args()

    if not os.path.isdir(args.raw_dir):
        print(f"Error: raw dir not found: {args.raw_dir}")
        sys.exit(1)

    os.makedirs(os.path.dirname(args.db), exist_ok=True)
    conn = sqlite3.connect(args.db)
    ensure_tables(conn)

    files = sorted(glob.glob(os.path.join(args.raw_dir, "*.json")))
    print(f"\nFound {len(files)} JSON files in {args.raw_dir}")
    total_rows = 0

    for path in files:
        name = os.path.basename(path)
        parts = name.replace(".json", "").split("_")
        scrape_date = parts[0] if parts else datetime.now().strftime("%Y-%m-%d")

        print(f"\n  {name}")

        # ── Matches ──────────────────────────────────────────────────────────
        if "matches" in name and "player" not in name:
            n = load_matches_file(conn, path)
            print(f"    → {n} matches")
            total_rows += n
            continue

        # ── Team stats ───────────────────────────────────────────────────────
        if "_team_" in name and "info" not in name and "matches" not in name:
            # Infer stat_type and period from filename
            stat_type = "overall"
            period    = "LAST_3"
            for st in ["additional_offense", "defensive", "play_types", "overall"]:
                if st in name:
                    stat_type = st
                    break
            for p in ["CURRENT_SEASON", "LAST_10", "LAST_5", "LAST_3", "ALL"]:
                if p in name:
                    period = p
                    break

            # Extract team_id from filename (between _team_ and next _)
            try:
                tid = name.split("_team_")[1].split("_")[0]
            except Exception:
                tid = args.team_id

            n = load_stats_file(
                conn, path, "team", tid, "Canada WNT",
                tid, args.season_id, period, stat_type, scrape_date,
            )
            print(f"    → {n} stat rows (team {stat_type})")
            total_rows += n
            continue

        # ── Player stats ─────────────────────────────────────────────────────
        if "_player_" in name:
            stat_type = "overall"
            period    = "LAST_3"
            for st in ["additional_offense", "defensive", "shot_chart", "play_types", "overall"]:
                if st in name:
                    stat_type = st
                    break
            for p in ["CURRENT_SEASON", "LAST_10", "LAST_5", "LAST_3", "ALL"]:
                if p in name:
                    period = p
                    break

            # Extract player name from filename
            try:
                after_player = name.split("_player_")[1]
                player_name_raw = "_".join(after_player.split("_")[:-2])  # strip stat_type + period
                player_name = player_name_raw.replace("_", " ").title()
                player_id   = player_name_raw  # use name as proxy ID (real ID in JSON)
            except Exception:
                player_name = "Unknown"
                player_id   = "unknown"

            if stat_type == "play_types":
                n = load_play_types_file(
                    conn, path, player_id, player_name,
                    args.team_id, args.season_id, period, scrape_date,
                )
            else:
                n = load_stats_file(
                    conn, path, "player", player_id, player_name,
                    args.team_id, args.season_id, period, stat_type, scrape_date,
                )
            print(f"    → {n} rows ({player_name} / {stat_type})")
            total_rows += n
            continue

        print(f"    → skipped (unrecognized pattern)")

    # Summary
    print(f"\n{'='*50}")
    print(f"✅ Load complete. {total_rows} total rows inserted.")
    print(f"   Database: {args.db}")

    for table in ["ssa_team_stats", "ssa_player_stats", "ssa_player_play_types", "ssa_matches"]:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"   {table}: {count} rows")

    conn.close()


if __name__ == "__main__":
    main()
