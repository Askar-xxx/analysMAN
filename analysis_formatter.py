"""
Модуль для извлечения структурированных данных из enriched_context
для последующего рендеринга в PNG таблицу.
"""
import logging
import re
from typing import List, Set

logger = logging.getLogger(__name__)
EMPTY_ROW_MARKERS = {
    "нет данных",
    "составы будут доступны после матча",
    "недостаточно данных",
    "недостаточно данных по составам",
}
CUP_NAME_MARKERS = (
    "champions league",
    "europa league",
    "conference league",
    "лига чемпионов",
    "лига европы",
    "лига конференций",
)
DATA_LIMITED_BADGE = "[Данные ограничены]"


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

    return ""


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
        return ""

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
        Строка формата "Сильная дома: 12 очков в 6 матчах (4W,0D,2L)"
    """
    form_key = 'team1_form' if is_home else 'team2_form'
    form_matches = enriched_data.get(form_key, [])

    if not form_matches:
        return ""

    # Фильтруем только домашние/выездные матчи
    filtered = []
    for m in form_matches:
        if is_home and m.get('home_team') == team_name:
            filtered.append(m)
        elif not is_home and m.get('away_team') == team_name:
            filtered.append(m)

    if not filtered:
        return ""

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

    return f"{quality} {location}: {points} очков в {total} матчах ({wins}W,{draws}D,{losses}L)"


def extract_h2h_history(enriched_data: dict) -> List[str]:
    """
    Извлекает историю личных встреч.

    Returns:
        Список строк формата ["2024-09-15: Team1 1:4 Team2", ...]
        Или с заголовком о прошлых сезонах если h2h_is_current_season = False
    """
    h2h_matches = enriched_data.get('h2h', [])

    if not h2h_matches:
        return []

    result = []

    # Проверяем флаг: матчи из текущего сезона или fallback
    is_current_season = enriched_data.get('h2h_is_current_season', True)

    if is_current_season and len(h2h_matches) == 1:
        result.append("В текущем сезоне пока только 1 очная встреча:")
        result.append("")  # Пустая строка для отступа
    elif not is_current_season:
        # Добавляем заголовок о прошлых сезонах
        result.append("В текущем сезоне команды не встречались")
        result.append("Последние встречи из прошлых сезонов:")
        result.append("")  # Пустая строка для отступа

    # Выводим все доступные матчи (до 10)
    for match in h2h_matches:
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
        return ""

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
        return "Состав без изменений"

    # Игроки которые выбыли
    removed = starters1 - starters2
    # Игроки которые добавлены
    added = starters2 - starters1

    changes = []

    # Показываем замены (максимум 2 для краткости)
    if removed and added:
        removed_list = sorted(removed)[:2]
        added_list = sorted(added)[:2]
        for i in range(min(len(removed_list), len(added_list))):
            changes.append(f"• {removed_list[i]} → {added_list[i]}")

    # Показываем выбывших (если нет добавленных)
    elif removed:
        for player in sorted(removed)[:2]:
            changes.append(f"• Вне старта: {player}")

    # Показываем добавленных (если нет выбывших)
    elif added:
        for player in sorted(added)[:2]:
            changes.append(f"• В старте: {player}")
    if not changes:
        return "Состав без изменений"
    return "Изменения в старте:\n" + "\n".join(changes)


def extract_lineup_changes(enriched_data: dict, team_name: str, is_home: bool) -> str:
    """
    Извлекает изменения в составе команды на основе последних матчей.

    Args:
        enriched_data: dict с данными включая team1_form, team2_form
        team_name: Название команды
        is_home: True для домашней команды

    Returns:
        Строка с описанием изменений стартового состава или пустая строка.
    """
    form_key = 'team1_form' if is_home else 'team2_form'
    form_matches = enriched_data.get(form_key, [])

    if len(form_matches) < 2:
        return ""

    # Берём первые 2 матча формы, для которых реально есть lineup,
    # чтобы не падать в заглушку из-за одного пустого события.
    lineup_event_ids = []
    for form_match in form_matches:
        event_id = form_match.get('event_id')
        if not event_id:
            continue
        if enriched_data.get(f'lineup_{event_id}'):
            lineup_event_ids.append(event_id)
        if len(lineup_event_ids) >= 2:
            break

    if len(lineup_event_ids) < 2:
        return ""

    event_id_1 = lineup_event_ids[0]  # Более новый матч
    event_id_2 = lineup_event_ids[1]  # Более старый матч
    lineup_1 = enriched_data.get(f'lineup_{event_id_1}', [])
    lineup_2 = enriched_data.get(f'lineup_{event_id_2}', [])

    # Сравниваем составы (lineup_2 → lineup_1, от старого к новому)
    return _compare_lineups(lineup_2, lineup_1, team_name)


def extract_last_match_events(enriched_data: dict, is_home: bool) -> str:
    """
    Извлекает события последнего матча (замены/карточки) по команде.

    Returns:
        Многострочная строка или пустая строка, если данных нет.
    """
    key = 'team1_last_match_events' if is_home else 'team2_last_match_events'
    events = enriched_data.get(key) or {}
    substitutions = events.get('subs') or []
    cards = events.get('cards') or []

    lines = []
    if substitutions:
        lines.append("Замены по ходу:")
        lines.extend([f"• {item}" for item in substitutions[:3]])
    if cards:
        lines.append("Карточки:")
        lines.extend([f"• {item}" for item in cards[:3]])

    return "\n".join(lines) if lines else ""


def extract_domestic_position(enriched_data: dict, is_home: bool) -> str:
    """Возвращает позицию команды в домашней лиге (для кубков). Пустая строка если нет данных."""
    key = 'team1_domestic_position' if is_home else 'team2_domestic_position'
    return enriched_data.get(key, '') or ''


def extract_cup_path(enriched_data: dict, is_home: bool) -> str:
    """Возвращает краткий кубковый путь команды (для кубков). Пустая строка если нет данных."""
    key = 'team1_cup_path' if is_home else 'team2_cup_path'
    path_rows = enriched_data.get(key, []) or []
    if not path_rows:
        return ''
    return "\n".join(path_rows[:3])


def _is_cup_match(match: dict, enriched_data: dict) -> bool:
    """Определить, является ли матч кубковым."""
    if enriched_data.get('is_cup') is True:
        return True
    league_name = (match.get('league') or '').lower()
    return any(marker in league_name for marker in CUP_NAME_MARKERS)


def _format_cup_round_label(round_num: int) -> str:
    round_map = {
        64: "1/32 финала",
        32: "1/16 финала",
        16: "1/8 финала",
        8: "1/4 финала",
        4: "1/2 финала",
        2: "Финал",
        1: "Финал",
    }
    return round_map.get(round_num, f"Раунд {round_num}")


def _normalize_league_display(league: str, is_cup: bool) -> str:
    """
    Нормализует подпись турнира в заголовке карточки.
    Для еврокубков конвертирует паттерн "32 тур" -> "1/16 финала".
    """
    if not league:
        return league
    if not is_cup:
        return league

    match = re.match(r"^(?P<name>.+?)\.\s*(?P<round>\d+)\s*тур\s*$", league.strip(), flags=re.IGNORECASE)
    if not match:
        return league

    league_name = match.group("name").strip()
    round_num = int(match.group("round"))
    return f"{league_name}. {_format_cup_round_label(round_num)}"


def _normalize_lines(value: str) -> List[str]:
    return [line.strip().lower() for line in str(value or '').split('\n') if line.strip()]


def _has_meaningful_value(value: str) -> bool:
    """Проверяет, что значение не является заглушкой."""
    lines = _normalize_lines(value)
    if not lines:
        return False
    return any(line not in EMPTY_ROW_MARKERS for line in lines)


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
    is_cup = _is_cup_match(match, enriched_data)
    if league:
        title += f"\n{_normalize_league_display(league, is_cup=is_cup)}"

    # Извлекаем данные для таблицы (базовые поля сохраняем для совместимости)
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
        'last_match_events': {
            'left': extract_last_match_events(enriched_data, is_home=True),
            'right': extract_last_match_events(enriched_data, is_home=False)
        },
        'history': extract_h2h_history(enriched_data),
        'stats_trends': {
            'left': extract_stats_trends(enriched_data, team1, is_home=True),
            'right': extract_stats_trends(enriched_data, team2, is_home=False)
        },
        'is_cup': is_cup
    }

    rows = []

    # Для кубков используем другой профиль строк: домашняя позиция + кубковый путь.
    if is_cup:
        rows.append({
            'label': 'Лиговая позиция',
            'left': extract_domestic_position(enriched_data, is_home=True),
            'right': extract_domestic_position(enriched_data, is_home=False),
            'colspan': False
        })
        rows.append({
            'label': 'Кубковый путь',
            'left': extract_cup_path(enriched_data, is_home=True),
            'right': extract_cup_path(enriched_data, is_home=False),
            'colspan': False
        })
    else:
        rows.append({
            'label': 'Турнирное положение',
            'left': data['tournament_position']['left'],
            'right': data['tournament_position']['right'],
            'colspan': False
        })

    rows.extend([
        {
            'label': 'Текущая форма',
            'left': data['current_form']['left'],
            'right': data['current_form']['right'],
            'colspan': False
        },
        {
            'label': 'Форма дома/на выезде',
            'left': data['home_away']['left'],
            'right': data['home_away']['right'],
            'colspan': False
        },
        {
            'label': 'Составы',
            'left': data['lineup_changes']['left'],
            'right': data['lineup_changes']['right'],
            'colspan': False
        },
        {
            'label': 'События последнего матча',
            'left': data['last_match_events']['left'],
            'right': data['last_match_events']['right'],
            'colspan': False
        },
        {
            'label': 'История встреч',
            'left': "\n".join(data['history']),
            'right': '',
            'colspan': True
        },
        {
            'label': 'Статистические тренды',
            'left': data['stats_trends']['left'],
            'right': data['stats_trends']['right'],
            'colspan': False
        },
    ])

    # Предрасчет заполненности до UI-адаптации:
    # эти метрики используются фильтром витрины и не зависят от подстановок.
    row_states = []
    for row in rows:
        left_has_data = _has_meaningful_value(row.get('left', ''))
        right_has_data = _has_meaningful_value(row.get('right', ''))
        row_states.append((row, left_has_data, right_has_data))

    raw_coverage_rows_count = 0
    raw_missing_cells_count = 0
    for row, left_has_data, right_has_data in row_states:
        if row.get('colspan'):
            if left_has_data:
                raw_coverage_rows_count += 1
            continue
        if left_has_data or right_has_data:
            raw_coverage_rows_count += 1
            if not left_has_data:
                raw_missing_cells_count += 1
            if not right_has_data:
                raw_missing_cells_count += 1

    # Адаптивный рендер: убираем строки, где реально нет данных.
    # Если данные есть только с одной стороны — явно помечаем пустую сторону.
    adaptive_rows = []
    for row, left_has_data, right_has_data in row_states:
        if row.get('colspan'):
            if left_has_data:
                adaptive_rows.append(row)
            continue
        if left_has_data or right_has_data:
            row = dict(row)  # копия чтобы не мутировать оригинал
            if not left_has_data:
                row['left'] = 'Недостаточно данных'
            if not right_has_data:
                row['right'] = 'Недостаточно данных'
            adaptive_rows.append(row)

    data['rows'] = adaptive_rows
    data['coverage_rows_count'] = len(adaptive_rows)
    data['raw_coverage_rows_count'] = raw_coverage_rows_count
    data['raw_missing_cells_count'] = raw_missing_cells_count
    expected_rows = len(rows) if rows else 1
    coverage_ratio = len(adaptive_rows) / expected_rows
    missing_cells = 0
    for row in adaptive_rows:
        if row.get('colspan'):
            continue
        for side in ('left', 'right'):
            if str(row.get(side, '')).strip().lower() == 'недостаточно данных':
                missing_cells += 1

    # Бейдж показываем только в реально плохих кейсах, чтобы не шуметь.
    is_data_limited = missing_cells >= 2 or coverage_ratio < 0.75
    data['is_data_limited'] = is_data_limited
    if is_data_limited and DATA_LIMITED_BADGE not in data['title']:
        data['title'] += f"\n{DATA_LIMITED_BADGE}"

    return data
