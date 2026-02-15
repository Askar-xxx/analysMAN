"""
Модуль для извлечения структурированных данных из enriched_context
для последующего рендеринга в PNG таблицу.
"""
import logging
import re
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


def extract_tournament_position(enriched_data: dict, team_name: str) -> str:
    """
    Извлекает турнирное положение команды из standings.

    Args:
        enriched_data: dict с ключами h2h, standings, team1_form, team2_form
        team_name: Название команды для поиска

    Returns:
        Строка формата "#5 место (зона ЛЧ), 43 очка после 23 матчей"
        или "Нет данных" если не найдено
    """
    standings = enriched_data.get('standings', {})
    table = standings.get('table', [])

    for entry in table:
        if entry['name'] == team_name or team_name in entry['name'] or entry['name'] in team_name:
            rank = entry['rank']
            points = entry['points']
            played = entry['played']

            # Определяем зону
            zone = ""
            if rank <= 4:
                zone = " (зона ЛЧ)"
            elif rank <= 7:
                zone = " (зона еврокубков)"
            elif rank >= 18:
                zone = " (зона вылета)"

            return f"#{rank} место{zone}, {points} очков после {played} матчей"

    return "Нет данных"


def extract_current_form(enriched_data: dict, team_name: str, is_home: bool) -> str:
    """
    Извлекает текущую форму команды (последние 6 матчей).

    Args:
        enriched_data: dict с данными
        team_name: Название команды
        is_home: True для домашней команды, False для выездной

    Returns:
        Строка формата "WWDWL (4 победы подряд)" или "Нет данных"
    """
    form_key = 'team1_form' if is_home else 'team2_form'
    form_matches = enriched_data.get(form_key, [])

    if not form_matches:
        return "Нет данных"

    # Формируем строку формы W/D/L
    form_str = ''
    for match in form_matches[:6]:  # Последние 6
        hs = int(match.get('home_score', 0) or 0)
        as_ = int(match.get('away_score', 0) or 0)

        # Определяем с какой стороны играла команда
        if match.get('home_team') == team_name:
            form_str += 'W' if hs > as_ else ('D' if hs == as_ else 'L')
        else:
            form_str += 'W' if as_ > hs else ('D' if hs == as_ else 'L')

    # Считаем статистику по форме
    wins = form_str.count('W')
    draws = form_str.count('D')
    losses = form_str.count('L')
    total = len(form_str)

    # Всегда добавляем комментарий с количеством побед/поражений
    comment = ""
    if wins >= losses:
        if wins > 0:
            comment = f" ({wins} побед в последних {total})"
    else:
        if losses > 0:
            comment = f" ({losses} поражений в последних {total})"

    return form_str + comment


def extract_home_away_form(enriched_data: dict, team_name: str, is_home: bool) -> str:
    """
    Извлекает форму дома/на выезде из enriched_data.

    Returns:
        Строка формата "Сильная дома: 12 очков в 6 матчах (4В,0Н,2П)"
    """
    form_key = 'team1_form' if is_home else 'team2_form'
    form_matches = enriched_data.get(form_key, [])

    if not form_matches:
        return "Нет данных"

    # Фильтруем только домашние/выездные матчи
    filtered = []
    for m in form_matches:
        if is_home and m.get('home_team') == team_name:
            filtered.append(m)
        elif not is_home and m.get('away_team') == team_name:
            filtered.append(m)

    if not filtered:
        return "Нет данных"

    # Считаем статистику
    wins = 0
    draws = 0
    losses = 0

    for match in filtered:
        hs = int(match.get('home_score', 0) or 0)
        as_ = int(match.get('away_score', 0) or 0)

        if is_home:
            if hs > as_:
                wins += 1
            elif hs == as_:
                draws += 1
            else:
                losses += 1
        else:
            if as_ > hs:
                wins += 1
            elif hs == as_:
                draws += 1
            else:
                losses += 1

    points = wins * 3 + draws
    total = len(filtered)

    # Оцениваем качество
    ppg = points / total if total > 0 else 0
    if ppg >= 2.0:
        quality = "Сильная"
    elif ppg >= 1.2:
        quality = "Средняя"
    else:
        quality = "Слабая"

    location = "дома" if is_home else "на выезде"

    return f"{quality} {location}: {points} очков в {total} матчах ({wins}В,{draws}Н,{losses}П)"


def extract_h2h_history(enriched_data: dict) -> List[str]:
    """
    Извлекает историю личных встреч.

    Returns:
        Список строк формата ["2024-09-15: Team1 1:4 Team2", ...]
        Или с заголовком о прошлых сезонах если h2h_is_current_season = False
    """
    h2h_matches = enriched_data.get('h2h', [])

    if not h2h_matches:
        return ["Нет данных"]

    result = []

    # Проверяем флаг: матчи из текущего сезона или fallback
    is_current_season = enriched_data.get('h2h_is_current_season', True)

    if not is_current_season:
        # Добавляем заголовок о прошлых сезонах
        result.append("⚠️ В текущем сезоне команды не встречались")
        result.append("Последние встречи из прошлых сезонов:")
        result.append("")  # Пустая строка для отступа

    for match in h2h_matches[:5]:  # Последние 5
        date = match.get('date', '')
        home = match.get('home_team', '')
        away = match.get('away_team', '')
        score = match.get('score', '?:?')
        result.append(f"{date}: {home} {score} {away}")

    return result


def extract_stats_trends(enriched_data: dict, team_name: str, is_home: bool) -> str:
    """
    Извлекает статистические тренды команды.

    Returns:
        Многострочный текст с процентами и средними значениями
    """
    form_key = 'team1_form' if is_home else 'team2_form'
    form_matches = enriched_data.get(form_key, [])

    if not form_matches:
        return "Нет данных"

    # Считаем статистику
    total = len(form_matches)
    scored_count = 0
    conceded_count = 0
    total_scored = 0
    total_conceded = 0

    for match in form_matches:
        hs = int(match.get('home_score', 0) or 0)
        as_ = int(match.get('away_score', 0) or 0)

        if match.get('home_team') == team_name:
            goals_for = hs
            goals_against = as_
        else:
            goals_for = as_
            goals_against = hs

        if goals_for > 0:
            scored_count += 1
        if goals_against > 0:
            conceded_count += 1

        total_scored += goals_for
        total_conceded += goals_against

    scored_pct = (scored_count / total * 100) if total > 0 else 0
    conceded_pct = (conceded_count / total * 100) if total > 0 else 0
    avg_scored = total_scored / total if total > 0 else 0
    avg_conceded = total_conceded / total if total > 0 else 0

    location = "домашних" if is_home else "выездных"

    lines = [
        f"• Забивают в {scored_pct:.0f}% матчей",
        f"• Пропускают в {conceded_pct:.0f}% {location} игр",
        f"• В среднем {avg_scored:.2f} гола за матч",
        f"• Пропускают {avg_conceded:.2f} в среднем"
    ]

    return "\n".join(lines)


def _compare_lineups(lineup1: List[dict], lineup2: List[dict], team_name: str) -> str:
    """
    Сравнивает два состава команды и возвращает описание изменений.

    Args:
        lineup1: Состав матча #2 (более старый)
        lineup2: Состав матча #3 (более новый)
        team_name: Название команды для фильтрации

    Returns:
        Строка с описанием изменений или "Изменений нет"
    """
    def get_starters(lineup: List[dict]) -> Set[str]:
        """Получить имена игроков основного состава для команды."""
        return {
            p.get('strPlayer', '')
            for p in lineup
            if p.get('strTeam') == team_name and p.get('strSubstitute') == 'No'
        }

    starters1 = get_starters(lineup1)
    starters2 = get_starters(lineup2)

    # Если составы идентичны
    if starters1 == starters2:
        return "Изменений нет"

    # Игроки которые выбыли
    removed = starters1 - starters2
    # Игроки которые добавлены
    added = starters2 - starters1

    changes = []

    # Показываем замены (максимум 2 для краткости)
    if removed and added:
        removed_list = list(removed)[:2]
        added_list = list(added)[:2]
        for i in range(min(len(removed_list), len(added_list))):
            changes.append(f"Замена: {removed_list[i]} → {added_list[i]}")

    # Показываем выбывших (если нет добавленных)
    elif removed:
        for player in list(removed)[:2]:
            changes.append(f"Исключён: {player}")

    # Показываем добавленных (если нет выбывших)
    elif added:
        for player in list(added)[:2]:
            changes.append(f"Добавлен: {player}")

    return "; ".join(changes) if changes else "Изменений нет"


def extract_lineup_changes(enriched_data: dict, team_name: str, is_home: bool) -> str:
    """
    Извлекает изменения в составе команды на основе последних матчей.

    Args:
        enriched_data: dict с данными включая team1_form, team2_form
        team_name: Название команды
        is_home: True для домашней команды

    Returns:
        Строка с описанием изменений или "Составы будут доступны после матча"
    """
    form_key = 'team1_form' if is_home else 'team2_form'
    form_matches = enriched_data.get(form_key, [])

    if len(form_matches) < 2:
        return "Составы будут доступны после матча"

    # Получаем event_id последних 2 матчей
    event_id_1 = form_matches[0].get('event_id')  # Более новый матч
    event_id_2 = form_matches[1].get('event_id')  # Более старый матч

    if not event_id_1 or not event_id_2:
        return "Составы будут доступны после матча"

    # Получаем составы для обоих матчей
    lineup_1 = enriched_data.get(f'lineup_{event_id_1}', [])
    lineup_2 = enriched_data.get(f'lineup_{event_id_2}', [])

    if not lineup_1 or not lineup_2:
        return "Составы будут доступны после матча"

    # Сравниваем составы (lineup_2 → lineup_1, от старого к новому)
    return _compare_lineups(lineup_2, lineup_1, team_name)


def build_table_data(match: dict, enriched_data: dict) -> dict:
    """
    Формирует структурированные данные для рендеринга таблицы.

    Args:
        match: dict матча с полями team1, team2, league, match_date
        enriched_data: dict с h2h, standings, team1_form, team2_form

    Returns:
        dict с данными для рендеринга таблицы:
        {
            'title': "Team1 — Team2, 16 Feb 2026",
            'team_left': "Team1",
            'team_right': "Team2",
            'tournament_position': {'left': "...", 'right': "..."},
            'current_form': {'left': "...", 'right': "..."},
            'home_away': {'left': "...", 'right': "..."},
            'key_player': {'left': "Нет данных", 'right': "Нет данных"},
            'injuries': {'left': "Нет данных", 'right': "Нет данных"},
            'history': ["...", "...", "..."],
            'stats_trends': {'left': "...", 'right': "..."}
        }
    """
    team1 = match.get('team1', 'Команда 1')
    team2 = match.get('team2', 'Команда 2')
    match_date = match.get('match_date', '')
    league = match.get('league', '')

    # Форматируем заголовок
    title = f"{team1} — {team2}, {match_date}"
    if league:
        title += f"\n{league}"

    # Извлекаем данные для таблицы
    data = {
        'title': title,
        'team_left': team1,
        'team_right': team2,
        'tournament_position': {
            'left': extract_tournament_position(enriched_data, team1),
            'right': extract_tournament_position(enriched_data, team2)
        },
        'current_form': {
            'left': extract_current_form(enriched_data, team1, is_home=True),
            'right': extract_current_form(enriched_data, team2, is_home=False)
        },
        'home_away': {
            'left': extract_home_away_form(enriched_data, team1, is_home=True),
            'right': extract_home_away_form(enriched_data, team2, is_home=False)
        },
        'lineup_changes': {
            'left': extract_lineup_changes(enriched_data, team1, is_home=True),
            'right': extract_lineup_changes(enriched_data, team2, is_home=False)
        },
        'history': extract_h2h_history(enriched_data),
        'stats_trends': {
            'left': extract_stats_trends(enriched_data, team1, is_home=True),
            'right': extract_stats_trends(enriched_data, team2, is_home=False)
        }
    }

    return data
