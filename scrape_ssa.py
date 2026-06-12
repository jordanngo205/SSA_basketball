#!/usr/bin/env python3
"""
SSA Scraper — Canada WNT
Scrapes every data type visible on the SSA team page:
  - Team overall stats
  - Team additional offense
  - Team play types (offense + defense breakdown)
  - Team defensive stats
  - Team match list
  - Per-player: overall, additional offense, play types, defensive, shot chart
  - Saves everything to data/raw/ as dated JSON files

Usage:
    python scrape_ssa.py                           # Canada WNT, last 3 games
    python scrape_ssa.py --period CURRENT_SEASON   # Full season
    python scrape_ssa.py --period LAST_5           # Last 5 games
    python scrape_ssa.py --team-only               # Skip per-player scraping
    python scrape_ssa.py --player-id <uuid>        # Single player only

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
# Known IDs — Canada WNT, 2026 FIBA World Cup
# ---------------------------------------------------------------------------

CANADA_WNT_ID  = "4f9b83f2-8209-4e04-a9bb-6fcd0a03f739"
SEASON_2026_ID = "cba189ee-e4b9-47c1-a650-437e3828160d"
COMP_TYPE      = "NATIONAL_TEAMS"

# Roster from SSA page screenshot (fill in as IDs are confirmed)
# Format: {player_name: player_id}
# IDs are fetched dynamically from the team endpoint; this is a fallback
KNOWN_ROSTER = {
    "Paige Crozon":       "d29fd8da-3ead-4c41-aa12-b496fb0debe9",
    "Katherine Plouffe":  "f532294f-8e69-4cbb-be69-7fa1cd6189b5",
    "Kacie Bosch":        "d9c544b9-cb4d-4280-9bef-6b1102fc7b2a",
    "Saicha Grant-Allen": "9f9a4068-97fb-4bd2-a865-0c354c533f4d",
    "Tara Wallack":       "2b6dc75e-dd80-4324-9737-8bc4a0859ce8",
}

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "raw")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _save(data, filename: str) -> str:
    """Save data as JSON to data/raw/."""
    os.makedirs(RAW_DIR, exist_ok=True)
    path = os.path.join(RAW_DIR, filename)
    sf.write_data(path, data)
    return path


def _safe_call(fn, label: str, *args, **kwargs):
    """Call an SSA function and return data, or None on error."""
    try:
        result = fn(*args, **kwargs)
        return result
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        print(f"  [HTTP {status}] {label} — skipping")
        return None
    except Exception as e:
        print(f"  [ERROR] {label}: {e}")
        return None


def _print_summary(label: str, stats: list[dict], mode: str = "total") -> None:
    flat = sf.flatten_stats(stats, mode=mode)
    if not flat:
        return
    print(f"\n  {'─'*45}")
    print(f"  {label} ({mode})")
    print(f"  {'─'*45}")
    for k, v in flat.items():
        print(f"    {k:<40} {v}")


# ---------------------------------------------------------------------------
# Team scraping
# ---------------------------------------------------------------------------

def scrape_team(session, access_token, team_id, season_id, period, date_str) -> dict:
    print(f"\n{'='*55}")
    print(f"  TEAM  |  period={period}")
    print(f"{'='*55}")

    results = {}

    # 1. Match list — always fetch first so we know what games exist
    print("\n[1/5] Matches...")
    matches = _safe_call(
        sf.get_all_team_matches, "team matches",
        session, access_token, team_id, season_id,
    )
    if matches is not None:
        _save(matches, f"{date_str}_team_{team_id}_matches.json")
        print(f"      {len(matches)} matches found")
        for m in sorted(matches, key=lambda x: x.get("matchStartTime", "")):
            home = m.get("homeTeamName", "")
            away = m.get("awayTeamName", "")
            hs   = m.get("homeTeamScore", "?")
            as_  = m.get("awayTeamScore", "?")
            dt   = (m.get("matchStartTime") or "")[:10]
            print(f"      {dt}  {home} {hs}–{as_} {away}")
        results["matches"] = matches

    # 2. Overall box stats
    print("\n[2/5] Overall stats...")
    data = _safe_call(
        sf.get_team_overall, "team overall",
        session, access_token, team_id, season_id, period, COMP_TYPE,
    )
    if data is not None:
        _save(data, f"{date_str}_team_{team_id}_overall_{period}.json")
        _print_summary("Team Overall", data)
        results["overall"] = data

    # 3. Offense play types (Set Play / Open Play / Transition)
    print("\n[3/5] Offense play types...")
    data = _safe_call(
        sf.get_team_additional_offense, "team offense play types",
        session, access_token, team_id, season_id, period, COMP_TYPE,
    )
    if data is not None:
        _save(data, f"{date_str}_team_{team_id}_offense_play_types_{period}.json")
        results["offense_play_types"] = data

    # 4. Defense play types (Set Play / Open Play / Transition)
    print("\n[4/5] Defense play types...")
    data = _safe_call(
        sf.get_team_additional_defense, "team defense play types",
        session, access_token, team_id, season_id, period, COMP_TYPE,
    )
    if data is not None:
        _save(data, f"{date_str}_team_{team_id}_defense_play_types_{period}.json")
        results["defense_play_types"] = data

    # 5. Individual play types (CUT, PNR, ISO, etc.)
    print("\n[5/5] Individual play types...")
    data = _safe_call(
        sf.get_team_play_types, "team individual play types",
        session, access_token, team_id, season_id, period, COMP_TYPE,
    )
    if data is not None:
        _save(data, f"{date_str}_team_{team_id}_play_types_detail_{period}.json")
        results["play_types_detail"] = data

    return results


# ---------------------------------------------------------------------------
# Roster resolution
# ---------------------------------------------------------------------------

def get_roster(session, access_token, team_id) -> list[dict]:
    """
    Fetch roster from team info endpoint.
    Returns list of {id, name, number, ...} dicts.
    Falls back to empty list if endpoint doesn't return players.
    """
    print("\nFetching roster...")
    team_info = _safe_call(
        sf.get_team_info, "team info",
        session, access_token, team_id, True,
    )
    if not team_info:
        print("  Could not fetch team info — player IDs unknown")
        return []

    # Save raw team info
    date_str = _today()
    _save(team_info, f"{date_str}_team_{team_id}_info.json")

    # Try common roster field names
    players = (
        team_info.get("players")
        or team_info.get("roster")
        or team_info.get("teamPlayers")
        or []
    )

    if not players:
        print("  Team info returned no players array — falling back to KNOWN_ROSTER")
        return [
            {"id": pid, "name": name}
            for name, pid in KNOWN_ROSTER.items()
            if pid
        ]

    print(f"  Roster: {len(players)} players")
    for p in players:
        name = p.get("name") or p.get("playerName") or "?"
        num  = p.get("number") or p.get("shirtNumber") or "-"
        pid  = p.get("id") or p.get("playerId") or "?"
        print(f"    #{num}  {name}  ({pid})")

    return players


# ---------------------------------------------------------------------------
# Player scraping
# ---------------------------------------------------------------------------

def scrape_player(
    session, access_token, player_id, player_name,
    season_id, period, date_str,
) -> dict:
    print(f"\n  {'─'*50}")
    print(f"  PLAYER: {player_name}  ({player_id})")
    print(f"  {'─'*50}")

    results = {}
    safe_name = player_name.replace(" ", "_")

    standard_endpoints = [
        ("overall",              sf.get_player_overall),
        ("offense_play_types",   sf.get_player_offense_play_types),
        ("defense_play_types",   sf.get_player_defense_play_types),
        ("play_types_detail",    sf.get_player_play_types),
        ("tendency_shooting",    sf.get_player_shooting_tendency),
        ("tendency_dribble",     sf.get_player_shooting_tendency_dribble),
        ("tendency_finishing",   sf.get_player_shooting_tendency_finishing),
        ("turnovers",            sf.get_player_turnovers),
    ]

    for key, fn in standard_endpoints:
        print(f"  → {key}...", end=" ", flush=True)
        data = _safe_call(
            fn, f"player {key}",
            session, access_token, player_id, season_id, period, COMP_TYPE,
        )
        if data is not None:
            fname = f"{date_str}_player_{safe_name}_{key}_{period}.json"
            _save(data, fname)
            results[key] = data
            print("✓")
        else:
            print("✗")
        time.sleep(0.2)

    # Shot zone charts (no-dribble and dribble)
    for dribble_flag, label in [(False, "shot_zones_no_dribble"), (True, "shot_zones_dribble")]:
        print(f"  → {label}...", end=" ", flush=True)
        data = _safe_call(
            sf.get_player_shot_zones, f"player {label}",
            session, access_token, player_id, season_id, dribble_flag, period, COMP_TYPE,
        )
        if data is not None:
            fname = f"{date_str}_player_{safe_name}_{label}_{period}.json"
            _save(data, fname)
            results[label] = data
            print("✓")
        else:
            print("✗")
        time.sleep(0.2)

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Scrape SSA data for Canada WNT")
    parser.add_argument(
        "--period", default="LAST_3",
        choices=list(sf.CONSTANTS.PERIODS.values()),
        help="Stat window: LAST_1 (last match), LAST_3, LAST_5, LAST_10, SEASON, ALL (default: LAST_3)"
    )
    parser.add_argument(
        "--team", default=CANADA_WNT_ID,
        help="Team UUID to scrape"
    )
    parser.add_argument(
        "--season", default=SEASON_2026_ID,
        help="Season UUID"
    )
    parser.add_argument(
        "--team-only", action="store_true",
        help="Only scrape team-level data, skip per-player"
    )
    parser.add_argument(
        "--player-id", default=None,
        help="Scrape a single player by UUID (skips team scrape)"
    )
    parser.add_argument(
        "--player-name", default="player",
        help="Name label used in filename when --player-id is set"
    )
    args = parser.parse_args()

    # Auth
    load_dotenv()
    username = os.getenv("SSA_USERNAME")
    password = os.getenv("SSA_PASSWORD")
    if not username or not password:
        print("Error: SSA_USERNAME and SSA_PASSWORD must be set in .env")
        sys.exit(1)

    print("Authenticating with SSA...")
    session = requests.Session()
    access_token, refresh_token = sf.get_access_token(session, username, password)

    date_str = _today()

    # ── Single player mode ──────────────────────────────────────────────────
    if args.player_id:
        scrape_player(
            session, access_token,
            args.player_id, args.player_name,
            args.season, args.period, date_str,
        )
        print(f"\n✅ Done. Files in: {RAW_DIR}")
        return

    # ── Team mode ───────────────────────────────────────────────────────────
    scrape_team(session, access_token, args.team, args.season, args.period, date_str)

    if args.team_only:
        print(f"\n✅ Done (team only). Files in: {RAW_DIR}")
        return

    # ── Per-player scraping ─────────────────────────────────────────────────
    print(f"\n{'='*55}")
    print("  PLAYERS")
    print(f"{'='*55}")

    roster = get_roster(session, access_token, args.team)

    if not roster:
        print("\n⚠️  No roster returned. Options:")
        print("  1. Run with --player-id <uuid> --player-name <name> for each player manually")
        print("  2. Check data/raw/*_team_info.json for player IDs")
        print("  3. The team info endpoint may use a different field — open an issue")
        sys.exit(0)

    all_player_results = {}
    for i, player in enumerate(roster, 1):
        pid  = player.get("id") or player.get("playerId")
        name = player.get("name") or player.get("playerName") or f"player_{i}"
        if not pid:
            print(f"  Skipping {name} — no ID found")
            continue

        print(f"\n[{i}/{len(roster)}]")
        result = scrape_player(
            session, access_token,
            pid, name,
            args.season, args.period, date_str,
        )
        all_player_results[name] = result

    # Save combined player summary
    summary_path = os.path.join(
        RAW_DIR, f"{date_str}_all_players_summary_{args.period}.json"
    )
    sf.write_data(summary_path, all_player_results)

    print(f"\n{'='*55}")
    print(f"✅ Complete.")
    print(f"   Team data:    {RAW_DIR}")
    print(f"   Players done: {len(all_player_results)}")
    print(f"   Period:       {args.period}")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()
