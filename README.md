# SSA Scraper — Canada WNT

Scrapes all data from [Strong Side Analytics](https://www.strongsideanalytics.com) for Canada WNT.

Mirrors the structure of the Synergy scraper in CoachVision.

---

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create your .env file
cp .env.example .env
# Edit .env and fill in your SSA credentials

# 3. Create output directories (auto-created on first run, but just in case)
mkdir -p data/raw data/db
```

---

## Usage

### Scrape everything (team + all players, last 3 games)
```bash
python scrape_ssa.py
```

### Scrape full season
```bash
python scrape_ssa.py --period CURRENT_SEASON
```

### Scrape last 5 games
```bash
python scrape_ssa.py --period LAST_5
```

### Scrape team data only (skip per-player)
```bash
python scrape_ssa.py --team-only
```

### Scrape a single player
```bash
python scrape_ssa.py \
  --player-id d29fd8da-3ead-4c41-aa12-b496fb0debe9 \
  --player-name "Paige Crozon"
```

### Load scraped JSON into SQLite
```bash
python load_ssa_db.py
```

---

## What gets scraped

### Team level
| File pattern | Contents |
|---|---|
| `*_team_*_overall_*.json` | Points, possessions, shooting splits, rebounds, assists, turnovers, blocks, steals, fouls |
| `*_team_*_additional_offense_*.json` | Shooting efficiency, shooting value |
| `*_team_*_play_types_*.json` | Set play / open play / transition breakdown (offense + defense) |
| `*_team_*_defensive_*.json` | Defensive stats |
| `*_team_*_matches.json` | All game results with scores |
| `*_team_*_info.json` | Team metadata + roster |

### Player level (per player on roster)
| File pattern | Contents |
|---|---|
| `*_player_*_overall_*.json` | Full box stats |
| `*_player_*_additional_offense_*.json` | Shooting efficiency |
| `*_player_*_play_types_*.json` | Play type breakdown |
| `*_player_*_defensive_*.json` | Defensive stats |
| `*_player_*_shot_chart_*.json` | Shot zone data |

---

## Data flow

```
SSA API
  ↓
scrape_ssa.py          → data/raw/*.json
  ↓
load_ssa_db.py         → data/db/ssa.db
  ↓
SQLite tables:
  ssa_team_stats
  ssa_player_stats
  ssa_player_play_types
  ssa_matches
```

---

## Known IDs

| Entity | ID |
|---|---|
| Canada WNT | `4f9b83f2-8209-4e04-a9bb-6fcd0a03f739` |
| 2026 FIBA CUPS season | `cba189ee-e4b9-47c1-a650-437e3828160d` |

---

## Troubleshooting

**Player endpoints return 404**
The shot_chart and additional_offense player endpoints are inferred from the team endpoint pattern.
If they 404, open the network tab on a player profile page in SSA and copy the actual URL paths,
then update `ssa_functions.py` accordingly.

**Roster not found**
If `get_team_info` returns no players array, check `data/raw/*_team_info.json` to see
what field the roster is nested under. Update `get_roster()` in `scrape_ssa.py`.

**Token expired mid-scrape**
The token lasts 1 hour. For large scrapes, add token refresh logic using
`sf.refresh_access_token(session, refresh_token)` in `scrape_ssa.py`.
