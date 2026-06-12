#!/usr/bin/env python3
"""
AI scouting report generator using Groq (free).
Pre-fetches all stats from SQLite and passes them directly in the prompt.

Usage:
    python scout_groq.py --opponent "Canada WNT" --period LAST_3
    python scout_groq.py --opponent "Canada WNT" --period SEASON --save report.md
"""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

try:
    from groq import Groq
except ImportError:
    print("Run: pip install groq")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "data", "db", "ssa.db")

MODEL = "llama-3.3-70b-versatile"


def get_conn():
    if not os.path.exists(DB_PATH):
        print(f"Database not found: {DB_PATH}\nRun: python load_ssa_db.py")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def q(conn, sql, params=()):
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


KEY_STATS = [
    "GAMES_PLAYED","WIN_PERCENTAGE","POSSESSIONS","POINTS","POINTS_PER_POSSESSIONS",
    "POINTS_ALLOWED_PER_POSSESSIONS","3PTM","3PTA","3PT%","2PTM","2PTA","2PT%",
    "1PTM","1PTA","1PT%","SHOOTING_EFF","DEFENSIVE_REBOUNDS","OFFENSIVE_REBOUNDS",
    "ASSISTS","TURNOVERS","FOULS","FOULS_AGAINST",
]


def build_context(conn, team_id: str, period: str) -> str:
    lines = []

    team = conn.execute("SELECT name FROM teams WHERE id=?", (team_id,)).fetchone()
    lines.append(f"TEAM: {team['name'] if team else team_id} | Period: {period}")

    # Matches (compact)
    matches = q(conn, "SELECT home_team_name,away_team_name,home_score,away_score,match_date FROM matches ORDER BY match_date")
    if matches:
        lines.append("RESULTS: " + " | ".join(
            f"{m['match_date']} {m['home_team_name']} {m['home_score']}-{m['away_score']} {m['away_team_name']}"
            for m in matches
        ))

    # Team stats (key labels only, per_game)
    stats = {s['stat_label']: s['per_game'] for s in
             q(conn, "SELECT stat_label, per_game FROM team_stats WHERE team_id=? AND period=?", (team_id, period))}
    if stats:
        lines.append("TEAM STATS (per_game): " + "  ".join(
            f"{k}={stats[k]}" for k in KEY_STATS if k in stats and stats[k] is not None
        ))

    # Team play types (offense + defense compact)
    for side in ("offense", "defense"):
        pt = q(conn, "SELECT label,possession,ppp,pct FROM team_play_types WHERE team_id=? AND period=? AND side=?",
               (team_id, period, side))
        if pt:
            lines.append(f"TEAM {side.upper()}: " + "  ".join(
                f"{r['label']}(poss={r['possession']},ppp={r['ppp']},pct={r['pct']}%)" for r in pt
            ))

    # Team individual play types
    detail = q(conn, "SELECT play_type,poss,ppp,usage,two_pt_pct,three_pt_pct,turnovers FROM team_play_types_detail WHERE team_id=? AND period=? AND poss>0 ORDER BY usage DESC",
               (team_id, period))
    if detail:
        lines.append("TEAM PLAY TYPES: " + "  ".join(
            f"{r['play_type']}(u={r['usage']}%,ppp={r['ppp']},1PT%={r['two_pt_pct']},2PT%={r['three_pt_pct']},TO={r['turnovers']})"
            for r in detail
        ))

    # Players
    players = q(conn, "SELECT id,full_name,position,height,jersey_number FROM players WHERE team_id=?", (team_id,))
    for p in players:
        pid = p['id']
        lines.append(f"\n--- {p['full_name']} | #{p['jersey_number']} | {p['position']} | {p['height']}cm ---")

        # Key stats (per_game only)
        ps = {s['stat_label']: s['per_game'] for s in
              q(conn, "SELECT stat_label, per_game FROM player_stats WHERE player_id=? AND period=?", (pid, period))}
        if ps:
            lines.append("STATS: " + "  ".join(
                f"{k}={ps[k]}" for k in KEY_STATS if k in ps and ps[k] is not None
            ))

        # Play type detail (non-zero only)
        ptd = q(conn, "SELECT play_type,poss,ppp,usage,two_pt_m,two_pt_a,two_pt_pct,three_pt_m,three_pt_a,three_pt_pct,turnovers FROM player_play_types_detail WHERE player_id=? AND period=? AND poss>0 ORDER BY usage DESC",
                (pid, period))
        if ptd:
            lines.append("PLAY TYPES: " + "  ".join(
                f"{r['play_type']}(u={r['usage']}%,ppp={r['ppp']},1PT={r['two_pt_m']}/{r['two_pt_a']}({r['two_pt_pct']}%),2PT={r['three_pt_m']}/{r['three_pt_a']}({r['three_pt_pct']}%),TO={r['turnovers']})"
                for r in ptd
            ))

        # Finishing (non-zero only)
        tf = q(conn, "SELECT shot_type,hand,made,attempted,pct FROM player_tendency_finishing WHERE player_id=? AND period=? AND attempted>0",
               (pid, period))
        if tf:
            lines.append("FINISHING: " + "  ".join(
                f"{r['shot_type']}/{r['hand']}:{r['made']}/{r['attempted']}({r['pct']}%)" for r in tf
            ))

        # Dribble jumper hand tendency (non-zero)
        td = q(conn, "SELECT play_type,hand,two_pt_m,two_pt_a,two_pt_pct FROM player_tendency_dribble WHERE player_id=? AND period=? AND two_pt_a>0",
               (pid, period))
        if td:
            lines.append("DRIBBLE JUMPER: " + "  ".join(
                f"{r['play_type']}/{r['hand']}:{r['two_pt_m']}/{r['two_pt_a']}({r['two_pt_pct']}%)" for r in td
            ))

        # Shot zones (non-zero, no-dribble)
        znd = q(conn, "SELECT zone,made,total,pct FROM player_shot_zones WHERE player_id=? AND period=? AND is_dribble=0 AND total>0 ORDER BY total DESC",
                (pid, period))
        if znd:
            lines.append("ZONES(no-drib): " + "  ".join(f"{r['zone']}:{r['made']}/{r['total']}({r['pct']}%)" for r in znd))

        # Shot zones dribble
        zd = q(conn, "SELECT zone,made,total,pct FROM player_shot_zones WHERE player_id=? AND period=? AND is_dribble=1 AND total>0 ORDER BY total DESC",
               (pid, period))
        if zd:
            lines.append("ZONES(drib): " + "  ".join(f"{r['zone']}:{r['made']}/{r['total']}({r['pct']}%)" for r in zd))

    return "\n".join(lines)


SYSTEM_PROMPT = """You are an elite 3x3 basketball analyst working for Canada WNT.
Generate a concise, actionable scouting report for the opponent based solely on the stats provided.

3x3 SCORING: inside arc = 1PT, outside arc = 2PT, free throw = 1PT.
API LABELS: 2PT% in the data = inside-arc (1PT in 3x3). 3PT% = outside-arc (2PT in 3x3). Use 3x3 terms in the report.
ZONE LABELS: TWO_POINTS_LAYUP_LEFT/RIGHT = left/right layup. THREE_POINTS_* = outside-arc zones.

REPORT FORMAT:
# [Team] Scouting Report
**[Our Team] vs [Opponent] | Period: [period]**

## Team Overview
[2-3 sentences: record, win%, key stats]

## Offensive Profile
| Play Type | Usage% | PPP |
|---|---|---|
[top play types table]

**Key tendencies:**
- [bullet points]

## Defensive Profile
- [bullet points from defense play type data]

## Players

### #[jersey] [Name] | [Position] | [Height]cm
| 2PT | 2PT% | 1PT | 1PT% | FT | FT% | PPG | REB | TO |
|---|---|---|---|---|---|---|---|---|
[stats row — use per_game values. 2PT=3PT% column, 1PT=2PT% column, FT=1PT% column]

**Shot zones:** [key hot/cold zones, left vs right dominance]
**Finishing:** [dominant hand, % at rim]
**Dribble jumpers:** [hand preference by play type]
**Scouting notes:**
- [3-5 specific, actionable bullets from the data]

## Matchup Notes
- [How Canada should attack each player's weaknesses]

RULES: Only state what the data supports. Flag stats with <5 attempts as small sample. Be specific."""


def call_groq(client, system: str, user: str, max_tokens: int = 1500) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=0.3,
    )
    return response.choices[0].message.content or ""


PLAYER_SYSTEM = """You are a 3x3 basketball scout for Canada WNT. Write a concise player scouting card from stats.
3x3 scoring: inside arc=1PT(2PT% column), outside arc=2PT(3PT% column), FT=1PT(1PT% column).
ZONES: TWO_POINTS_LAYUP_LEFT/RIGHT=layups. THREE_POINTS_*=outside arc shots.
Output format:
### #[jersey] [Name] | [Position] | [Height]cm
| 2PT | 2PT% | 1PT | 1PT% | FT | FT% | PPG | REB | TO |
|---|---|---|---|---|---|---|---|---|
[per_game stats row]
**Shot zones:** [key zones, left vs right]
**Finishing:** [dominant hand, rim %, shot type]
**Dribble jumper:** [hand by play type]
**Play types:** [top 3 by usage, ppp, key note]
**Scouting notes:**
- [3 specific actionable bullets from data only]"""


def generate_report(opponent: str, period: str, our_team: str = "Canada WNT") -> str:
    conn = get_conn()
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    team_row = conn.execute("SELECT id FROM teams WHERE name LIKE ?", (f"%{opponent.split()[0]}%",)).fetchone()
    if not team_row:
        teams = q(conn, "SELECT id, name FROM teams")
        print(f"Team '{opponent}' not found. Available: {[t['name'] for t in teams]}")
        conn.close()
        sys.exit(1)
    team_id = team_row["id"]

    print(f"\nGenerating: {our_team} vs {opponent} ({period})")

    # --- Team section (one request) ---
    print("  [1/6] Team overview...")
    team_ctx = build_context(conn, team_id, period)
    # Only send team portion (before first player section)
    team_only = team_ctx.split("\n--- ")[0]
    print(f"        {len(team_only)} chars")

    team_section = call_groq(client, SYSTEM_PROMPT,
        f"Write only the Team Overview, Offensive Profile, and Defensive Profile sections "
        f"for this scouting report on {opponent} (period: {period}, vs {our_team}).\n\n"
        f"=== TEAM DATA ===\n{team_only}\n=== END ===",
        max_tokens=800,
    )

    # --- Per-player sections (one request each) ---
    players = q(conn, "SELECT id, full_name, position, height, jersey_number FROM players WHERE team_id=?", (team_id,))
    player_sections = []

    for i, p in enumerate(players, 2):
        pid = p['id']
        print(f"  [{i}/{len(players)+1}] {p['full_name']}...")

        # Build compact single-player context
        plines = [f"Player: {p['full_name']} | #{p['jersey_number']} | {p['position']} | {p['height']}cm"]

        ps = {s['stat_label']: s['per_game'] for s in
              q(conn, "SELECT stat_label, per_game FROM player_stats WHERE player_id=? AND period=?", (pid, period))}
        if ps:
            plines.append("STATS(per_game): " + "  ".join(
                f"{k}={ps[k]}" for k in KEY_STATS if k in ps and ps[k] is not None
            ))

        ptd = q(conn, "SELECT play_type,poss,ppp,usage,two_pt_m,two_pt_a,two_pt_pct,three_pt_m,three_pt_a,three_pt_pct,turnovers FROM player_play_types_detail WHERE player_id=? AND period=? AND poss>0 ORDER BY usage DESC LIMIT 5",
                (pid, period))
        if ptd:
            plines.append("PLAY TYPES: " + "  ".join(
                f"{r['play_type']}(u={r['usage']}%,ppp={r['ppp']},1PT={r['two_pt_m']}/{r['two_pt_a']}({r['two_pt_pct']}%),2PT={r['three_pt_m']}/{r['three_pt_a']}({r['three_pt_pct']}%),TO={r['turnovers']})"
                for r in ptd
            ))

        tf = q(conn, "SELECT shot_type,hand,made,attempted,pct FROM player_tendency_finishing WHERE player_id=? AND period=? AND attempted>0",
               (pid, period))
        if tf:
            plines.append("FINISHING: " + "  ".join(
                f"{r['shot_type']}/{r['hand']}:{r['made']}/{r['attempted']}({r['pct']}%)" for r in tf
            ))

        td = q(conn, "SELECT play_type,hand,two_pt_m,two_pt_a,two_pt_pct FROM player_tendency_dribble WHERE player_id=? AND period=? AND two_pt_a>0",
               (pid, period))
        if td:
            plines.append("DRIB JUMPER: " + "  ".join(
                f"{r['play_type']}/{r['hand']}:{r['two_pt_m']}/{r['two_pt_a']}({r['two_pt_pct']}%)" for r in td
            ))

        znd = q(conn, "SELECT zone,made,total,pct FROM player_shot_zones WHERE player_id=? AND period=? AND is_dribble=0 AND total>0 ORDER BY total DESC",
                (pid, period))
        if znd:
            plines.append("ZONES(no-drib): " + "  ".join(f"{r['zone']}:{r['made']}/{r['total']}({r['pct']}%)" for r in znd))

        zd = q(conn, "SELECT zone,made,total,pct FROM player_shot_zones WHERE player_id=? AND period=? AND is_dribble=1 AND total>0 ORDER BY total DESC",
               (pid, period))
        if zd:
            plines.append("ZONES(drib): " + "  ".join(f"{r['zone']}:{r['made']}/{r['total']}({r['pct']}%)" for r in zd))

        player_ctx = "\n".join(plines)
        print(f"        {len(player_ctx)} chars")

        section = call_groq(client, PLAYER_SYSTEM,
            f"Generate the player scouting card for this player.\n\n"
            f"=== DATA ===\n{player_ctx}\n=== END ===",
            max_tokens=600,
        )
        player_sections.append(section)

    conn.close()

    # --- Final matchup notes (one request) ---
    print(f"  [{len(players)+2}/{len(players)+2}] Matchup notes...")
    matchup = call_groq(client, SYSTEM_PROMPT,
        f"Based on the scouting report for {opponent}, write a brief '## Matchup Notes' section "
        f"(2-3 sentences max per player) on how {our_team} should attack each player's statistical weaknesses.\n\n"
        f"Players: {', '.join(p['full_name'] for p in players)}",
        max_tokens=400,
    )

    report = (
        f"# {opponent} Scouting Report\n"
        f"**{our_team} vs {opponent} | Period: {period}**\n\n"
        + team_section + "\n\n"
        + "## Players\n\n"
        + "\n\n".join(player_sections) + "\n\n"
        + matchup
    )
    print(f"\n  Done.")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--opponent", required=True)
    parser.add_argument("--period", default="LAST_3",
                        choices=["LAST_1", "LAST_3", "LAST_5", "LAST_10", "SEASON", "ALL"])
    parser.add_argument("--team", default="Canada WNT")
    parser.add_argument("--save", default=None)
    args = parser.parse_args()

    report = generate_report(args.opponent, args.period, args.team)

    print("\n" + "═" * 60)
    print(report)

    if args.save:
        Path(args.save).write_text(report)
        print(f"\nSaved → {args.save}")


if __name__ == "__main__":
    main()
