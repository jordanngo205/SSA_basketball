#!/usr/bin/env python3
"""Generate SSA 3x3 Women's Basketball Analytics Dashboard (2025-2026 data)"""

import sqlite3, json, os, sys, base64
from html import escape

DB_PATH = os.path.join(os.path.dirname(__file__), 'data/db/ssa.db')
OUT_PATH = os.path.join(os.path.dirname(__file__), 'docs/index.html')

# Embed logo as base64 so the HTML is self-contained (no external file dependency)
_logo_path = os.path.join(os.path.dirname(__file__), 'Canada_Basketball_logo.svg.webp')
if os.path.exists(_logo_path):
    _logo_b64 = base64.b64encode(open(_logo_path, 'rb').read()).decode()
    LOGO_SRC = f'data:image/webp;base64,{_logo_b64}'
else:
    LOGO_SRC = 'Canada_Basketball_logo.svg.webp'

STAT_LABELS = [
    'GAMES_PLAYED','WIN_PERCENTAGE','POINTS','POINTS_ALLOWED',
    'POINTS_PER_POSSESSIONS','POINTS_ALLOWED_PER_POSSESSIONS',
    'SHOOTING_EFF','1PT%','2PT%','3PT%',
    '1PTM','1PTA','2PTM','2PTA','3PTM','3PTA',
    'TURNOVERS','OFFENSIVE_REBOUNDS','DEFENSIVE_REBOUNDS',
    'ASSISTS','BLOCKS','STEALS','FOULS','POSSESSIONS',
]

PLAYER_LABELS = [
    'GAMES_PLAYED','POINTS','POINTS_PER_POSSESSIONS','SHOOTING_EFF',
    '1PT%','2PT%','3PT%','1PTM','1PTA','2PTM','2PTA','3PTM','3PTA',
    'TURNOVERS','ASSISTS','BLOCKS','STEALS',
]

PT_DISPLAY = {
    'PICK_AND_ROLL':'Pick & Roll','SPOT_UP':'Spot Up','TRANSITION':'Transition',
    'ISOLATION':'Isolation','POST_UP':'Post Up','CUT':'Cut',
    'OFFENSIVE_REBOUND':'Off Rebound','HANDOFF':'Hand Off',
    'OFFSCREEN':'Off Screen','NO_PLAY_TYPES':'Other',
}


def q(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def extract_data(conn):
    # ── Identify women's teams & players ─────────────────────────────────────
    # All women's teams: sex='FEMALE' is now set for both WNT and women's clubs
    all_women_team_ids = set(r[0] for r in q(conn, "SELECT id FROM teams WHERE sex='FEMALE'"))
    wnt_team_ids       = set(r[0] for r in q(conn, "SELECT id FROM teams WHERE sex='FEMALE' AND competition_type='NATIONAL_TEAMS'"))
    women_clubs_team_ids = set(r[0] for r in q(conn, "SELECT id FROM teams WHERE sex='FEMALE' AND competition_type='CLUBS'"))

    # ── Women's player IDs ────────────────────────────────────────────────────
    # 1. Players with NATIONAL_TEAMS stats = confirmed women (all WNT players)
    # Women's players = all players on women's teams (sex='FEMALE')
    if all_women_team_ids:
        ph_wt2 = ','.join('?' * len(all_women_team_ids))
        women_player_ids_all = set(r[0] for r in q(conn,
            f"SELECT DISTINCT id FROM players WHERE team_id IN ({ph_wt2})",
            list(all_women_team_ids)
        ))
    else:
        women_player_ids_all = set()

    print(f"  Women's WNT teams: {len(wnt_team_ids)}, Women's clubs teams: {len(women_clubs_team_ids)}")
    print(f"  Total women's players: {len(women_player_ids_all)}")

    # ── Teams ────────────────────────────────────────────────────────────────
    teams = {}
    ph = ','.join('?' * len(STAT_LABELS))
    if all_women_team_ids:
        ph_wt = ','.join('?' * len(all_women_team_ids))
        for period in ['SEASON', 'LAST_5', 'LAST_3', 'LAST_1']:
            rows = q(conn, f'''
                SELECT t.id, t.name, t.competition_type, ts.stat_label, ts.per_game, ts.total
                FROM teams t JOIN team_stats ts ON ts.team_id=t.id
                WHERE ts.period=? AND ts.stat_label IN ({ph})
                  AND t.id IN ({ph_wt})
            ''', [period] + STAT_LABELS + list(all_women_team_ids))
            for r in rows:
                tid = r['id']
                if tid not in teams:
                    teams[tid] = {
                        'id': tid,
                        'name': r['name'].strip(),
                        'competition_type': r['competition_type'],
                        'stats': {p: {} for p in ['SEASON', 'LAST_5', 'LAST_3', 'LAST_1']},
                    }
                teams[tid]['stats'][period][r['stat_label']] = {
                    'pg': round(r['per_game'], 4) if r['per_game'] is not None else None,
                    'tot': round(r['total'], 1) if r['total'] is not None else None,
                }

    teams_list = [
        t for t in teams.values()
        if (t['stats']['SEASON'].get('GAMES_PLAYED') or {}).get('pg', 0) >= 1
    ]

    # ── Team play types (offense detail) ─────────────────────────────────────
    play_types = {}
    if all_women_team_ids:
        ph_wt = ','.join('?' * len(all_women_team_ids))
        for r in q(conn,
                f"SELECT * FROM team_play_types_detail WHERE period='SEASON' AND team_id IN ({ph_wt})",
                list(all_women_team_ids)):
            tid = r['team_id']
            if tid not in play_types:
                play_types[tid] = {'offense': []}
            play_types[tid]['offense'].append({
                'label': r['play_type'],
                'poss': round(r['poss'], 1),
                'ppp': round(r['ppp'], 3),
                'usage': round(r['usage'], 1),
                '2pt_pct': round(r['two_pt_pct'], 1) if r['two_pt_pct'] else 0,
                '3pt_pct': round(r['three_pt_pct'], 1) if r['three_pt_pct'] else 0,
            })
        for r in q(conn,
                f"SELECT * FROM team_play_types WHERE period='SEASON' AND team_id IN ({ph_wt})",
                list(all_women_team_ids)):
            tid = r['team_id']
            if tid not in play_types:
                play_types[tid] = {'offense': []}
            key = f"{r['side']}_hl"
            if key not in play_types[tid]:
                play_types[tid][key] = []
            play_types[tid][key].append({
                'label': r['label'],
                'poss': round(r['possession'], 1),
                'points': round(r['points'], 1),
                'ppp': round(r['ppp'], 3),
                'pct': round(r['pct'], 1),
            })

    # ── Players (women only, matched by team_id) ──────────────────────────────
    players = {}
    ph2 = ','.join('?' * len(PLAYER_LABELS))
    if women_player_ids_all:
        ph_wp = ','.join('?' * len(women_player_ids_all))
        rows = q(conn, f'''
            SELECT p.id, p.team_id, p.full_name, p.position, p.height,
                   t.name as team_name, t.competition_type as team_ct,
                   ps.stat_label, ps.per_game, ps.total, ps.competition_type as stat_ct
            FROM players p
            JOIN teams t ON t.id = p.team_id
            JOIN player_stats ps ON ps.player_id = p.id
            WHERE ps.period = 'SEASON'
              AND ps.stat_label IN ({ph2})
              AND p.id IN ({ph_wp})
        ''', PLAYER_LABELS + list(women_player_ids_all))

        for r in rows:
            key = (r['id'], r['stat_ct'])
            if key not in players:
                players[key] = {
                    'id': r['id'],
                    'team_id': r['team_id'],
                    'name': r['full_name'],
                    'pos': (r['position'] or '').replace('CENTER', 'C').replace('FORWARD', 'F').replace('GUARD', 'G'),
                    'ht': r['height'],
                    'team': r['team_name'].strip(),
                    'team_ct': r['team_ct'],
                    'ct': r['stat_ct'],
                    'stats': {},
                }
            players[key]['stats'][r['stat_label']] = {
                'pg': round(r['per_game'], 4) if r['per_game'] is not None else None,
                'tot': round(r['total'], 1) if r['total'] is not None else None,
            }

    players_list = [
        p for p in players.values()
        if (p['stats'].get('GAMES_PLAYED') or {}).get('pg', 0) >= 1
    ]

    # ── Recent matches (with actual scores) ───────────────────────────────────
    matches_raw = q(conn, """
        SELECT m.id, m.match_date, m.season_name,
               m.home_team_id, m.home_team_name, m.home_score,
               m.away_team_id, m.away_team_name, m.away_score,
               ht.competition_type as h_ct
        FROM matches m
        JOIN teams ht ON ht.id = m.home_team_id
        JOIN teams at ON at.id = m.away_team_id
        WHERE (COALESCE(m.home_score,0) + COALESCE(m.away_score,0)) > 0
          AND ht.sex='FEMALE' AND at.sex='FEMALE'
        ORDER BY m.match_date DESC
        LIMIT 300
    """)
    matches_list = [{
        'id': r['id'],
        'date': r['match_date'],
        'season': r['season_name'] or '',
        'ct': r['h_ct'] or '',
        'htid': r['home_team_id'],
        'ht':   (r['home_team_name'] or '').strip(),
        'hs':   r['home_score'],
        'atid': r['away_team_id'],
        'at':   (r['away_team_name'] or '').strip(),
        'as':   r['away_score'],
    } for r in matches_raw]

    # ── Per-match team stats (scraped via matchIds API filter) ─────────────────
    # per_game = actual stat value for that specific game
    match_stats = {}
    for r in q(conn, "SELECT match_id, team_id, stat_label, per_game FROM match_team_stats"):
        if r['per_game'] is None:
            continue
        ms = match_stats.setdefault(r['match_id'], {})
        ms.setdefault(r['team_id'], {})[r['stat_label']] = round(r['per_game'], 4)

    # ── Per-match play types (high-level breakdown: Set Play, Open Play, etc.) ──
    match_play_types = {}
    for r in q(conn, """
        SELECT match_id, team_id, side, label, possession, points, ppp, pct
        FROM match_team_play_types
    """):
        mp = match_play_types.setdefault(r['match_id'], {})
        tp = mp.setdefault(r['team_id'], {})
        key = f"{r['side']}_hl"
        tp.setdefault(key, []).append({
            'label':  r['label'],
            'poss':   round(r['possession'] or 0, 1),
            'points': round(r['points'] or 0, 1),
            'ppp':    round(r['ppp'] or 0, 3),
            'pct':    round(r['pct'] or 0, 1),
        })

    # ── Per-match play type detail (PNR, ISO, Spot Up, etc.) ──────────────────
    for r in q(conn, """
        SELECT match_id, team_id, play_type, poss, ppp, usage,
               two_pt_pct, three_pt_pct, turnovers, assists
        FROM match_team_play_types_detail
    """):
        mp = match_play_types.setdefault(r['match_id'], {})
        tp = mp.setdefault(r['team_id'], {})
        tp.setdefault('offense', []).append({
            'label':   r['play_type'],
            'poss':    round(r['poss'] or 0, 1),
            'ppp':     round(r['ppp'] or 0, 3),
            'usage':   round(r['usage'] or 0, 1),
            '2pt_pct': round(r['two_pt_pct'] or 0, 1),
            '3pt_pct': round(r['three_pt_pct'] or 0, 1),
        })

    # ── Per-match player stats ─────────────────────────────────────────────────
    # match_player_stats: {match_id: {team_id: [{name, pos, stats:{...}}]}}
    PLAYER_MATCH_LABELS = [
        'POINTS', 'ASSISTS', 'TURNOVERS', 'OFFENSIVE_REBOUNDS', 'DEFENSIVE_REBOUNDS',
        'STEALS', 'BLOCKS', '2PTM', '2PTA', '1PTM', '1PTA', '3PTM', '3PTA',
        'POINTS_PER_POSSESSIONS', 'SHOOTING_EFF',
    ]
    ph_pm = ','.join('?' * len(PLAYER_MATCH_LABELS))
    match_player_stats = {}  # {match_id: {team_id: {player_id: {name, pos, stats}}}}
    # Get player names/positions for display
    player_meta = {r['id']: {'name': r['full_name'], 'pos': r['position'] or ''}
                   for r in q(conn, "SELECT id, full_name, position FROM players")}

    try:
        rows = q(conn, f"""
            SELECT mps.match_id, mps.team_id, mps.player_id, mps.stat_label, mps.per_game
            FROM match_player_stats mps
            JOIN players p ON p.id = mps.player_id AND p.team_id = mps.team_id
            WHERE mps.stat_label IN ({ph_pm})
        """, PLAYER_MATCH_LABELS)
        for r in rows:
            mp = match_player_stats.setdefault(r['match_id'], {})
            tp = mp.setdefault(r['team_id'], {})
            pid = r['player_id']
            if pid not in tp:
                meta = player_meta.get(pid, {})
                tp[pid] = {
                    'id':   pid,
                    'name': meta.get('name', pid[:8]),
                    'pos':  (meta.get('pos') or '').replace('CENTER','C').replace('FORWARD','F').replace('GUARD','G'),
                    'stats': {},
                }
            if r['per_game'] is not None:
                tp[pid]['stats'][r['stat_label']] = round(r['per_game'], 2)
    except Exception:
        pass  # table may not exist yet on first run

    return teams_list, players_list, play_types, matches_list, match_stats, match_play_types, match_player_stats


def build_html(teams, players, play_types, matches, match_stats, match_play_types, match_player_stats):
    data = json.dumps({
        'teams': teams,
        'players': players,
        'playTypes': play_types,
        'matches': matches,
        'ptDisplay': PT_DISPLAY,
        'matchStats': match_stats,
        'matchPlayTypes': match_play_types,
        'matchPlayerStats': match_player_stats,
    }, separators=(',', ':'))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SSA 3x3 Women's Series — Analytics Dashboard (2026–2027)</title>
<style>
/* ── Reset & Base ─────────────────────────────────────────────────────── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
:root {{
  --bg: #f0f2f5; --bg2: #ffffff; --bg3: #f5f6f8;
  --border: #e2e5ea; --border2: #c9cdd4;
  --text: #111827; --text2: #6b7280; --text3: #9ca3af;
  --blue: #1a56db; --green: #16a34a; --red: #dc2626;
  --yellow: #b45309; --orange: #c2410c; --purple: #7c3aed;
  --canada: #d52b1e; --canada-dark: #a81e13;
  --bar: #3b72c8;
  --radius: 6px;
  --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}}
html {{ background: var(--bg); color: var(--text); font-family: var(--font); font-size: 14px; }}
body {{ min-height: 100vh; }}

/* ── Layout ───────────────────────────────────────────────────────────── */
.app {{ display: flex; flex-direction: column; height: 100vh; overflow: hidden; }}
.topbar {{
  background: #111; border-bottom: 4px solid var(--canada);
  padding: 0 28px; display: flex; align-items: center; gap: 20px; flex-shrink: 0; height: 100px;
}}
.logo {{ font-weight: 700; font-size: 15px; color: #fff; letter-spacing: -.3px; white-space: nowrap;
  display: flex; align-items: center; gap: 18px; }}
.logo img {{ height: 64px; width: auto; }}
.logo-text {{ display: flex; flex-direction: column; line-height: 1.3; }}
.logo-text .logo-main {{ font-size: 26px; font-weight: 800; color: #fff; letter-spacing: -.4px; }}
.logo-text .logo-sub {{ font-size: 13px; color: rgba(255,255,255,.6); font-weight: 500; letter-spacing: .4px; }}
.logo-badge {{ font-size: 12px; font-weight: 700; background: var(--canada); color: #fff;
  padding: 4px 12px; border-radius: 4px; margin-left: 12px; letter-spacing: .3px; }}
.topstats {{ display: flex; gap: 24px; margin-left: auto; }}
.topstat {{ text-align: center; }}
.topstat-n {{ font-size: 18px; font-weight: 800; color: #fff; line-height: 1; }}
.topstat-l {{ font-size: 10px; color: rgba(255,255,255,.5); text-transform: uppercase; letter-spacing: .5px; }}

.nav {{ background: #fff; border-bottom: 1px solid var(--border);
  display: flex; overflow-x: auto; flex-shrink: 0; box-shadow: 0 1px 3px rgba(0,0,0,.06); }}
.nav-btn {{
  padding: 12px 18px; font-size: 13px; font-weight: 500; color: var(--text2);
  border: none; background: none; cursor: pointer; white-space: nowrap;
  border-bottom: 3px solid transparent; transition: all .15s; letter-spacing: .1px;
}}
.nav-btn:hover {{ color: var(--text); }}
.nav-btn.active {{ color: var(--canada); border-bottom-color: var(--canada); font-weight: 600; }}

.content {{ flex: 1; overflow-y: auto; padding: 20px; }}
.tab {{ display: none; }}
.tab.active {{ display: block; }}

/* ── Cards / Sections ─────────────────────────────────────────────────── */
.card {{
  background: #fff; border: 1px solid var(--border);
  border-radius: var(--radius); margin-bottom: 16px; overflow: hidden;
  box-shadow: 0 1px 4px rgba(0,0,0,.06);
}}
.card-hdr {{
  padding: 10px 16px; background: var(--bg3); border-bottom: 1px solid var(--border);
  border-left: 3px solid var(--canada);
  font-size: 11px; font-weight: 700; color: var(--text2);
  text-transform: uppercase; letter-spacing: .7px; display: flex; align-items: center; gap: 8px;
}}
.card-body {{ padding: 16px; }}

/* ── Grid ─────────────────────────────────────────────────────────────── */
.grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
.grid3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }}
.grid4 {{ display: grid; grid-template-columns: repeat(4,1fr); gap: 16px; }}
@media(max-width:900px) {{ .grid2,.grid3,.grid4 {{ grid-template-columns: 1fr; }} }}

/* ── Tables ───────────────────────────────────────────────────────────── */
.tbl-wrap {{ overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; }}
thead th {{
  background: #f5f6f8; color: var(--text2); font-weight: 700;
  padding: 8px 10px; text-align: right; white-space: nowrap;
  position: sticky; top: 0; z-index: 2; cursor: pointer; user-select: none;
  border-bottom: 2px solid var(--border); letter-spacing: .3px; font-size: 11px;
}}
thead th:first-child, thead th:nth-child(2) {{ text-align: left; }}
thead th.sorted {{ color: var(--canada); }}
thead th:hover {{ color: var(--text); }}
tbody tr {{ border-bottom: 1px solid var(--border); transition: background .1s; }}
tbody tr:hover {{ background: #fafafa; }}
tbody td {{ padding: 7px 10px; text-align: right; color: var(--text); }}
tbody td:first-child, tbody td:nth-child(2) {{ text-align: left; }}
.rank-cell {{ color: var(--text3); font-size: 11px; width: 30px; }}
.team-cell {{ font-weight: 600; }}
.player-cell {{ font-weight: 600; }}
.team-badge {{
  display: inline-block; font-size: 9px; font-weight: 700; padding: 1px 4px;
  border-radius: 3px; margin-left: 4px; vertical-align: middle;
}}
.badge-clubs {{ background: rgba(88,166,255,.15); color: var(--blue); }}
.badge-wnt {{ background: rgba(63,185,80,.15); color: var(--green); }}

/* Color scale cells */
.hot {{ color: #3fb950; font-weight: 600; }}
.warm {{ color: #7ce38b; }}
.cold {{ color: #f85149; font-weight: 600; }}
.cool {{ color: #ffa198; }}
.neutral {{ color: var(--text); }}

/* ── Filters / Controls ───────────────────────────────────────────────── */
.controls {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 14px; }}
.toggle-group {{ display: flex; border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.06); }}
.toggle-btn {{
  padding: 6px 16px; font-size: 12px; font-weight: 500; border: none;
  background: #fff; color: var(--text2); cursor: pointer; transition: all .15s;
}}
.toggle-btn.active {{ background: var(--canada); color: #fff; font-weight: 700; }}
.select-wrap select {{
  background: #fff; color: var(--text); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 6px 10px; font-size: 12px; cursor: pointer;
  box-shadow: 0 1px 3px rgba(0,0,0,.04);
}}
label.ctrl-label {{ font-size: 11px; color: var(--text2); }}
input[type=range] {{ accent-color: var(--canada); }}

/* ── Overview stat cards ─────────────────────────────────────────────── */
.stat-cards {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }}
.stat-card {{
  background: #fff; border: 1px solid var(--border); border-radius: var(--radius);
  border-top: 3px solid var(--canada);
  padding: 12px 16px; min-width: 130px; flex: 1;
  box-shadow: 0 1px 4px rgba(0,0,0,.06);
}}
.stat-card-n {{ font-size: 24px; font-weight: 700; color: var(--canada); line-height: 1.1; }}
.stat-card-l {{ font-size: 11px; color: var(--text2); margin-top: 2px; }}
.stat-card-sub {{ font-size: 10px; color: var(--text3); margin-top: 4px; }}

/* ── Player leader cards ─────────────────────────────────────────────── */
.leader-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px,1fr)); gap: 10px; }}
.lcard {{
  background: #fff; border: 1px solid var(--border); border-radius: var(--radius);
  padding: 12px; position: relative; box-shadow: 0 1px 3px rgba(0,0,0,.05);
}}
.lcard-rank {{ position: absolute; top: 8px; right: 10px; font-size: 16px; font-weight: 800;
  color: var(--border2); line-height: 1; }}
.lcard-rank.top3 {{ color: var(--canada); }}
.lcard-name {{ font-size: 13px; font-weight: 700; color: var(--text); line-height: 1.2; padding-right: 24px; }}
.lcard-team {{ font-size: 10px; color: var(--text2); margin-top: 2px; }}
.lcard-stat {{ font-size: 22px; font-weight: 800; color: var(--canada); margin-top: 6px; line-height: 1; }}
.lcard-stat-l {{ font-size: 10px; color: var(--text2); }}
.lcard-sub {{ font-size: 10px; color: var(--text3); margin-top: 4px; }}
.lcard-bar {{ height: 4px; border-radius: 2px; background: var(--border); margin-top: 8px; }}
.lcard-bar-fill {{ height: 100%; border-radius: 2px; background: linear-gradient(90deg,#f9a8b8,#d52b1e); transition: width .3s; }}

/* ── Competition-type label in card headers ──────────────────────────── */
.ct-tag {{ font-size: 10px; font-weight: 800; padding: 2px 7px; border-radius: 3px;
  letter-spacing: .6px; margin-left: 6px; vertical-align: middle; }}
.ct-tag-wnt  {{ background: rgba(63,185,80,.18); color: var(--green); }}
.ct-tag-club {{ background: rgba(88,166,255,.15); color: var(--blue); }}

/* ── Bar chart ───────────────────────────────────────────────────────── */
.hbar-row {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-size: 11px; }}
.hbar-label {{ width: 130px; text-align: right; color: var(--text2); overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; flex-shrink: 0; }}
.hbar-track {{ flex: 1; height: 16px; background: #f0f2f5; border-radius: 3px; overflow: hidden; }}
.hbar-fill {{ height: 100%; border-radius: 3px; display: flex; align-items: center; padding-left: 5px;
  font-size: 10px; font-weight: 600; color: #fff; white-space: nowrap; transition: width .3s; }}
.hbar-val {{ color: var(--text); width: 50px; text-align: right; flex-shrink: 0; }}

/* ── Trend table ─────────────────────────────────────────────────────── */
.trend-table {{ font-size: 12px; border-collapse: collapse; width: 100%; }}
.trend-table th, .trend-table td {{ padding: 7px 12px; border: 1px solid var(--border); text-align: right; }}
.trend-table th {{ background: #f5f6f8; color: var(--text2); font-size: 11px; font-weight: 700; }}
.trend-table td:first-child {{ text-align: left; color: var(--text2); font-size: 11px; }}
.arrow-up {{ color: var(--green); }}
.arrow-dn {{ color: var(--red); }}
.arrow-eq {{ color: var(--text3); }}

/* ── Matchup ─────────────────────────────────────────────────────────── */
.matchup-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }}
.matchup-row {{ display: flex; align-items: center; gap: 8px; padding: 6px 0;
  border-bottom: 1px solid var(--border); }}
.matchup-stat-label {{ flex: 0 0 150px; text-align: center; font-size: 11px; color: var(--text2);
  font-weight: 600; text-transform: uppercase; letter-spacing: .3px; }}
.matchup-bar-left {{ flex: 1; height: 20px; background: var(--bg3); border-radius: 3px 0 0 3px;
  display: flex; justify-content: flex-end; overflow: hidden; }}
.matchup-bar-right {{ flex: 1; height: 20px; background: var(--bg3); border-radius: 0 3px 3px 0;
  display: flex; overflow: hidden; }}
.matchup-fill-left {{ height: 100%; border-radius: 3px 0 0 3px; }}
.matchup-fill-right {{ height: 100%; border-radius: 0 3px 3px 0; }}
.matchup-val-left {{ font-size: 11px; font-weight: 600; padding: 0 6px; color: var(--text); white-space: nowrap; align-self: center; }}
.matchup-val-right {{ font-size: 11px; font-weight: 600; padding: 0 6px; color: var(--text); white-space: nowrap; align-self: center; }}
.matchup-team-hdr {{ display: flex; justify-content: space-between; margin-bottom: 12px; }}
.matchup-team-name {{ font-size: 16px; font-weight: 700; color: var(--text); }}

/* ── Selector ────────────────────────────────────────────────────────── */
.team-select-row {{ display: flex; gap: 12px; margin-bottom: 16px; align-items: center; flex-wrap: wrap; }}
.team-select-row select {{ flex: 1; min-width: 200px; }}

/* ── Play type bars ─────────────────────────────────────────────────── */
.pt-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
@media(max-width:700px) {{ .pt-grid {{ grid-template-columns: 1fr; }} }}

/* ── Section title ─────────────────────────────────────────────────── */
.section-title {{
  font-size: 11px; font-weight: 600; color: var(--text2); text-transform: uppercase;
  letter-spacing: .7px; margin-bottom: 10px; padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}}

/* ── Sub-tabs ──────────────────────────────────────────────────────── */
.subtabs {{ display: flex; gap: 4px; margin-bottom: 14px; flex-wrap: wrap; }}
.subtab-btn {{
  padding: 5px 12px; font-size: 12px; font-weight: 500; color: var(--text2);
  border: 1px solid var(--border); border-radius: 20px; background: var(--bg2); cursor: pointer;
  transition: all .15s;
}}
.subtab-btn.active {{ background: var(--canada); border-color: var(--canada); color: #fff; font-weight: 700; }}
.subtab {{ display: none; }}
.subtab.active {{ display: block; }}

/* ── Empty state ─────────────────────────────────────────────────────── */
.empty {{ text-align: center; padding: 40px; color: var(--text3); font-size: 13px; }}

/* ── Last Game Report ──────────────────────────────────────────────────── */
.lgr-score-banner {{
  display: grid; grid-template-columns: 1fr auto 1fr;
  align-items: center; padding: 24px 20px; margin-bottom: 16px;
  background: var(--bg3); border: 1px solid var(--border); border-radius: 8px;
  border-top: 3px solid var(--blue);
}}
.lgr-team {{ display: flex; flex-direction: column; }}
.lgr-team-a {{ align-items: flex-start; }}
.lgr-team-b {{ align-items: flex-end; }}
.lgr-team-name {{ font-size: 18px; font-weight: 800; }}
.lgr-team-sub {{ font-size: 11px; color: var(--text2); margin-top: 3px; }}
.lgr-score {{ font-size: 48px; font-weight: 900; color: var(--blue); line-height: 1; text-align: center; letter-spacing: -2px; }}
.lgr-score-sep {{ font-size: 28px; color: var(--text3); margin: 0 8px; }}
.lgr-winner-badge {{
  font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: .6px;
  background: var(--green); color: #000; padding: 2px 8px; border-radius: 3px; margin-top: 6px;
}}
.lgr-loser-badge {{
  font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: .6px;
  background: var(--bg4,#2d333b); color: var(--text3); padding: 2px 8px; border-radius: 3px; margin-top: 6px;
}}
.lgr-win-cell {{ color: #3fb950; }}
.lgr-lose-cell {{ color: #f85149; }}
.lgr-neutral-cell {{ color: var(--text2); }}
.lgr-narrative {{
  background: var(--bg3); border: 1px solid var(--border); border-radius: 8px;
  padding: 16px 20px; margin-bottom: 16px; line-height: 1.7;
}}
.lgr-narrative-title {{
  font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .7px;
  color: var(--text2); margin-bottom: 10px;
}}
.lgr-narrative p {{ font-size: 13px; color: var(--text); margin-bottom: 6px; }}
.lgr-narrative p:last-child {{ margin-bottom: 0; }}
.lgr-key {{ display: inline-block; font-weight: 700; }}
.lgr-grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }}
/* new layout helpers */
.lgr-split {{ display: grid; grid-template-columns: 1fr 1fr; }}
.lgr-panel {{ padding: 14px 16px; }}
.lgr-panel + .lgr-panel {{ border-left: 1px solid var(--border); }}
.lgr-panel-hdr {{ font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: .07em; color: var(--text3); margin-bottom: 10px; }}
.lgr-cmp-row {{ display: grid; grid-template-columns: 1fr 88px 1fr; align-items: center; padding: 6px 0; border-bottom: 1px solid rgba(48,54,61,.35); font-size: 12px; }}
.lgr-cmp-row:last-child {{ border-bottom: none; }}
.lgr-cmp-h {{ text-align: right; font-weight: 700; padding-right: 8px; }}
.lgr-cmp-a {{ text-align: left; font-weight: 700; padding-left: 8px; }}
.lgr-cmp-lbl {{ text-align: center; font-size: 9.5px; color: var(--text3); font-weight: 600; line-height: 1.25; }}
.lgr-pt-tbl {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
.lgr-pt-tbl td {{ padding: 5px 4px; border-bottom: 1px solid rgba(48,54,61,.3); vertical-align: middle; }}
.lgr-pt-tbl tr:last-child td {{ border-bottom: none; }}
.lgr-pt-tbl th {{ padding: 5px 4px; font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; color: var(--text3); border-bottom: 1px solid var(--border); }}
.lgr-bar-wrap {{ width: 60px; height: 6px; background: var(--bg3); border-radius: 3px; display: inline-block; }}
.lgr-bar-fill {{ height: 100%; border-radius: 3px; }}
.lgr-radar-card {{ display: grid; grid-template-columns: 300px 1fr; gap: 0; align-items: center; margin-bottom: 16px; background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }}
.lgr-radar-panel {{ padding: 16px; display: flex; flex-direction: column; align-items: center; border-right: 1px solid var(--border); }}
.lgr-legend {{ display: flex; gap: 16px; font-size: 11px; color: var(--text2); margin-top: 8px; }}
.lgr-edge-grid {{ display: grid; grid-template-columns: repeat(3,1fr); gap: 8px; padding: 16px; }}
.lgr-edge-pill {{ text-align: center; padding: 14px 8px; background: var(--bg3); border-radius: 6px; border: 1px solid var(--border); }}
.lgr-ctx-grid {{ display: grid; grid-template-columns: repeat(5,1fr); gap: 6px; }}
@media(max-width:800px) {{ .lgr-split,.lgr-radar-card {{ grid-template-columns: 1fr; }} .lgr-panel+.lgr-panel {{ border-left: none; border-top: 1px solid var(--border); }} .lgr-ctx-grid {{ grid-template-columns: repeat(3,1fr); }} }}

/* ── Scrollbar ───────────────────────────────────────────────────────── */
::-webkit-scrollbar {{ width: 6px; height: 6px; }}
::-webkit-scrollbar-track {{ background: var(--bg2); }}
::-webkit-scrollbar-thumb {{ background: var(--border2); border-radius: 3px; }}

/* ── Tooltip ─────────────────────────────────────────────────────────── */
[data-tip] {{ position: relative; cursor: help; }}
[data-tip]:hover::after {{
  content: attr(data-tip);
  position: absolute; bottom: 125%; left: 50%; transform: translateX(-50%);
  background: var(--bg3); border: 1px solid var(--border); color: var(--text);
  padding: 4px 8px; border-radius: 4px; font-size: 11px; white-space: nowrap;
  z-index: 100; pointer-events: none;
}}

.note {{ font-size: 11px; color: var(--text3); margin-top: 8px; }}
</style>
</head>
<body>
<div class="app">

<!-- Top bar -->
<div class="topbar">
  <div class="logo">
    <img src="{LOGO_SRC}" alt="Canada Basketball">
    <div class="logo-text">
      <span class="logo-main">Canada Basketball</span>
      <span class="logo-sub">3×3 Women's Series Analytics</span>
    </div>
    <span class="logo-badge">2026–27</span>
  </div>
  <div class="topstats" id="topstats"></div>
</div>

<!-- Nav tabs -->
<nav class="nav">
  <button class="nav-btn active" onclick="showTab('overview',this)">&#128200; Overview</button>
  <button class="nav-btn" onclick="showTab('rankings',this)">&#127942; Team Rankings</button>
  <button class="nav-btn" onclick="showTab('leaders',this)">&#128100; Player Leaders</button>
  <button class="nav-btn" onclick="showTab('matchup',this)">&#9876; Matchup Analyzer</button>
  <button class="nav-btn" onclick="showTab('intel',this)">&#129302; Team Intelligence</button>
  <button class="nav-btn" onclick="showTab('lastgame',this)">&#128203; Last Game Report</button>
</nav>

<!-- Content -->
<div class="content">

<!-- ╔══ TAB: OVERVIEW ════════════════════════════════════════════════════╗ -->
<div class="tab active" id="tab-overview">
  <div class="stat-cards" id="ov-cards"></div>
  <div class="grid2">
    <div class="card">
      <div class="card-hdr">&#127942; WNT Top Teams — Win % <span class="ct-tag ct-tag-wnt">WNT</span></div>
      <div class="card-body" id="ov-wnt-top"></div>
    </div>
    <div class="card">
      <div class="card-hdr">&#127942; Clubs Top Teams — Win % <span class="ct-tag ct-tag-club">CLUB</span></div>
      <div class="card-body" id="ov-clubs-top"></div>
    </div>
  </div>
  <div class="grid2">
    <div class="card">
      <div class="card-hdr">&#128293; Top Scorers <span class="ct-tag ct-tag-wnt">WNT</span></div>
      <div class="card-body" id="ov-scorers-wnt"></div>
    </div>
    <div class="card">
      <div class="card-hdr">&#128293; Top Scorers <span class="ct-tag ct-tag-club">CLUB</span></div>
      <div class="card-body" id="ov-scorers-clubs"></div>
    </div>
  </div>
  <div class="grid2">
    <div class="card">
      <div class="card-hdr">&#127919; Best Shooters — PPP <span class="ct-tag ct-tag-wnt">WNT</span></div>
      <div class="card-body" id="ov-ppp-wnt"></div>
    </div>
    <div class="card">
      <div class="card-hdr">&#127919; Best Shooters — PPP <span class="ct-tag ct-tag-club">CLUB</span></div>
      <div class="card-body" id="ov-ppp-clubs"></div>
    </div>
  </div>
  <div class="grid2">
    <div class="card">
      <div class="card-hdr">&#127936; Best Arc Shooters — 2PT% <span class="ct-tag ct-tag-wnt">WNT</span></div>
      <div class="card-body" id="ov-arc-wnt"></div>
    </div>
    <div class="card">
      <div class="card-hdr">&#127936; Best Arc Shooters — 2PT% <span class="ct-tag ct-tag-club">CLUB</span></div>
      <div class="card-body" id="ov-arc-clubs"></div>
    </div>
  </div>
  <div class="grid2">
    <div class="card">
      <div class="card-hdr">&#127775; Best Inside Shooters — 1PT% <span class="ct-tag ct-tag-wnt">WNT</span></div>
      <div class="card-body" id="ov-inside-wnt"></div>
    </div>
    <div class="card">
      <div class="card-hdr">&#127775; Best Inside Shooters — 1PT% <span class="ct-tag ct-tag-club">CLUB</span></div>
      <div class="card-body" id="ov-inside-clubs"></div>
    </div>
  </div>
  <div class="grid2">
    <div class="card">
      <div class="card-hdr">&#129309; Key Pass Leaders <span class="ct-tag ct-tag-wnt">WNT</span></div>
      <div class="card-body" id="ov-passes-wnt"></div>
    </div>
    <div class="card">
      <div class="card-hdr">&#129309; Key Pass Leaders <span class="ct-tag ct-tag-club">CLUB</span></div>
      <div class="card-body" id="ov-passes-clubs"></div>
    </div>
  </div>
  <p class="note">&#9432; SSA data covers 2026–2027 season only. 1PT% = inside-arc shots (1 pt each) | 2PT% = outside-arc shots (2 pts) | FT% = free throws. Key Passes = assists.</p>
</div>

<!-- ╔══ TAB: TEAM RANKINGS ═══════════════════════════════════════════════╗ -->
<div class="tab" id="tab-rankings">
  <div class="controls">
    <div class="toggle-group">
      <button class="toggle-btn" id="rank-ct-all" onclick="setRankCt('ALL',this)">Both</button>
      <button class="toggle-btn active" id="rank-ct-wnt" onclick="setRankCt('NATIONAL_TEAMS',this)">WNT</button>
      <button class="toggle-btn" id="rank-ct-clubs" onclick="setRankCt('CLUBS',this)">Clubs</button>
    </div>
    <div class="select-wrap">
      <label class="ctrl-label">Min GP: </label>
      <select id="rank-min-gp" onchange="renderRankings()">
        <option value="1">1+</option>
        <option value="3">3+</option>
        <option value="5" selected>5+</option>
        <option value="8">8+</option>
        <option value="10">10+</option>
      </select>
    </div>
  </div>
  <div class="card">
    <div class="card-hdr">Team Rankings <span id="rank-count" style="font-weight:400;color:var(--text3)"></span></div>
    <div class="tbl-wrap">
      <table id="rank-table">
        <thead>
          <tr>
            <th onclick="sortRank(0)">#</th>
            <th onclick="sortRank(1)" style="text-align:left">Team</th>
            <th onclick="sortRank(2)" data-tip="Games Played">GP</th>
            <th onclick="sortRank(3)" data-tip="Win Percentage">Win%</th>
            <th onclick="sortRank(4)" data-tip="Points per game">PTS</th>
            <th onclick="sortRank(5)" data-tip="Points Allowed per game">PA</th>
            <th onclick="sortRank(6)" data-tip="Points per Possession (offense)">PPP</th>
            <th onclick="sortRank(7)" data-tip="Points per Possession allowed (defense)">PPP-D</th>
            <th onclick="sortRank(8)" data-tip="Shooting Efficiency (all shots)">SE%</th>
            <th onclick="sortRank(9)" data-tip="Outside arc shot % (2 pts)">2PT%</th>
            <th onclick="sortRank(10)" data-tip="Inside arc shot % (1 pt)">1PT%</th>
            <th onclick="sortRank(11)" data-tip="Free throw % (3 pts)">FT%</th>
            <th onclick="sortRank(12)" data-tip="Turnovers per game">TO</th>
            <th onclick="sortRank(13)" data-tip="Offensive rebounds per game">OREB</th>
            <th onclick="sortRank(14)" data-tip="Defensive rebounds per game">DREB</th>
            <th onclick="sortRank(15)" data-tip="Blocks per game">BLK</th>
            <th onclick="sortRank(16)" data-tip="Steals per game">STL</th>
          </tr>
        </thead>
        <tbody id="rank-tbody"></tbody>
      </table>
    </div>
  </div>
</div>

<!-- ╔══ TAB: PLAYER LEADERS ══════════════════════════════════════════════╗ -->
<div class="tab" id="tab-leaders">
  <div class="controls">
    <div class="toggle-group">
      <button class="toggle-btn" onclick="setLeaderCt('ALL',this)">Both</button>
      <button class="toggle-btn active" onclick="setLeaderCt('NATIONAL_TEAMS',this)">WNT</button>
      <button class="toggle-btn" onclick="setLeaderCt('CLUBS',this)">Clubs</button>
    </div>
    <div class="select-wrap">
      <label class="ctrl-label">Min GP: </label>
      <select id="leader-min-gp" onchange="renderLeaders()">
        <option value="3">3+</option>
        <option value="5" selected>5+</option>
        <option value="8">8+</option>
        <option value="10">10+</option>
      </select>
    </div>
    <div class="select-wrap" id="leader-min-att-wrap" style="display:none">
      <label class="ctrl-label">Min Att: </label>
      <select id="leader-min-att" onchange="renderLeaders()">
        <option value="0">Any</option>
        <option value="3">3+</option>
        <option value="5" selected>5+</option>
        <option value="10">10+</option>
        <option value="20">20+</option>
      </select>
    </div>
  </div>
  <div class="subtabs">
    <button class="subtab-btn active" onclick="showSubtab('leaders','scoring',this)">&#128293; Scoring</button>
    <button class="subtab-btn" onclick="showSubtab('leaders','ppp',this)">&#127919; Efficiency (PPP)</button>
    <button class="subtab-btn" onclick="showSubtab('leaders','arc',this)">&#127936; Arc (2PT%)</button>
    <button class="subtab-btn" onclick="showSubtab('leaders','inside',this)">&#128247; Inside (1PT%)</button>
    <button class="subtab-btn" onclick="showSubtab('leaders','ft',this)">&#127775; Free Throw</button>
    <button class="subtab-btn" onclick="showSubtab('leaders','assist',this)">&#129309; Assists</button>
    <button class="subtab-btn" onclick="showSubtab('leaders','stocks',this)">&#128737; Stocks</button>
    <button class="subtab-btn" onclick="showSubtab('leaders','keypasses',this)">&#127919; Key Passes</button>
  </div>
  <div class="subtab active" id="leaders-scoring"><div class="leader-grid" id="lg-scoring"></div></div>
  <div class="subtab" id="leaders-ppp"><div class="leader-grid" id="lg-ppp"></div></div>
  <div class="subtab" id="leaders-arc"><div class="leader-grid" id="lg-arc"></div></div>
  <div class="subtab" id="leaders-inside"><div class="leader-grid" id="lg-inside"></div></div>
  <div class="subtab" id="leaders-ft"><div class="leader-grid" id="lg-ft"></div></div>
  <div class="subtab" id="leaders-assist"><div class="leader-grid" id="lg-assist"></div></div>
  <div class="subtab" id="leaders-stocks"><div class="leader-grid" id="lg-stocks"></div></div>
  <div class="subtab" id="leaders-keypasses"><div class="leader-grid" id="lg-keypasses"></div></div>
  <p class="note">&#9432; 1PT% = inside-arc shots (1 pt each) | 2PT% = outside-arc shots (2 pts) | FT% = free throws</p>
</div>

<!-- ╔══ TAB: MATCHUP ANALYZER ════════════════════════════════════════════╗ -->
<div class="tab" id="tab-matchup">
  <div class="team-select-row" style="margin-bottom:8px">
    <div class="toggle-group">
      <button class="toggle-btn active" id="mu-wnt-btn" onclick="setMuCt('NATIONAL_TEAMS',this)">WNT</button>
      <button class="toggle-btn" id="mu-clubs-btn" onclick="setMuCt('CLUBS',this)">Clubs</button>
    </div>
    <span style="font-size:11px;color:var(--text3);align-self:center">Both teams must be same competition</span>
  </div>
  <div class="team-select-row">
    <div class="select-wrap" style="flex:1">
      <select id="mu-team-a" onchange="renderMatchup()">
        <option value="">— Team A —</option>
      </select>
    </div>
    <div style="font-size:20px;font-weight:700;color:var(--text3);padding:0 4px">vs</div>
    <div class="select-wrap" style="flex:1">
      <select id="mu-team-b" onchange="renderMatchup()">
        <option value="">— Team B —</option>
      </select>
    </div>
  </div>
  <div id="mu-content"><div class="empty">Select two teams above to compare</div></div>
</div>

<!-- ╔══ TAB: TEAM INTELLIGENCE ═══════════════════════════════════════════╗ -->
<div class="tab" id="tab-intel">
  <div class="controls" style="margin-bottom:10px">
    <div class="toggle-group">
      <button class="toggle-btn active" onclick="setTiCt('ALL',this)">All</button>
      <button class="toggle-btn" onclick="setTiCt('NATIONAL_TEAMS',this)">WNT</button>
      <button class="toggle-btn" onclick="setTiCt('CLUBS',this)">Clubs</button>
    </div>
  </div>
  <div class="team-select-row" style="margin-bottom:12px">
    <div class="select-wrap" style="flex:1">
      <select id="ti-team" onchange="renderTeamIntel()">
        <option value="">— Select a team —</option>
      </select>
    </div>
  </div>
  <div id="ti-content"><div class="empty">Select a team above to see their intelligence report</div></div>
</div>

<!-- ╔══ TAB: LAST GAME REPORT ════════════════════════════════════════════╗ -->
<div class="tab" id="tab-lastgame">
  <div class="controls" style="margin-bottom:10px">
    <div class="toggle-group">
      <button class="toggle-btn active" onclick="setLgrCt('ALL',this)">All</button>
      <button class="toggle-btn" onclick="setLgrCt('NATIONAL_TEAMS',this)">2026 WNT</button>
      <button class="toggle-btn" onclick="setLgrCt('CLUBS',this)">2026 Club</button>
    </div>
  </div>
  <div class="team-select-row" style="margin-bottom:8px">
    <div class="select-wrap" style="flex:1">
      <select id="lgr-match" onchange="renderLastGame()">
        <option value="">— Select a match —</option>
      </select>
    </div>
  </div>
  <div id="lgr-content"><div class="empty">Select a match above to view the game report</div></div>
</div>

</div><!-- /content -->
</div><!-- /app -->

<script>
const DATA = {data};

// ── Helpers ────────────────────────────────────────────────────────────────
const pg = (stats, lbl) => lbl==='STOCKS' ? (stats?.['STEALS']?.pg??0)+(stats?.['BLOCKS']?.pg??0) : (stats?.[lbl]?.pg ?? 0);
const tot = (stats, lbl) => stats?.[lbl]?.tot ?? 0;
const f1 = v => v ? v.toFixed(1) : '—';
const f2 = v => v ? v.toFixed(2) : '—';
const fPct = v => v ? v.toFixed(1) + '%' : '—';
const fPPP = v => v ? v.toFixed(3) : '—';

function colorPPP(v) {{
  if (!v) return '';
  if (v >= 0.60) return 'hot'; if (v >= 0.52) return 'warm';
  if (v <= 0.35) return 'cold'; if (v <= 0.43) return 'cool';
  return 'neutral';
}}
function colorPct(v, hi=70, lo=45) {{
  if (!v) return '';
  if (v >= hi) return 'hot'; if (v >= (hi+lo)/2) return 'warm';
  if (v <= lo) return 'cold'; if (v <= (hi+lo)/2*0.85) return 'cool';
  return 'neutral';
}}
function colorWin(v) {{
  if (!v) return '';
  if (v >= 75) return 'hot'; if (v >= 55) return 'warm';
  if (v <= 30) return 'cold'; if (v <= 45) return 'cool';
  return 'neutral';
}}
function colorPPPD(v) {{ // lower is better for defense
  if (!v) return '';
  if (v <= 0.38) return 'hot'; if (v <= 0.46) return 'warm';
  if (v >= 0.58) return 'cold'; if (v >= 0.52) return 'cool';
  return 'neutral';
}}
function barColor(pct) {{
  const h = Math.round(pct * 1.2); // 0-120 hue
  return `hsl(${{h}},70%,50%)`;
}}

const PT_DISPLAY = DATA.ptDisplay;
const PT_COLORS = {{
  PICK_AND_ROLL:'#58a6ff', SPOT_UP:'#3fb950', TRANSITION:'#d29922',
  ISOLATION:'#f85149', POST_UP:'#bc8cff', CUT:'#ffa657',
  OFFENSIVE_REBOUND:'#79c0ff', HANDOFF:'#56d364', OFFSCREEN:'#ffa198',
  NO_PLAY_TYPES:'#6e7681',
}};

// ── State ─────────────────────────────────────────────────────────────────
let rankCt = 'NATIONAL_TEAMS', rankSortCol = 3, rankSortDir = -1;
let leaderCt = 'NATIONAL_TEAMS';
let muCt = 'NATIONAL_TEAMS';

// ── Tab navigation ─────────────────────────────────────────────────────────
function showTab(id, btn) {{
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + id).classList.add('active');
  btn.classList.add('active');
}}
function showSubtab(group, id, btn) {{
  document.querySelectorAll(`#leaders-scoring,#leaders-ppp,#leaders-arc,#leaders-inside,#leaders-ft,#leaders-assist,#leaders-stocks,#leaders-keypasses`)
    .forEach(t => t.classList.remove('active'));
  document.getElementById(`leaders-${{id}}`).classList.add('active');
  btn.closest('.subtabs').querySelectorAll('.subtab-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const shootingTabs = ['arc','inside','ft'];
  const wrap = document.getElementById('leader-min-att-wrap');
  if (wrap) wrap.style.display = shootingTabs.includes(id) ? '' : 'none';
  renderLeaders();
}}

// ── Overview ───────────────────────────────────────────────────────────────
function renderOverview() {{
  const teams = DATA.teams;
  const players = DATA.players;
  const wnt = teams.filter(t => t.competition_type === 'NATIONAL_TEAMS' && pg(t.stats.SEASON,'GAMES_PLAYED') >= 5);
  const clubs = teams.filter(t => t.competition_type === 'CLUBS' && pg(t.stats.SEASON,'GAMES_PLAYED') >= 5);
  const allPlayers = players.filter(p => pg(p.stats,'GAMES_PLAYED') >= 5);

  // Top stat cards
  const totalGP_wnt = wnt.reduce((s,t)=>s+pg(t.stats.SEASON,'GAMES_PLAYED'),0);
  const totalGP_clubs = clubs.reduce((s,t)=>s+pg(t.stats.SEASON,'GAMES_PLAYED'),0);
  const avgWin_wnt = wnt.length ? (wnt.reduce((s,t)=>s+pg(t.stats.SEASON,'WIN_PERCENTAGE'),0)/wnt.length) : 0;
  document.getElementById('ov-cards').innerHTML = [
    ['WNT Teams',   wnt.length,                  '5+ GP in database'],
    ['WNT Games',   Math.round(totalGP_wnt/2),   'Unique matches'],
    ['Players',     players.length,               'With 5+ games'],
    ['Club Teams',  clubs.length,                 '5+ GP in database'],
    ['Club Games',  Math.round(totalGP_clubs/2),  'Unique matches'],
  ].map(([l,n,s])=>`<div class="stat-card"><div class="stat-card-n">${{n}}</div><div class="stat-card-l">${{l}}</div><div class="stat-card-sub">${{s}}</div></div>`).join('');

  // Top stats in topbar
  document.getElementById('topstats').innerHTML = [
    ['Teams', teams.length],
    ['Players', players.length],
    ['WNT', wnt.length],
    ['Clubs', clubs.length],
  ].map(([l,n])=>`<div class="topstat"><div class="topstat-n">${{n}}</div><div class="topstat-l">${{l}}</div></div>`).join('');

  // WNT top
  const wntSorted = [...wnt].sort((a,b)=>pg(b.stats.SEASON,'WIN_PERCENTAGE')-pg(a.stats.SEASON,'WIN_PERCENTAGE')).slice(0,10);
  document.getElementById('ov-wnt-top').innerHTML = renderTopTeamBars(wntSorted, 'WIN_PERCENTAGE', 'Win%', v=>v.toFixed(0)+'%');

  // Clubs top
  const clubsSorted = [...clubs].sort((a,b)=>pg(b.stats.SEASON,'WIN_PERCENTAGE')-pg(a.stats.SEASON,'WIN_PERCENTAGE')).slice(0,10);
  document.getElementById('ov-clubs-top').innerHTML = renderTopTeamBars(clubsSorted, 'WIN_PERCENTAGE', 'Win%', v=>v.toFixed(0)+'%');

  const wntP  = allPlayers.filter(p=>p.ct==='NATIONAL_TEAMS');
  const clubP = allPlayers.filter(p=>p.ct==='CLUBS');
  const minGP5 = p => pg(p.stats,'GAMES_PLAYED') >= 5;

  const fill = (id, arr, key, lbl, fmt) =>
    document.getElementById(id).innerHTML = renderMiniLeaders([...arr].sort((a,b)=>pg(b.stats,key)-pg(a.stats,key)).slice(0,8), key, lbl, fmt);

  // Top scorers
  fill('ov-scorers-wnt',  wntP,  'POINTS', 'pts/g', v=>v.toFixed(1));
  fill('ov-scorers-clubs',clubP, 'POINTS', 'pts/g', v=>v.toFixed(1));

  // PPP
  fill('ov-ppp-wnt',  wntP.filter(minGP5),  'POINTS_PER_POSSESSIONS', 'PPP', v=>v.toFixed(3));
  fill('ov-ppp-clubs',clubP.filter(minGP5), 'POINTS_PER_POSSESSIONS', 'PPP', v=>v.toFixed(3));

  // Arc 2PT%
  fill('ov-arc-wnt',  wntP,  '3PT%', '2PT%', v=>v.toFixed(1)+'%');
  fill('ov-arc-clubs',clubP, '3PT%', '2PT%', v=>v.toFixed(1)+'%');

  // Inside 1PT%
  fill('ov-inside-wnt',  wntP,  '2PT%', '1PT%', v=>v.toFixed(1)+'%');
  fill('ov-inside-clubs',clubP, '2PT%', '1PT%', v=>v.toFixed(1)+'%');

  // Key Passes (Assists)
  fill('ov-passes-wnt',  wntP,  'ASSISTS', 'ast/g', v=>v.toFixed(2));
  fill('ov-passes-clubs',clubP, 'ASSISTS', 'ast/g', v=>v.toFixed(2));
}}

function renderTopTeamBars(teams, statLabel, label, fmt) {{
  const max = Math.max(...teams.map(t=>pg(t.stats.SEASON,statLabel)));
  return teams.map((t,i)=>{{
    const v = pg(t.stats.SEASON,statLabel);
    const pct = max ? (v/max*100) : 0;
    const gp = pg(t.stats.SEASON,'GAMES_PLAYED');
    const color = 'linear-gradient(90deg,#f9a8b8,#d52b1e)';
    return `<div class="hbar-row">
      <span class="hbar-label">${{i+1}}. ${{escape(t.name)}}</span>
      <div class="hbar-track"><div class="hbar-fill" style="width:${{pct}}%;background:${{color}}">
        ${{pct > 30 ? fmt(v) : ''}}
      </div></div>
      <span class="hbar-val">${{pct<=30?fmt(v):''}} <span style="color:var(--text3);font-size:10px">(${{gp}}G)</span></span>
    </div>`;
  }}).join('');
}}

function renderMiniLeaders(players, statLabel, label, fmt) {{
  return players.map((p,i)=>{{
    const v = pg(p.stats, statLabel);
    const gp = pg(p.stats, 'GAMES_PLAYED');
    const ctBadge = p.ct === 'NATIONAL_TEAMS' ? '<span class="team-badge badge-wnt">WNT</span>' : '<span class="team-badge badge-clubs">CLB</span>';
    return `<div class="hbar-row">
      <span class="hbar-label" style="width:160px;text-align:left"><b>${{i+1}}.</b> ${{escape(p.name)}} ${{ctBadge}}</span>
      <span style="color:var(--text2);font-size:10px;min-width:80px;flex-shrink:0">${{escape(p.team)}}</span>
      <span style="color:var(--bar);font-weight:700;min-width:50px;text-align:right">${{fmt(v)}}</span>
      <span style="color:var(--text3);font-size:10px;min-width:30px;text-align:right">${{gp.toFixed(0)}}G</span>
    </div>`;
  }}).join('');
}}

// ── Rankings ───────────────────────────────────────────────────────────────
function setRankCt(ct, btn) {{
  rankCt = ct;
  document.querySelectorAll('#rank-ct-all,#rank-ct-wnt,#rank-ct-clubs').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  renderRankings();
}}

function renderRankings() {{
  const minGP = parseInt(document.getElementById('rank-min-gp').value);
  let teams = DATA.teams.filter(t => pg(t.stats.SEASON,'GAMES_PLAYED') >= minGP);
  if (rankCt !== 'ALL') teams = teams.filter(t => t.competition_type === rankCt);

  const getVal = (t, col) => {{
    const s = t.stats.SEASON;
    switch(col) {{
      case 0: return 0;
      case 1: return t.name;
      case 2: return pg(s,'GAMES_PLAYED');
      case 3: return pg(s,'WIN_PERCENTAGE');
      case 4: return pg(s,'POINTS');
      case 5: return pg(s,'POINTS_ALLOWED');
      case 6: return pg(s,'POINTS_PER_POSSESSIONS');
      case 7: return pg(s,'POINTS_ALLOWED_PER_POSSESSIONS');
      case 8: return pg(s,'SHOOTING_EFF')*100;
      case 9: return pg(s,'3PT%');
      case 10: return pg(s,'2PT%');
      case 11: return pg(s,'1PT%');
      case 12: return pg(s,'TURNOVERS');
      case 13: return pg(s,'OFFENSIVE_REBOUNDS');
      case 14: return pg(s,'DEFENSIVE_REBOUNDS');
      case 15: return pg(s,'BLOCKS');
      case 16: return pg(s,'STEALS');
      default: return 0;
    }}
  }};

  // When showing both competitions, sort within each group separately
  let rows = [];
  if (rankCt === 'ALL') {{
    const wnt   = teams.filter(t=>t.competition_type==='NATIONAL_TEAMS');
    const clubs = teams.filter(t=>t.competition_type==='CLUBS');
    const sortFn = (a,b) => {{
      const av=getVal(a,rankSortCol), bv=getVal(b,rankSortCol);
      return typeof av==='string' ? rankSortDir*av.localeCompare(bv) : rankSortDir*(av-bv);
    }};
    wnt.sort(sortFn); clubs.sort(sortFn);
    rows = [
      {{ separator: true, label: `WNT — National Teams (${{wnt.length}})`, color:'var(--green)' }},
      ...wnt.map((t,i)=>(({{...t,_rank:i+1,_total:wnt.length}})),),
      {{ separator: true, label: `Clubs (${{clubs.length}})`, color:'var(--blue)' }},
      ...clubs.map((t,i)=>(({{...t,_rank:i+1,_total:clubs.length}})),),
    ];
  }} else {{
    teams.sort((a,b) => {{
      const av=getVal(a,rankSortCol), bv=getVal(b,rankSortCol);
      return typeof av==='string' ? rankSortDir*av.localeCompare(bv) : rankSortDir*(av-bv);
    }});
    rows = teams.map((t,i) => ({{...t,_rank:i+1,_total:teams.length}}));
  }}

  document.getElementById('rank-count').textContent = `— ${{teams.length}} teams`;
  document.querySelectorAll('#rank-table thead th').forEach((th,i)=>{{
    th.classList.toggle('sorted', i===rankSortCol);
    th.textContent = th.textContent.replace(/[▲▼]/g,'');
    if (i===rankSortCol) th.textContent += rankSortDir===1?' ▲':' ▼';
  }});

  const tbody = document.getElementById('rank-tbody');
  tbody.innerHTML = rows.map(row => {{
    if (row.separator) return `<tr style="background:var(--bg3)">
      <td colspan="17" style="text-align:left;font-size:11px;font-weight:700;color:${{row.color}};
           padding:7px 12px;letter-spacing:.5px;text-transform:uppercase;border-top:2px solid ${{row.color}}22">
        ${{row.label}}
      </td></tr>`;
    const t = row;
    const i = t._rank - 1;
    const s = t.stats.SEASON;
    const ct = t.competition_type;
    const badge = ct==='NATIONAL_TEAMS'
      ? '<span class="team-badge badge-wnt">WNT</span>'
      : '<span class="team-badge badge-clubs">CLB</span>';
    const win = pg(s,'WIN_PERCENTAGE');
    const ppp = pg(s,'POINTS_PER_POSSESSIONS');
    const pppd = pg(s,'POINTS_ALLOWED_PER_POSSESSIONS');
    const se = pg(s,'SHOOTING_EFF')*100;
    const two = pg(s,'3PT%');
    const one = pg(s,'2PT%');
    const ft = pg(s,'1PT%');
    return `<tr>
      <td class="rank-cell">${{i+1}}</td>
      <td class="team-cell">${{escape(t.name)}}${{badge}}</td>
      <td>${{pg(s,'GAMES_PLAYED').toFixed(0)}}</td>
      <td class="${{colorWin(win)}}">${{win.toFixed(0)}}%</td>
      <td>${{f1(pg(s,'POINTS'))}}</td>
      <td>${{f1(pg(s,'POINTS_ALLOWED'))}}</td>
      <td class="${{colorPPP(ppp)}}">${{fPPP(ppp)}}</td>
      <td class="${{colorPPPD(pppd)}}">${{fPPP(pppd)}}</td>
      <td class="${{colorPct(se,65,48)}}">${{se?se.toFixed(1)+'%':'—'}}</td>
      <td class="${{colorPct(two,65,40)}}">${{two?two.toFixed(1)+'%':'—'}}</td>
      <td class="${{colorPct(one,70,50)}}">${{one?one.toFixed(1)+'%':'—'}}</td>
      <td class="${{colorPct(ft,80,60)}}">${{ft?ft.toFixed(1)+'%':'—'}}</td>
      <td class="${{pg(s,'TURNOVERS')<=4?'hot':pg(s,'TURNOVERS')>=6?'cold':'neutral'}}">${{f1(pg(s,'TURNOVERS'))}}</td>
      <td>${{f1(pg(s,'OFFENSIVE_REBOUNDS'))}}</td>
      <td>${{f1(pg(s,'DEFENSIVE_REBOUNDS'))}}</td>
      <td>${{f1(pg(s,'BLOCKS'))}}</td>
      <td>${{f1(pg(s,'STEALS'))}}</td>
    </tr>`;
  }}).join('');
}}

function sortRank(col) {{
  if (rankSortCol === col) rankSortDir *= -1;
  else {{ rankSortCol = col; rankSortDir = col <= 1 ? 1 : -1; }}
  renderRankings();
}}

// ── Player Leaders ─────────────────────────────────────────────────────────
function setLeaderCt(ct, btn) {{
  leaderCt = ct;
  btn.closest('.toggle-group').querySelectorAll('.toggle-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  renderLeaders();
}}

function renderLeaders() {{
  const minGP  = parseInt(document.getElementById('leader-min-gp').value);
  const minAtt = parseInt(document.getElementById('leader-min-att').value);
  let players = DATA.players.filter(p=>pg(p.stats,'GAMES_PLAYED')>=minGP);
  if (leaderCt !== 'ALL') players = players.filter(p=>p.ct===leaderCt);

  if (leaderCt === 'ALL') {{
    renderLeaderGridDual('lg-scoring',   players,                                                          'POINTS',                 'pts/g',  v=>v.toFixed(1),     null, 12);
    renderLeaderGridDual('lg-ppp',       players.filter(p=>pg(p.stats,'GAMES_PLAYED')>=5),                'POINTS_PER_POSSESSIONS', 'PPP',    v=>v.toFixed(3),     null, 12);
    renderLeaderGridDual('lg-arc',       players.filter(p=>tot(p.stats,'3PTA')>=minAtt),                  '3PT%',                   '2PT%',   v=>v.toFixed(1)+'%', p=>tot(p.stats,'3PTM')+'/'+tot(p.stats,'3PTA'), 12);
    renderLeaderGridDual('lg-inside',    players.filter(p=>tot(p.stats,'2PTA')>=minAtt),                  '2PT%',                   '1PT%',   v=>v.toFixed(1)+'%', p=>tot(p.stats,'2PTM')+'/'+tot(p.stats,'2PTA'), 12);
    renderLeaderGridDual('lg-ft',        players.filter(p=>tot(p.stats,'1PTA')>=minAtt),                  '1PT%',                   'FT%',    v=>v.toFixed(1)+'%', p=>tot(p.stats,'1PTM')+'/'+tot(p.stats,'1PTA'), 12);
    renderLeaderGridDual('lg-assist',    players,                                                          'ASSISTS',                'ast/g',  v=>v.toFixed(2),     null, 12);
    renderLeaderGridDual('lg-stocks',    players,                                                          'STOCKS',                 'stk/g',  v=>v.toFixed(2),     p=>pg(p.stats,'STEALS').toFixed(1)+' STL + '+pg(p.stats,'BLOCKS').toFixed(1)+' BLK', 12);
    renderLeaderGridDual('lg-keypasses', players,                                                          'ASSISTS',                'ast/g',  v=>v.toFixed(2),     null, 12);
  }} else {{
    renderLeaderGrid('lg-scoring',   players,                                                              'POINTS',                 'pts/g',  v=>v.toFixed(1),     null, 15);
    renderLeaderGrid('lg-ppp',       players.filter(p=>pg(p.stats,'GAMES_PLAYED')>=5),                    'POINTS_PER_POSSESSIONS', 'PPP',    v=>v.toFixed(3),     null, 15);
    renderLeaderGrid('lg-arc',       players.filter(p=>tot(p.stats,'3PTA')>=minAtt),                      '3PT%',                   '2PT%',   v=>v.toFixed(1)+'%', p=>tot(p.stats,'3PTM')+'/'+tot(p.stats,'3PTA'), 15);
    renderLeaderGrid('lg-inside',    players.filter(p=>tot(p.stats,'2PTA')>=minAtt),                      '2PT%',                   '1PT%',   v=>v.toFixed(1)+'%', p=>tot(p.stats,'2PTM')+'/'+tot(p.stats,'2PTA'), 15);
    renderLeaderGrid('lg-ft',        players.filter(p=>tot(p.stats,'1PTA')>=minAtt),                      '1PT%',                   'FT%',    v=>v.toFixed(1)+'%', p=>tot(p.stats,'1PTM')+'/'+tot(p.stats,'1PTA'), 15);
    renderLeaderGrid('lg-assist',    players,                                                              'ASSISTS',                'ast/g',  v=>v.toFixed(2),     null, 15);
    renderLeaderGrid('lg-stocks',    players,                                                              'STOCKS',                 'stk/g',  v=>v.toFixed(2),     p=>pg(p.stats,'STEALS').toFixed(1)+' STL + '+pg(p.stats,'BLOCKS').toFixed(1)+' BLK', 15);
    renderLeaderGrid('lg-keypasses', players,                                                              'ASSISTS',                'ast/g',  v=>v.toFixed(2),     null, 15);
  }}
}}

function renderLeaderCards(players, statLabel, label, fmt, subFn, maxN) {{
  const sorted = [...players].sort((a,b)=>pg(b.stats,statLabel)-pg(a.stats,statLabel)).slice(0,maxN);
  const maxVal = sorted.length ? pg(sorted[0].stats,statLabel) : 1;
  if (!sorted.length) return '<div class="empty">No players match filters</div>';
  return sorted.map((p,i) => {{
    const v = pg(p.stats,statLabel);
    const gp = pg(p.stats,'GAMES_PLAYED');
    const barPct = maxVal ? Math.round(v/maxVal*100) : 0;
    const sub = subFn ? subFn(p) : `${{gp.toFixed(0)}}G · ${{p.pos}} · ${{p.ht?p.ht+'cm':'?'}}`;
    return `<div class="lcard">
      <div class="lcard-rank ${{i<3?'top3':''}}">${{i+1}}</div>
      <div class="lcard-name">${{escape(p.name)}}</div>
      <div class="lcard-team">${{escape(p.team)}}</div>
      <div class="lcard-stat">${{fmt(v)}}</div>
      <div class="lcard-stat-l">${{label}}</div>
      <div class="lcard-sub">${{sub}}</div>
      <div class="lcard-bar"><div class="lcard-bar-fill" style="width:${{barPct}}%"></div></div>
    </div>`;
  }}).join('');
}}

function renderLeaderGrid(containerId, players, statLabel, label, fmt, subFn, maxN) {{
  const el = document.getElementById(containerId);
  el.innerHTML = renderLeaderCards(players, statLabel, label, fmt, subFn, maxN);
}}

function renderLeaderGridDual(containerId, players, statLabel, label, fmt, subFn, maxN) {{
  const wnt   = players.filter(p=>p.ct==='NATIONAL_TEAMS');
  const clubs = players.filter(p=>p.ct==='CLUBS');
  const el = document.getElementById(containerId);
  el.innerHTML = `
    <div style="margin-bottom:10px;padding-bottom:6px;border-bottom:2px solid var(--canada);
         font-size:11px;font-weight:700;color:var(--canada);letter-spacing:.5px">
      &#127937; WNT — National Teams
    </div>
    <div class="leader-grid" style="margin-bottom:24px">${{renderLeaderCards(wnt,statLabel,label,fmt,subFn,maxN)}}</div>
    <div style="margin-bottom:10px;padding-bottom:6px;border-bottom:2px solid var(--bar);
         font-size:11px;font-weight:700;color:var(--bar);letter-spacing:.5px">
      &#127936; Clubs
    </div>
    <div class="leader-grid">${{renderLeaderCards(clubs,statLabel,label,fmt,subFn,maxN)}}</div>`;
}}

// ── Team Intelligence (merged with Deep Dive) ──────────────────────────────

// ── Matchup Analyzer ───────────────────────────────────────────────────────
function setMuCt(ct, btn) {{
  muCt = ct;
  document.querySelectorAll('#mu-wnt-btn,#mu-clubs-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  populateMUTeams();
  renderMatchup();
}}

function populateMUTeams() {{
  const teams = [...DATA.teams]
    .filter(t => pg(t.stats.SEASON,'GAMES_PLAYED')>=1 && t.competition_type===muCt)
    .sort((a,b) => a.name.localeCompare(b.name));
  ['mu-team-a','mu-team-b'].forEach(id => {{
    const sel = document.getElementById(id);
    const cur = sel.value;
    sel.innerHTML = '<option value="">— Select team —</option>' +
      teams.map(t=>`<option value="${{t.id}}" ${{t.id===cur?'selected':''}}>${{escape(t.name)}}</option>`).join('');
    // Reset if current selection no longer valid
    if (cur && !teams.find(t=>t.id===cur)) sel.value = '';
  }});
}}

function renderMatchup() {{
  const idA = document.getElementById('mu-team-a').value;
  const idB = document.getElementById('mu-team-b').value;
  const cont = document.getElementById('mu-content');
  if (!idA || !idB) {{ cont.innerHTML = '<div class="empty">Select two teams above to compare</div>'; return; }}

  const ta = DATA.teams.find(t=>t.id===idA);
  const tb = DATA.teams.find(t=>t.id===idB);
  if (!ta || !tb) return;

  const ROWS = [
    ['Win %','WIN_PERCENTAGE',v=>v.toFixed(0)+'%',false,'higher'],
    ['PTS/game','POINTS',v=>v.toFixed(1),false,'higher'],
    ['PA/game','POINTS_ALLOWED',v=>v.toFixed(1),false,'lower'],
    ['PPP (off)','POINTS_PER_POSSESSIONS',v=>v.toFixed(3),false,'higher'],
    ['PPP (def)','POINTS_ALLOWED_PER_POSSESSIONS',v=>v.toFixed(3),false,'lower'],
    ['Shooting Eff','SHOOTING_EFF',v=>(v*100).toFixed(1)+'%',false,'higher'],
    ['2PT% (arc)','3PT%',v=>v.toFixed(1)+'%',false,'higher'],
    ['1PT% (inside)','2PT%',v=>v.toFixed(1)+'%',false,'higher'],
    ['FT%','1PT%',v=>v.toFixed(1)+'%',false,'higher'],
    ['Turnovers','TURNOVERS',v=>v.toFixed(1),false,'lower'],
    ['Off Rebounds','OFFENSIVE_REBOUNDS',v=>v.toFixed(1),false,'higher'],
    ['Def Rebounds','DEFENSIVE_REBOUNDS',v=>v.toFixed(1),false,'higher'],
    ['Blocks','BLOCKS',v=>v.toFixed(1),false,'higher'],
    ['Steals','STEALS',v=>v.toFixed(1),false,'higher'],
    ['Fouls','FOULS',v=>v.toFixed(1),false,'lower'],
  ];

  const rows = ROWS.map(([label, stat, fmt, _, better]) => {{
    const va = pg(ta.stats.SEASON, stat);
    const vb = pg(tb.stats.SEASON, stat);
    if (!va && !vb) return null;
    const maxV = Math.max(va||0, vb||0);
    const pctA = maxV ? Math.round((va||0)/maxV*85) : 0;
    const pctB = maxV ? Math.round((vb||0)/maxV*85) : 0;
    const aWins = better==='higher' ? va>vb : va<vb;
    const bWins = better==='higher' ? vb>va : vb<va;
    const colorA = aWins ? '#3fb950' : bWins ? '#f85149' : '#58a6ff';
    const colorB = bWins ? '#3fb950' : aWins ? '#f85149' : '#58a6ff';
    return `<div class="matchup-row">
      <div style="flex:1;display:flex;align-items:center;justify-content:flex-end;gap:6px">
        <span class="matchup-val-left" style="color:${{colorA}};font-size:12px">${{va?fmt(va):'—'}}</span>
        <div class="matchup-bar-left" style="width:120px">
          <div class="matchup-fill-left" style="width:${{pctA}}%;background:${{colorA}}"></div>
        </div>
      </div>
      <div class="matchup-stat-label">${{label}}</div>
      <div style="flex:1;display:flex;align-items:center;gap:6px">
        <div class="matchup-bar-right" style="width:120px">
          <div class="matchup-fill-right" style="width:${{pctB}}%;background:${{colorB}}"></div>
        </div>
        <span class="matchup-val-right" style="color:${{colorB}};font-size:12px">${{vb?fmt(vb):'—'}}</span>
      </div>
    </div>`;
  }}).filter(Boolean).join('');

  const gpA = pg(ta.stats.SEASON,'GAMES_PLAYED');
  const gpB = pg(tb.stats.SEASON,'GAMES_PLAYED');
  const winA = pg(ta.stats.SEASON,'WIN_PERCENTAGE');
  const winB = pg(tb.stats.SEASON,'WIN_PERCENTAGE');

  cont.innerHTML = `
    <div class="card">
      <div class="matchup-team-hdr" style="padding:16px 20px;border-bottom:1px solid var(--border)">
        <div>
          <div class="matchup-team-name" style="color:#3fb950">${{escape(ta.name)}}</div>
          <div style="font-size:11px;color:var(--text2)">${{ta.competition_type==='NATIONAL_TEAMS'?'WNT':'Clubs'}} · ${{gpA.toFixed(0)}} GP · ${{winA.toFixed(0)}}% Win</div>
        </div>
        <div style="font-size:13px;color:var(--text3);font-weight:700">vs</div>
        <div style="text-align:right">
          <div class="matchup-team-name" style="color:#58a6ff">${{escape(tb.name)}}</div>
          <div style="font-size:11px;color:var(--text2)">${{tb.competition_type==='NATIONAL_TEAMS'?'WNT':'Clubs'}} · ${{gpB.toFixed(0)}} GP · ${{winB.toFixed(0)}}% Win</div>
        </div>
      </div>
      <div style="padding:12px 20px">${{rows}}</div>
    </div>`;
}}

// ── Helper: escape HTML ────────────────────────────────────────────────────
function escape(s) {{
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

// ── Team Intelligence ──────────────────────────────────────────────────────
let tiCt = 'ALL';
function setTiCt(ct, btn) {{
  tiCt = ct;
  btn.closest('.toggle-group').querySelectorAll('.toggle-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  populateTiTeams();
  renderTeamIntel();
}}

function populateTiTeams() {{
  const ct = tiCt;
  let teams = DATA.teams.filter(t => pg(t.stats.SEASON,'GAMES_PLAYED') >= 1);
  if (ct !== 'ALL') teams = teams.filter(t => t.competition_type === ct);
  teams.sort((a,b) => a.name.localeCompare(b.name));
  const sel = document.getElementById('ti-team');
  const cur = sel.value;
  sel.innerHTML = '<option value="">— Select a team —</option>' +
    teams.map(t => `<option value="${{t.id}}" ${{t.id===cur?'selected':''}}>${{escape(t.name)}} (${{t.competition_type==='NATIONAL_TEAMS'?'WNT':'Clubs'}})</option>`).join('');
}}

const TI_GROUPS = [
  {{ title:'&#127942; Results & Scoring', stats:[
    {{ label:'Win %',              key:'WIN_PERCENTAGE',                 better:'higher', fmt:v=>v.toFixed(0)+'%'        }},
    {{ label:'Points / game',      key:'POINTS',                         better:'higher', fmt:v=>v.toFixed(1)            }},
    {{ label:'Points Allowed / g', key:'POINTS_ALLOWED',                 better:'lower',  fmt:v=>v.toFixed(1)            }},
  ]}},
  {{ title:'&#127919; Shooting Efficiency', stats:[
    {{ label:'PPP (offense)',      key:'POINTS_PER_POSSESSIONS',         better:'higher', fmt:v=>v.toFixed(3)            }},
    {{ label:'PPP (defense)',      key:'POINTS_ALLOWED_PER_POSSESSIONS', better:'lower',  fmt:v=>v.toFixed(3)            }},
    {{ label:'Shooting Eff %',    key:'SHOOTING_EFF',                   better:'higher', fmt:v=>(v*100).toFixed(1)+'%' }},
  ]}},
  {{ title:'&#127936; Shot Types', stats:[
    {{ label:'2PT% (arc)',         key:'3PT%',   better:'higher', fmt:v=>v.toFixed(1)+'%' }},
    {{ label:'1PT% (inside)',     key:'2PT%',   better:'higher', fmt:v=>v.toFixed(1)+'%' }},
    {{ label:'Free Throw %',      key:'1PT%',   better:'higher', fmt:v=>v.toFixed(1)+'%' }},
    {{ label:'2PT attempts / g',  key:'3PTA',   better:'higher', fmt:v=>v.toFixed(1)     }},
    {{ label:'1PT attempts / g',  key:'2PTA',   better:'higher', fmt:v=>v.toFixed(1)     }},
  ]}},
  {{ title:'&#128737; Defense & Rebounding', stats:[
    {{ label:'Turnovers / game',   key:'TURNOVERS',           better:'lower',  fmt:v=>v.toFixed(1) }},
    {{ label:'Off Rebounds / g',   key:'OFFENSIVE_REBOUNDS',  better:'higher', fmt:v=>v.toFixed(1) }},
    {{ label:'Def Rebounds / g',   key:'DEFENSIVE_REBOUNDS',  better:'higher', fmt:v=>v.toFixed(1) }},
    {{ label:'Blocks / game',      key:'BLOCKS',              better:'higher', fmt:v=>v.toFixed(1) }},
    {{ label:'Steals / game',      key:'STEALS',              better:'higher', fmt:v=>v.toFixed(1) }},
  ]}},
];

function renderTeamIntel() {{
  const tid = document.getElementById('ti-team').value;
  const ct  = tiCt;
  const cont = document.getElementById('ti-content');
  if (!tid) {{ cont.innerHTML = '<div class="empty">Select a team above to see their intelligence report</div>'; return; }}

  const team = DATA.teams.find(t => t.id === tid);
  if (!team) return;

  // Peers = same competition type, min 3 GP
  const peers = DATA.teams.filter(t =>
    t.competition_type === team.competition_type &&
    pg(t.stats.SEASON,'GAMES_PLAYED') >= 3
  );

  // ── Per-stat analytics ──────────────────────────────────────────────────
  function calcStat(key, better, scale) {{
    const scl = scale || 1;
    const vals = peers
      .map(t => ({{ id:t.id, name:t.name, v: pg(t.stats.SEASON,key)*scl }}))
      .filter(x => x.v > 0);
    if (!vals.length) return null;
    const sorted = [...vals].sort((a,b) => better==='higher' ? b.v-a.v : a.v-b.v);
    const avg = vals.reduce((s,x)=>s+x.v,0) / vals.length;
    const teamV = pg(team.stats.SEASON,key)*scl;
    const rank = sorted.findIndex(x=>x.id===tid) + 1;
    if (!rank) return null;
    const pctile = Math.round((1 - (rank-1)/sorted.length)*100);
    return {{
      teamV, avg,
      leader: sorted[0],
      worst:  sorted[sorted.length-1],
      rank, total: sorted.length,
      pctile,
      min: Math.min(...vals.map(x=>x.v)),
      max: Math.max(...vals.map(x=>x.v)),
    }};
  }}

  // Flatten all stat defs and compute
  const allStats = TI_GROUPS.flatMap(g => g.stats);
  const computed = allStats.map(s => ({{ s, d: calcStat(s.key, s.better, s.scale) }})).filter(x=>x.d);
  const leaders  = computed.filter(x=>x.d.rank===1);

  // Sort by percentile for strengths / weaknesses
  const byPctile = [...computed].sort((a,b)=>b.d.pctile-a.d.pctile);
  const strengths  = byPctile.slice(0,5);
  const weaknesses = [...computed].sort((a,b)=>a.d.pctile-b.d.pctile).slice(0,5);

  // ── Leader badges ───────────────────────────────────────────────────────
  const badgeHtml = leaders.length ? `
    <div style="display:flex;flex-wrap:wrap;gap:10px;margin-bottom:18px">
      ${{leaders.map(x=>`
        <div style="background:rgba(210,153,34,.12);border:1px solid rgba(210,153,34,.5);
             border-radius:8px;padding:10px 16px;display:flex;align-items:center;gap:10px">
          <span style="font-size:20px">&#127942;</span>
          <div>
            <div style="font-size:10px;font-weight:700;color:var(--yellow);letter-spacing:.5px">#1 IN LEAGUE</div>
            <div style="font-size:14px;font-weight:700;color:var(--text)">${{x.s.label}}</div>
            <div style="font-size:11px;color:var(--text2)">${{x.s.fmt(x.d.teamV)}} &nbsp;&middot;&nbsp; ${{x.d.total}} teams</div>
          </div>
        </div>`).join('')}}
    </div>` : '';

  // ── Percentile overview bar list ────────────────────────────────────────
  const pctHtml = byPctile.map(x => {{
    const color = x.d.pctile>=80?'var(--green)':x.d.pctile>=55?'var(--blue)':x.d.pctile>=30?'var(--yellow)':'var(--red)';
    const isTop = x.d.rank===1;
    return `
      <div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border)">
        <span style="width:155px;font-size:11.5px;font-weight:600;color:var(--text);flex-shrink:0">${{x.s.label}}</span>
        <div style="flex:1;height:14px;background:var(--bg);border-radius:3px;overflow:hidden">
          <div style="width:${{x.d.pctile}}%;height:100%;background:${{color}};border-radius:3px;opacity:.85"></div>
        </div>
        <span style="width:38px;text-align:right;font-size:11px;font-weight:800;color:${{color}};flex-shrink:0">${{x.d.pctile}}th</span>
        <span style="width:46px;text-align:right;font-size:10px;color:var(--text3);flex-shrink:0">#${{x.d.rank}}/${{x.d.total}}</span>
        <span style="width:60px;text-align:right;font-size:12px;font-weight:700;color:${{isTop?'var(--yellow)':'var(--text2)'}};flex-shrink:0">
          ${{isTop?'&#127942;&nbsp;':''}}${{x.s.fmt(x.d.teamV)}}
        </span>
      </div>`;
  }}).join('');

  // ── Strengths & Weaknesses ──────────────────────────────────────────────
  function swRow(x, good) {{
    const color = good ? 'var(--green)' : 'var(--red)';
    return `
      <div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--border)">
        <div style="flex:1">
          <div style="font-size:12px;font-weight:700;color:var(--text)">${{x.s.label}}</div>
          <div style="font-size:10px;color:var(--text3)">#${{x.d.rank}} of ${{x.d.total}} teams &nbsp;&middot;&nbsp; ${{x.d.pctile}}th percentile</div>
        </div>
        <div style="text-align:right">
          <div style="font-size:18px;font-weight:800;color:${{color}}">${{x.s.fmt(x.d.teamV)}}</div>
          <div style="font-size:10px;color:var(--text3)">Avg: ${{x.s.fmt(x.d.avg)}}</div>
        </div>
      </div>`;
  }}

  const swHtml = `
    <div class="card" style="margin-bottom:12px">
      <div class="card-hdr">&#128170; Top Strengths</div>
      <div class="card-body" style="padding:4px 16px">${{strengths.map(x=>swRow(x,true)).join('')}}</div>
    </div>
    <div class="card">
      <div class="card-hdr">&#9888; Areas to Improve</div>
      <div class="card-body" style="padding:4px 16px">${{weaknesses.map(x=>swRow(x,false)).join('')}}</div>
    </div>`;

  // ── Stat comparison bars (grouped) ──────────────────────────────────────
  function statRow(s, d) {{
    if (!d || !d.teamV) return '';
    const isTop   = d.rank===1;
    const isBot   = d.rank===d.total;
    const diffAbs = d.teamV - d.avg;
    const isGood  = s.better==='higher' ? diffAbs>=0 : diffAbs<=0;
    const diffFmt = (diffAbs>=0?'+':'')+d.teamV.toFixed(2).replace(/\.?0+$/,'')+' vs '+d.avg.toFixed(2).replace(/\.?0+$/,'');
    const diffSimple = (diffAbs>=0?'+':'')+Math.abs(diffAbs).toFixed(s.key.includes('%')||s.scale?1:2)+(s.key.includes('%')||s.scale?'pp':'');

    // Bar: position of team value relative to [min..max] range padded 5%
    const pad = (d.max - d.min)*0.05 || 0.01;
    const lo = d.min - pad, hi = d.max + pad;
    const span = hi - lo;
    const teamPct  = Math.min(Math.max((d.teamV - lo)/span*100, 0), 100);
    const avgPct   = Math.min(Math.max((d.avg - lo)/span*100, 0), 100);
    const leaderPct= Math.min(Math.max((d.leader.v - lo)/span*100, 0), 100);
    const worstPct = Math.min(Math.max((d.worst.v - lo)/span*100, 0), 100);

    const teamColor  = isTop ? 'var(--yellow)' : isGood ? 'var(--green)' : 'var(--red)';
    const rankColor  = d.pctile>=75?'var(--green)':d.pctile>=50?'var(--blue)':d.pctile>=25?'var(--yellow)':'var(--red)';

    return `
      <div style="padding:14px 0;border-bottom:1px solid var(--border)">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap">
          <span style="font-size:13px;font-weight:700;color:var(--text);min-width:160px">${{s.label}}</span>
          <span style="font-size:20px;font-weight:800;color:${{teamColor}}">${{s.fmt(d.teamV)}}</span>
          ${{isTop ? '<span style="font-size:10px;font-weight:700;background:rgba(210,153,34,.2);color:var(--yellow);padding:2px 7px;border-radius:3px">&#127942; BEST IN LEAGUE</span>' : ''}}
          <span style="font-size:11px;color:${{isGood?'var(--green)':'var(--red)'}};font-weight:600">${{isGood?'&#9650;':'&#9660;'}} ${{diffSimple}} vs avg</span>
          <span style="margin-left:auto;font-size:11px;font-weight:700;color:${{rankColor}};background:rgba(0,0,0,.3);padding:2px 8px;border-radius:3px">#${{d.rank}} / ${{d.total}}</span>
        </div>

        <!-- Distribution bar -->
        <div style="position:relative;height:28px;margin:0 6px 4px">
          <!-- Background track -->
          <div style="position:absolute;inset:8px 0;background:var(--bg);border-radius:4px"></div>
          <!-- Colored fill from start to team position -->
          <div style="position:absolute;top:8px;bottom:8px;left:0;width:${{teamPct.toFixed(1)}}%;background:${{isGood?'rgba(63,185,80,.2)':'rgba(248,81,73,.2)'}};border-radius:4px 0 0 4px;transition:width .4s"></div>
          <!-- Worst marker -->
          <div style="position:absolute;top:4px;bottom:4px;left:${{worstPct.toFixed(1)}}%;width:1px;background:var(--red);opacity:.4"></div>
          <!-- Avg line -->
          <div style="position:absolute;top:2px;bottom:2px;left:${{avgPct.toFixed(1)}}%;width:2px;background:var(--text3);border-radius:1px"></div>
          <!-- Leader dot (only if not us) -->
          ${{!isTop ? `<div style="position:absolute;top:50%;left:${{leaderPct.toFixed(1)}}%;transform:translate(-50%,-50%);width:10px;height:10px;background:var(--yellow);border-radius:50%;border:2px solid var(--bg2)"></div>` : ''}}
          <!-- Team dot -->
          <div style="position:absolute;top:50%;left:${{teamPct.toFixed(1)}}%;transform:translate(-50%,-50%);width:22px;height:22px;background:${{teamColor}};border-radius:50%;border:3px solid var(--bg2);z-index:2;box-shadow:0 0 8px ${{teamColor}}44"></div>
        </div>

        <!-- Legend -->
        <div style="display:flex;font-size:10px;color:var(--text3);gap:16px;padding:0 6px;flex-wrap:wrap">
          <span>&#9646; Worst: ${{s.fmt(d.worst.v)}} (${{escape(d.worst.name)}})</span>
          <span style="color:var(--text3)">| Avg: ${{s.fmt(d.avg)}}</span>
          ${{!isTop ? `<span>&#11044; Leader: ${{s.fmt(d.leader.v)}} (${{escape(d.leader.name)}})</span>` : ''}}
          <span style="margin-left:auto">&#11044; = this team</span>
        </div>
      </div>`;
  }}

  let groupsHtml = '';
  for (const g of TI_GROUPS) {{
    const rowsHtml = g.stats.map(s => statRow(s, calcStat(s.key, s.better, s.scale))).join('');
    if (!rowsHtml.trim()) continue;
    groupsHtml += `
      <div class="card" style="margin-bottom:16px">
        <div class="card-hdr">${{g.title}}</div>
        <div class="card-body" style="padding:0 16px">${{rowsHtml}}</div>
      </div>`;
  }}

  const ctLabel = team.competition_type==='NATIONAL_TEAMS'?'WNT':'Clubs';
  const gp = pg(team.stats.SEASON,'GAMES_PLAYED');
  const winPct = pg(team.stats.SEASON,'WIN_PERCENTAGE');
  const deepDiveHtml = buildDeepDiveHtml(team, tid);

  cont.innerHTML = `
    <!-- Team header -->
    <div style="display:flex;align-items:center;gap:16px;margin-bottom:16px;padding:16px 20px;
         background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius)">
      <div>
        <div style="font-size:22px;font-weight:800;color:var(--text)">${{escape(team.name)}}</div>
        <div style="font-size:12px;color:var(--text2);margin-top:2px">${{ctLabel}} &nbsp;&middot;&nbsp; ${{gp.toFixed(0)}} games played &nbsp;&middot;&nbsp; ${{winPct.toFixed(0)}}% win rate</div>
      </div>
      <div style="margin-left:auto;text-align:right">
        <div style="font-size:11px;color:var(--text3)">Compared against</div>
        <div style="font-size:18px;font-weight:700;color:var(--blue)">${{peers.length}}</div>
        <div style="font-size:11px;color:var(--text3)">${{ctLabel}} teams (3+ GP)</div>
      </div>
    </div>

    ${{badgeHtml}}

    <div class="grid2" style="margin-bottom:16px">
      <div class="card">
        <div class="card-hdr">&#128202; Percentile Rankings vs ${{ctLabel}} League</div>
        <div class="card-body" style="padding:4px 16px">${{pctHtml}}</div>
      </div>
      <div>${{swHtml}}</div>
    </div>

    ${{groupsHtml}}

    <p class="note">&#9432; Distribution bar: &#9646; = worst in league &nbsp;|&nbsp; grey line = league average &nbsp;|&nbsp; &#11044; yellow = league leader &nbsp;|&nbsp; &#11044; colored = this team</p>

    <!-- ── Deep Dive Section ── -->
    <div style="border-top:2px solid var(--border);margin:24px 0 16px;padding-top:8px;
         font-size:11px;font-weight:700;color:var(--text3);letter-spacing:.8px">
      TEAM BREAKDOWN
    </div>
    ${{deepDiveHtml}}
  `;
}}

function buildDeepDiveHtml(team, tid) {{
  const s = team.stats;
  const PERIODS = ['SEASON','LAST_5','LAST_3','LAST_1'];
  const P_LABELS = {{SEASON:'Full Season',LAST_5:'Last 5',LAST_3:'Last 3',LAST_1:'Last 1'}};
  const TREND_STATS = [
    ['GAMES_PLAYED','GP',v=>v.toFixed(0),''],
    ['WIN_PERCENTAGE','Win%',v=>v.toFixed(0)+'%','colorWin'],
    ['POINTS','PTS/g',v=>v.toFixed(1),''],
    ['POINTS_ALLOWED','PA/g',v=>v.toFixed(1),''],
    ['POINTS_PER_POSSESSIONS','PPP',v=>v.toFixed(3),'colorPPP'],
    ['POINTS_ALLOWED_PER_POSSESSIONS','PPP-D',v=>v.toFixed(3),'colorPPPD'],
    ['SHOOTING_EFF','SE%',v=>(v*100).toFixed(1)+'%',''],
    ['3PT%','2PT%',v=>v.toFixed(1)+'%','colorArc'],
    ['2PT%','1PT%',v=>v.toFixed(1)+'%','colorInside'],
    ['1PT%','FT%',v=>v.toFixed(1)+'%',''],
    ['TURNOVERS','TO/g',v=>v.toFixed(1),'colorTO'],
    ['OFFENSIVE_REBOUNDS','OREB',v=>v.toFixed(1),''],
    ['DEFENSIVE_REBOUNDS','DREB',v=>v.toFixed(1),''],
    ['BLOCKS','BLK',v=>v.toFixed(1),''],
    ['STEALS','STL',v=>v.toFixed(1),''],
  ];

  function applyColor(fn, v) {{
    if (!fn) return '';
    if (fn==='colorWin') return colorWin(v);
    if (fn==='colorPPP') return colorPPP(v);
    if (fn==='colorPPPD') return colorPPPD(v);
    if (fn==='colorArc') return colorPct(v,65,40);
    if (fn==='colorInside') return colorPct(v,70,50);
    if (fn==='colorTO') return v<=4?'hot':v>=6?'cold':'neutral';
    return '';
  }}
  function arrow(cur, prev) {{
    if (!cur || !prev || Math.abs(cur-prev)<0.005) return '<span class="arrow-eq">—</span>';
    return cur>prev ? '<span class="arrow-up">▲</span>' : '<span class="arrow-dn">▼</span>';
  }}

  let trendHtml = `<table class="trend-table"><thead><tr><th>Stat</th>
    ${{PERIODS.map(p=>`<th>${{P_LABELS[p]}}</th>`).join('')}}
  </tr></thead><tbody>`;
  TREND_STATS.forEach(([lbl, name, fmt, colorFn]) => {{
    const vals = PERIODS.map(p => pg(s[p], lbl));
    trendHtml += `<tr><td>${{name}}</td>`;
    vals.forEach((v,i) => {{
      const cls = applyColor(colorFn, v);
      const arr = i>0 ? ' '+arrow(v, vals[i-1]) : '';
      trendHtml += `<td class="${{cls}}">${{v ? fmt(v) : '—'}}${{arr}}</td>`;
    }});
    trendHtml += '</tr>';
  }});
  trendHtml += '</tbody></table>';

  // Offensive play types
  const pt = DATA.playTypes[tid];
  let ptHtml = '<div class="empty">No play type data</div>';
  if (pt && pt.offense && pt.offense.length) {{
    const sorted = [...pt.offense].sort((a,b)=>b.usage-a.usage);
    ptHtml = `<div>` + sorted.map(p => {{
      const color = PT_COLORS[p.label] || '#58a6ff';
      const pppColor = colorPPP(p.ppp);
      return `<div style="margin-bottom:10px">
        <div style="display:flex;justify-content:space-between;margin-bottom:3px">
          <span style="font-size:12px;font-weight:600;color:${{color}}">${{PT_DISPLAY[p.label]||p.label}}</span>
          <span style="font-size:11px;color:var(--text2)">${{p.usage.toFixed(1)}}% usage &nbsp;|&nbsp; <span class="${{pppColor}}">${{p.ppp.toFixed(3)}} PPP</span> &nbsp;|&nbsp; ${{p.poss.toFixed(1)}} poss/g</span>
        </div>
        <div style="flex:1;height:12px;background:var(--bg);border-radius:3px;overflow:hidden">
          <div style="width:${{p.usage.toFixed(1)}}%;height:100%;background:${{color}};opacity:.7;border-radius:3px"></div>
        </div>
      </div>`;
    }}).join('') + '</div>';
  }}

  // Defensive breakdown — with usage bars
  let defHtml = '<div class="empty">No defensive data</div>';
  if (pt && pt.defense_hl) {{
    defHtml = `<div>` + pt.defense_hl.map(d => {{
      const pppCls = colorPPPD(d.ppp);
      // Bar color: green = good defense (low PPP), red = bad (high PPP)
      const barColor = d.ppp < 0.45 ? 'var(--green)' : d.ppp < 0.55 ? 'var(--yellow)' : 'var(--red)';
      const barW = d.pct.toFixed(1);
      return `<div style="margin-bottom:10px">
        <div style="display:flex;justify-content:space-between;margin-bottom:3px">
          <span style="font-size:12px;font-weight:600;color:var(--text)">${{d.label.replace(/_/g,' ')}}</span>
          <span style="font-size:11px;color:var(--text2)">${{d.pct.toFixed(1)}}% of poss &nbsp;|&nbsp; <span class="${{pppCls}}">${{d.ppp.toFixed(3)}} PPP allowed</span></span>
        </div>
        <div style="flex:1;height:12px;background:var(--bg);border-radius:3px;overflow:hidden">
          <div style="width:${{barW}}%;height:100%;background:${{barColor}};opacity:.7;border-radius:3px"></div>
        </div>
      </div>`;
    }}).join('') + '</div>';
  }}

  // Roster table
  const teamPlayers = DATA.players.filter(p=>
    p.team_id === team.id && p.ct === team.competition_type
  ).sort((a,b)=>pg(b.stats,'POINTS')-pg(a.stats,'POINTS'));

  let rosterHtml = '<div class="empty">No player data</div>';
  if (teamPlayers.length) {{
    rosterHtml = `<div class="tbl-wrap"><table>
      <thead><tr>
        <th style="text-align:left">Player</th><th>Pos</th><th>GP</th><th>PTS</th>
        <th>PPP</th><th>SE%</th><th>2PT%</th><th>1PT%</th><th>FT%</th><th>TO</th>
      </tr></thead><tbody>` +
      teamPlayers.map(p=>{{
        const ps = p.stats;
        return `<tr>
          <td class="player-cell" style="text-align:left">${{escape(p.name)}}</td>
          <td style="text-align:center">${{p.pos}}</td>
          <td>${{pg(ps,'GAMES_PLAYED').toFixed(0)}}</td>
          <td class="${{pg(ps,'POINTS')>=6?'hot':pg(ps,'POINTS')>=4?'warm':''}}">${{f1(pg(ps,'POINTS'))}}</td>
          <td class="${{colorPPP(pg(ps,'POINTS_PER_POSSESSIONS'))}}">${{fPPP(pg(ps,'POINTS_PER_POSSESSIONS'))}}</td>
          <td>${{pg(ps,'SHOOTING_EFF')?(pg(ps,'SHOOTING_EFF')*100).toFixed(1)+'%':'—'}}</td>
          <td class="${{colorPct(pg(ps,'3PT%'),65,40)}}">${{pg(ps,'3PT%')?pg(ps,'3PT%').toFixed(1)+'%':'—'}}</td>
          <td class="${{colorPct(pg(ps,'2PT%'),70,50)}}">${{pg(ps,'2PT%')?pg(ps,'2PT%').toFixed(1)+'%':'—'}}</td>
          <td>${{pg(ps,'1PT%')?pg(ps,'1PT%').toFixed(1)+'%':'—'}}</td>
          <td>${{f1(pg(ps,'TURNOVERS'))}}</td>
        </tr>`;
      }}).join('') + '</tbody></table></div>';
  }}

  return `
    <div class="card" style="margin-bottom:16px">
      <div class="card-hdr">${{escape(team.name)}} — Period Trends (${{team.competition_type==='NATIONAL_TEAMS'?'WNT':'Clubs'}})</div>
      <div class="tbl-wrap">${{trendHtml}}</div>
    </div>
    <div class="grid2" style="margin-bottom:16px">
      <div class="card">
        <div class="card-hdr">&#127939; Offensive Play Types</div>
        <div class="card-body">${{ptHtml}}</div>
      </div>
      <div class="card">
        <div class="card-hdr">&#128737; Defensive Breakdown</div>
        <div class="card-body">${{defHtml}}</div>
      </div>
    </div>
    <div class="card">
      <div class="card-hdr">&#128100; Roster Stats — Season</div>
      ${{rosterHtml}}
    </div>`;
}}

// ── Last Game Report ───────────────────────────────────────────────────────
let lgrCt = 'ALL';
function setLgrCt(ct, btn) {{
  lgrCt = ct;
  btn.closest('.toggle-group').querySelectorAll('.toggle-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  populateLgrMatches();
}}

function populateLgrMatches() {{
  const sel = document.getElementById('lgr-match');
  let ms = DATA.matches;
  if (lgrCt !== 'ALL') ms = ms.filter(m => m.ct === lgrCt);
  // Group by date descending
  const byDate = {{}};
  ms.forEach(m => {{ (byDate[m.date] = byDate[m.date] || []).push(m); }});
  const dates = Object.keys(byDate).sort().reverse();
  let opts = '<option value="">— Select a match —</option>';
  dates.forEach(d => {{
    opts += `<optgroup label="${{d}}">`;
    byDate[d].forEach(m => {{
      const win = m.hs > m.as ? m.ht : m.at;
      opts += `<option value="${{m.id}}">${{escape(m.ht)}} ${{m.hs}} – ${{m.as}} ${{escape(m.at)}}</option>`;
    }});
    opts += '</optgroup>';
  }});
  sel.innerHTML = opts;
  document.getElementById('lgr-content').innerHTML = '<div class="empty">Select a match above to view the game report</div>';
}}

// ── Radar chart builder ─────────────────────────────────────────────────────

function renderLastGame() {{
  const mid = document.getElementById('lgr-match').value;
  const el = document.getElementById('lgr-content');
  if (!mid) {{ el.innerHTML = '<div class="empty">Select a match above</div>'; return; }}

  const match = DATA.matches.find(m => m.id === mid);
  if (!match) return;

  const winner = match.hs > match.as ? 'home' : match.as > match.hs ? 'away' : 'tie';
  const htName = match.ht, atName = match.at;
  const htScore = match.hs, atScore = match.as;
  const htWon = winner==='home', atWon = winner==='away';
  const wName = htWon?htName:atName, lName = htWon?atName:htName;
  const wScore = htWon?htScore:atScore, lScore = htWon?atScore:htScore;
  const margin = Math.abs(htScore-atScore);
  const domStr = margin>=10?'dominant':margin>=6?'comfortable':margin>=3?'solid':'narrow';

  const findTeam = (tid, name) => DATA.teams.find(t=>t.id===tid) ||
    DATA.teams.find(t=>t.name.toLowerCase()===name.toLowerCase());
  const tH = findTeam(match.htid, htName);
  const tA = findTeam(match.atid, atName);

  // ── Score Banner ──────────────────────────────────────────────────────────
  const hCol = htWon?'#3fb950':'#8b949e';
  const aCol = atWon?'#3fb950':'#8b949e';
  const bannerHtml =
    '<div class="lgr-score-banner">'+
      '<div class="lgr-team lgr-team-a">'+
        '<div class="lgr-team-name" style="color:'+hCol+'">'+escape(htName)+'</div>'+
        '<div class="lgr-team-sub">'+(tH?(tH.competition_type==='NATIONAL_TEAMS'?'WNT':'Clubs')+' · '+Math.round(pg(tH.stats.SEASON,'GAMES_PLAYED'))+' GP':'Home')+'</div>'+
        '<div class="'+(htWon?'lgr-winner-badge':'lgr-loser-badge')+'">'+(htWon?'&#127942; Winner':winner==='tie'?'TIE':'LOSS')+'</div>'+
      '</div>'+
      '<div style="text-align:center">'+
        '<div class="lgr-score"><span style="color:'+hCol+'">'+htScore+'</span><span class="lgr-score-sep">–</span><span style="color:'+aCol+'">'+atScore+'</span></div>'+
        '<div style="font-size:10px;color:var(--text3);margin-top:6px">'+match.date+' · '+escape(match.season)+'</div>'+
        '<div style="font-size:11px;font-weight:700;color:var(--yellow);margin-top:4px">Margin: '+margin+' pts</div>'+
      '</div>'+
      '<div class="lgr-team lgr-team-b">'+
        '<div class="lgr-team-name" style="color:'+aCol+'">'+escape(atName)+'</div>'+
        '<div class="lgr-team-sub">'+(tA?(tA.competition_type==='NATIONAL_TEAMS'?'WNT':'Clubs')+' · '+Math.round(pg(tA.stats.SEASON,'GAMES_PLAYED'))+' GP':'Away')+'</div>'+
        '<div class="'+(atWon?'lgr-winner-badge':'lgr-loser-badge')+'">'+(atWon?'&#127942; Winner':winner==='tie'?'TIE':'LOSS')+'</div>'+
      '</div>'+
    '</div>';

  if (!tH || !tA) {{
    const missing = [!tH?htName:null,!tA?atName:null].filter(Boolean);
    el.innerHTML = bannerHtml+'<div class="empty">Stats not yet scraped for: '+missing.map(escape).join(', ')+'</div>';
    return;
  }}

  // ── Stats setup ───────────────────────────────────────────────────────────
  const sHS = tH.stats.SEASON||{{}}, sAS = tA.stats.SEASON||{{}};
  const matchData = (DATA.matchStats||{{}})[mid]||{{}};
  const msH = matchData[match.htid]||{{}}, msA = matchData[match.atid]||{{}};
  const hasMatchStats = Object.keys(msH).length>0 && Object.keys(msA).length>0;
  // Wrap flat per_game values into {{pg:v}} so cmpRow's pg() helper works unchanged
  const toS = flat => Object.fromEntries(Object.entries(flat).map(([k,v])=>[k,{{pg:v}}]));
  const sH = hasMatchStats ? toS(msH) : sHS;
  const sA = hasMatchStats ? toS(msA) : sAS;
  const dataLabel = hasMatchStats ? 'This match' : 'Season avg';

  const matchPT = (DATA.matchPlayTypes||{{}})[mid]||{{}};
  const ptH = matchPT[match.htid] || DATA.playTypes[tH.id];
  const ptA = matchPT[match.atid] || DATA.playTypes[tA.id];
  const PT_LBL = {{PICK_AND_ROLL:'Pick & Roll',SPOT_UP:'Spot Up',TRANSITION:'Transition',ISOLATION:'Isolation',POST_UP:'Post Up',CUT:'Cut',OFFENSIVE_REBOUND:'Off Reb',HANDOFF:'Handoff',OFFSCREEN:'Off Screen',NO_PLAY_TYPES:'Other'}};
  const DEF_LBL = {{TRANSITION:'Transition',SET_PLAY:'Set Play',OPEN_PLAY:'Open Play',CLEARED_BY_PASS:'Cleared (Pass)',CLEARED_BY_DRIBBLE:'Cleared (Dribble)'}};

  // ── Stat comparison helper ────────────────────────────────────────────────
  let offWH=0,offWA=0,offT=0, defWH=0,defWA=0,defT=0;
  const cmpRow = (lbl,key,fmt,better,bucket) => {{
    const vh=pg(sH,key), va=pg(sA,key);
    if (!vh&&!va) return '';
    const hBetter=better==='higher'?vh>va:vh<va;
    const aBetter=better==='higher'?va>vh:va<vh;
    if(bucket==='off'){{ if(hBetter)offWH++; else if(aBetter)offWA++; else offT++; }}
    else {{ if(hBetter)defWH++; else if(aBetter)defWA++; else defT++; }}
    const clH=hBetter?'lgr-win-cell':aBetter?'lgr-lose-cell':'lgr-neutral-cell';
    const clA=aBetter?'lgr-win-cell':hBetter?'lgr-lose-cell':'lgr-neutral-cell';
    return '<div class="lgr-cmp-row">'+
      '<div class="lgr-cmp-h '+clH+'">'+(vh?fmt(vh):'—')+'</div>'+
      '<div class="lgr-cmp-lbl">'+lbl+'</div>'+
      '<div class="lgr-cmp-a '+clA+'">'+(va?fmt(va):'—')+'</div>'+
    '</div>';
  }};

  // ── Offense stats ─────────────────────────────────────────────────────────
  const fMA = (m,a) => m||a ? (m?m.toFixed(0):'0')+' / '+(a?a.toFixed(0):'0') : '—';
  const offRows =
    cmpRow('PPP','POINTS_PER_POSSESSIONS',v=>v.toFixed(3),'higher','off')+
    cmpRow('Points','POINTS',v=>v.toFixed(1),'higher','off')+
    cmpRow('Possessions','POSSESSIONS',v=>v.toFixed(1),'higher','off')+
    cmpRow('Shoot Eff %','SHOOTING_EFF',v=>(v*100).toFixed(1)+'%','higher','off')+
    cmpRow('Shoot Value','SHOOTING_VALUE',v=>v.toFixed(1),'higher','off')+
    cmpRow('2PT % (arc)','3PT%',v=>v.toFixed(1)+'%','higher','off')+
    cmpRow('1PT %','2PT%',v=>v.toFixed(1)+'%','higher','off')+
    cmpRow('FT %','1PT%',v=>v.toFixed(1)+'%','higher','off')+
    (()=>{{ const vh=pg(sH,'3PTM'),va=pg(sA,'3PTM'),vh2=pg(sH,'3PTA'),va2=pg(sA,'3PTA'); if(!vh&&!va) return ''; const hB=vh>va,aB=va>vh; if(hB)offWH++; else if(aB)offWA++; else offT++; return '<div class="lgr-cmp-row"><div class="lgr-cmp-h '+(hB?'lgr-win-cell':aB?'lgr-lose-cell':'lgr-neutral-cell')+'">'+fMA(vh,vh2)+'</div><div class="lgr-cmp-lbl">2PT M/A</div><div class="lgr-cmp-a '+(aB?'lgr-win-cell':hB?'lgr-lose-cell':'lgr-neutral-cell')+'">'+fMA(va,va2)+'</div></div>'; }})() +
    (()=>{{ const vh=pg(sH,'2PTM'),va=pg(sA,'2PTM'),vh2=pg(sH,'2PTA'),va2=pg(sA,'2PTA'); if(!vh&&!va) return ''; const hB=vh>va,aB=va>vh; if(hB)offWH++; else if(aB)offWA++; else offT++; return '<div class="lgr-cmp-row"><div class="lgr-cmp-h '+(hB?'lgr-win-cell':aB?'lgr-lose-cell':'lgr-neutral-cell')+'">'+fMA(vh,vh2)+'</div><div class="lgr-cmp-lbl">1PT M/A</div><div class="lgr-cmp-a '+(aB?'lgr-win-cell':hB?'lgr-lose-cell':'lgr-neutral-cell')+'">'+fMA(va,va2)+'</div></div>'; }})() +
    (()=>{{ const vh=pg(sH,'1PTM'),va=pg(sA,'1PTM'),vh2=pg(sH,'1PTA'),va2=pg(sA,'1PTA'); if(!vh&&!va) return ''; const hB=vh>va,aB=va>vh; if(hB)offWH++; else if(aB)offWA++; else offT++; return '<div class="lgr-cmp-row"><div class="lgr-cmp-h '+(hB?'lgr-win-cell':aB?'lgr-lose-cell':'lgr-neutral-cell')+'">'+fMA(vh,vh2)+'</div><div class="lgr-cmp-lbl">FT M/A</div><div class="lgr-cmp-a '+(aB?'lgr-win-cell':hB?'lgr-lose-cell':'lgr-neutral-cell')+'">'+fMA(va,va2)+'</div></div>'; }})() +
    cmpRow('Assists','ASSISTS',v=>v.toFixed(1),'higher','off')+
    cmpRow('Off Rebounds','OFFENSIVE_REBOUNDS',v=>v.toFixed(1),'higher','off')+
    cmpRow('Turnovers','TURNOVERS',v=>v.toFixed(1),'lower','off');

  // ── Defense stats ─────────────────────────────────────────────────────────
  const defRows =
    cmpRow('PPP Allowed','POINTS_ALLOWED_PER_POSSESSIONS',v=>v.toFixed(3),'lower','def')+
    cmpRow('Pts Allowed','POINTS_ALLOWED',v=>v.toFixed(1),'lower','def')+
    cmpRow('Def Rebounds','DEFENSIVE_REBOUNDS',v=>v.toFixed(1),'higher','def')+
    cmpRow('Steals','STEALS',v=>v.toFixed(1),'higher','def')+
    cmpRow('Blocks','BLOCKS',v=>v.toFixed(1),'higher','def')+
    cmpRow('Fouls','FOULS',v=>v.toFixed(1),'lower','def')+
    cmpRow('Fouls Against','FOULS_AGAINST',v=>v.toFixed(1),'higher','def')+
    cmpRow('NSF In Bonus','NSF_IN_BONUS',v=>v.toFixed(1),'higher','def')+
    cmpRow('NSF Agst Bonus','NSF_AGAINST_IN_BONUS',v=>v.toFixed(1),'lower','def');

  // ── Offense play type table (butterfly layout) ────────────────────────────
  const offPTSet = [...new Set([...(ptH?.offense||[]).map(x=>x.label),...(ptA?.offense||[]).map(x=>x.label)])];
  const offPTSorted = offPTSet.map(lbl => {{
    const hd=ptH?.offense?.find(x=>x.label===lbl)||null;
    const ad=ptA?.offense?.find(x=>x.label===lbl)||null;
    return {{lbl,hd,ad,usage:(hd?.usage||0)+(ad?.usage||0)}};
  }}).sort((a,b)=>b.usage-a.usage);
  const maxUsage = Math.max(...offPTSorted.map(x=>Math.max(x.hd?.usage||0,x.ad?.usage||0)),1);

  const offPTRows = offPTSorted.map(({{lbl,hd,ad}})=>{{
    const hPPP=hd?.ppp||0, aPPP=ad?.ppp||0;
    const hWin=hPPP>aPPP&&hPPP>0, aWin=aPPP>hPPP&&aPPP>0;
    const hUsage=hd?.usage||0, aUsage=ad?.usage||0;
    const BAR=72;
    const hW=Math.round(hUsage/maxUsage*BAR), aW=Math.round(aUsage/maxUsage*BAR);
    const h2pct=hd?.two_pt_pct||0, a2pct=ad?.two_pt_pct||0;
    const hTO=hd?.turnovers||0, aTO=ad?.turnovers||0;
    return '<tr>'+
      // Home: value right, bar grows LEFT from center
      '<td style="padding:6px 8px 6px 4px">'+
        '<div style="display:flex;align-items:center;gap:6px;justify-content:flex-end">'+
          '<div>'+
            '<div style="font-size:13px;font-weight:'+(hWin?700:500)+';color:'+(hWin?'#3fb950':hPPP?'var(--text)':'var(--text3)')+';text-align:right">'+(hd?hd.ppp.toFixed(3):'—')+'</div>'+
            '<div style="font-size:9px;color:var(--text3);text-align:right">'+(hd?hUsage+'% usage':'')+'</div>'+
            (h2pct?'<div style="font-size:9px;color:var(--text3);text-align:right">2PT '+h2pct.toFixed(1)+'%</div>':'')+
          '</div>'+
          '<div style="display:flex;align-items:flex-end;justify-content:flex-end;width:'+BAR+'px;flex-shrink:0">'+
            '<div style="height:8px;width:'+hW+'px;background:linear-gradient(to left,#3fb950,#3fb95060);border-radius:3px 0 0 3px"></div>'+
          '</div>'+
        '</div>'+
      '</td>'+
      // Center: play type name
      '<td style="text-align:center;padding:6px 10px;white-space:nowrap">'+
        '<div style="font-size:11px;font-weight:600;color:var(--text2)">'+(PT_LBL[lbl]||lbl)+'</div>'+
      '</td>'+
      // Away: bar grows RIGHT from center, value left
      '<td style="padding:6px 4px 6px 8px">'+
        '<div style="display:flex;align-items:center;gap:6px">'+
          '<div style="display:flex;align-items:flex-start;width:'+BAR+'px;flex-shrink:0">'+
            '<div style="height:8px;width:'+aW+'px;background:linear-gradient(to right,#58a6ff,#58a6ff60);border-radius:0 3px 3px 0"></div>'+
          '</div>'+
          '<div>'+
            '<div style="font-size:13px;font-weight:'+(aWin?700:500)+';color:'+(aWin?'#3fb950':aPPP?'var(--text)':'var(--text3)')+'">'+( ad?ad.ppp.toFixed(3):'—')+'</div>'+
            '<div style="font-size:9px;color:var(--text3)">'+(ad?aUsage+'% usage':'')+'</div>'+
            (a2pct?'<div style="font-size:9px;color:var(--text3)">2PT '+a2pct.toFixed(1)+'%</div>':'')+
          '</div>'+
        '</div>'+
      '</td>'+
    '</tr>';
  }}).join('');

  const ptColHdr =
    '<div style="display:grid;grid-template-columns:1fr 100px 1fr;padding:8px 8px 8px;border-bottom:1px solid var(--border);margin-bottom:2px">'+
      '<div style="text-align:right;font-weight:800;font-size:12px;color:#3fb950;padding-right:8px">'+escape(htName)+'</div>'+
      '<div style="text-align:center;font-size:9px;color:var(--text3);font-weight:700">PLAY TYPE</div>'+
      '<div style="font-weight:800;font-size:12px;color:#58a6ff;padding-left:8px">'+escape(atName)+'</div>'+
    '</div>';

  const offPTHtml = offPTRows ?
    ptColHdr+'<table style="width:100%;border-collapse:collapse"><tbody>'+offPTRows+'</tbody></table>'
    : '<div class="empty" style="padding:24px">No play type data</div>';

  // ── Defense play type table (butterfly layout) ────────────────────────────
  const defHlH = ptH?.defense_hl||[];
  const defHlA = ptA?.defense_hl||[];
  const defPTSet = [...new Set([...defHlH.map(x=>x.label),...defHlA.map(x=>x.label)])];
  const DEF_ORDER = ['TRANSITION','SET_PLAY','OPEN_PLAY','CLEARED_BY_PASS','CLEARED_BY_DRIBBLE'];
  const defPTSorted = [...DEF_ORDER.filter(l=>defPTSet.includes(l)),...defPTSet.filter(l=>!DEF_ORDER.includes(l))];
  const maxDefPoss = Math.max(...defPTSorted.map(l=>{{
    const hd=defHlH.find(x=>x.label===l), ad=defHlA.find(x=>x.label===l);
    return Math.max(hd?.poss||0, ad?.poss||0);
  }}), 1);

  const defPTRows = defPTSorted.map(lbl=>{{
    const hd=defHlH.find(x=>x.label===lbl)||null;
    const ad=defHlA.find(x=>x.label===lbl)||null;
    if (!hd&&!ad) return '';
    const hPPP=hd?.ppp||0, aPPP=ad?.ppp||0;
    const hWin=hPPP>0&&aPPP>0&&hPPP<aPPP, aWin=hPPP>0&&aPPP>0&&aPPP<hPPP;
    const hPoss=hd?.poss||0, aPoss=ad?.poss||0;
    const BAR=72;
    const hW=Math.round(hPoss/maxDefPoss*BAR), aW=Math.round(aPoss/maxDefPoss*BAR);
    return '<tr>'+
      '<td style="padding:6px 8px 6px 4px">'+
        '<div style="display:flex;align-items:center;gap:6px;justify-content:flex-end">'+
          '<div>'+
            '<div style="font-size:13px;font-weight:'+(hWin?700:500)+';color:'+(hWin?'#3fb950':hPPP?'var(--text)':'var(--text3)')+';text-align:right">'+(hd?hd.ppp.toFixed(3):'—')+'</div>'+
            '<div style="font-size:9px;color:var(--text3);text-align:right">'+(hd?hPoss.toFixed(0)+' poss':'')+'</div>'+
          '</div>'+
          '<div style="display:flex;align-items:flex-end;justify-content:flex-end;width:'+BAR+'px;flex-shrink:0">'+
            '<div style="height:8px;width:'+hW+'px;background:linear-gradient(to left,#3fb950,#3fb95060);border-radius:3px 0 0 3px"></div>'+
          '</div>'+
        '</div>'+
      '</td>'+
      '<td style="text-align:center;padding:6px 10px;white-space:nowrap">'+
        '<div style="font-size:11px;font-weight:600;color:var(--text2)">'+(DEF_LBL[lbl]||lbl)+'</div>'+
        '<div style="font-size:8px;color:var(--text3);margin-top:1px">PPP allowed ↓</div>'+
      '</td>'+
      '<td style="padding:6px 4px 6px 8px">'+
        '<div style="display:flex;align-items:center;gap:6px">'+
          '<div style="display:flex;align-items:flex-start;width:'+BAR+'px;flex-shrink:0">'+
            '<div style="height:8px;width:'+aW+'px;background:linear-gradient(to right,#58a6ff,#58a6ff60);border-radius:0 3px 3px 0"></div>'+
          '</div>'+
          '<div>'+
            '<div style="font-size:13px;font-weight:'+(aWin?700:500)+';color:'+(aWin?'#3fb950':aPPP?'var(--text)':'var(--text3)')+'">'+( ad?ad.ppp.toFixed(3):'—')+'</div>'+
            '<div style="font-size:9px;color:var(--text3)">'+(ad?aPoss.toFixed(0)+' poss':'')+'</div>'+
          '</div>'+
        '</div>'+
      '</td>'+
    '</tr>';
  }}).filter(Boolean).join('');

  const defColHdrInner =
    '<div style="display:grid;grid-template-columns:1fr 120px 1fr;padding:8px 8px 8px;border-bottom:1px solid var(--border);margin-bottom:2px">'+
      '<div style="text-align:right;font-weight:800;font-size:12px;color:#3fb950;padding-right:8px">'+escape(htName)+'</div>'+
      '<div style="text-align:center;font-size:9px;color:var(--text3);font-weight:700">CATEGORY</div>'+
      '<div style="font-weight:800;font-size:12px;color:#58a6ff;padding-left:8px">'+escape(atName)+'</div>'+
    '</div>';

  const defPTHtml = defPTRows ?
    defColHdrInner+'<table style="width:100%;border-collapse:collapse"><tbody>'+defPTRows+'</tbody></table>'
    : '<div class="empty" style="padding:24px">No defense play type data</div>';

  // ── Radar + Edge scoreboard ───────────────────────────────────────────────
  const totalWH = offWH+defWH, totalWA = offWA+defWA, totalT = offT+defT;

  // ── Section card builder ──────────────────────────────────────────────────
  const sectionCard = (icon, title, wins_h, wins_a, statsHtml, ptHtml) => {{
    const colHdr =
      '<div style="display:grid;grid-template-columns:1fr 88px 1fr;padding:7px 16px 8px;border-bottom:1px solid var(--border)">'+
        '<div style="text-align:right;font-weight:800;font-size:12px;color:#3fb950;padding-right:8px">'+escape(htName)+'</div>'+
        '<div style="text-align:center;font-size:8px;color:var(--text3);font-weight:700">STAT</div>'+
        '<div style="font-weight:800;font-size:12px;color:#58a6ff;padding-left:8px">'+escape(atName)+'</div>'+
      '</div>';
    return '<div class="card" style="margin-bottom:16px">'+
      '<div style="display:flex;align-items:center;justify-content:space-between;padding:10px 16px;border-bottom:1px solid var(--border)">'+
        '<div style="display:flex;align-items:center;gap:8px">'+
          '<span style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--text)">'+icon+' '+title+'</span>'+
          '<span style="font-size:9px;color:var(--text3)">'+dataLabel+'</span>'+
        '</div>'+
        '<div style="font-size:11px">'+
          '<span style="color:#3fb950;font-weight:700">'+escape(htName)+' '+wins_h+'</span>'+
          '<span style="color:var(--text3)"> – </span>'+
          '<span style="color:#58a6ff;font-weight:700">'+wins_a+' '+escape(atName)+'</span>'+
        '</div>'+
      '</div>'+
      // Left: stat comparison | Right: play type
      '<div class="lgr-split">'+
        '<div class="lgr-panel">'+colHdr+statsHtml+'</div>'+
        '<div class="lgr-panel">'+ptHtml+'</div>'+
      '</div>'+
    '</div>';
  }};

  const offCard = sectionCard('&#9651;','Offense',offWH,offWA,offRows,offPTHtml);
  const defCard = sectionCard('&#9661;','Defense',defWH,defWA,defRows,defPTHtml);

  // ── Player box score ──────────────────────────────────────────────────────
  const matchPl = (DATA.matchPlayerStats||{{}})[mid]||{{}};
  const plH = Object.values(matchPl[match.htid]||{{}}).sort((a,b)=>(b.stats.POINTS||0)-(a.stats.POINTS||0));
  const plA = Object.values(matchPl[match.atid]||{{}}).sort((a,b)=>(b.stats.POINTS||0)-(a.stats.POINTS||0));
  const plCols = [
    ['PTS','POINTS',v=>v.toFixed(0)],
    ['2PM','3PTM',v=>v.toFixed(0)],['2PA','3PTA',v=>v.toFixed(0)],
    ['1PM','2PTM',v=>v.toFixed(0)],['1PA','2PTA',v=>v.toFixed(0)],
    ['FTM','1PTM',v=>v.toFixed(0)],['FTA','1PTA',v=>v.toFixed(0)],
    ['AST','ASSISTS',v=>v.toFixed(0)],
    ['OR','OFFENSIVE_REBOUNDS',v=>v.toFixed(0)],
    ['DR','DEFENSIVE_REBOUNDS',v=>v.toFixed(0)],
    ['STL','STEALS',v=>v.toFixed(0)],
    ['BLK','BLOCKS',v=>v.toFixed(0)],
    ['TO','TURNOVERS',v=>v.toFixed(0)],
    ['PPP','POINTS_PER_POSSESSIONS',v=>v.toFixed(3)],
  ];
  const plTblHdr = '<tr style="position:sticky;top:0;background:var(--bg2);z-index:1">'+
    '<th style="text-align:left;padding:7px 8px;font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--text3);border-bottom:1px solid var(--border)">Player</th>'+
    plCols.map(([l])=>'<th style="text-align:center;padding:7px 4px;font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--text3);border-bottom:1px solid var(--border)">'+l+'</th>').join('')+
  '</tr>';
  const plRow = (p,col) => {{
    const s = p.stats||{{}};
    const pts = s.POINTS||0;
    return '<tr>'+
      '<td style="padding:6px 8px;font-size:12px;font-weight:'+(pts>0?600:400)+';color:'+(pts>0?col:'var(--text3)')+';white-space:nowrap">'+
        escape(p.name)+
        (p.pos?'<span style="font-size:9px;color:var(--text3);margin-left:4px">'+p.pos+'</span>':'')+
      '</td>'+
      plCols.map(([,key,fmt])=>{{
        const v=s[key];
        return '<td style="text-align:center;padding:6px 4px;font-size:12px;color:'+(v?'var(--text)':'var(--text3)')+'">'+
          (v!=null?fmt(v):'—')+'</td>';
      }}).join('')+
    '</tr>';
  }};
  const plTblRows = (players, col) => players.length
    ? players.map(p=>plRow(p,col)).join('')
    : '<tr><td colspan="'+(plCols.length+1)+'" style="padding:16px;text-align:center;color:var(--text3);font-size:12px">No player data</td></tr>';

  const playerCard = plH.length || plA.length ?
    '<div class="card" style="margin-bottom:16px">'+
      '<div class="card-hdr">Player Box Scores</div>'+
      '<div class="lgr-split">'+
        '<div class="lgr-panel">'+
          '<div style="font-size:11px;font-weight:700;color:#3fb950;margin-bottom:8px">'+escape(htName)+'</div>'+
          '<div style="overflow-x:auto"><table class="lgr-pt-tbl" style="min-width:600px"><thead>'+plTblHdr+'</thead><tbody>'+plTblRows(plH,'#3fb950')+'</tbody></table></div>'+
        '</div>'+
        '<div class="lgr-panel">'+
          '<div style="font-size:11px;font-weight:700;color:#58a6ff;margin-bottom:8px">'+escape(atName)+'</div>'+
          '<div style="overflow-x:auto"><table class="lgr-pt-tbl" style="min-width:600px"><thead>'+plTblHdr+'</thead><tbody>'+plTblRows(plA,'#58a6ff')+'</tbody></table></div>'+
        '</div>'+
      '</div>'+
    '</div>'
    : '';

  // ── Season context ────────────────────────────────────────────────────────
  const ctxMini = (s,col) => {{
    const stats=[
      ['GP','GAMES_PLAYED',v=>v.toFixed(0)],
      ['Win%','WIN_PERCENTAGE',v=>v.toFixed(0)+'%'],
      ['PPP','POINTS_PER_POSSESSIONS',v=>v.toFixed(3)],
      ['dPPP','POINTS_ALLOWED_PER_POSSESSIONS',v=>v.toFixed(3)],
      ['Shoot%','SHOOTING_EFF',v=>(v*100).toFixed(0)+'%'],
      ['TO','TURNOVERS',v=>v.toFixed(1)],
      ['Ast','ASSISTS',v=>v.toFixed(1)],
      ['OR','OFFENSIVE_REBOUNDS',v=>v.toFixed(1)],
    ];
    return stats.map(([lbl,key,fmt])=>{{
      const v=pg(s,key);
      return '<div style="text-align:center;padding:8px 4px;background:var(--bg3);border:1px solid var(--border);border-radius:6px">'+
        '<div style="font-size:15px;font-weight:800;color:'+col+'">'+(v?fmt(v):'—')+'</div>'+
        '<div style="font-size:9px;color:var(--text3);margin-top:2px">'+lbl+'</div>'+
      '</div>';
    }}).join('');
  }};

  const ctxCard =
    '<div class="lgr-grid2" style="margin-bottom:0">'+
      '<div class="card">'+
        '<div class="card-hdr" style="color:#3fb950">'+escape(htName)+' — Season</div>'+
        '<div class="card-body"><div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px">'+ctxMini(sHS,'#3fb950')+'</div></div>'+
      '</div>'+
      '<div class="card">'+
        '<div class="card-hdr" style="color:#58a6ff">'+escape(atName)+' — Season</div>'+
        '<div class="card-body"><div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px">'+ctxMini(sAS,'#58a6ff')+'</div></div>'+
      '</div>'+
    '</div>';

  el.innerHTML = bannerHtml + offCard + defCard + playerCard + ctxCard;
}}

// ── Init ───────────────────────────────────────────────────────────────────
renderOverview();
renderRankings();
renderLeaders();
populateMUTeams();
populateTiTeams();
populateLgrMatches();
</script>
</body>
</html>"""


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    print("Extracting data from SSA DB...")
    teams, players, play_types, matches, match_stats, match_play_types, match_player_stats = extract_data(conn)
    print(f"  Teams: {len(teams)}, Players: {len(players)}, Matches: {len(matches)}, "
          f"Match stats: {len(match_stats)} matches, Player match stats: {len(match_player_stats)} matches")
    conn.close()

    print("Building dashboard HTML...")
    html = build_html(teams, players, play_types, matches, match_stats, match_play_types, match_player_stats)

    with open(OUT_PATH, 'w') as f:
        f.write(html)
    print(f"✅ Saved → {OUT_PATH}  ({len(html)//1024} KB)")


if __name__ == '__main__':
    main()
