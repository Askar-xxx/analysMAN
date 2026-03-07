from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Iterable

import database
from profile_ranking import get_profile_score_breakdown, select_profile_matches

logger = logging.getLogger(__name__)

FALLBACK_DESCRIPTION = (
    "Сейчас витрина обновляется. Нажмите Start, чтобы посмотреть доступные матчи."
)


def _format_match_day_label(match_date_raw: str, now: datetime) -> str:
    match_date = datetime.strptime(str(match_date_raw), "%Y-%m-%d").date()
    today = now.date()
    if match_date == today:
        return "Сегодня"
    if match_date == today + timedelta(days=1):
        return "Завтра"
    return match_date.strftime("%d.%m")


def build_dynamic_description(matches: Iterable[dict]) -> str:
    selected_matches = list(matches)
    if not selected_matches:
        return FALLBACK_DESCRIPTION

    now = datetime.now()
    lines = ["🔥 Самые интересные матчи с AI-разбором:", ""]
    for match in selected_matches:
        day_label = _format_match_day_label(match["match_date"], now)
        lines.append(
            f"{match['team1']} - {match['team2']} — {day_label}, {match['match_time']}"
        )
    lines.extend(["", "Нажмите Start и выберите матч!"])
    return "\n".join(lines)


async def update_dynamic_description(bot, now: datetime | None = None) -> str:
    current_time = now or datetime.now()
    candidates = database.get_visible_profile_candidates(
        sport="football",
        days_ahead=3,
        now=current_time,
    )
    selected_matches = select_profile_matches(candidates, current_time, limit=3)
    for match in selected_matches:
        breakdown = get_profile_score_breakdown(match, current_time)
        logger.info(
            "Description selected: %s - %s | %s %s | catalog=%s time=%s profile=%s",
            match["team1"],
            match["team2"],
            match["match_date"],
            match["match_time"],
            breakdown["catalog_score"],
            breakdown["time_boost"],
            breakdown["profile_score"],
        )
    description = build_dynamic_description(selected_matches)
    await bot.set_my_description(description=description)
    logger.info("Описание бота обновлено: %s матчей", len(selected_matches))
    return description
