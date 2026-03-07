from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta
from typing import Dict, Iterable, List

from sync_matches import LEAGUE_WEIGHTS, STAGE_BONUSES, TEAM_ALIASES, TEAM_TIER_WEIGHTS


def _match_value(match: Dict, key: str, default=None):
    if hasattr(match, "keys"):
        try:
            return match[key]
        except Exception:
            return default
    return match.get(key, default)


def _canonicalize_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = (
        text.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u2010", "-")
        .replace("\u2011", "-")
        .replace("\u2012", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2212", "-")
    )
    text = text.replace("-", " ")
    text = text.replace("'", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_team_name(team_name: str) -> str:
    normalized = _canonicalize_text(team_name)
    return TEAM_ALIASES.get(normalized, normalized)


def _get_team_weight(team_name: str) -> int:
    normalized = _normalize_team_name(team_name)
    return TEAM_TIER_WEIGHTS.get(normalized, 0)


def _get_league_weight(league_name: str) -> int:
    league_lc = str(league_name or "").lower()
    for label, weight in LEAGUE_WEIGHTS.items():
        if label in league_lc:
            return weight
    return 12


def _get_stage_bonus(league_name: str) -> int:
    league_lc = str(league_name or "").lower()
    for markers, bonus in STAGE_BONUSES:
        if any(marker in league_lc for marker in markers):
            return bonus
    return 0


def _get_matchup_bonus(team1: str, team2: str) -> int:
    team1_weight = _get_team_weight(team1)
    team2_weight = _get_team_weight(team2)
    is_team1_tier_a = team1_weight >= 12
    is_team2_tier_a = team2_weight >= 12
    is_team1_tier_b = team1_weight >= 8
    is_team2_tier_b = team2_weight >= 8

    if is_team1_tier_a and is_team2_tier_a:
        return 12
    if (is_team1_tier_a and is_team2_tier_b) or (is_team2_tier_a and is_team1_tier_b):
        return 7
    if is_team1_tier_b and is_team2_tier_b:
        return 5
    return 0


def _get_premium_pair_bonus(match: Dict) -> int:
    league_weight = _get_league_weight(_match_value(match, "league"))
    team_weight = _get_team_weight(_match_value(match, "team1")) + _get_team_weight(_match_value(match, "team2"))
    if league_weight >= 28 and team_weight >= 16:
        return 4
    return 0


def _get_neutral_match_penalty(match: Dict) -> int:
    team1_weight = _get_team_weight(_match_value(match, "team1"))
    team2_weight = _get_team_weight(_match_value(match, "team2"))
    matchup_bonus = _get_matchup_bonus(_match_value(match, "team1"), _match_value(match, "team2"))
    stage_bonus = _get_stage_bonus(_match_value(match, "league"))
    if team1_weight == 0 and team2_weight == 0 and matchup_bonus == 0 and stage_bonus == 0:
        return 4
    return 0


def compute_catalog_score(match: Dict) -> int:
    league_weight = _get_league_weight(_match_value(match, "league"))
    team1_weight = _get_team_weight(_match_value(match, "team1"))
    team2_weight = _get_team_weight(_match_value(match, "team2"))
    matchup_bonus = _get_matchup_bonus(_match_value(match, "team1"), _match_value(match, "team2"))
    stage_bonus = _get_stage_bonus(_match_value(match, "league"))
    premium_pair_bonus = _get_premium_pair_bonus(match)
    neutral_match_penalty = _get_neutral_match_penalty(match)
    return (
        league_weight
        + team1_weight
        + team2_weight
        + matchup_bonus
        + stage_bonus
        + premium_pair_bonus
        - neutral_match_penalty
    )


def _parse_match_datetime(match: Dict) -> datetime | None:
    match_datetime_str = f"{_match_value(match, 'match_date')} {_match_value(match, 'match_time')}"
    try:
        return datetime.strptime(match_datetime_str, "%Y-%m-%d %H:%M")
    except Exception:
        return None


def _compute_time_boost(match: Dict, now: datetime) -> int:
    match_datetime = _parse_match_datetime(match)
    if match_datetime is None:
        return 0
    delta_seconds = (match_datetime - now).total_seconds()
    if delta_seconds < 0:
        return -6

    if match_datetime.date() == now.date():
        if delta_seconds <= 6 * 3600:
            return 12
        return 8

    if match_datetime.date() == (now + timedelta(days=1)).date():
        return 3

    return 0


def compute_profile_score(match: Dict, now: datetime) -> int:
    return compute_catalog_score(match) + _compute_time_boost(match, now)


def get_profile_score_breakdown(match: Dict, now: datetime) -> Dict[str, int]:
    catalog_score = compute_catalog_score(match)
    time_boost = _compute_time_boost(match, now)
    return {
        "catalog_score": catalog_score,
        "time_boost": time_boost,
        "profile_score": catalog_score + time_boost,
    }


def select_profile_matches(matches: Iterable[Dict], now: datetime, limit: int = 3) -> List[Dict]:
    candidates = list(matches)

    def sort_key(match: Dict):
        match_datetime = _parse_match_datetime(match)
        catalog_score = compute_catalog_score(match)
        profile_score = catalog_score + _compute_time_boost(match, now)
        return (
            -profile_score,
            match_datetime or datetime.max,
            -catalog_score,
            _match_value(match, "league", ""),
            _match_value(match, "team1", ""),
            _match_value(match, "team2", ""),
        )

    return sorted(candidates, key=sort_key)[:limit]
