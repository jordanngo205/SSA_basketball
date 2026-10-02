# SSA 3x3 Women's Series — Analytics Dashboard

**Live dashboard:** https://jordanngo205.github.io/SSA_basketball/

Scraper and auto-updating analytics dashboard for the SSA 3x3 Women's Series (2026–27), built on [Strong Side Analytics](https://www.strongsideanalytics.com) data for Canada Basketball. Covers women's national teams and club teams, with team, player, play-type and per-match stats.

---

## How it updates

A GitHub Actions workflow (`.github/workflows/update-dashboard.yml`) runs every day at 06:00 UTC:

1. `scrape_wnt_db.py --all-periods` — women's national teams
2. `scrape_clubs.py --discover` then `--all-women --all-periods` — club teams
3. `scrape_match_stats.py` — per-match team stats
4. `generate_dashboard.py` — rebuilds `docs/index.html`
5. Commits `docs/index.html` and `data/db/ssa.db` if anything changed

GitHub Pages serves the dashboard from `docs/`. The workflow needs `SSA_USERNAME` and `SSA_PASSWORD` set as repository secrets, and can also be run manually from the Actions tab.

---

## Local setup

```bash
pip install -r requirements.txt
cp .env.example .env      # fill in SSA_USERNAME and SSA_PASSWORD
mkdir -p data/raw data/db
```

Run the same pipeline as the workflow:

```bash
python scrape_wnt_db.py --all-periods
python scrape_clubs.py --discover
python scrape_clubs.py --all-women --all-periods
python scrape_match_stats.py
python generate_dashboard.py
```

---

## Files

| File | Purpose |
|---|---|
| `ssa_functions.py` | SSA API auth (JWT + refresh token) and endpoint helpers |
| `scrape_wnt_db.py` | National-team scraper, writes straight to SQLite |
| `scrape_clubs.py` | Club-team discovery and scraper |
| `scrape_match_stats.py` | Per-match team stats for every match in the DB |
| `discover_players.py` | Matches roster names to SSA player IDs, then scrapes them |
| `scrape_ssa.py` | Canada WNT team + player scraper to JSON (`data/raw/`) |
| `scrape_ssa_all_teams.py` | Same, for every WNT team in the 2026 FIBA CUPS |
| `load_ssa_db.py` | Loads `data/raw/*.json` into `data/db/ssa.db` |
| `generate_dashboard.py` | Builds the self-contained dashboard HTML |
| `scout.py`, `scout_claude.py`, `scout_groq.py` | AI opponent scouting reports from the SQLite stats |
| `generate_scout_report.py`, `generate_canada_report.py`, `report_html.py` | Printable scouting reports |

---

## Single-team JSON scraper

`scrape_ssa.py` pulls every data type on the SSA team page into `data/raw/`:

```bash
python scrape_ssa.py                              # team + players, last 3 games
python scrape_ssa.py --period CURRENT_SEASON      # full season
python scrape_ssa.py --period LAST_5              # last 5 games
python scrape_ssa.py --team-only                  # skip per-player
python scrape_ssa.py --player-id <uuid> --player-name "Name"
python load_ssa_db.py                             # load JSON into SQLite
```

### Known IDs

| Entity | ID |
|---|---|
| Canada WNT | `4f9b83f2-8209-4e04-a9bb-6fcd0a03f739` |
| 2026 FIBA CUPS season | `cba189ee-e4b9-47c1-a650-437e3828160d` |

---

## Troubleshooting

**Player endpoints return 404** — the shot_chart and additional_offense player endpoints are inferred from the team endpoint pattern. Copy the real paths from the network tab on an SSA player page and update `ssa_functions.py`.

**Roster not found** — check `data/raw/*_team_info.json` for the field the roster is nested under and update `get_roster()` in `scrape_ssa.py`.

**Token expired mid-scrape** — tokens last 1 hour. For long scrapes, call `sf.refresh_access_token(session, refresh_token)`.
