#!/usr/bin/env python3
"""
Generic opponent scouting report generator.

Usage:
    python generate_scout_report.py --team "Hungary"
    python generate_scout_report.py --team "China" --color "#DE2910" --seed 3
    python generate_scout_report.py --team "USA" --players "Kelsey Plum,Cierra Burdick" --period LAST_3

Player lookup:
  - Searches DB for team name match (WNT first, then Clubs).
  - --players overrides with a comma-separated name list (partial match).
  - For each player, WNT data is used if available; falls back to Clubs.

Output:
    <team_slug>_scout_report.html  — self-contained, shareable HTML file.
"""
import argparse, sqlite3, os, sys, json, urllib.request, base64
from html import escape

_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env):
    for line in open(_env):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "data", "db", "ssa.db")

COURT_PNG_URL   = "https://www.strongsideanalytics.com/assets/images/shooting-map-sm.png"
COURT_PNG_LOCAL = os.path.join(BASE_DIR, "shooting-map-sm.png")

def ensure_court_png():
    if not os.path.exists(COURT_PNG_LOCAL):
        print("Downloading court background...", flush=True)
        urllib.request.urlretrieve(COURT_PNG_URL, COURT_PNG_LOCAL)

# ── SSA zone polygons ─────────────────────────────────────────────────────────
SSA_ZONE_POLYGONS = {
    "TWO_POINTS_LAYUP_LEFT":
        "955,545 955,58 708,58 686,90 669,119 659,146 648,179 643,217 642,247 "
        "643,279 651,307 661,342 673,373 692,400 709,424 731,454 755,473 787,495 "
        "817,513 852,526 899,540",
    "TWO_POINTS_LAYUP_RIGHT":
        "955,547 955,56 1195,57 1228,104 1248,147 1258,199 1261,247 1258,290 "
        "1244,333 1230,370 1211,404 1184,440 1150,474 1111,498 1072,521 1029,534 989,543",
    "TWO_POINTS_MID_LEFT_WING":
        "405,57 692,54 671,86 654,121 642,150 634,181 632,198 627,222 627,248 "
        "628,273 632,306 636,327 647,353 655,376 666,396 678,416 692,434 706,452 "
        "720,470 737,485 755,494 677,748 623,715 577,677 538,639 507,603 484,573 "
        "461,540 437,504 422,467 409,428 396,393 385,346 378,312 377,273 374,226 "
        "379,186 385,134 391,93",
    "TWO_POINTS_MID_TOP":
        "768,504 687,755 732,777 768,789 795,798 821,806 844,812 870,816 899,820 "
        "928,821 961,821 994,820 1025,816 1059,810 1090,804 1125,793 1154,782 "
        "1179,773 1215,756 1138,502 1119,516 1102,526 1076,537 1049,545 1021,553 "
        "993,559 962,561 928,560 901,560 881,555 858,547 829,534 805,525",
    "TWO_POINTS_MID_RIGHT_WING":
        "1216,57 1507,58 1518,86 1526,124 1531,154 1535,181 1536,213 1535,248 "
        "1535,277 1532,306 1530,334 1526,357 1520,380 1509,413 1497,448 1483,486 "
        "1466,510 1450,540 1431,568 1409,600 1386,625 1361,651 1337,673 1309,695 "
        "1281,716 1232,750 1152,497 1179,470 1209,434 1228,407 1247,377 1257,347 "
        "1270,304 1275,252 1274,213 1270,174 1261,142 1247,108 1234,78",
    "TWO_POINTS_LONG_LEFT_CORNER":
        "183,57 391,56 369,121 357,181 354,232 354,272 355,306 359,337 366,369 "
        "373,401 382,432 391,459 404,486 414,508 428,533 444,557 456,576 227,764 190,712",
    "TWO_POINTS_LONG_LEFT_WING":
        "238,782 474,594 513,639 542,672 570,697 600,719 631,740 657,755 681,770 "
        "712,785 735,789 652,1062 589,1039 535,1013 490,988 448,962 408,937 374,910 "
        "342,883 313,856 287,832 260,804",
    "TWO_POINTS_LONG_TOP":
        "665,1065 748,799 803,818 842,828 872,830 899,833 930,836 955,837 987,834 "
        "1026,830 1056,826 1083,821 1119,812 1160,799 1248,1066 1250,1070 1212,1081 "
        "1168,1091 1123,1101 1083,1108 1040,1113 1001,1117 965,1120 931,1120 889,1117 "
        "852,1114 811,1108 768,1098 718,1085",
    "TWO_POINTS_LONG_RIGHT_WING":
        "1179,791 1262,1062 1300,1051 1339,1034 1374,1017 1410,995 1435,981 1469,958 "
        "1504,934 1536,910 1573,884 1604,849 1627,825 1672,781 1435,588 1418,618 "
        "1388,649 1360,678 1325,707 1292,732 1258,754 1228,769 1205,779",
    "TWO_POINTS_LONG_RIGHT_CORNER":
        "1524,58 1723,57 1726,711 1683,763 1448,577 1484,518 1504,478 1516,443 "
        "1528,405 1540,361 1547,321 1551,280 1551,240 1551,213 1550,179 1544,146 1536,103",
    "THREE_POINTS_LEFT_CORNER":  "52,57 160,56 159,713 54,715",
    "THREE_POINTS_LEFT_WING":
        "55,731 160,731 191,771 215,798 239,824 264,851 295,879 322,907 351,929 "
        "383,953 410,973 443,995 474,1013 510,1032 548,1054 588,1071 627,1086 "
        "679,1104 542,1733 55,1733",
    "THREE_POINTS_TOP":
        "1224,1105 1359,1733 560,1734 692,1108 736,1120 786,1129 838,1137 884,1141 "
        "934,1145 979,1147 1021,1145 1066,1140 1100,1134 1137,1128 1181,1118",
    "THREE_POINTS_RIGHT_WING":
        "1857,727 1855,1732 1375,1732 1239,1104 1305,1078 1359,1055 1418,1021 "
        "1464,996 1501,970 1544,938 1578,917 1609,886 1640,855 1674,820 1698,793 "
        "1725,759 1752,725",
    "THREE_POINTS_RIGHT_CORNER": "1752,58 1858,58 1858,709 1752,709",
}
SSA_TEXT_POS = {
    "TWO_POINTS_LAYUP_LEFT":         (810,  310, 370),
    "TWO_POINTS_LAYUP_RIGHT":        (1080, 310, 370),
    "TWO_POINTS_MID_LEFT_WING":      (518,  344, 404),
    "TWO_POINTS_MID_TOP":            (944,  699, 759),
    "TWO_POINTS_MID_RIGHT_WING":     (1374, 399, 459),
    "TWO_POINTS_LONG_LEFT_CORNER":   (263,  499, 559),
    "TWO_POINTS_LONG_LEFT_WING":     (489,  825, 885),
    "TWO_POINTS_LONG_TOP":           (957,  1000, 1060),
    "TWO_POINTS_LONG_RIGHT_WING":    (1404, 850, 910),
    "TWO_POINTS_LONG_RIGHT_CORNER":  (1600, 557, 617),
    "THREE_POINTS_LEFT_CORNER":      (100,  310, 370),
    "THREE_POINTS_LEFT_WING":        (301,  1096, 1156),
    "THREE_POINTS_TOP":              (957,  1280, 1340),
    "THREE_POINTS_RIGHT_WING":       (1600, 1071, 1131),
    "THREE_POINTS_RIGHT_CORNER":     (1804, 310, 370),
}

def zone_fill(pct, total):
    if total == 0: return "transparent", 0
    if pct >= 55:  return "#4CAF50", 0.75
    if pct >= 40:  return "#FFC107", 0.75
    if pct >= 25:  return "#FF7043", 0.75
    return "#EF5350", 0.75

def make_court_svg(zone_data, title):
    lines = [
        f'<div style="text-align:center">',
        f'<div style="font-size:9px;font-weight:bold;color:#555;margin-bottom:2px;text-transform:uppercase">{title}</div>',
        f'<svg viewBox="0 0 1905 1787" preserveAspectRatio="xMidYMid meet" '
        f'xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%;max-width:280px;display:block;margin:auto;border-radius:4px;border:1px solid #ccc">',
        f'<image href="shooting-map-sm.png" width="100%" height="100%"/>',
    ]
    for zone, pts in SSA_ZONE_POLYGONS.items():
        d = zone_data.get(zone, {}); total = d.get("total", 0); pct = d.get("pct", 0.0)
        fill, opacity = zone_fill(pct, total)
        lines.append(f'<polygon points="{pts}" fill="{fill}" fill-opacity="{opacity}" '
                     f'stroke="rgba(255,255,255,0.25)" stroke-width="2"/>')
    for zone, (tx, ty_pct, ty_mt) in SSA_TEXT_POS.items():
        d = zone_data.get(zone, {}); total = d.get("total", 0)
        made = d.get("made", 0); pct = d.get("pct", 0.0)
        if total > 0:
            lines.append(f'<text text-anchor="middle" font-size="72" font-weight="700" '
                         f'fill="white" stroke="rgba(0,0,0,0.5)" stroke-width="8" paint-order="stroke" '
                         f'x="{tx}" y="{ty_pct}">{pct:.0f}%</text>')
            lines.append(f'<text text-anchor="middle" font-size="58" '
                         f'fill="white" stroke="rgba(0,0,0,0.5)" stroke-width="6" paint-order="stroke" '
                         f'x="{tx}" y="{ty_mt}">{made}/{total}</text>')
    leg = [("#4CAF50","≥55%"),("#FFC107","40–55%"),("#FF7043","25–40%"),("#EF5350","<25%")]
    for i, (clr, lbl) in enumerate(leg):
        lx = 1350 + i * 130
        lines.append(f'<rect x="{lx}" y="1740" width="28" height="28" fill="{clr}" rx="4"/>')
        lines.append(f'<text x="{lx+36}" y="1762" font-size="36" fill="white" '
                     f'stroke="rgba(0,0,0,0.5)" stroke-width="4" paint-order="stroke">{lbl}</text>')
    lines += ['</svg>', '</div>']
    return "\n".join(lines)

# ── DB helpers ────────────────────────────────────────────────────────────────

def q(conn, sql, *args): return conn.execute(sql, args).fetchall()

def fetch_stats(conn, pid, period, ct):
    return {r["stat_label"]: dict(r) for r in q(conn,
        "SELECT stat_label,total,per_game FROM player_stats WHERE player_id=? AND period=? AND competition_type=?",
        pid, period, ct)}

def fetch_play_types(conn, pid, period, ct):
    return [dict(r) for r in q(conn,
        "SELECT play_type,poss,ppp,usage,two_pt_m,two_pt_a,two_pt_pct,three_pt_m,three_pt_a,three_pt_pct,turnovers "
        "FROM player_play_types_detail WHERE player_id=? AND period=? AND competition_type=? ORDER BY usage DESC",
        pid, period, ct) if r["usage"] and r["usage"] > 0]

def fetch_finishing(conn, pid, period, ct):
    return {(r["shot_type"], r["hand"]): dict(r) for r in q(conn,
        "SELECT shot_type,hand,made,attempted,pct FROM player_tendency_finishing "
        "WHERE player_id=? AND period=? AND competition_type=? AND attempted>0", pid, period, ct)}

def fetch_turnovers(conn, pid, period, ct):
    return [dict(r) for r in q(conn,
        "SELECT play_type,bad_pass,traveling,total FROM player_turnovers "
        "WHERE player_id=? AND period=? AND competition_type=? AND total>0 ORDER BY total DESC", pid, period, ct)]

def fetch_shooting_tendency(conn, pid, period, ct):
    return {(r["category"], r["hand"]): dict(r) for r in q(conn,
        "SELECT category,hand,two_pt_m,two_pt_a,two_pt_pct FROM player_tendency_shooting "
        "WHERE player_id=? AND period=? AND competition_type=?", pid, period, ct)}

def fetch_dribble_tendency(conn, pid, period, ct):
    return [dict(r) for r in q(conn,
        "SELECT play_type,hand,two_pt_m,two_pt_a,two_pt_pct FROM player_tendency_dribble "
        "WHERE player_id=? AND period=? AND competition_type=? AND two_pt_a>0", pid, period, ct)]

def fetch_zone_data(conn, pid, period, is_dribble, ct):
    return {r["zone"]: dict(r) for r in q(conn,
        "SELECT zone,made,missed,total,pct FROM player_shot_zones "
        "WHERE player_id=? AND period=? AND is_dribble=? AND competition_type=?", pid, period, is_dribble, ct)}

def fetch_defense(conn, pid, period, ct):
    return [dict(r) for r in q(conn,
        "SELECT label,possession,ppp,pct FROM player_play_types "
        "WHERE player_id=? AND period=? AND competition_type=? AND side='defense' ORDER BY possession DESC",
        pid, period, ct)]

def resolve_player(conn, player, period="SEASON"):
    """Return (pid, competition_type, stats) — WNT preferred, clubs fallback."""
    for pid, ct in [(player.get("wnt_id"), "NATIONAL_TEAMS"), (player.get("clubs_id"), "CLUBS")]:
        if pid:
            stats = fetch_stats(conn, pid, period, ct)
            if stats:
                return pid, ct, stats
    return None, None, {}

def resolve_player_dual(conn, player, period="SEASON"):
    """Return dict of {ct: {pid, stats, ...}} for all available sources.
    A single player ID can have both NATIONAL_TEAMS and CLUBS stats."""
    sources = {}
    # Gather all unique player IDs
    seen_pids = set()
    for pid in filter(None, [player.get("wnt_id"), player.get("clubs_id")]):
        if pid in seen_pids:
            continue
        seen_pids.add(pid)
        # Check both competition types for this ID
        for ct in ("NATIONAL_TEAMS", "CLUBS"):
            stats = fetch_stats(conn, pid, period, ct)
            if stats and ct not in sources:
                sources[ct] = {"pid": pid, "stats": stats}
    return sources

def lookup_roster(conn, team_query, player_names=None):
    """
    Build roster from DB. If player_names given, search by name across all teams.
    Otherwise find team by name and return all its players.
    Returns list of {full_name, wnt_id, clubs_id}.
    """
    if player_names:
        roster = []
        for name in player_names:
            name = name.strip()
            # Search WNT first
            wnt = conn.execute(
                "SELECT p.id FROM players p JOIN teams t ON p.team_id=t.id "
                "WHERE p.full_name LIKE ? AND t.competition_type='NATIONAL_TEAMS'",
                (f"%{name}%",)).fetchone()
            clubs = conn.execute(
                "SELECT p.id FROM players p JOIN teams t ON p.team_id=t.id "
                "WHERE p.full_name LIKE ? AND t.competition_type='CLUBS'",
                (f"%{name}%",)).fetchone()
            roster.append({
                "full_name": name,
                "wnt_id":   wnt["id"]   if wnt   else None,
                "clubs_id": clubs["id"] if clubs else None,
            })
        return roster

    # Collect all players from BOTH WNT and CLUBS teams matching the query,
    # then merge by name so each player gets wnt_id + clubs_id where available.
    by_name = {}  # full_name → {wnt_id, clubs_id}
    for ct in ("NATIONAL_TEAMS", "CLUBS"):
        pid_col = "wnt_id" if ct == "NATIONAL_TEAMS" else "clubs_id"
        teams = conn.execute(
            "SELECT id FROM teams WHERE name LIKE ? AND competition_type=?",
            (f"%{team_query}%", ct)).fetchall()
        for team in teams:
            for p in conn.execute(
                    "SELECT id, full_name FROM players WHERE team_id=? ORDER BY full_name",
                    (team["id"],)).fetchall():
                entry = by_name.setdefault(p["full_name"], {"full_name": p["full_name"],
                                                             "wnt_id": None, "clubs_id": None})
                entry[pid_col] = p["id"]
    return sorted(by_name.values(), key=lambda x: x["full_name"])

# ── Helpers ───────────────────────────────────────────────────────────────────

PT_LABELS = {
    "PICK_AND_ROLL":"Pick & Roll","HANDOFF":"Handoff","OFFSCREEN":"Off Screen",
    "TRANSITION":"Transition","CUT":"Cut","POST_UP":"Post Up","SPOT_UP":"Spot Up",
    "OFFENSIVE_REBOUND":"Off. Rebound","ISOLATION":"Isolation","NO_PLAY_TYPES":"Unclassified",
    # defense high-level categories
    "OPEN_PLAY":"Open Play","SET_PLAY":"Set Play",
    "CLEARED_BY_DRIBBLE":"Cleared (Dribble)","CLEARED_BY_PASS":"Cleared (Pass)",
}
def ppt(s): return PT_LABELS.get(s, s.replace("_"," ").title())
# defense coloring: high PPP allowed is BAD (red), low is good (green) — inverted from offense
def def_ppp_cls(v):
    if v >= 0.60: return "cold"   # bad — opponents scoring easily
    if v <  0.35: return "hot"    # good — locking down
    return ""
def sv(d, key, field="per_game"): return d.get(key, {}).get(field, 0.0) or 0.0
def pct_cls(v):
    if v >= 55: return "hot"
    if v >= 40: return "warm"
    if v <  25: return "cold"
    return ""
def ppp_cls(v):
    if v >= 0.60: return "hot"
    if v <  0.35: return "cold"
    return ""
def cm_to_ft(cm):
    if not cm: return "?"
    t = cm / 2.54; return f"{int(t//12)}'{int(round(t%12))}\""

# ── Claude ────────────────────────────────────────────────────────────────────

def claude(prompt, max_tokens=900):
    import time
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key: raise RuntimeError("ANTHROPIC_API_KEY not set")
    body = json.dumps({"model":"claude-opus-4-8","max_tokens":max_tokens,
                       "messages":[{"role":"user","content":prompt}]}).encode()
    for attempt in range(5):
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=body, method="POST",
            headers={"x-api-key":key,"anthropic-version":"2023-06-01","content-type":"application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())["content"][0]["text"]
        except urllib.error.HTTPError as e:
            if e.code in (529, 503, 429) and attempt < 4:
                wait = 15 * (attempt + 1)
                print(f"  API {e.code} — retrying in {wait}s...", flush=True)
                time.sleep(wait)
            else:
                raise

SCORING_CTX = ("3x3 SCORING: inside arc = 1pt (DB: 2PT%/2PTM/2PTA); "
               "outside arc = 2pt (DB: 3PT%/3PTM/3PTA); free throw = 1pt (DB: 1PT%).")

def build_summary(name, ct, stats, pts, fin, tvs, tend, z0, z1, defense, gp):
    def gs(l): return stats.get(l, {}).get("per_game", 0) or 0
    lines = [
        f"PLAYER: {name}  [DATA: {ct}]",
        f"GP={gp:.0f}  PPG={gs('POINTS'):.1f}  PPP(off)={gs('POINTS_PER_POSSESSIONS'):.2f}",
        f"Inside(1PT): {gs('2PTM'):.1f}/{gs('2PTA'):.1f} ({gs('2PT%'):.0f}%)",
        f"Outside(2PT): {gs('3PTM'):.1f}/{gs('3PTA'):.1f} ({gs('3PT%'):.0f}%)",
        f"FT: {gs('1PTM'):.1f}/{gs('1PTA'):.1f} ({gs('1PT%'):.0f}%)",
        f"ORB={gs('OFFENSIVE_REBOUNDS'):.1f} DRB={gs('DEFENSIVE_REBOUNDS'):.1f} "
        f"AST={gs('ASSISTS'):.1f} TO={gs('TURNOVERS'):.1f} STL={gs('STEALS'):.1f} BLK={gs('BLOCKS'):.1f} "
        f"FC={gs('FOULS'):.1f} FD={gs('FOULS_AGAINST'):.1f}",
        "\nOFFENSE — Play Types (usage%, PPP):",
    ]
    for r in pts[:7]:
        lines.append(f"  {ppt(r['play_type'])}: {r['usage']:.0f}% {r['ppp']:.2f}PPP "
                     f"1PT {r['two_pt_m']}/{r['two_pt_a']}({r['two_pt_pct']:.0f}%) "
                     f"2PT {r['three_pt_m']}/{r['three_pt_a']}({r['three_pt_pct']:.0f}%) TO={r['turnovers']}")
    lines.append("\nRim finishing (LAYUP-type only — NOT all rim attempts; use shot zones for full rim picture):")
    for (st, hand), d in fin.items():
        if (d.get("attempted") or 0) > 0:
            lines.append(f"  {st}/{hand}: {d['made']}/{d['attempted']} ({d['pct']:.0f}%)")
    lines.append("\nShooting tendency (all 2PT arc shots, dribble vs no-dribble):")
    for (cat, hand), d in tend.items():
        if (d.get("two_pt_a") or 0) > 0:
            lines.append(f"  {cat}/{hand}: {d['two_pt_m']}/{d['two_pt_a']} ({d['two_pt_pct']:.0f}%)")
    if tvs:
        lines.append("\nTurnovers:")
        for r in tvs: lines.append(f"  {ppt(r['play_type'])}: {r['total']} (bp={r['bad_pass']} trv={r['traveling']})")
    lines.append("\nShot zones — no-dribble (ALL shot types in each court zone, catch-and-shoot/cuts/putbacks):")
    for zone, d in z0.items():
        if d.get("total", 0) > 0: lines.append(f"  {zone}: {d['made']}/{d['total']} ({d['pct']:.0f}%)")
    lines.append("\nShot zones — off-dribble (ALL shot types in each court zone, self-created):")
    for zone, d in z1.items():
        if d.get("total", 0) > 0: lines.append(f"  {zone}: {d['made']}/{d['total']} ({d['pct']:.0f}%)")
    lines.append(f"\nDEFENSE — Points allowed={gs('POINTS_ALLOWED'):.1f}/game  "
                 f"PPP allowed={gs('POINTS_ALLOWED_PER_POSSESSIONS'):.2f}  "
                 f"DRB={gs('DEFENSIVE_REBOUNDS'):.1f}  STL={gs('STEALS'):.1f}  BLK={gs('BLOCKS'):.1f}  FC={gs('FOULS'):.1f}")
    lines.append("Defense by play type (PPP allowed, possessions defended):")
    for d in defense:
        lines.append(f"  {ppt(d['label'])}: {d['ppp']:.2f} PPP allowed ({int(d['possession'] or 0)} poss)")
    return "\n".join(lines)

SCOUT_STYLE = (
    "Write like a professional scout briefing a coaching staff — precise, direct, tactical. "
    "No casual or broadcast language ('stingy', 'cough up', 'soft spot', 'lock up', 'break down', 'deadly', 'lethal'). "
    "Each bullet must do TWO things: (1) interpret what the number reveals about the player or team — their tendency, pattern, or vulnerability; "
    "then (2) state the coaching action or game-plan implication for Canada. "
    "Always cite the exact number that justifies both parts. "
    "Example structure: 'She converts 11/15 (73%) on rim attempts with her right hand — her primary finishing weapon — so Canada must force left-hand drives or contest right-side cuts early.' "
    "Never just restate a stat. Every number must be tied to a meaning AND a response."
)

def claude_scout(name, team_name, ct, stats, pts, fin, tvs, tend, z0, z1, defense, gp,
                 primary_threat=False):
    data = build_summary(name, ct, stats, pts, fin, tvs, tend, z0, z1, defense, gp)
    warn = f"NOTE: only {gp:.0f} game(s) — small sample." if gp < 5 else ""
    ct_label = "National Team (WNT)" if ct == "NATIONAL_TEAMS" else "Club competition"
    if primary_threat:
        bullet_n = 5
        word_lim = "≤ 90 words"
        threat_note = (
            f"⚠️ PRIMARY THREAT — This is {team_name.split()[0]}'s best and most dangerous player. "
            "Provide 5 detailed bullets per section. Identify every weapon, every tendency, "
            "and every specific Canada game-plan response with exact numbers."
        )
        max_tok = 2800
    else:
        bullet_n = 3
        word_lim = "≤ 70 words"
        threat_note = ""
        max_tok = 1800
    prompt = f"""{SCORING_CTX}
{SCOUT_STYLE}
{warn}
{threat_note}
You are an elite 3x3 scout writing an opponent report for Canada WNT vs {team_name}.
Data for {name}. Competition: {ct_label}. Use ONLY these numbers — no hallucination.

{data}

Return VALID JSON only (no markdown) with exactly 3 keys, each = array of strings:
{{"offense":[...],"defense":[...],"attack":[...]}}
- "offense": exactly {bullet_n} bullets — identify this player's offensive weapons and liabilities with specific actions Canada should be aware of (cite exact numbers)
- "defense": exactly {bullet_n} bullets — identify specific defensive patterns: which situations this player concedes in, what matchups Canada can target, foul/rebounding tendencies (cite exact numbers)
- "attack": exactly {bullet_n} game-plan bullets — specific actions Canada should run TO or AWAY FROM this player, including both offensive and defensive matchup decisions (cite numbers)
Each bullet {word_lim}. No headers, no numbering. Lead each bullet with the coaching insight, not the stat."""
    raw = claude(prompt, max_tok).strip()
    if raw.startswith("```"): raw = "\n".join(raw.splitlines()[1:])
    if raw.endswith("```"):   raw = "\n".join(raw.splitlines()[:-1])
    s = raw.find("{"); e = raw.rfind("}") + 1
    if s != -1 and e > s: raw = raw[s:e]
    try:    return json.loads(raw)
    except:
        # retry once on parse error
        import time; time.sleep(5)
        raw2 = claude(prompt, max_tok).strip()
        s = raw2.find("{"); e = raw2.rfind("}") + 1
        if s != -1 and e > s: raw2 = raw2[s:e]
        try:    return json.loads(raw2)
        except: return {"offense":["[parse error]"],"defense":[],"attack":[]}

def bullets_html(items, cls):
    return "".join(f'<li class="{cls}">{escape(i)}</li>\n' for i in items)

def claude_team_scout(team_name, gp, wins, ppg, ppp, off_types, def_types):
    """Generate team-level AI scouting: offense tendencies, defensive profile, Canada attack plan."""
    off_lines = "\n".join(
        f"  {ppt(r['play_type'])}: {r['usage']:.0f}% usage, {r['ppp']:.2f} PPP, "
        f"1PT {r['two_pt_m']}/{r['two_pt_a']}({r['two_pt_pct']:.0f}%), "
        f"2PT {r['three_pt_m']}/{r['three_pt_a']}({r['three_pt_pct']:.0f}%), TO={r['turnovers']}"
        for r in off_types if (r['usage'] or 0) > 0
    )
    def_lines = "\n".join(
        f"  {ppt(r['label'])}: {r['ppp']:.2f} PPP allowed ({int(r['possession'] or 0)} poss, {r['pct'] or 0:.0f}% of def)"
        for r in def_types
    )
    data = (
        f"TEAM: {team_name}\n"
        f"Record: {gp}G {wins}W-{gp-wins}L ({wins/gp*100:.0f}% win)\n"
        f"Offense: {ppg:.1f} PPG, {ppp:.2f} PPP\n\n"
        f"OFFENSE — Play Types:\n{off_lines}\n\n"
        f"DEFENSE — PPP Allowed by Situation:\n{def_lines}"
    )
    prompt = f"""{SCORING_CTX}
{SCOUT_STYLE}
You are an elite 3x3 scout writing a team-level opponent report for Canada WNT coaching staff.
Use ONLY the data below — no hallucination.

{data}

Return VALID JSON only (no markdown) with exactly 3 keys, each = array of 3 strings:
{{"offense":[...],"defense":[...],"attack":[...]}}
- "offense": 3 bullets — identify the offensive actions this team runs most, what works and what doesn't, and what Canada's defense needs to be prepared for (cite exact numbers)
- "defense": 3 bullets — identify specific defensive vulnerabilities and strengths by situation: what play types/situations to run AT them and what to avoid (cite exact PPP numbers and possession counts)
- "attack": 3 game-plan bullets — concrete schemes Canada should run against this team as a unit, based on the data (specific actions, not general advice)
Each bullet ≤ 70 words. No headers, no numbering. Lead with the insight or recommended action, not the stat."""
    raw = claude(prompt, 1800).strip()
    if raw.startswith("```"): raw = "\n".join(raw.splitlines()[1:])
    if raw.endswith("```"):   raw = "\n".join(raw.splitlines()[:-1])
    s = raw.find("{"); e = raw.rfind("}") + 1
    if s != -1 and e > s: raw = raw[s:e]
    try:    return json.loads(raw)
    except: return {"offense":["[parse error]"],"defense":[],"attack":[]}

# ── Player card ───────────────────────────────────────────────────────────────

def player_card_no_data(name):
    return f"""<div class="pcard no-data-card">
  <div class="pheader"><span class="pname">{escape(name)}</span>
  <span class="pmeta">No SSA data found — manual scouting required</span></div>
  <div class="no-data-body"><p><b>Player not found in SSA database.</b></p></div>
</div>"""

_card_counter = [0]

def render_source_panel(pid, ct, stats, period, conn, accent, ai_html, hidden=False):
    """Renders one complete statbar+body panel for a given competition type."""
    pts     = fetch_play_types(conn, pid, period, ct)
    fin     = fetch_finishing(conn, pid, period, ct)
    tvs     = fetch_turnovers(conn, pid, period, ct)
    tend    = fetch_shooting_tendency(conn, pid, period, ct)
    drib    = fetch_dribble_tendency(conn, pid, period, ct)
    z0      = fetch_zone_data(conn, pid, period, 0, ct)
    z1      = fetch_zone_data(conn, pid, period, 1, ct)
    defense = fetch_defense(conn, pid, period, ct)
    stats_l1 = fetch_stats(conn, pid, "LAST_1", ct)

    gp  = sv(stats,"GAMES_PLAYED"); ppg = sv(stats,"POINTS"); ppp = sv(stats,"POINTS_PER_POSSESSIONS")
    one_m = sv(stats,"2PTM"); one_a = sv(stats,"2PTA"); one_pct = sv(stats,"2PT%")
    two_m = sv(stats,"3PTM"); two_a = sv(stats,"3PTA"); two_pct = sv(stats,"3PT%")
    ft_m  = sv(stats,"1PTM"); ft_a  = sv(stats,"1PTA"); ft_pct  = sv(stats,"1PT%")
    orb = sv(stats,"OFFENSIVE_REBOUNDS"); drb = sv(stats,"DEFENSIVE_REBOUNDS")
    stl = sv(stats,"STEALS"); blk = sv(stats,"BLOCKS"); to_pg = sv(stats,"TURNOVERS")
    fd  = sv(stats,"FOULS_AGAINST"); fc = sv(stats,"FOULS")
    pts_allowed = sv(stats,"POINTS_ALLOWED"); ppp_allowed = sv(stats,"POINTS_ALLOWED_PER_POSSESSIONS")

    stitle_css = f"color:{accent};border-color:{accent}"

    pt_rows = ""
    for r in pts[:5]:
        pv = r["ppp"] or 0
        o1 = f'{r["two_pt_pct"]:.0f}%'  if (r["two_pt_a"] or 0) > 0   else "—"
        o2 = f'{r["three_pt_pct"]:.0f}%' if (r["three_pt_a"] or 0) > 0 else "—"
        to = r["turnovers"] or 0
        pt_rows += (f'<tr><td>{ppt(r["play_type"])}</td><td>{r["usage"]:.0f}%</td>'
                    f'<td class="{ppp_cls(pv)}">{pv:.2f}</td>'
                    f'<td class="{pct_cls(r["two_pt_pct"] or 0 if (r["two_pt_a"] or 0)>0 else 30)}">{o1}</td>'
                    f'<td class="{pct_cls(r["three_pt_pct"] or 0 if (r["three_pt_a"] or 0)>0 else 30)}">{o2}</td>'
                    f'<td{"  class=\"warn-to\"" if to>=2 else ""}>{to}</td></tr>\n')

    f_rh = fin.get(("LAYUP","RIGHT"),{}); f_lh = fin.get(("LAYUP","LEFT"),{}); rim = fin.get(("ALL","ALL"),{})
    rt = rim.get("attempted",0)
    fin_line = (f'<b>{rim.get("made",0)}/{rt} ({rim.get("pct",0):.0f}%)</b> &nbsp;·&nbsp; '
                f'RH {f_rh.get("made",0)}/{f_rh.get("attempted",0)} ({f_rh.get("pct",0):.0f}%) '
                f'&nbsp;·&nbsp; LH {f_lh.get("made",0)}/{f_lh.get("attempted",0)} ({f_lh.get("pct",0):.0f}%)'
               ) if rt > 0 else "No rim attempts"

    dj=tend.get(("DRIBBLE_JUMPER","ALL"),{}); djr=tend.get(("DRIBBLE_JUMPER","RIGHT"),{})
    djl=tend.get(("DRIBBLE_JUMPER","LEFT"),{}); ndj=tend.get(("NO_DRIBBLE_JUMPER","ALL"),{})
    dj_line = (f'Pull-up: <b>{dj.get("two_pt_m",0)}/{dj.get("two_pt_a",0)} ({dj.get("two_pt_pct",0):.0f}%)</b> '
               f'[RH {djr.get("two_pt_m",0)}/{djr.get("two_pt_a",0)} · LH {djl.get("two_pt_m",0)}/{djl.get("two_pt_a",0)}] '
               f'&nbsp;·&nbsp; C&amp;S: <b>{ndj.get("two_pt_m",0)}/{ndj.get("two_pt_a",0)} ({ndj.get("two_pt_pct",0):.0f}%)</b>')

    to_rows = "".join(
        f'<tr><td>{ppt(r["play_type"])}</td>'
        f'<td class="{"warn-to" if (r["total"] or 0)>=2 else ""}">{r["total"] or 0}</td>'
        f'<td>{r["bad_pass"] or 0}</td><td>{r["traveling"] or 0}</td></tr>\n' for r in tvs)
    def_rows = "".join(
        f'<tr><td>{ppt(d["label"])}</td>'
        f'<td class="{def_ppp_cls(d["ppp"] or 0)}">{d["ppp"] or 0:.2f}</td>'
        f'<td>{d["possession"] or 0:.0f}</td>'
        f'<td style="color:#888">{d.get("pct") or 0:.0f}%</td></tr>\n' for d in defense)
    tend_rows = ""
    for cat in ["TOTAL_SHOTS","DRIBBLE_JUMPER","NO_DRIBBLE_JUMPER","CATCH_AND_SHOOT"]:
        for hand in ["ALL","RIGHT","LEFT"]:
            d = tend.get((cat, hand), {})
            if (d.get("two_pt_a") or 0) > 0:
                label = cat.replace("_"," ").title() + (f" ({hand.title()})" if hand != "ALL" else "")
                tend_rows += (f'<tr><td>{label}</td><td>{d["two_pt_m"] or 0}/{d["two_pt_a"] or 0}</td>'
                              f'<td class="{pct_cls(d["two_pt_pct"] or 0)}">{d["two_pt_pct"] or 0:.0f}%</td></tr>\n')
    drib_rows = "".join(
        f'<tr><td>{"Overall" if d["play_type"]=="ALL" else d["play_type"].replace("_"," ").title()}</td>'
        f'<td>{"Both" if d["hand"]=="ALL" else d["hand"].title()}</td>'
        f'<td>{d["two_pt_m"] or 0}/{d["two_pt_a"] or 0}</td>'
        f'<td class="{pct_cls(d["two_pt_pct"] or 0)}">{d["two_pt_pct"] or 0:.0f}%</td></tr>\n' for d in drib)

    def gl1(l): return stats_l1.get(l, {}).get("per_game", 0) or 0
    def delta(key):
        diff = gl1(key) - sv(stats, key)
        cls  = "form-up" if diff > 0.05 else ("form-dn" if diff < -0.05 else "")
        arr  = "&#8593;" if diff > 0.05 else ("&#8595;" if diff < -0.05 else "&#8212;")
        return f'<span class="{cls}">{arr}{abs(diff):.1f}</span>'
    recent_html = ""
    if gl1("GAMES_PLAYED") > 0:
        recent_html = f"""
      <div class="stitle" style="margin-top:8px;{stitle_css}">Recent Form &mdash; Last 1 Game</div>
      <table class="ptt"><thead><tr><th>Stat</th><th>Season</th><th>Last 1</th><th>Trend</th></tr></thead><tbody>
        <tr><td>PPG</td><td>{ppg:.1f}</td><td>{gl1("POINTS"):.1f}</td><td>{delta("POINTS")}</td></tr>
        <tr><td>PPP</td><td>{ppp:.2f}</td><td>{gl1("POINTS_PER_POSSESSIONS"):.2f}</td><td>{delta("POINTS_PER_POSSESSIONS")}</td></tr>
        <tr><td>1PT%</td><td>{one_pct:.0f}%</td><td>{gl1("2PT%"):.0f}%</td><td>{delta("2PT%")}</td></tr>
        <tr><td>2PT%</td><td>{two_pct:.0f}%</td><td>{gl1("3PT%"):.0f}%</td><td>{delta("3PT%")}</td></tr>
        <tr><td>ORB</td><td>{orb:.1f}</td><td>{gl1("OFFENSIVE_REBOUNDS"):.1f}</td><td>{delta("OFFENSIVE_REBOUNDS")}</td></tr>
        <tr><td>DRB</td><td>{drb:.1f}</td><td>{gl1("DEFENSIVE_REBOUNDS"):.1f}</td><td>{delta("DEFENSIVE_REBOUNDS")}</td></tr>
        <tr><td>TO</td><td>{to_pg:.1f}</td><td>{gl1("TURNOVERS"):.1f}</td><td>{delta("TURNOVERS")}</td></tr>
      </tbody></table>"""

    svg0 = make_court_svg(z0, "No Dribble (C&amp;S)")
    svg1 = make_court_svg(z1, "Off Dribble")
    sample_warn = f'<div class="sample-warn">&#9888; Small sample: {gp:.0f} game(s)</div>' if gp < 5 else ""

    display = 'display:none' if hidden else ''
    ct_key  = ct  # used as data attribute
    return f"""
<div class="ct-panel" data-ct="{ct_key}" style="{display}">
  <div class="statbar">
    <div class="sc"><div class="sh">GP</div><div class="sv">{gp:.0f}</div></div>
    <div class="sc"><div class="sh">1PT (inside)</div><div class="sv">{one_m:.1f}/{one_a:.1f}</div><div class="sp {pct_cls(one_pct)}">{one_pct:.0f}%</div></div>
    <div class="sc"><div class="sh">2PT (arc)</div><div class="sv">{two_m:.1f}/{two_a:.1f}</div><div class="sp {pct_cls(two_pct)}">{two_pct:.0f}%</div></div>
    <div class="sc"><div class="sh">FT</div><div class="sv">{ft_m:.1f}/{ft_a:.1f}</div><div class="sp">{ft_pct:.0f}%</div></div>
    <div class="sc"><div class="sh">PPG</div><div class="sv">{ppg:.1f}</div></div>
    <div class="sc"><div class="sh">PPP</div><div class="sv {ppp_cls(ppp)}">{ppp:.2f}</div></div>
    <div class="sc"><div class="sh">ORB</div><div class="sv">{orb:.1f}</div></div>
    <div class="sc"><div class="sh">DRB</div><div class="sv">{drb:.1f}</div></div>
    <div class="sc"><div class="sh">STL</div><div class="sv">{stl:.1f}</div></div>
    <div class="sc"><div class="sh">FC</div><div class="sv">{fc:.1f}</div></div>
    <div class="sc"><div class="sh">FD</div><div class="sv">{fd:.1f}</div></div>
  </div>{sample_warn}
  <div class="pbody">
    <div class="pleft">
      <div class="stitle" style="{stitle_css}">Offense &mdash; Play Types</div>
      <table class="ptt"><thead><tr><th>Action</th><th>Usage</th><th>PPP</th><th>1PT%</th><th>2PT%</th><th>TO</th></tr></thead>
      <tbody>{pt_rows or "<tr><td colspan='6' style='color:#aaa'>No data</td></tr>"}</tbody></table>
      <div class="stitle" style="margin-top:8px;{stitle_css}">Rim Finishing &amp; Arc Shooting</div>
      <div class="infoline">&#11044; Rim: {fin_line}</div>
      <div class="infoline">&#11044; {dj_line}</div>
      {"<table class='ptt' style='margin-top:4px'><thead><tr><th>Shooting Type</th><th>M/A</th><th>Pct</th></tr></thead><tbody>"+tend_rows+"</tbody></table>" if tend_rows else ""}
      {"<div class='stitle' style='margin-top:8px;"+stitle_css+"'>Dribble Tendency</div><table class='ptt'><thead><tr><th>Type</th><th>Hand</th><th>M/A</th><th>Pct</th></tr></thead><tbody>"+drib_rows+"</tbody></table>" if drib_rows else ""}
      <div class="stitle" style="margin-top:8px;{stitle_css}">Turnovers &mdash; {to_pg:.1f}/game</div>
      {"<table class='ptt'><thead><tr><th>Play Type</th><th>Total</th><th>Bad Pass</th><th>Travel</th></tr></thead><tbody>"+to_rows+"</tbody></table>" if to_rows else "<div class='infoline' style='color:#aaa'>None recorded</div>"}
      <div class="stitle" style="margin-top:8px;{stitle_css}">Defense</div>
      <div class="def-summary">
        <span class="def-stat"><span class="def-lbl">Pts Allowed</span><span class="def-val">{pts_allowed:.1f}</span></span>
        <span class="def-stat"><span class="def-lbl">PPP Allowed</span><span class="def-val {ppp_cls(1-ppp_allowed)}">{ppp_allowed:.2f}</span></span>
        <span class="def-stat"><span class="def-lbl">DRB</span><span class="def-val">{drb:.1f}</span></span>
        <span class="def-stat"><span class="def-lbl">STL</span><span class="def-val">{stl:.1f}</span></span>
        <span class="def-stat"><span class="def-lbl">BLK</span><span class="def-val">{blk:.1f}</span></span>
        <span class="def-stat"><span class="def-lbl">FC</span><span class="def-val">{fc:.1f}</span></span>
      </div>
      <table class="ptt" style="margin-top:4px"><thead><tr><th>Situation</th><th>PPP Allowed</th><th>Poss</th><th>% of Def</th></tr></thead>
      <tbody>{def_rows or "<tr><td colspan='4' style='color:#aaa'>No data</td></tr>"}</tbody></table>
      {recent_html}
    </div>
    <div class="pright">
      {ai_html}
      <div class="stitle" style="margin-top:8px;{stitle_css}">Shot Charts</div>
      <div class="chartrow">{svg0}{svg1}</div>
    </div>
  </div>
</div>"""

def player_card(conn, player, period, team_name, accent, primary_names=None):
    name = player["full_name"]
    sources = resolve_player_dual(conn, player, period)
    if not sources:
        return player_card_no_data(name)

    _card_counter[0] += 1
    card_id = _card_counter[0]
    stitle_css = f"color:{accent};border-color:{accent}"

    # Pick primary = most games, prefer WNT on tie
    def gp_for(ct): return sv(sources[ct]["stats"], "GAMES_PLAYED")
    ct_order = sorted(sources.keys(),
                      key=lambda c: (gp_for(c), c == "NATIONAL_TEAMS"),
                      reverse=True)
    primary_ct = ct_order[0]
    primary    = sources[primary_ct]

    prow = conn.execute("SELECT position,height FROM players WHERE id=?",
                        (primary["pid"],)).fetchone()
    pos = (prow["position"] or "").replace("CENTER","C").replace("FORWARD","F").replace("GUARD","G") if prow else ""
    ht  = cm_to_ft(prow["height"] if prow else None)

    # Build toggle buttons (shown only when dual source)
    toggle_html = ""
    if len(sources) > 1:
        btns = ""
        for i, ct in enumerate(ct_order):
            label = "WNT" if ct == "NATIONAL_TEAMS" else "CLUBS"
            gp_n  = gp_for(ct)
            active = "ct-btn-active" if i == 0 else ""
            btns += (f'<button class="ct-btn {active}" '
                     f'onclick="switchCT(this,\'{ct}\',{card_id})">'
                     f'{label} <span class="ct-btn-gp">{gp_n:.0f}G</span></button>')
        toggle_html = f'<div class="ct-toggle">{btns}</div>'

    # Render each source panel with its own AI analysis
    panels_html = ""
    for i, ct in enumerate(ct_order):
        src    = sources[ct]
        s_pid  = src["pid"]; s_stats = src["stats"]; s_gp = gp_for(ct)
        s_pts  = fetch_play_types(conn, s_pid, period, ct)
        s_fin  = fetch_finishing(conn, s_pid, period, ct)
        s_tvs  = fetch_turnovers(conn, s_pid, period, ct)
        s_tend = fetch_shooting_tendency(conn, s_pid, period, ct)
        s_z0   = fetch_zone_data(conn, s_pid, period, 0, ct)
        s_z1   = fetch_zone_data(conn, s_pid, period, 1, ct)
        s_def  = fetch_defense(conn, s_pid, period, ct)
        ct_label = "WNT" if ct == "NATIONAL_TEAMS" else "CLUBS"
        is_primary = any(frag in name.lower() for frag in (primary_names or set()))
        print(f"  Generating AI analysis for {name} ({ct_label}){'  ⭐ PRIMARY THREAT' if is_primary else ''}...", flush=True)
        sec = claude_scout(name, team_name, ct, s_stats, s_pts, s_fin, s_tvs, s_tend,
                           s_z0, s_z1, s_def, s_gp, primary_threat=is_primary)
        off_html  = bullets_html(sec.get("offense", []), "note-strength")
        def_html  = bullets_html(sec.get("defense", []), "note-defense")
        atk_html  = bullets_html(sec.get("attack",  []), "note-exploit")
        ct_ai_html = f"""<div class="stitle" style="{stitle_css}">&#129302; AI Scout Analysis &mdash; Claude</div>
      <div class="scout-section">
        <div class="scout-label offense-label">&#9654; Offensive Profile</div>
        <ul class="notes">{off_html}</ul>
      </div>
      <div class="scout-section">
        <div class="scout-label defense-label">&#9632; Defensive Profile</div>
        <ul class="notes">{def_html}</ul>
      </div>
      <div class="scout-section">
        <div class="scout-label exploit-label">&#9733; How to Attack</div>
        <ul class="notes">{atk_html}</ul>
      </div>"""
        panels_html += render_source_panel(
            s_pid, ct, s_stats, period, conn, accent, ct_ai_html,
            hidden=(i > 0))

    is_primary = any(frag in name.lower() for frag in (primary_names or set()))
    primary_badge = (' <span style="font-size:9px;font-weight:bold;background:rgba(255,255,255,0.25);'
                     'padding:2px 8px;border-radius:3px;letter-spacing:.5px">⭐ PRIMARY THREAT</span>'
                     if is_primary else "")
    return f"""
<div class="pcard" id="card-{card_id}">
  <div class="pheader">
    <span class="pname">{escape(name)}</span>{primary_badge}
    {toggle_html}
    <span class="pmeta">{pos} &nbsp;·&nbsp; {ht}</span>
  </div>
  {panels_html}
</div>"""

# ── Team overview section ─────────────────────────────────────────────────────

def render_team_section(conn, team_query, period, accent):
    """Renders a team-level overview card with offense + defense play types."""
    # Find clubs team matching query
    team = conn.execute(
        "SELECT id, name FROM teams WHERE name LIKE ? AND competition_type='CLUBS'",
        (f"%{team_query}%",)).fetchone()
    if not team:
        return ""
    tid = team["id"]; tname = team["name"].strip()

    stats = {r["stat_label"]: r for r in conn.execute(
        "SELECT stat_label, total, per_game FROM team_stats WHERE team_id=? AND period=?",
        (tid, period)).fetchall()}
    if not stats:
        return ""

    def ts(label, field="per_game"):
        row = stats.get(label)
        return (row[field] or 0) if row else 0

    gp   = int(ts("GAMES_PLAYED", "total"))
    wins = int(ts("GAMES_WON", "total"))
    pct  = ts("WIN_PERCENTAGE", "total")
    ppg  = ts("POINTS")
    ppp  = ts("POINTS_PER_POSSESSIONS")

    stitle_css = f"color:{accent};border-color:{accent}"

    def pt_rows_html(side):
        detail = conn.execute("""
            SELECT play_type, poss, ppp, usage, two_pt_m, two_pt_a, two_pt_pct,
                   three_pt_m, three_pt_a, three_pt_pct, turnovers
            FROM team_play_types_detail
            WHERE team_id=? AND period=?
            ORDER BY usage DESC
        """, (tid, period)).fetchall()
        rows = ""
        for r in detail:
            if not (r["usage"] and r["usage"] > 0): continue
            o1 = f'{r["two_pt_pct"]:.0f}%'   if (r["two_pt_a"] or 0) > 0   else "—"
            o2 = f'{r["three_pt_pct"]:.0f}%'  if (r["three_pt_a"] or 0) > 0 else "—"
            pv = r["ppp"] or 0
            to = r["turnovers"] or 0
            rows += (f'<tr><td>{ppt(r["play_type"])}</td><td>{r["usage"]:.0f}%</td>'
                     f'<td class="{ppp_cls(pv)}">{pv:.2f}</td>'
                     f'<td class="{pct_cls(r["two_pt_pct"] or 0 if (r["two_pt_a"] or 0)>0 else 30)}">{o1}</td>'
                     f'<td class="{pct_cls(r["three_pt_pct"] or 0 if (r["three_pt_a"] or 0)>0 else 30)}">{o2}</td>'
                     f'<td{"  class=\"warn-to\"" if to>=5 else ""}>{to}</td></tr>\n')
        return rows

    def def_rows_html():
        rows = conn.execute("""
            SELECT label, possession, ppp, pct FROM team_play_types
            WHERE team_id=? AND period=? AND side='defense'
            ORDER BY pct DESC
        """, (tid, period)).fetchall()
        out = ""
        for r in rows:
            pv = r["ppp"] or 0
            out += (f'<tr><td>{ppt(r["label"])}</td>'
                    f'<td class="{def_ppp_cls(pv)}">{pv:.2f}</td>'
                    f'<td>{int(r["possession"] or 0)}</td>'
                    f'<td style="color:#888">{r["pct"] or 0:.0f}%</td></tr>\n')
        return out

    # raw data objects for AI
    off_types_raw = [dict(r) for r in conn.execute("""
        SELECT play_type, poss, ppp, usage, two_pt_m, two_pt_a, two_pt_pct,
               three_pt_m, three_pt_a, three_pt_pct, turnovers
        FROM team_play_types_detail WHERE team_id=? AND period=? ORDER BY usage DESC
    """, (tid, period)).fetchall()]
    off_types_raw = [r for r in off_types_raw if (r["usage"] or 0) > 0]
    def_types_raw = [dict(r) for r in conn.execute("""
        SELECT label, possession, ppp, pct FROM team_play_types
        WHERE team_id=? AND period=? AND side='defense' ORDER BY pct DESC
    """, (tid, period)).fetchall()]

    off_rows = pt_rows_html("offense")
    def_html = def_rows_html()

    print(f"  Generating AI team analysis for {tname}...")
    team_ai = claude_team_scout(tname, gp, wins, ppg, ppp, off_types_raw, def_types_raw)
    t_off_html = bullets_html(team_ai.get("offense", []), "note-strength")
    t_def_html = bullets_html(team_ai.get("defense", []), "note-defense")
    t_atk_html = bullets_html(team_ai.get("attack",  []), "note-exploit")
    team_ai_html = f"""
    <div class="stitle" style="margin-top:6px;{stitle_css}">🤖 AI Team Scout — Claude</div>
    <div class="scout-section">
      <div class="scout-label offense-label">► Offensive Identity</div>
      <ul class="notes">{t_off_html}</ul>
    </div>
    <div class="scout-section">
      <div class="scout-label defense-label">■ Defensive Profile</div>
      <ul class="notes">{t_def_html}</ul>
    </div>
    <div class="scout-section">
      <div class="scout-label exploit-label">★ How Canada Should Attack</div>
      <ul class="notes">{t_atk_html}</ul>
    </div>"""

    return f"""
<div class="pcard" style="margin-bottom:22px">
  <div class="pheader">
    <span class="pname">{tname} — Team Overview</span>
    <span class="pmeta">{gp}G &nbsp;·&nbsp; {wins}W-{gp-wins}L &nbsp;·&nbsp; {pct:.0f}% Win &nbsp;·&nbsp; {ppg:.1f} PPG &nbsp;·&nbsp; {ppp:.2f} PPP</span>
  </div>
  <div class="statbar">
    <div class="sc"><div class="sh">Games</div><div class="sv">{gp}</div></div>
    <div class="sc"><div class="sh">Wins</div><div class="sv">{wins}</div></div>
    <div class="sc"><div class="sh">Win%</div><div class="sv">{pct:.0f}%</div></div>
    <div class="sc"><div class="sh">PPG (team)</div><div class="sv">{ppg:.1f}</div></div>
    <div class="sc"><div class="sh">PPP (off)</div><div class="sv {ppp_cls(ppp)}">{ppp:.2f}</div></div>
  </div>
  <div class="pbody">
    <div class="pleft">
      <div class="stitle" style="{stitle_css}">Team Offense — Play Types</div>
      <table class="ptt"><thead><tr><th>Action</th><th>Usage</th><th>PPP</th><th>1PT%</th><th>2PT%</th><th>TO</th></tr></thead>
      <tbody>{off_rows or "<tr><td colspan='6' style='color:#aaa'>No data</td></tr>"}</tbody></table>
      <div class="stitle" style="margin-top:8px;{stitle_css}">Team Defense — PPP Allowed by Situation</div>
      <table class="ptt"><thead><tr><th>Situation</th><th>PPP Allowed</th><th>Poss</th><th>% of Def</th></tr></thead>
      <tbody>{def_html or "<tr><td colspan='4' style='color:#aaa'>No data</td></tr>"}</tbody></table>
    </div>
    <div class="pright">{team_ai_html}</div>
  </div>
</div>"""

# ── CSS ───────────────────────────────────────────────────────────────────────

def build_css(accent):
    return f"""
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ font-family:Arial,Helvetica,sans-serif; font-size:11px; color:#111; background:#fff; padding:16px; max-width:1400px; margin:auto; }}
.hdr {{ text-align:center; border-bottom:3px solid {accent}; padding-bottom:10px; margin-bottom:12px; }}
.hdr h1 {{ font-size:24px; font-weight:900; color:{accent}; letter-spacing:1px; }}
.hdr h2 {{ font-size:13px; color:#444; font-weight:600; margin-top:3px; }}
.hdr .sub {{ font-size:10px; color:#888; margin-top:2px; }}
.snote {{ background:#fff8e1; border:1px solid #ffe082; border-radius:3px; padding:5px 10px; font-size:10px; margin-bottom:12px; }}
.pcard {{ border:2px solid #1a1a2e; border-radius:5px; margin-bottom:18px; overflow:hidden; }}
.pcard.no-data-card {{ border-color:#ccc; }}
.pheader {{ background:{accent}; color:white; padding:8px 12px; display:flex; align-items:center; gap:10px; flex-wrap:wrap; }}
.pname {{ font-size:14px; font-weight:bold; }}
.pmeta {{ font-size:10px; color:rgba(255,255,255,0.8); }}
.ct-badge {{ font-size:9px; font-weight:bold; padding:2px 6px; border-radius:3px; }}
.ct-wnt {{ background:#436F4D; color:white; }}
.ct-clubs {{ background:#1a1a2e; color:white; }}
.ct-toggle {{ display:flex; gap:4px; margin-left:4px; }}
.ct-btn {{ font-size:9px; font-weight:bold; padding:3px 8px; border-radius:12px; border:1.5px solid rgba(255,255,255,0.5); background:rgba(255,255,255,0.15); color:white; cursor:pointer; transition:all 0.15s; }}
.ct-btn:hover {{ background:rgba(255,255,255,0.3); }}
.ct-btn-active {{ background:white !important; color:#1a1a2e !important; border-color:white !important; }}
.ct-btn-gp {{ font-weight:normal; opacity:0.8; font-size:8px; }}
.sample-warn {{ font-size:9px; background:#fff3cd; color:#7d5800; padding:2px 8px; border-left:3px solid #ffc107; margin:4px 0 0; }}
.statbar {{ display:flex; background:#f5f5f5; border-bottom:1px solid #ddd; flex-wrap:wrap; }}
.sc {{ text-align:center; flex:1; min-width:60px; padding:5px 4px; border-right:1px solid #ddd; }}
.sc:last-child {{ border-right:none; }}
.sh {{ font-size:7.5px; font-weight:bold; color:#777; text-transform:uppercase; }}
.sv {{ font-size:13px; font-weight:700; }}
.sp {{ font-size:9px; color:#555; }}
.hot {{ color:#2e7d32 !important; font-weight:bold; }}
.warm {{ color:#f57f17 !important; }}
.cold {{ color:#b71c1c !important; font-weight:bold; }}
.pbody {{ display:grid; grid-template-columns:1fr 1fr; }}
.pleft {{ padding:9px 11px; border-right:1px solid #ddd; }}
.pright {{ padding:9px 11px; }}
.stitle {{ font-size:8.5px; font-weight:bold; text-transform:uppercase; letter-spacing:.5px; border-bottom:1px solid; margin-bottom:5px; padding-bottom:2px; }}
table.ptt {{ width:100%; border-collapse:collapse; font-size:10.5px; }}
table.ptt th {{ background:#e8e8e8; padding:2px 4px; font-size:8.5px; font-weight:bold; color:#555; text-align:left; }}
table.ptt td {{ padding:2px 4px; border-bottom:1px solid #f4f4f4; }}
table.ptt tr:nth-child(even) td {{ background:#fafafa; }}
.warn-to {{ color:#b71c1c; font-weight:bold; }}
.infoline {{ font-size:10px; margin-bottom:3px; line-height:1.5; }}
.to-tag {{ display:inline-block; background:#fce4e4; color:#b71c1c; font-size:9px; border-radius:3px; padding:0 4px; margin-right:3px; font-weight:600; }}
.scout-section {{ margin-bottom:7px; }}
.scout-label {{ font-size:8px; font-weight:bold; text-transform:uppercase; letter-spacing:.4px; padding:2px 6px; border-radius:3px 3px 0 0; display:inline-block; margin-bottom:3px; }}
.offense-label {{ background:#1565C0; color:white; }}
.defense-label {{ background:#4a148c; color:white; }}
.exploit-label {{ background:#1a1a2e; color:white; }}
ul.notes {{ padding-left:13px; margin:0; }}
ul.notes li {{ font-size:10.5px; margin-bottom:3px; line-height:1.5; }}
.note-strength {{ color:#1565C0; font-weight:600; }}
.note-defense {{ color:#4a148c; font-weight:600; }}
.note-exploit {{ color:#1a1a2e; font-weight:600; }}
.def-summary {{ display:flex; gap:10px; flex-wrap:wrap; margin:4px 0; background:#f3e5f5; border-radius:3px; padding:5px 8px; }}
.def-stat {{ display:flex; flex-direction:column; align-items:center; min-width:44px; }}
.def-lbl {{ font-size:8px; color:#666; text-transform:uppercase; }}
.def-val {{ font-size:12px; font-weight:bold; color:#4a148c; }}
.chartrow {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:6px; }}
.no-data-body {{ padding:16px; color:#666; font-size:11px; line-height:1.6; }}
.form-up {{ color:#2e7d32; font-weight:bold; }}
.form-dn {{ color:#b71c1c; font-weight:bold; }}
.footer {{ text-align:right; font-size:9px; color:#aaa; margin-top:10px; border-top:1px solid #eee; padding-top:6px; }}
@page {{ size:A4; margin:6mm 10mm; }}
@media print {{
  body {{ padding:0; max-width:100%; font-size:9.5px; }}
  .pcard {{ break-inside:avoid; page-break-inside:avoid; margin-bottom:8px; }}
  .pheader {{ padding:5px 10px; }}
  .pname {{ font-size:12px; }}
  .statbar .sc {{ padding:3px 2px; }}
  .sv {{ font-size:11px; }} .sh {{ font-size:7px; }} .sp {{ font-size:8px; }}
  .pleft, .pright {{ padding:5px 8px; }}
  table.ptt th {{ font-size:7.5px; padding:1px 3px; }}
  table.ptt td {{ font-size:9px; padding:1px 3px; }}
  ul.notes li {{ font-size:9px; margin-bottom:2px; line-height:1.35; }}
  .chartrow {{ gap:5px; }}
}}"""

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate opponent scouting report from SSA data")
    parser.add_argument("--team",    required=True, help='Team name to scout, e.g. "Hungary" or "China"')
    parser.add_argument("--players", default=None,  help='Override roster: comma-separated player names')
    parser.add_argument("--seed",    default=None,  help='Tournament seed number (optional)')
    parser.add_argument("--color",   default="#C8102E", help='Accent color hex (default: red)')
    parser.add_argument("--period",  default="SEASON",
                        choices=["SEASON","LAST_1","LAST_3","LAST_5"], help='Data period')
    parser.add_argument("--title",   default=None,  help='Override report title (default: "<TEAM> — SCOUTING REPORT")')
    parser.add_argument("--primary", default=None,  help='Comma-separated name fragment(s) for PRIMARY THREAT badge (e.g. "hank" or "raneem,hank")')
    args = parser.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Missing ANTHROPIC_API_KEY in .env"); sys.exit(1)

    ensure_court_png()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Build roster
    player_names = [n.strip() for n in args.players.split(",")] if args.players else None
    roster = lookup_roster(conn, args.team, player_names)
    if not roster:
        print(f"No players found for team '{args.team}'. Use --players to specify names manually.")
        sys.exit(1)

    team_name = args.title or f"{args.team.upper()} WNT — SCOUTING REPORT"
    seed_str  = f"Seed #{args.seed} | " if args.seed else ""
    accent    = args.color
    period    = args.period
    slug      = args.team.lower().replace(" ", "_")
    out_path  = os.path.join(BASE_DIR, f"{slug}_scout_report.html")
    primary_names = set(n.strip().lower() for n in args.primary.split(",")) if args.primary else set()

    print(f"Generating {team_name} scouting report | {len(roster)} players | period={period}")

    team_html = render_team_section(conn, args.team, period, accent)

    cards_html = ""
    for player in roster:
        print(f"\n[{player['full_name']}]")
        cards_html += player_card(conn, player, period, team_name, accent, primary_names)

    css = build_css(accent)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{team_name}</title>
<style>{css}</style>
</head>
<body>
<div class="hdr">
  <h1>{escape(team_name)}</h1>
  <h2>{seed_str}Opponent Analysis for Canada WNT Coaching Staff</h2>
  <div class="sub">Data: SSA (strongsideanalytics.com) | Season 2026 | AI analysis: Claude claude-opus-4-8</div>
</div>
<div class="snote">
  All AI insights (strengths / weaknesses / how to exploit) generated by Claude claude-opus-4-8 from SSA data.
  Players with both WNT and Clubs data show a toggle in the header — click to switch views.
  AI analysis uses the source with most games. Players with &lt;5 games flagged as small sample.
</div>
{team_html}
{cards_html}
<div class="footer">Generated by SSA Basketball Scout System · Claude AI · {period}</div>
<script>
function switchCT(btn, ct, cardId) {{
  var card = document.getElementById('card-' + cardId);
  card.querySelectorAll('.ct-btn').forEach(function(b) {{ b.classList.remove('ct-btn-active'); }});
  btn.classList.add('ct-btn-active');
  card.querySelectorAll('.ct-panel').forEach(function(p) {{
    p.style.display = p.dataset.ct === ct ? '' : 'none';
  }});
}}
</script>
</body>
</html>"""

    # Embed court PNG as base64 — makes file fully self-contained
    court_png = os.path.join(BASE_DIR, "shooting-map-sm.png")
    if os.path.exists(court_png):
        with open(court_png, "rb") as f:
            court_b64 = base64.b64encode(f.read()).decode()
        html = html.replace('href="shooting-map-sm.png"',
                            f'href="data:image/png;base64,{court_b64}"')

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n✅ Saved → {out_path}  (self-contained)")

if __name__ == "__main__":
    main()
