"""
Strong Side Analytics (SSA) API functions.
Mirrors the structure of synergy_functions.py in your CoachVision project.

API Base: https://www.strongsideanalytics.com/ssa-be/api/v1/
Auth:     POST /auth/login → JWT Bearer token (1hr) + refresh token

Discovered endpoints (from network inspection, Jun 2026):
  POST /auth/login
  POST /reporting/team/{teamId}/overall/{period}/{competitionType}
  POST /reporting/team/{teamId}/overall-additional-offensive/{period}/{competitionType}
  POST /reporting/team/{teamId}/play-types/{period}/{competitionType}
  POST /reporting/team/{teamId}/defensive/{period}/{competitionType}
  POST /reporting/player/{playerId}/overall/{period}/{competitionType}
  POST /reporting/player/{playerId}/play-types/{period}/{competitionType}
  POST /reporting/player/{playerId}/shot-chart/{period}/{competitionType}
  GET  /matches?teamId=&seasonId=&page=&size=&sort=id&direction=DESC
  GET  /teams/{teamId}?includePlayers=true
  GET  /players/{playerId}
"""

import requests
import json
import os
import re
import platform
from datetime import datetime


BASE_URL = "https://www.strongsideanalytics.com/ssa-be/api/v1"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class CONSTANTS:
    # Period filters — used as path segment in reporting URLs
    PERIODS = {
        "last_1":         "LAST_1",
        "last_3":         "LAST_3",
        "last_5":         "LAST_5",
        "last_10":        "LAST_10",
        "season":         "SEASON",
        "current_season": "CURRENT_SEASON",
        "all":            "ALL",
    }

    # Competition types — used as path segment in reporting URLs
    COMPETITION_TYPES = {
        "national_teams": "NATIONAL_TEAMS",
        "clubs":          "CLUBS",
    }

    # Report endpoint suffixes (path segment after teamId/playerId/overall)
    REPORT_ENDPOINTS = {
        "overall":              "overall",
        "additional_offense":   "overall-additional-offensive",
        "play_types":           "play-types",
        "defensive":            "defensive",
        "shot_chart":           "shot-chart",
    }

    # Known season IDs (add more here as seasons are created in SSA)
    SEASON_IDS = {
        "2026 FIBA CUPS": "cba189ee-e4b9-47c1-a650-437e3828160d",
    }

    # Known team IDs
    TEAM_IDS = {
        "Canada WNT": "4f9b83f2-8209-4e04-a9bb-6fcd0a03f739",
    }


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def make_windows_safe(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", name)


def write_data(path: str, data) -> None:
    try:
        if platform.system() == "Windows":
            path = make_windows_safe(path)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        print(f"  Saved → {path}")
    except Exception as e:
        print(f"  ERROR saving {path}: {e}")


def flatten_stats(stats: list[dict], mode: str = "total") -> dict:
    """
    Convert SSA's label/values array into a plain dict.

    Args:
        stats: Raw response list from any reporting endpoint
               e.g. [{"label": "POINTS", "values": {"total": 15.11, "perGame": 13.33}}, ...]
        mode:  "total" or "perGame"

    Returns:
        {"POINTS": 15.11, "POSSESSIONS": 37.89, ...}
    """
    if not isinstance(stats, list):
        return {}
    return {
        item["label"]: item["values"].get(mode)
        for item in stats
        if isinstance(item, dict) and "label" in item and "values" in item
    }


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def get_access_token(
    session: requests.Session,
    username: str,
    password: str,
) -> tuple[str, str]:
    """
    Authenticate with SSA using email + password.
    Returns (access_token, refresh_token).

    Token expires in 3600 seconds. Use refresh_access_token() to renew.
    """
    resp = session.post(
        f"{BASE_URL}/auth/login",
        json={"username": username, "password": password, "grantType": "password"},
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    print(f"SSA authenticated. Token expires in {data.get('expiresIn', 3600)}s.")
    return data["token"], data["refreshToken"]


def refresh_access_token(
    session: requests.Session,
    refresh_token: str,
) -> tuple[str, str]:
    """
    Renew an expired access token.
    Returns (new_access_token, new_refresh_token).
    """
    resp = session.post(
        f"{BASE_URL}/auth/refresh",
        json={"refreshToken": refresh_token},
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["token"], data["refreshToken"]


def _headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }


def _report_post(
    session: requests.Session,
    access_token: str,
    url: str,
    season_id: str,
    match_ids: list,
) -> list | dict:
    """Shared POST body for all reporting endpoints."""
    resp = session.post(
        url,
        json={"matchIds": match_ids or [], "seasonId": season_id},
        headers=_headers(access_token),
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Team reporting
# ---------------------------------------------------------------------------

def get_team_overall(
    session, access_token, team_id, season_id,
    period="LAST_3", competition_type="NATIONAL_TEAMS", match_ids=None,
) -> list[dict]:
    """
    Overall team box stats (possessions, points, shooting splits, rebounds, etc.).
    Confirmed endpoint: POST /reporting/team/{teamId}/overall/{period}/{competitionType}
    """
    url = f"{BASE_URL}/reporting/team/{team_id}/overall/{period}/{competition_type}"
    return _report_post(session, access_token, url, season_id, match_ids)


def get_team_additional_offense(
    session, access_token, team_id, season_id,
    period="LAST_3", competition_type="NATIONAL_TEAMS", match_ids=None,
) -> list[dict]:
    """Offense play-type breakdown: Set Play, Open Play (cleared by pass/dribble), Transition."""
    url = f"{BASE_URL}/reporting/team/{team_id}/overall-additional-offensive/{period}/{competition_type}"
    return _report_post(session, access_token, url, season_id, match_ids)


def get_team_additional_defense(
    session, access_token, team_id, season_id,
    period="LAST_3", competition_type="NATIONAL_TEAMS", match_ids=None,
) -> list[dict]:
    """Defense play-type breakdown: Set Play, Open Play (cleared by pass/dribble), Transition."""
    url = f"{BASE_URL}/reporting/team/{team_id}/overall-additional-defensive/{period}/{competition_type}"
    return _report_post(session, access_token, url, season_id, match_ids)


def get_team_play_types(
    session, access_token, team_id, season_id,
    period="LAST_3", competition_type="NATIONAL_TEAMS", match_ids=None,
) -> list[dict]:
    """Individual play-type breakdown (CUT, PNR, ISO, SPOT_UP, etc.) — offense side."""
    url = f"{BASE_URL}/reporting/team/{team_id}/offense/{period}/{competition_type}"
    return _report_post(session, access_token, url, season_id, match_ids)


def get_team_defensive(
    session, access_token, team_id, season_id,
    period="LAST_3", competition_type="NATIONAL_TEAMS", match_ids=None,
) -> list[dict]:
    """Defensive stats for the team."""
    url = f"{BASE_URL}/reporting/team/{team_id}/overall-additional-defensive/{period}/{competition_type}"
    return _report_post(session, access_token, url, season_id, match_ids)


# ---------------------------------------------------------------------------
# Player reporting
# ---------------------------------------------------------------------------

def get_player_overall(
    session, access_token, player_id, season_id,
    period="LAST_3", competition_type="NATIONAL_TEAMS", match_ids=None,
) -> list[dict]:
    """Overall stats for a single player."""
    url = f"{BASE_URL}/reporting/player/{player_id}/overall/{period}/{competition_type}"
    return _report_post(session, access_token, url, season_id, match_ids)


def get_player_additional_offense(
    session, access_token, player_id, season_id,
    period="LAST_3", competition_type="NATIONAL_TEAMS", match_ids=None,
) -> list[dict]:
    """Additional offensive metrics for a single player."""
    url = f"{BASE_URL}/reporting/player/{player_id}/overall-additional-offensive/{period}/{competition_type}"
    return _report_post(session, access_token, url, season_id, match_ids)


def get_player_play_types(
    session, access_token, player_id, season_id,
    period="LAST_3", competition_type="NATIONAL_TEAMS", match_ids=None,
) -> list[dict]:
    """Individual play-type breakdown for a player (CUT, PNR, ISO, HANDOFF, etc.)."""
    url = f"{BASE_URL}/reporting/player/{player_id}/offense/{period}/{competition_type}"
    return _report_post(session, access_token, url, season_id, match_ids)


def get_player_offense_play_types(
    session, access_token, player_id, season_id,
    period="LAST_3", competition_type="NATIONAL_TEAMS", match_ids=None,
) -> list[dict]:
    """Offense play-type summary: Set Play, Open Play (cleared by pass/dribble), Transition."""
    url = f"{BASE_URL}/reporting/player/{player_id}/overall-additional-offensive/{period}/{competition_type}"
    return _report_post(session, access_token, url, season_id, match_ids)


def get_player_defense_play_types(
    session, access_token, player_id, season_id,
    period="LAST_3", competition_type="NATIONAL_TEAMS", match_ids=None,
) -> list[dict]:
    """Defense play-type summary: Set Play, Open Play (cleared by pass/dribble), Transition."""
    url = f"{BASE_URL}/reporting/player/{player_id}/overall-additional-defensive/{period}/{competition_type}"
    return _report_post(session, access_token, url, season_id, match_ids)


def get_player_shooting_tendency(
    session, access_token, player_id, season_id,
    period="LAST_3", competition_type="NATIONAL_TEAMS", match_ids=None,
) -> list[dict]:
    """Overall shooting report: short/mid/2pt by dribble jumper vs no-dribble, left/right hand."""
    url = f"{BASE_URL}/reporting/player/{player_id}/shooting/tendency/{period}/{competition_type}"
    return _report_post(session, access_token, url, season_id, match_ids)


def get_player_shooting_tendency_dribble(
    session, access_token, player_id, season_id,
    period="LAST_3", competition_type="NATIONAL_TEAMS", match_ids=None,
) -> list[dict]:
    """Dribble jumper tendency: by play type (PNR, Handoff, ISO, etc.) and hand (left/right)."""
    url = f"{BASE_URL}/reporting/player/{player_id}/shooting/tendency/dribble/{period}/{competition_type}"
    return _report_post(session, access_token, url, season_id, match_ids)


def get_player_shooting_tendency_finishing(
    session, access_token, player_id, season_id,
    period="LAST_3", competition_type="NATIONAL_TEAMS", match_ids=None,
) -> list[dict]:
    """Finishing at the rim: layup/floater/hook by hand (left/right), made/attempted/%."""
    url = f"{BASE_URL}/reporting/player/{player_id}/shooting/tendency/finishing/{period}/{competition_type}"
    return _report_post(session, access_token, url, season_id, match_ids)


# ---------------------------------------------------------------------------
# Team metadata & roster
# ---------------------------------------------------------------------------

def get_team_info(
    session, access_token, team_id, include_players: bool = True,
) -> dict:
    """
    Fetch team metadata + roster (player IDs, names, numbers).
    includePlayers=true returns the full roster array.
    """
    params = {"includePlayers": "true"} if include_players else {}
    resp = session.get(
        f"{BASE_URL}/teams/{team_id}",
        params=params,
        headers=_headers(access_token),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_player_info(session, access_token, player_id) -> dict:
    """Fetch player metadata (name, number, position, nationality, etc.)."""
    resp = session.get(
        f"{BASE_URL}/players/{player_id}",
        headers=_headers(access_token),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------

def get_team_matches(
    session, access_token, team_id, season_id,
    page: int = 0, size: int = 50,
) -> list[dict]:
    """Paginated match list for a team."""
    resp = session.get(
        f"{BASE_URL}/matches",
        params={
            "teamId":    team_id,
            "seasonId":  season_id,
            "page":      page,
            "size":      size,
            "sort":      "id",
            "direction": "DESC",
        },
        headers=_headers(access_token),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_all_team_matches(
    session, access_token, team_id, season_id, page_size: int = 50,
) -> list[dict]:
    """Fetch all pages of matches for a team."""
    all_matches, page = [], 0
    while True:
        data = get_team_matches(session, access_token, team_id, season_id, page, page_size)
        if isinstance(data, dict):
            batch = data.get("content") or data.get("result") or []
            total_pages = data.get("totalPages", 1)
        else:
            batch = data
            total_pages = 1
        if not batch:
            break
        all_matches.extend(batch)
        if page >= total_pages - 1:
            break
        page += 1
    return all_matches


# ---------------------------------------------------------------------------
# Season-wide match discovery (all teams)
# ---------------------------------------------------------------------------

def get_season_matches_page(
    session, access_token, season_id,
    page: int = 0, size: int = 50,
    competition_type: str = "NATIONAL_TEAMS",
    sex: str = "FEMALE",
    extra_params: dict = None,
) -> dict:
    """
    Fetch a page of all matches for a season across all teams.
    Tries multiple param combinations since the exact filter key is unknown.

    Returns raw response dict (may have 'content', 'totalPages', etc.)
    or a list depending on what the endpoint returns.
    """
    base_params = {
        "seasonId":        season_id,
        "page":            page,
        "size":            size,
        "sort":            "id",
        "direction":       "DESC",
        "competitionType": competition_type,
    }
    if sex:
        base_params["sex"] = sex
    if extra_params:
        base_params.update(extra_params)

    resp = session.get(
        f"{BASE_URL}/matches",
        params=base_params,
        headers=_headers(access_token),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def discover_all_teams(
    session, access_token, season_id,
    competition_type: str = "NATIONAL_TEAMS",
    sex: str = "FEMALE",
    page_size: int = 50,
) -> dict[str, str]:
    """
    Paginate through all season matches and extract every unique team.

    Returns:
        {team_id: team_name} dict for all teams found
    """
    teams = {}
    page = 0

    while True:
        try:
            data = get_season_matches_page(
                session, access_token, season_id,
                page=page, size=page_size,
                competition_type=competition_type, sex=sex,
            )
        except Exception as e:
            print(f"  Error fetching matches page {page}: {e}")
            break

        # Handle both paginated {content: [...]} and flat list responses
        if isinstance(data, dict):
            matches = data.get("content") or data.get("result") or []
            total_pages = data.get("totalPages", 1)
        elif isinstance(data, list):
            matches = data
            total_pages = 1
        else:
            break

        for m in matches:
            for side in ("home", "away"):
                tid  = m.get(f"{side}TeamId")
                name = m.get(f"{side}TeamName")
                sex_field = m.get(f"{side}TeamSex", "")
                if tid and name and sex_field == sex:
                    teams[tid] = name

        if not matches or page >= total_pages - 1:
            break
        page += 1

    return teams
