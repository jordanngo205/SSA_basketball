#!/usr/bin/env python3
"""
Discover player IDs by matching provided roster names against the full SSA player database,
then scrape full stats for every matched player.

Phase 1: Page all ~1501 players, build name→ID lookup, match against ROSTERS
Phase 2: Scrape full stats for every matched player
Phase 3: Load into SQLite

Usage:
    python discover_players.py                  # Full run
    python discover_players.py --discover-only  # Just match names, save roster
    python discover_players.py --scrape-only    # Use existing roster, scrape stats
    python discover_players.py --team "Japan WNT"
"""

import argparse
import json
import os
import sys
import time
import sqlite3
import unicodedata
import requests
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ssa_functions as sf

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
RAW_DIR     = os.path.join(BASE_DIR, "data", "raw")
DB_PATH     = os.path.join(BASE_DIR, "data", "db", "ssa.db")
ROSTER_FILE = os.path.join(BASE_DIR, "data", "rosters.json")

SEASON_ID = "cba189ee-e4b9-47c1-a650-437e3828160d"
COMP_TYPE = "NATIONAL_TEAMS"

# Provided rosters — names as given, matched against SSA player database
ROSTERS: dict[str, list[str]] = {
    "United States WNT": [
        "Joyce Allyson Edwards", "Milaysia Mikeco Fulwiley", "Shakira Jade Austin",
        "Nazahrah Ansaria Hillmon-Baker", "Allisha Gray", "Veronica Burton",
        "Mikaylah Williams", "Madison Scott", "Sahara Williams", "Taylor Bigby",
    ],
    "Ukraine WNT": [
        "Anzhelika Liashko", "Kateryna Koval", "Miriam Uro-Nilie", "Krystyna Filevych",
    ],
    "Tonga WNT": [
        "Makeili Talia Ika", "Kara-Lynne Enari", "Lesila Kefu Finau",
        "Ana Rachel Salote Fui Enari",
    ],
    "Thailand WNT": [
        "Supavadee Kunchuan", "Sroifa Phetnin", "Kanokwan Prajuapsook", "Sasiporn Wongtapha",
    ],
    "Spain WNT": [
        "Gracia Alonso De Armiño", "Vega Gimeno", "Sandra Ygueravide", "Juana Camilion",
        "Ainhoa Gervasini", "Cecilia Muhate", "Alba Prieto", "Txell Alarcón Otero",
    ],
    "Singapore WNT": [
        "Lydia Ang Zi Yi", "Jermaine Lim Jia Ying", "XingYue Han", "Lai Hor Ying Matilda",
    ],
    "Poland WNT": [
        "Klaudia Gertchen", "Anna Pawłowska", "Weronika Telenga", "Aleksandra Zięmborska",
    ],
    "Philippines WNT": [
        "Mikka Cacho", "Kacey Dela Rosa", "Afril Bernardino", "Cheska Apag",
        "Reynalyn Ferrer", "Camille Clarin",
    ],
    "New Zealand WNT": [
        "Azure Luseane Anderson", "Gabriella Fotu", "Eva Sydney Langton", "Sharne Pupuke-Robati",
    ],
    "Netherlands WNT": [
        "Janis Boonstra", "Noortje Driessen", "Ilse Kuijt", "Evelien Lutje Schipholt",
        "Zoë Slagter", "Lotte van Kruistum",
    ],
    "Mongolia WNT": [
        "Ariuntsetseg Bat-Erdene", "Narangoo Erdenebayan", "Nandinkhusel Nyamjav",
        "Khulan Onolbaatar", "Bolor-Erdene Battsooj",
    ],
    "Malaysia WNT": [
        "Hui Pin Pang", "Suet Ying Foo", "SinJie Tan", "Fook Yee Yap",
    ],
    "Madagascar WNT": [
        "Sydonie Andriamihajanirina", "Minaoharisoa Christiane Jaofera",
        "Ravaka Randriatahiana", "Tokin'Iaina Sambatrarimiora", "Harisoa Muriel Hajanirina",
    ],
    "Lithuania WNT": [
        "Gabriele Sulske", "Justina Miknaite", "Kamile Nacickaite-van der Horst",
        "Giedre Labuckiene", "Martyna Petrenaite",
    ],
    "Latvia WNT": [
        "Paula Mauriņa", "Marta Miščenko", "Digna Strautmane", "Ketija Vihmane", "Paula Cirša",
    ],
    "Kazakhstan WNT": [
        "Tamila Zhakipova", "Ulyana Kudryavtseva", "Shugyla Kemel", "Dilnaz Yerkebay",
    ],
    "Japan WNT": [
        "Miku Takahashi", "Aya Tsurumi", "Sakura Noguchi", "Momoka Hanashima",
        "Aoi Katsura", "Kiho Miyashita",
    ],
    "Italy WNT": [
        "Beatrice Noemi Caloro", "Caterina Gilli", "Giorgia Palmieri", "Maria Miccoli",
    ],
    "Hungary WNT": [
        "Tamara Szerencsés", "Mia David", "Franka Toth", "Vivi Böröndy",
        "Klaudia Papp", "Virág Kiss", "Réka Lelik",
    ],
    "Germany WNT": [
        "Ama Degbeon", "Laura Zolper", "Marie Reichert", "Britta Christin Daub",
    ],
    "France WNT": [
        "Hortense Limouzin", "Marie Michelle Milapie", "Laetitia Guapo", "Marie Mané",
        "Myriam Djekoundade", "Marie-Eve Paget",
    ],
    "Egypt WNT": [
        "Raneem Mohamed", "Hala ElShaarawy", "Nadine Selaawy", "Soraya Mohamed",
    ],
    "Czech Republic WNT": [
        "Lucie Svatoňová", "Monika Fučíkova", "Kateřina Galíčková",
        "Anna Rylichová", "Karolina Sotolova",
    ],
    "Chinese Taipei WNT": [
        "Chun-Hsi Chiu", "Chen-I Li", "Yu-Tsz Lee", "Yu Min Chang",
    ],
    "Serbia WNT": [
        "Nevena Vuckovic",
    ],
    "China WNT": [
        "ZhiTing Zhang", "A Ganajing", "Wanglai Zhang", "JianPing Zhang",
        "Wenxia Li", "Yuyan Li", "Lili Wang", "FengYi Sun",
    ],
    "Canada WNT": [
        "Paige Crozon", "Katherine Plouffe", "Kacie Bosch",
        "Saicha Grant-Allen", "Tara Wallack",
    ],
    "Brazil WNT": [
        "Luana de Souza", "Kawanni Silva", "Gabriela Guimarães", "Gabriella D'Arrigo",
    ],
    "Azerbaijan WNT": [
        "Arica Carter", "Tatyana Deniskina", "Brianna Fraser",
        "Alexandra Mollenhauer", "Dina Ulyanova",
    ],
    "Australia WNT": [
        "Sina Elke Höllerl", "Rebekka Kalaydjiev", "Anja Fuchs-Robetin",
        "Sigrid Koizar", "Alexia Allesch",
    ],
}


def _normalize(name: str) -> str:
    """Lowercase, collapse whitespace, strip accents, normalize apostrophes."""
    # Normalize unicode apostrophe variants to standard apostrophe
    name = name.replace("’", "'").replace("ʼ", "'")
    nfkd = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(stripped.lower().split())


def get_team_id_map() -> dict[str, str]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, name FROM teams").fetchall()
    conn.close()
    return {r["name"]: r["id"] for r in rows}


def save_roster(roster: dict) -> None:
    os.makedirs(os.path.dirname(ROSTER_FILE), exist_ok=True)
    with open(ROSTER_FILE, "w") as f:
        json.dump(roster, f, indent=2)
    print(f"  Roster saved → {ROSTER_FILE}")


def load_roster() -> dict:
    if not os.path.exists(ROSTER_FILE):
        return {}
    with open(ROSTER_FILE) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Phase 1: match provided names against SSA player database
# ---------------------------------------------------------------------------

def discover_all_players(session, token) -> dict:
    team_id_map = get_team_id_map()

    print("  Paging all players from SSA...")
    api_players: dict[str, dict] = {}   # normalized_full_name → player record
    page, total_pages = 0, 1
    total_scanned = 0

    while page < total_pages:
        resp = session.get(
            f"{sf.BASE_URL}/players",
            params={"size": 100, "page": page},
            headers=sf._headers(token),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        total_pages = data.get("totalPages", 1)

        for p in data.get("content", []):
            first = (p.get("firstName") or "").strip()
            last  = (p.get("lastName") or "").strip()
            full  = f"{first} {last}".strip()
            key   = _normalize(full)
            api_players[key] = {**p, "_full_name": full}

        total_scanned += len(data.get("content", []))
        print(f"  Page {page+1}/{total_pages}  scanned={total_scanned}", end="\r")
        page += 1
        time.sleep(0.1)

    print(f"\n  API has {len(api_players)} unique player names")

    roster: dict[str, list] = {}
    unmatched: list[tuple[str, str]] = []

    for team_name, names in ROSTERS.items():
        team_id = team_id_map.get(team_name)
        if not team_id:
            print(f"  WARNING: '{team_name}' not in DB — skipping")
            continue

        roster[team_id] = []
        for name in names:
            key = _normalize(name)
            p   = api_players.get(key)

            if not p:
                # Try matching on just last word (last name)
                last_word = key.split()[-1]
                candidates = [(k, v) for k, v in api_players.items() if last_word in k.split()]
                if len(candidates) == 1:
                    p = candidates[0][1]
                    print(f"  ~ fuzzy '{name}' → '{p['_full_name']}'")

            if p:
                roster[team_id].append({
                    "id":       p["id"],
                    "name":     p["_full_name"],
                    "position": p.get("position"),
                    "height":   p.get("height"),
                    "jersey":   p.get("favouriteJerseyNumber") or "",
                })
            else:
                unmatched.append((team_name, name))

    if unmatched:
        print(f"\n  ⚠  {len(unmatched)} names not matched:")
        for team, name in unmatched:
            print(f"    [{team}] {name}")
    else:
        print("  All names matched ✓")

    matched = sum(len(v) for v in roster.values())
    print(f"  Matched: {matched} players across {len(roster)} teams")
    return roster


# ---------------------------------------------------------------------------
# DB insert helpers
# ---------------------------------------------------------------------------

def _upsert(conn, table, row):
    cols = ", ".join(row.keys())
    phs  = ", ".join(["?"] * len(row))
    conn.execute(f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({phs})", list(row.values()))


def _insert_overall(conn, player_id, period, data):
    for item in data:
        v = item.get("values", {})
        _upsert(conn, "player_stats", {
            "player_id": player_id, "period": period, "competition_type": COMP_TYPE,
            "stat_label": item["label"],
            "total": v.get("total"), "per_game": v.get("perGame"),
        })


def _insert_play_types(conn, player_id, period, side, data):
    for item in data:
        v = item.get("values", {})
        _upsert(conn, "player_play_types", {
            "player_id": player_id, "period": period, "competition_type": COMP_TYPE, "side": side,
            "label": item["label"],
            "possession": v.get("possession"), "points": v.get("points"),
            "ppp": v.get("pointsPerPossession"), "pct": v.get("possessionPercentage"),
        })


def _insert_play_types_detail(conn, player_id, period, data):
    for item in data:
        v = item.get("values", {})
        _upsert(conn, "player_play_types_detail", {
            "player_id": player_id, "period": period, "competition_type": COMP_TYPE, "play_type": item["label"],
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


def _insert_tendency_shooting(conn, player_id, period, data):
    current_cat = "TOTAL_SHOTS"
    for item in data:
        label, level = item["label"], item["level"]
        if level == 0:
            current_cat, hand = label, "ALL"
        elif level == 1:
            hand = ("LEFT" if "LEFT" in label else "RIGHT") if label.startswith("FROM_") else "ALL"
            if not label.startswith("FROM_"):
                current_cat = label
        else:
            hand = "LEFT" if "LEFT" in label else "RIGHT"
        _upsert(conn, "player_tendency_shooting", {
            "player_id": player_id, "period": period, "competition_type": COMP_TYPE,
            "category": current_cat, "hand": hand,
            **_shooting_vals(item["values"]),
        })


def _insert_tendency_dribble(conn, player_id, period, data):
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
        _upsert(conn, "player_tendency_dribble", {
            "player_id": player_id, "period": period, "competition_type": COMP_TYPE,
            "play_type": current_pt, "hand": hand,
            **_shooting_vals(item["values"]),
        })


def _insert_tendency_finishing(conn, player_id, period, data):
    current_shot = "ALL"
    for item in data:
        label, level = item["label"], item["level"]
        v = item["values"]
        if level in (0, 1):
            current_shot, hand = label, "ALL"
        else:
            hand = "LEFT" if "LEFT" in label else "RIGHT"
        _upsert(conn, "player_tendency_finishing", {
            "player_id": player_id, "period": period, "competition_type": COMP_TYPE,
            "shot_type": current_shot, "hand": hand,
            "made": v.get("made", 0), "attempted": v.get("attempted", 0),
            "pct": v.get("percentage", 0.0),
        })


def _insert_turnovers(conn, player_id, period, data):
    for item in data:
        v = item.get("values", {})
        _upsert(conn, "player_turnovers", {
            "player_id": player_id, "period": period, "competition_type": COMP_TYPE, "play_type": item["label"],
            "bad_pass": v.get("BAD_PASS", 0), "traveling": v.get("TRAVELING", 0),
            "dribble_turnover": v.get("DRIBBLE_TURNOVER", 0),
            "line_violation": v.get("LINE_VIOLATION", 0),
            "clock_violation": v.get("CLOCK_VIOLATION", 0),
            "offensive_foul": v.get("OFFENSIVE_FOUL", 0),
            "other": v.get("OTHER", 0), "total": v.get("TOTAL", 0),
        })


def _insert_shot_zones(conn, player_id, period, is_dribble, data):
    for item in data:
        v = item.get("values", {})
        _upsert(conn, "player_shot_zones", {
            "player_id": player_id, "period": period, "competition_type": COMP_TYPE,
            "is_dribble": 1 if is_dribble else 0,
            "zone": item["label"],
            "made": v.get("made", 0), "missed": v.get("missed", 0),
            "total": v.get("total", 0), "pct": v.get("percentage", 0.0),
        })


# ---------------------------------------------------------------------------
# Phase 2: scrape stats directly into SQLite
# ---------------------------------------------------------------------------

def scrape_player(session, token, conn, player_id, player_name, period) -> None:
    results = []

    endpoints = [
        (sf.get_player_overall,                   lambda d: _insert_overall(conn, player_id, period, d)),
        (sf.get_player_offense_play_types,         lambda d: _insert_play_types(conn, player_id, period, "offense", d)),
        (sf.get_player_defense_play_types,         lambda d: _insert_play_types(conn, player_id, period, "defense", d)),
        (sf.get_player_play_types,                 lambda d: _insert_play_types_detail(conn, player_id, period, d)),
        (sf.get_player_shooting_tendency,          lambda d: _insert_tendency_shooting(conn, player_id, period, d)),
        (sf.get_player_shooting_tendency_dribble,  lambda d: _insert_tendency_dribble(conn, player_id, period, d)),
        (sf.get_player_shooting_tendency_finishing, lambda d: _insert_tendency_finishing(conn, player_id, period, d)),
        (sf.get_player_turnovers,                  lambda d: _insert_turnovers(conn, player_id, period, d)),
    ]

    for fn, insert_fn in endpoints:
        try:
            data = fn(session, token, player_id, SEASON_ID, period, COMP_TYPE)
            insert_fn(data)
            results.append("✓")
        except Exception:
            results.append("✗")
        time.sleep(0.15)

    for is_dribble in (False, True):
        try:
            data = sf.get_player_shot_zones(session, token, player_id, SEASON_ID, is_dribble, period, COMP_TYPE)
            _insert_shot_zones(conn, player_id, period, is_dribble, data)
            results.append("✓")
        except Exception:
            results.append("✗")
        time.sleep(0.15)

    conn.commit()
    print(f"    {''.join(results)}", flush=True)


# ---------------------------------------------------------------------------
# Seed players into DB
# ---------------------------------------------------------------------------

def seed_players_to_db(conn, roster: dict) -> None:
    for team_id, players in roster.items():
        for p in players:
            conn.execute(
                "INSERT OR REPLACE INTO players (id, full_name, team_id, position, height, jersey_number) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (p["id"], p["name"], team_id, p.get("position"), p.get("height"), p.get("jersey", "")),
            )
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    print(f"  Players in DB: {n}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--scrape-only",   action="store_true")
    parser.add_argument("--team",          default=None, help="Limit to one team name")
    parser.add_argument("--period",        default="SEASON",
                        choices=["LAST_1","LAST_3","LAST_5","LAST_10","SEASON","ALL"])
    args = parser.parse_args()

    load_dotenv(os.path.join(BASE_DIR, ".env"))
    session = requests.Session()
    print("Authenticating...")
    token, _ = sf.get_access_token(session, os.getenv("SSA_USERNAME"), os.getenv("SSA_PASSWORD"))

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    if not args.scrape_only:
        print("\n=== Phase 1: Matching players ===")
        roster = discover_all_players(session, token)
        save_roster(roster)
    else:
        roster = load_roster()
        if not roster:
            print("No roster file found. Run without --scrape-only first.")
            sys.exit(1)
        print(f"Loaded existing roster: {sum(len(v) for v in roster.values())} players")

    if args.discover_only:
        print("\nDone (discover only).")
        conn.close()
        return

    if args.team:
        row = conn.execute("SELECT id FROM teams WHERE name LIKE ?",
                           (f"%{args.team.split()[0]}%",)).fetchone()
        if not row:
            print(f"Team not found: {args.team}")
            conn.close()
            sys.exit(1)
        roster = {row[0]: roster.get(row[0], [])}

    seed_players_to_db(conn, roster)

    team_id_map   = get_team_id_map()
    name_map      = {v: k for k, v in team_id_map.items()}
    total_players = sum(len(v) for v in roster.values())

    print(f"\n=== Phase 2: Scraping → SQLite ({total_players} players, period={args.period}) ===")

    done = 0
    for team_id, players in roster.items():
        team_name = name_map.get(team_id, team_id)
        print(f"\n  {team_name} ({len(players)} players)")
        for p in players:
            done += 1
            print(f"  [{done}/{total_players}] {p['name']}", end="  ", flush=True)
            scrape_player(session, token, conn, p["id"], p["name"], args.period)

    conn.close()
    print(f"\n✅ Complete — {done} players scraped directly into DB")

    print(f"\n✅ Complete — {done} players scraped")


if __name__ == "__main__":
    main()
