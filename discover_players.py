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
    "China WNT": [
        "ZhiTing Zhang", "A Ganajing", "Wanglai Zhang", "JianPing Zhang",
        "Wenxia Li", "Yuyan Li", "Lili Wang",
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
# Phase 2: scrape stats
# ---------------------------------------------------------------------------

def scrape_player(session, token, player_id, player_name, period, date_str) -> None:
    safe = player_name.replace(" ", "_").replace("/", "_")
    endpoints = [
        ("overall",            sf.get_player_overall),
        ("offense_play_types", sf.get_player_offense_play_types),
        ("defense_play_types", sf.get_player_defense_play_types),
        ("play_types_detail",  sf.get_player_play_types),
        ("tendency_shooting",  sf.get_player_shooting_tendency),
        ("tendency_dribble",   sf.get_player_shooting_tendency_dribble),
        ("tendency_finishing", sf.get_player_shooting_tendency_finishing),
        ("turnovers",          sf.get_player_turnovers),
    ]

    results = []
    for key, fn in endpoints:
        try:
            data = fn(session, token, player_id, SEASON_ID, period, COMP_TYPE)
            path = os.path.join(RAW_DIR, f"{date_str}_player_{safe}_{key}_{period}.json")
            sf.write_data(path, data)
            results.append("✓")
        except Exception:
            results.append("✗")
        time.sleep(0.15)

    for is_dribble, label in [(False, "shot_zones_no_dribble"), (True, "shot_zones_dribble")]:
        try:
            data = sf.get_player_shot_zones(session, token, player_id, SEASON_ID, is_dribble, period, COMP_TYPE)
            path = os.path.join(RAW_DIR, f"{date_str}_player_{safe}_{label}_{period}.json")
            sf.write_data(path, data)
            results.append("✓")
        except Exception:
            results.append("✗")
        time.sleep(0.15)

    print(f"    {''.join(results)}")


# ---------------------------------------------------------------------------
# Seed players into DB
# ---------------------------------------------------------------------------

def seed_players_to_db(roster: dict) -> None:
    conn = sqlite3.connect(DB_PATH)

    for team_id, players in roster.items():
        for p in players:
            conn.execute(
                "INSERT OR REPLACE INTO players (id, full_name, team_id, position, height, jersey_number) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (p["id"], p["name"], team_id, p.get("position"), p.get("height"), p.get("jersey", "")),
            )

    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    conn.close()
    print(f"  Players in DB: {n}")


def load_into_db() -> None:
    print("\nLoading into SQLite...")
    import subprocess
    subprocess.run([sys.executable, os.path.join(BASE_DIR, "load_ssa_db.py")], check=True)


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
    parser.add_argument("--no-db",         action="store_true")
    args = parser.parse_args()

    load_dotenv(os.path.join(BASE_DIR, ".env"))
    session = requests.Session()
    print("Authenticating...")
    token, _ = sf.get_access_token(session, os.getenv("SSA_USERNAME"), os.getenv("SSA_PASSWORD"))
    os.makedirs(RAW_DIR, exist_ok=True)

    from datetime import datetime
    date_str = datetime.now().strftime("%Y-%m-%d")

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
        return

    if args.team:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT id FROM teams WHERE name LIKE ?",
                           (f"%{args.team.split()[0]}%",)).fetchone()
        conn.close()
        if not row:
            print(f"Team not found: {args.team}")
            sys.exit(1)
        roster = {row[0]: roster.get(row[0], [])}

    seed_players_to_db(roster)

    team_id_map  = get_team_id_map()
    name_map     = {v: k for k, v in team_id_map.items()}
    total_players = sum(len(v) for v in roster.values())

    print(f"\n=== Phase 2: Scraping stats ({total_players} players, period={args.period}) ===")

    done = 0
    for team_id, players in roster.items():
        team_name = name_map.get(team_id, team_id)
        print(f"\n  {team_name} ({len(players)} players)")
        for p in players:
            done += 1
            print(f"  [{done}/{total_players}] {p['name']}", end="  ")
            scrape_player(session, token, p["id"], p["name"], args.period, date_str)

    if not args.no_db:
        load_into_db()

    print(f"\n✅ Complete — {done} players scraped")


if __name__ == "__main__":
    main()
