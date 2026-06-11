#!/usr/bin/env python3
"""
SSA Scraper — All WNT Teams, 2026 FIBA CUPS
Discovers every WNT team by paginating matches across all 4 competition phases,
then scrapes team + player data for each one.

Usage:
    python scrape_ssa_all_teams.py                         # All teams, LAST_3
    python scrape_ssa_all_teams.py --period CURRENT_SEASON # Full season
    python scrape_ssa_all_teams.py --team-only             # Skip per-player
    python scrape_ssa_all_teams.py --resume                # Skip already-done teams

Requires:
    SSA_USERNAME and SSA_PASSWORD in .env
    pip install requests python-dotenv
"""

import argparse
import json
import os
import sys
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ssa_functions as sf


# ---------------------------------------------------------------------------
# Config — all IDs confirmed from network inspection
# ---------------------------------------------------------------------------

SEASON_ID  = "cba189ee-e4b9-47c1-a650-437e3828160d"  # 2026 FIBA CUPS
COMP_TYPE  = "NATIONAL_TEAMS"
SEX        = "FEMALE"

# All 4 competition phases in the season — iterate all to find every team
COMPETITION_PHASES = {
    "FIBA 3x3 World Cup 2026":        "62fdd1aa-de94-4e5d-aff0-3638f7fba1fe",
    "World Cup Qualifier 2026":        "3d93930e-1672-4419-b9e4-c815d697a459",
    "Asia Cup":                        "4a784855-1d9f-49f9-835d-7aad002a8f80",
    "3x3 Champions Cup 2026":         "f463038c-1854-42ef-aa82-de293c014c3c",
}

# Hardcoded fallback — confirmed from match data across this session
KNOWN_TEAMS = {
    "4f9b83f2-8209-4e04-a9bb-6fcd0a03f739": "Canada WNT",
    "99909fac-ccfa-45c4-b2fd-6e8a6f896a2b": "France WNT",
    "971c6a0d-e3b0-495e-9b3e-2f8d9697a1dc": "Japan WNT",
    "6a552d77-b7fc-4c03-a953-5915024c0653": "Ukraine WNT",
    "9c7dae40-61a3-40ff-8365-4ee22d2be0c7": "Australia WNT",
    "6f7db5e9-3a21-49e2-90b9-b0ae6f19d85a": "Philippines WNT",
}

RAW_DIR       = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "raw")
PROGRESS_FILE = os.path.join(RAW_DIR, "_progress.json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _save(data, filename: str) -> None:
    os.makedirs(RAW_DIR, exist_ok=True)
    sf.write_data(os.path.join(RAW_DIR, filename), data)


def _safe_call(fn, label: str, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        print(f"    [HTTP {status}] {label} — skipping")
        return None
    except Exception as e:
        print(f"    [ERROR] {label}: {e}")
        return None


def _load_progress() -> set:
    try:
        with open(PROGRESS_FILE) as f:
            return set(json.load(f))
    except Exception:
        return set()


def _save_progress(done: set) -> None:
    os.makedirs(RAW_DIR, exist_ok=True)
    with open(PROGRESS_FILE, "w") as f:
        json.dump(list(done), f)


# ---------------------------------------------------------------------------
# Team discovery — paginate matches across all competition phases
# ---------------------------------------------------------------------------

def discover_teams(session, access_token) -> dict[str, str]:
    """
    Pull matches from every competition phase in the season,
    extract all unique WNT team IDs from home/away fields.
    Always merges in KNOWN_TEAMS as a guaranteed baseline.
    """
    print("Discovering WNT teams from competition phases...")
    teams = {}

    for phase_name, phase_id in COMPETITION_PHASES.items():
        print(f"  Phase: {phase_name}")
        page = 0
        while True:
            try:
                resp = session.get(
                    f"{sf.BASE_URL}/matches",
                    params={
                        "seasonId":          SEASON_ID,
                        "competitionPhaseId": phase_id,
                        "competitionType":   COMP_TYPE,
                        "page":              page,
                        "size":              50,
                        "sort":              "id",
                        "direction":         "DESC",
                    },
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json",
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"    Error fetching page {page}: {e}")
                break

            # Handle paginated {content:[]} or flat list
            if isinstance(data, dict):
                matches     = data.get("content") or data.get("result") or []
                total_pages = data.get("totalPages", 1)
            elif isinstance(data, list):
                matches     = data
                total_pages = 1
            else:
                break

            found_this_page = 0
            for m in matches:
                for side in ("home", "away"):
                    tid  = m.get(f"{side}TeamId")
                    name = m.get(f"{side}TeamName", "")
                    sex  = m.get(f"{side}TeamSex", "")
                    if tid and sex == SEX and tid not in teams:
                        teams[tid] = name
                        found_this_page += 1

            if found_this_page:
                print(f"    page {page}: +{found_this_page} teams")

            if not matches or page >= total_pages - 1:
                break
            page += 1

        time.sleep(0.2)

    # Always include known teams
    before = len(teams)
    teams.update({k: v for k, v in KNOWN_TEAMS.items() if k not in teams})
    added = len(teams) - before
    if added:
        print(f"  Added {added} known teams not found in phase matches")

    print(f"\n  Total: {len(teams)} WNT teams discovered")
    for name in sorted(teams.values()):
        print(f"    {name}")

    return teams


# ---------------------------------------------------------------------------
# Scrape one team
# ---------------------------------------------------------------------------

def scrape_team(
    session, access_token,
    team_id, team_name,
    period, date_str,
    team_only: bool = False,
) -> None:
    safe_name = team_name.replace(" ", "_")
    print(f"\n  {'─'*52}")
    print(f"  {team_name}")
    print(f"  {'─'*52}")

    # Match list
    matches = _safe_call(
        sf.get_all_team_matches, "matches",
        session, access_token, team_id, SEASON_ID,
    )
    if matches is not None:
        _save(matches, f"{date_str}_{safe_name}_matches.json")
        print(f"    matches : {len(matches)}")

    # Team stats
    for label, fn in [
        ("overall",            sf.get_team_overall),
        ("additional_offense", sf.get_team_additional_offense),
        ("play_types",         sf.get_team_play_types),
        ("defensive",          sf.get_team_defensive),
    ]:
        data = _safe_call(
            fn, label,
            session, access_token, team_id, SEASON_ID, period, COMP_TYPE,
        )
        if data is not None:
            _save(data, f"{date_str}_{safe_name}_{label}_{period}.json")
            print(f"    {label:<22} ✓")
        else:
            print(f"    {label:<22} ✗")
        time.sleep(0.15)

    if team_only:
        return

    # Roster
    team_info = _safe_call(
        sf.get_team_info, "team_info",
        session, access_token, team_id, True,
    )
    if team_info:
        _save(team_info, f"{date_str}_{safe_name}_info.json")

    players = []
    if team_info:
        players = (
            team_info.get("players")
            or team_info.get("roster")
            or team_info.get("teamPlayers")
            or []
        )

    if not players:
        print(f"    roster  : not in team_info — check {safe_name}_info.json")
        return

    print(f"    roster  : {len(players)} players")

    # Per-player
    for player in players:
        pid  = player.get("id") or player.get("playerId")
        name = player.get("name") or player.get("playerName") or pid
        if not pid:
            continue

        safe_pname = (name or pid).replace(" ", "_")
        print(f"      {name:<28}", end=" ", flush=True)

        for key, fn in [
            ("overall",            sf.get_player_overall),
            ("additional_offense", sf.get_player_additional_offense),
            ("play_types",         sf.get_player_play_types),
            ("defensive",          sf.get_player_defensive),
            ("shot_chart",         sf.get_player_shot_chart),
        ]:
            data = _safe_call(
                fn, key,
                session, access_token, pid, SEASON_ID, period, COMP_TYPE,
            )
            if data is not None:
                _save(data, f"{date_str}_{safe_name}_{safe_pname}_{key}_{period}.json")
                print("✓", end="", flush=True)
            else:
                print("✗", end="", flush=True)
            time.sleep(0.1)

        print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Scrape all WNT teams from SSA 2026 FIBA CUPS")
    parser.add_argument(
        "--period", default="LAST_3",
        choices=list(sf.CONSTANTS.PERIODS.values()),
        help="Stat window (default: LAST_3)"
    )
    parser.add_argument(
        "--team-only", action="store_true",
        help="Skip per-player scraping"
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip teams already scraped (reads data/raw/_progress.json)"
    )
    parser.add_argument(
        "--team-id", default=None,
        help="Scrape a single team by UUID (for testing)"
    )
    args = parser.parse_args()

    load_dotenv()
    username = os.getenv("SSA_USERNAME")
    password = os.getenv("SSA_PASSWORD")
    if not username or not password:
        print("Error: SSA_USERNAME and SSA_PASSWORD must be set in .env")
        sys.exit(1)

    print("Authenticating...")
    session = requests.Session()
    access_token, _ = sf.get_access_token(session, username, password)

    date_str = _today()
    done     = _load_progress() if args.resume else set()

    # Single team test mode
    if args.team_id:
        name = KNOWN_TEAMS.get(args.team_id, "Unknown WNT")
        scrape_team(session, access_token, args.team_id, name,
                    args.period, date_str, args.team_only)
        print(f"\n✅ Done. Files in: {RAW_DIR}")
        return

    # Discover all teams
    teams = discover_teams(session, access_token)
    total = len(teams)

    print(f"\n{'='*55}")
    print(f"  Scraping {total} teams  |  period = {args.period}")
    if args.team_only:
        print(f"  Mode: team stats only")
    if args.resume:
        print(f"  Resume: skipping {len(done)} already-done teams")
    print(f"{'='*55}")

    for i, (team_id, team_name) in enumerate(sorted(teams.items(), key=lambda x: x[1]), 1):
        print(f"\n[{i}/{total}]", end="")

        if args.resume and team_id in done:
            print(f" SKIP: {team_name}")
            continue

        scrape_team(
            session, access_token,
            team_id, team_name,
            args.period, date_str,
            args.team_only,
        )

        done.add(team_id)
        _save_progress(done)
        time.sleep(0.3)

    print(f"\n{'='*55}")
    print(f"✅ Complete.")
    print(f"   Teams scraped : {len(done)}/{total}")
    print(f"   Period        : {args.period}")
    print(f"   Files in      : {RAW_DIR}")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()
