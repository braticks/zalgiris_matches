from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Tuple

SOFASCORE_TEAM_ID = 6662

TOURNAMENTS: Dict[str, Dict[str, Any]] = {
    "euroleague": {"name": "Eurolyga", "id": 138},
    "lkl": {"name": "LKL", "id": 975},
    "kmt": {"name": "KMT", "id": 11012},
}


def _season_text(season: Dict[str, Any]) -> str:
    parts = [season.get("name"), season.get("year")]
    return " ".join(str(part) for part in parts if part).lower()


def select_current_season(seasons: Iterable[Dict[str, Any]], now: datetime) -> Optional[Dict[str, Any]]:
    """Pick the season matching the current European basketball season."""
    seasons = [season for season in seasons if isinstance(season, dict) and season.get("id") is not None]
    if not seasons:
        return None

    start_year = now.year if now.month >= 7 else now.year - 1
    end_year = start_year + 1
    yy = start_year % 100
    yy_next = end_year % 100
    patterns = (
        f"{yy:02d}/{yy_next:02d}",
        f"{start_year}/{end_year}",
        f"{start_year}/{yy_next:02d}",
        f"{start_year}-{end_year}",
        f"{start_year}-{yy_next:02d}",
    )

    for season in seasons:
        text = _season_text(season)
        if any(pattern in text for pattern in patterns):
            return season

    # Some competitions use a single calendar year instead of 26/27 notation.
    for season in seasons:
        text = _season_text(season)
        if str(start_year) in text:
            return season

    return None


def _find_team_row(node: Any, context: Optional[str] = None) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if isinstance(node, list):
        for item in node:
            row, row_context = _find_team_row(item, context)
            if row is not None:
                return row, row_context
        return None, None

    if not isinstance(node, dict):
        return None, None

    local_context = context
    if isinstance(node.get("name"), str) and any(key in node for key in ("rows", "groups", "standings")):
        local_context = node["name"]

    rows = node.get("rows")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            team = row.get("team") or {}
            if isinstance(team, dict) and team.get("id") == SOFASCORE_TEAM_ID:
                return row, local_context

    for key, value in node.items():
        if key == "rows":
            continue
        if isinstance(value, (dict, list)):
            row, row_context = _find_team_row(value, local_context)
            if row is not None:
                return row, row_context

    return None, None


def parse_team_standing(payload: Any) -> Optional[Dict[str, Any]]:
    """Extract Žalgiris row from SofaScore standings JSON."""
    row, stage = _find_team_row(payload)
    if row is None:
        return None

    team = row.get("team") or {}
    result: Dict[str, Any] = {
        "position": row.get("position", row.get("rank")),
        "team": team.get("name") if isinstance(team, dict) else None,
        "matches": row.get("matches", row.get("played", row.get("gamesPlayed"))),
        "wins": row.get("wins"),
        "losses": row.get("losses"),
        "percentage": row.get("percentage"),
        "points": row.get("points"),
        "games_behind": row.get("gamesBehind"),
        "score_for": row.get("scoreFor"),
        "score_against": row.get("scoreAgainst"),
        "stage": stage,
    }
    return {key: value for key, value in result.items() if value is not None}
