#!/usr/bin/env python3
"""
AI scouting report generator — Canada WNT vs opponent.

Usage:
    python scout.py --opponent "Japan WNT" --period LAST_3
    python scout.py --opponent "Japan WNT" --period SEASON --team "Canada WNT"
    python scout.py --opponent "Japan WNT" --period LAST_3 --save report.md

Requires ANTHROPIC_API_KEY in environment or .env file.
"""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("Run: pip install anthropic")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "data", "db", "ssa.db")

SYSTEM_PROMPT = """You are an elite 3x3 basketball analyst working for Canada WNT.
Your job is to generate opponent scouting reports that coaches can use immediately.

SCORING REMINDER (3x3 basketball):
- Inside the arc = 1 point (API labels: 2PTA/2PTM/2PT%)
- Outside the arc = 2 points (API labels: 3PTA/3PTM/3PT%)
- Free throws = 1 point (API labels: 1PTA/1PTM/1PT%)
When writing the report, use the 3x3 labels: 2PT, 1PT, FT — NOT 3PT/2PT/1PT.

SHOT ZONE LABELS (15 court zones):
- TWO_POINTS_LAYUP_LEFT / RIGHT = layups left/right of basket
- THREE_POINTS_LEFT/RIGHT_CORNER = corner 2PT shots (outside arc)
- THREE_POINTS_LEFT/RIGHT_WING = wing 2PT shots
- THREE_POINTS_TOP = top-of-key 2PT shot
- TWO_POINTS_LONG_* = mid-range shots (between arc and paint)
- TWO_POINTS_MID_* = short mid-range shots (edge of paint area)

PLAY TYPE LABELS:
- PICK_AND_ROLL, HANDOFF, OFFSCREEN, ISOLATION, CUT, SPOT_UP,
  POST_UP, OFFENSIVE_REBOUND, TRANSITION, NO_PLAY_TYPES

REPORT FORMAT — match this structure exactly:

---
# [OPPONENT NAME] Scouting Report
**[Our Team] vs [Opponent]  |  [Date if known]**
Period: [LAST_3 / SEASON]

## Team Overview
[2-3 sentences: record, win%, style summary]

## Offensive Profile
| Play Type | Usage | PPP |
|---|---|---|
[table of top play types by usage]

**Key offensive tendencies:**
- [bullet points derived from play type + transition stats]

## Defensive Profile
**On-ball:** [tendencies from defense play types]
**Off-ball:** [tendencies]

## Players

### #[jersey] [Name] | [Position] | [Height]
| 2PT | 2PT% | 1PT | 1PT% | FT | FT% | PPG | REB | FD | FC |
|---|---|---|---|---|---|---|---|---|---|
[stats row using LAST_3 per-game values]

**Shot zones (no-dribble):** [left vs right, hot zones, cold zones]
**Shot zones (dribble):** [left vs right tendencies]
**Finishing:** [rim finishing: shot type, dominant hand, %]
**Play type tendencies:** [top 3 play types by usage, PPP, key observations]
**Dribble jumper:** [left vs right by play type]
**Scouting notes:**
- [3-5 actionable bullet points derived purely from the stats]

[repeat for each player]

## Defensive Matchup Notes
[1-2 sentences per player on how to attack/contain them based on weaknesses in the data]

---

IMPORTANT RULES:
1. Only state what the data supports — no guessing or generic statements.
2. Bullet points must be specific and actionable (e.g. "Goes right hand on 100% of HANDOFF dribble jumper attempts — shade left").
3. Flag any stat with < 5 attempts as "small sample".
4. Compare to Canada's own stats where relevant (e.g. "Their 2PT% (55%) is higher than Canada's (49%)").
5. Use the query_db tool freely — query as many times as needed to build a complete picture.
"""


def get_conn():
    if not os.path.exists(DB_PATH):
        print(f"Database not found: {DB_PATH}")
        print("Run: python load_ssa_db.py")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def run_query(conn, sql: str) -> str:
    try:
        rows = conn.execute(sql).fetchall()
        if not rows:
            return "No results."
        headers = list(rows[0].keys())
        lines = [" | ".join(headers)]
        lines.append("-" * len(lines[0]))
        for row in rows:
            lines.append(" | ".join(str(v) if v is not None else "-" for v in row))
        return "\n".join(lines)
    except Exception as e:
        return f"SQL error: {e}"


TOOLS = [
    {
        "name": "query_db",
        "description": (
            "Execute a read-only SQL query against the SQLite scouting database. "
            "Use this to retrieve any stats needed for the report.\n\n"
            "TABLES:\n"
            "  teams(id, name, competition_type, sex)\n"
            "  players(id, full_name, team_id, position, height, jersey_number, nationality)\n"
            "  matches(id, home_team_name, away_team_name, home_score, away_score, match_date)\n"
            "  team_stats(team_id, period, stat_label, total, per_game)\n"
            "  team_play_types(team_id, period, side, label, possession, points, ppp, pct)\n"
            "  team_play_types_detail(team_id, period, play_type, poss, ppp, usage, ft_m, ft_a, "
            "two_pt_m, two_pt_a, two_pt_pct, three_pt_m, three_pt_a, three_pt_pct, turnovers, assists)\n"
            "  player_stats(player_id, period, stat_label, total, per_game)\n"
            "    key stat_labels: GAMES_PLAYED, GAMES_WON, WIN_PERCENTAGE, POSSESSIONS, POINTS, "
            "POINTS_PER_POSSESSIONS, 3PTA, 3PTM, 3PT%, 2PTA, 2PTM, 2PT%, 1PTA, 1PTM, 1PT%, "
            "SHOOTING_EFF, DEFENSIVE_REBOUNDS, OFFENSIVE_REBOUNDS, ASSISTS, TURNOVERS, BLOCKS, "
            "STEALS, FOULS, FOULS_AGAINST\n"
            "  player_play_types(player_id, period, side, label, possession, points, ppp, pct)\n"
            "    side: 'offense' or 'defense'  |  label: SET_PLAY, OPEN_PLAY, TRANSITION, etc.\n"
            "  player_play_types_detail(player_id, period, play_type, poss, ppp, usage, "
            "ft_m, ft_a, two_pt_m, two_pt_a, two_pt_pct, three_pt_m, three_pt_a, three_pt_pct, turnovers, assists)\n"
            "  player_tendency_shooting(player_id, period, category, hand, "
            "short_range_m, short_range_a, short_range_pct, mid_range_m, mid_range_a, mid_range_pct, "
            "two_pt_m, two_pt_a, two_pt_pct)\n"
            "    category: TOTAL_SHOTS, DRIBBLE_JUMPER, NO_DRIBBLE_JUMPER  |  hand: ALL, LEFT, RIGHT\n"
            "  player_tendency_dribble(player_id, period, play_type, hand, "
            "short_range_m, short_range_a, short_range_pct, mid_range_m, mid_range_a, mid_range_pct, "
            "two_pt_m, two_pt_a, two_pt_pct)\n"
            "    play_type: ALL, PICK_AND_ROLL, HANDOFF, ISOLATION, SPOT_UP, OFFSCREEN, etc.\n"
            "  player_tendency_finishing(player_id, period, shot_type, hand, made, attempted, pct)\n"
            "    shot_type: ALL, LAYUP, FLOATER_OR_RUNNER, HOOK_SHOT, DUNK, TIP_SHOT, JUMPER\n"
            "  player_turnovers(player_id, period, play_type, bad_pass, traveling, "
            "dribble_turnover, line_violation, clock_violation, offensive_foul, other, total)\n"
            "  player_shot_zones(player_id, period, is_dribble, zone, made, missed, total, pct)\n"
            "    is_dribble: 0=no-dribble, 1=dribble\n"
            "    zones: TWO_POINTS_LAYUP_LEFT/RIGHT, THREE_POINTS_RIGHT/LEFT_CORNER/WING/TOP, "
            "TWO_POINTS_LONG_*/MID_*\n"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SELECT query to execute"}
            },
            "required": ["sql"],
        },
    }
]


def generate_report(opponent: str, period: str, our_team: str = "Canada WNT") -> str:
    conn = get_conn()
    client = anthropic.Anthropic()

    # Build initial context message
    teams = conn.execute("SELECT id, name FROM teams").fetchall()
    players = conn.execute("SELECT id, full_name, team_id FROM players").fetchall()
    team_list = "\n".join(f"  {t['id']} — {t['name']}" for t in teams)
    player_list = "\n".join(f"  {p['id']} — {p['full_name']} (team: {p['team_id']})" for p in players)

    user_msg = (
        f"Generate a scouting report for **{opponent}** from the perspective of **{our_team}**.\n"
        f"Period: **{period}**\n\n"
        f"Available teams in DB:\n{team_list}\n\n"
        f"Available players in DB:\n{player_list}\n\n"
        "Use the query_db tool to fetch all stats you need, then produce the full report."
    )

    messages = [{"role": "user", "content": user_msg}]

    print(f"\nGenerating scouting report: {our_team} vs {opponent} ({period})")
    print("─" * 60)

    tool_calls = 0
    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8096,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=TOOLS,
            messages=messages,
        )

        # Accumulate assistant content
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use" and block.name == "query_db":
                    tool_calls += 1
                    sql = block.input.get("sql", "")
                    result = run_query(conn, sql)
                    print(f"  [{tool_calls}] {sql[:80].replace(chr(10), ' ')}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})

        elif response.stop_reason == "end_turn":
            break
        else:
            break

    conn.close()

    # Extract final text
    report = ""
    for block in response.content:
        if hasattr(block, "text"):
            report += block.text

    print(f"\n  Done — {tool_calls} DB queries made.")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--opponent", required=True, help="Opponent team name")
    parser.add_argument("--period", default="LAST_3",
                        choices=["LAST_1", "LAST_3", "LAST_5", "LAST_10", "SEASON", "ALL"])
    parser.add_argument("--team", default="Canada WNT", help="Our team name")
    parser.add_argument("--save", default=None, help="Save report to file (e.g. report.md)")
    args = parser.parse_args()

    report = generate_report(args.opponent, args.period, args.team)

    print("\n" + "═" * 60)
    print(report)

    if args.save:
        Path(args.save).write_text(report)
        print(f"\nSaved → {args.save}")


if __name__ == "__main__":
    main()
