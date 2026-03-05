"""
Модуль для извлечения структурированных данных из enriched_context
для последующего рендеринга в PNG таблицу.
"""
import logging
import re
from typing import List

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
    "fa cup",
    "copa del rey",
    "dfb pokal",
    "coppa italia",
    "coupe de france",
    "carabao cup",
    "league cup",
)
DATA_LIMITED_BADGE = "[Данные ограничены]"

# Core rows — обязательные строки, которые не скрываются даже при пустых данных
CORE_LABELS = {
    'Турнирное положение', 'Лиговая позиция', 'Кубковый путь',
    'Текущая форма', 'Форма дома/на выезде',
    'История встреч', 'Статистические тренды',
}
# Optional rows скрываются если пусты с обеих сторон
OPTIONAL_LABELS = {'Изменения состава', 'События последнего матча'}


def _ru_plural(n: int, one: str, few: str, many: str) -> str:
    """Русские склонения: 1 матч, 2 матча, 5 матчей."""
    abs_n = abs(n)
    if abs_n % 10 == 1 and abs_n % 100 != 11:
        return one
    if 2 <= abs_n % 10 <= 4 and not (12 <= abs_n % 100 <= 14):
        return few
    return many


def _is_team_match(match: dict, side: str, team_name: str, team_id: str = '') -> bool:
    """
    Проверяет, является ли команда домашней/гостевой в матче.
    Приоритет: team_id, fallback на team_name.

    Args:
        match: dict матча
        side: 'home' или 'away'
        team_name: Название команды
        team_id: ID команды (приоритет)
    """
    if team_id:
        match_team_id = str(match.get(f'{side}_team_id', '') or '')
        if match_team_id and match_team_id == str(team_id):
            return True
        if match_team_id:
            return False
    # Fallback на строковое сравнение
    return match.get(f'{side}_team') == team_name


def extract_tournament_position(enriched_data: dict, team_name: str, team_id: str = '') -> str:
    """
    Извлекает турнирное положение команды из standings.

    Args:
        enriched_data: dict с ключами h2h, standings, team1_form, team2_form
        team_name: Название команды для поиска
        team_id: ID команды (приоритет над именем)

    Returns:
        Строка формата "#5 место (зона ЛЧ), 43 очка после 23 матчей"
        или "" если не найдено
    """
    standings = enriched_data.get('standings', {})
    table = standings.get('table', [])

    for entry in table:
        # Матчинг по ID (приоритет), fallback на имя
        if team_id and entry.get('team_id'):
            if entry['team_id'] != team_id:
                continue
        elif not (entry['name'] == team_name or team_name in entry['name'] or entry['name'] in team_name):
            continue

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

        pts_word = _ru_plural(points, 'очко', 'очка', 'очков')
        return f"#{rank} место{zone}, {points} {pts_word} после {played} матчей"

    return ""


def extract_current_form(enriched_data: dict, team_name: str, is_home: bool,
                         team_id: str = '') -> str:
    """
    Извлекает текущую форму команды (последние 5 матчей).

    Args:
        enriched_data: dict с данными
        team_name: Название команды
        is_home: True для домашней команды, False для выездной
        team_id: ID команды для точного матчинга (fallback на team_name)

    Returns:
        Строка формата "WWDWL (4 победы в последних 5)" или ""
    """
    form_key = 'team1_form' if is_home else 'team2_form'
    form_matches = enriched_data.get(form_key, [])

    if not form_matches:
        return ""

    # Формируем строку формы W/D/L
    form_str = ''
    for match in form_matches[:5]:  # Последние 5
        hs = int(match.get('home_score', 0) or 0)
        as_ = int(match.get('away_score', 0) or 0)

        # Определяем с какой стороны играла команда (приоритет ID, fallback имя)
        is_home_team = _is_team_match(match, 'home', team_name, team_id)
        is_away_team = _is_team_match(match, 'away', team_name, team_id)
        # Грязные данные: обе стороны совпадают — пропускаем
        if is_home_team and is_away_team:
            continue
        if is_home_team:
            form_str += 'W' if hs > as_ else ('D' if hs == as_ else 'L')
        else:
            # Либо явный матч гостя, либо имя не совпало (fallback — считаем как гость)
            form_str += 'W' if as_ > hs else ('D' if hs == as_ else 'L')

    # Защита: обрезаем до 5 символов на случай грязных данных
    form_str = form_str[:5]

    # Считаем статистику по форме
    wins = form_str.count('W')
    losses = form_str.count('L')
    total = len(form_str)

    # Всегда добавляем комментарий с количеством побед/поражений
    comment = ""
    if wins >= losses:
        if wins > 0:
            w_word = _ru_plural(wins, 'победа', 'победы', 'побед')
            comment = f" ({wins} {w_word} в последних {total})"
    else:
        if losses > 0:
            l_word = _ru_plural(losses, 'поражение', 'поражения', 'поражений')
            comment = f" ({losses} {l_word} в последних {total})"

    return form_str + comment


def extract_home_away_form(enriched_data: dict, team_name: str, is_home: bool,
                           team_id: str = '') -> str:
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
    filter_side = 'home' if is_home else 'away'
    filtered = []
    for m in form_matches:
        if _is_team_match(m, filter_side, team_name, team_id):
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

    pts_word = _ru_plural(points, 'очко', 'очка', 'очков')
    match_word = _ru_plural(total, 'матче', 'матчах', 'матчах')
    return f"{quality} {location}: {points} {pts_word} в {total} {match_word} ({wins}W,{draws}D,{losses}L)"


def extract_h2h_history(enriched_data: dict, team1: str = '', team2: str = '') -> List[str]:
    """
    Извлекает историю личных встреч.

    Args:
        enriched_data: dict с данными
        team1: Каноническое имя домашней команды (для нормализации)
        team2: Каноническое имя гостевой команды (для нормализации)

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
    h2h_season_source = enriched_data.get('h2h_season_source', 'search')
    is_cup = enriched_data.get('is_cup', False)
    tournament_label = "кубка" if is_cup else "лиги"

    if is_current_season and len(h2h_matches) == 1:
        result.append(f"В этом сезоне {tournament_label} сыграна 1 очная встреча:")
        result.append("")  # Пустая строка для отступа
    elif is_current_season and len(h2h_matches) > 1:
        result.append(f"Очные встречи в сезоне {tournament_label}: {len(h2h_matches)}")
        result.append("")
    elif not is_current_season:
        if h2h_season_source == 'schedule_confirmed':
            result.append(f"В этом сезоне {tournament_label} команды ещё не встречались.")
        else:
            result.append("Данные о встречах в текущем сезоне не найдены.")
        fallback_label = "Последние встречи из других турниров:" if is_cup \
            else "Последние встречи из прошлых сезонов:"
        result.append(fallback_label)
        result.append("")  # Пустая строка для отступа

    # Нормализация: API может возвращать разные написания (Wolves / Wolverhampton Wanderers).
    # Используем team_id из H2H данных (приоритет), fallback на точное совпадение алиаса.
    home_team_id = _normalize_team_id(enriched_data.get('_home_team_id'))
    away_team_id = _normalize_team_id(enriched_data.get('_away_team_id'))
    team1_meta = enriched_data.get('team1_meta') or {}
    team2_meta = enriched_data.get('team2_meta') or {}

    def _split_aliases(raw_value: str) -> List[str]:
        if not raw_value:
            return []
        return [part.strip() for part in re.split(r"[,;|/]", str(raw_value)) if part.strip()]

    def _collect_aliases(canonical_name: str, meta: dict) -> set:
        aliases = set()

        def _add(value: str):
            value = str(value or '').strip()
            if value:
                aliases.add(value.lower())

        _add(canonical_name)
        _add(meta.get('team_name', ''))
        _add(meta.get('team_short', ''))
        _add(meta.get('team_alternate', ''))
        for alias in meta.get('aliases', []) or []:
            _add(alias)
        for alias in _split_aliases(meta.get('team_alternate', '')):
            _add(alias)
        return aliases

    team1_aliases = _collect_aliases(team1, team1_meta)
    team2_aliases = _collect_aliases(team2, team2_meta)

    def normalize_team(h2h_match: dict, side: str) -> str:
        """Нормализует имя команды из H2H матча по team_id или точному совпадению алиаса."""
        api_name = h2h_match.get(f'{side}_team', '')
        api_tid = _normalize_team_id(h2h_match.get(f'{side}_team_id'))
        # Матчинг по ID (надёжный)
        if api_tid:
            if home_team_id and api_tid == home_team_id:
                return team1
            if away_team_id and api_tid == away_team_id:
                return team2
        # Точное совпадение имени
        if api_name:
            api_lc = api_name.strip().lower()
            if team1 and api_lc in team1_aliases:
                return team1
            if team2 and api_lc in team2_aliases:
                return team2
        return api_name

    # Выводим все доступные матчи (до 10)
    for match in h2h_matches:
        date = match.get('date', '')
        home = normalize_team(match, 'home')
        away = normalize_team(match, 'away')
        score = match.get('score', '?:?')
        result.append(f"{date}: {home} {score} {away}")

    return result


def extract_stats_trends(enriched_data: dict, team_name: str, is_home: bool,
                         team_id: str = '') -> str:
    """
    Извлекает статистические тренды команды.
    Использует расширенное окно (team*_trends_form, до 10 матчей) если доступно.

    Returns:
        Многострочный текст с дробями, процентами и средними значениями
    """
    # Приоритет: расширенное окно трендов (до 10), fallback на форму (5)
    trends_key = 'team1_trends_form' if is_home else 'team2_trends_form'
    form_key = 'team1_form' if is_home else 'team2_form'
    form_matches = enriched_data.get(trends_key) or enriched_data.get(form_key, [])

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

        if _is_team_match(match, 'home', team_name, team_id):
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

    lines = [
        f"• Забивают в {scored_pct:.0f}% последних матчей",
        f"• Пропускают в {conceded_pct:.0f}% последних матчей",
        f"• В среднем {avg_scored:.2f} гола за матч",
        f"• Пропускают {avg_conceded:.2f} в среднем"
    ]

    return "\n".join(lines)


def _get_stats_trends_window(enriched_data: dict, is_home: bool) -> int:
    """Возвращает окно матчей для блока статистических трендов."""
    window_key = 'team1_trends_window' if is_home else 'team2_trends_window'
    try:
        window = int(enriched_data.get(window_key) or 0)
        if window > 0:
            return window
    except Exception:
        pass

    trends_key = 'team1_trends_form' if is_home else 'team2_trends_form'
    form_key = 'team1_form' if is_home else 'team2_form'
    form_matches = enriched_data.get(trends_key) or enriched_data.get(form_key, [])
    return len(form_matches) if form_matches else 0


def _normalize_team_id(value) -> str:
    """Приводит None/int/str к строке с strip()."""
    if value is None:
        return ''
    return str(value).strip()


def _compare_lineups(lineup1: List[dict], lineup2: List[dict], team_name: str,
                     team_id: str = '', opponent_team_id: str = '') -> str:
    """
    Сравнивает два состава команды и возвращает описание изменений.
    С confidence-валидацией по team_id для фильтрации игроков соперника.

    Args:
        lineup1: Состав матча #2 (более старый)
        lineup2: Состав матча #3 (более новый)
        team_name: Название команды для фильтрации
        team_id: ID своей команды (нормализованный)
        opponent_team_id: ID команды-соперника (нормализованный)

    Returns:
        Строка с описанием изменений или "Изменений нет"
    """
    norm_team_id = _normalize_team_id(team_id)
    norm_opponent_id = _normalize_team_id(opponent_team_id)

    def classify_player(player: dict) -> str:
        """Классифицирует игрока: own / opponent / unknown.

        Lineup event'а содержит игроков обеих команд.
        strTeam != team_name — это нормально (игрок соперника в том же event),
        НЕ считается contamination. Contamination — только по idTeam,
        когда idTeam совпадает с opponent_team_id у игрока,
        чей strTeam == team_name (ошибка данных API).
        """
        p_team_name = player.get('strTeam', '')
        # Игрок с чужим strTeam — просто из другой команды в том же event, пропускаем
        if p_team_name and p_team_name != team_name:
            return 'other_team'
        # Игрок с strTeam == team_name — проверяем idTeam на contamination
        p_team_id = _normalize_team_id(player.get('idTeam'))
        if p_team_id:
            if norm_team_id and p_team_id == norm_team_id:
                return 'own'
            # Ключевое правило: если игрок помечен как наша команда по strTeam,
            # но его idTeam не совпадает с нашим team_id — это contamination.
            if norm_team_id and p_team_id != norm_team_id:
                return 'opponent'
            if norm_opponent_id and p_team_id == norm_opponent_id:
                return 'opponent'  # strTeam совпадает, но idTeam — соперника!
        # strTeam совпадает, idTeam нет или не заполнен
        if p_team_name == team_name:
            return 'own'
        return 'unknown'

    def get_starters(lineup: List[dict]) -> tuple:
        """Получить имена игроков основного состава + счётчики confidence."""
        own_players = set()
        opponent_count = 0
        unknown_count = 0
        total = 0
        own_count = 0
        for p in lineup:
            if p.get('strSubstitute') != 'No':
                continue
            cls = classify_player(p)
            if cls == 'other_team':
                continue  # игрок соперника из того же event — нормально, пропускаем
            total += 1
            if cls == 'own':
                own_players.add(p.get('strPlayer', ''))
                own_count += 1
            elif cls == 'opponent':
                opponent_count += 1
            else:
                unknown_count += 1
        return own_players, opponent_count, unknown_count, total, own_count

    starters1, opp1, unk1, tot1, own1 = get_starters(lineup1)
    starters2, opp2, unk2, tot2, own2 = get_starters(lineup2)

    total_players = tot1 + tot2
    total_opponent = opp1 + opp2
    total_unknown = unk1 + unk2

    # Confidence rules
    confidence = 'ok'
    if total_opponent > 0:
        confidence = 'contaminated'
        logger.debug(
            "Lineup confidence: contaminated (opponent_count=%d, unknown=%d, total=%d) team=%s",
            total_opponent, total_unknown, total_players, team_name
        )
    elif total_players > 0 and total_unknown / total_players > 0.4:
        confidence = 'low'
        logger.debug(
            "Lineup confidence: low (unknown=%d, total=%d, ratio=%.2f) team=%s",
            total_unknown, total_players, total_unknown / total_players, team_name
        )

    if confidence in ('contaminated', 'low'):
        return "Недостаточно надёжных данных по составам"

    # Если составы идентичны
    if starters1 == starters2:
        return "Состав без изменений"

    # Игроки которые выбыли
    removed = starters1 - starters2
    # Игроки которые добавлены
    added = starters2 - starters1

    changes = []
    is_partial_source = own1 < 11 or own2 < 11
    availability_note = (
        f"• Источник: старт {own2}/11 (последний), {own1}/11 (предыдущий)"
        if is_partial_source else ""
    )

    # Показываем списки выбывших и добавленных (без ложных "стрелочек замен")
    if removed:
        removed_list = ", ".join(sorted(removed)[:3])
        changes.append(f"• Выпали из старта: {removed_list}")
    if added:
        added_list = ", ".join(sorted(added)[:3])
        changes.append(f"• Вернулись в старт: {added_list}")

    if not changes:
        if is_partial_source:
            return (
                "Состав без изменений (по доступным данным)\n"
                + availability_note
            )
        return "Состав без изменений"

    lines = []
    if availability_note:
        lines.append(availability_note)
    lines.extend(changes)
    return "\n".join(lines)


def extract_lineup_changes(enriched_data: dict, team_name: str, is_home: bool,
                           team_id: str = '', opponent_team_id: str = '') -> str:
    """
    Извлекает изменения в составе команды на основе последних матчей.

    Args:
        enriched_data: dict с данными включая team1_form, team2_form
        team_name: Название команды
        is_home: True для домашней команды
        team_id: ID своей команды для confidence-валидации
        opponent_team_id: ID соперника для фильтрации

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
    result = _compare_lineups(lineup_2, lineup_1, team_name,
                              team_id=team_id, opponent_team_id=opponent_team_id)
    logger.debug(
        "Lineup changes for %s (team_id=%s): %s",
        team_name, team_id, result[:80] if result else '(empty)'
    )
    return result


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

    # Фильтрация плейсхолдерных имён
    placeholder_re = re.compile(r'^(Substitution \d+|Unknown|None)$', re.IGNORECASE)

    def _filter_placeholder_subs(subs: list) -> list:
        filtered = []
        for item in subs:
            parts = item.split(' → ')
            if any(placeholder_re.match(p.strip()) for p in parts):
                continue
            filtered.append(item)
        return filtered

    substitutions = _filter_placeholder_subs(substitutions)

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


def _sanitize_round_in_league(league: str, enriched_data: dict) -> str:
    """
    Убирает тур из заголовка лиги, если он сильно расходится с реальностью.
    Проверяет по standings.played обеих команд.
    """
    match = re.match(r"^(?P<name>.+?)\.\s*(?P<round>\d+)\s*тур\s*$", league.strip(), flags=re.IGNORECASE)
    if not match:
        return league

    round_num = int(match.group("round"))
    standings = enriched_data.get('standings', {})
    table = standings.get('table', [])
    if not table:
        return league

    played_values = [int(e.get('played', 0) or 0) for e in table if e.get('played')]
    if not played_values:
        return league

    # Ожидаемый тур ≈ max(played) + 1
    expected_round = max(played_values) + 1
    if abs(round_num - expected_round) > 2:
        return match.group("name").strip()

    return league


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
    home_team_id = str(match.get('home_team_id') or '')
    away_team_id = str(match.get('away_team_id') or '')
    match_date = match.get('match_date', '')
    league = match.get('league', '')

    # Форматируем заголовок
    title = f"{team1} — {team2}, {match_date}"
    is_cup = _is_cup_match(match, enriched_data)
    h2h_data = dict(enriched_data or {})
    if home_team_id:
        h2h_data['_home_team_id'] = home_team_id
    if away_team_id:
        h2h_data['_away_team_id'] = away_team_id

    if league:
        display_league = _normalize_league_display(league, is_cup=is_cup)
        if not is_cup:
            display_league = _sanitize_round_in_league(display_league, enriched_data)
        title += f"\n{display_league}"

    # Извлекаем данные для таблицы (базовые поля сохраняем для совместимости)
    data = {
        'title': title,
        'team_left': team1,
        'team_right': team2,
        'tournament_position': {
            'left': extract_tournament_position(enriched_data, team1, team_id=home_team_id),
            'right': extract_tournament_position(enriched_data, team2, team_id=away_team_id)
        },
        'current_form': {
            'left': extract_current_form(enriched_data, team1, is_home=True, team_id=home_team_id),
            'right': extract_current_form(enriched_data, team2, is_home=False, team_id=away_team_id)
        },
        'home_away': {
            'left': extract_home_away_form(enriched_data, team1, is_home=True, team_id=home_team_id),
            'right': extract_home_away_form(enriched_data, team2, is_home=False, team_id=away_team_id)
        },
        'lineup_changes': {
            'left': extract_lineup_changes(enriched_data, team1, is_home=True,
                                           team_id=home_team_id, opponent_team_id=away_team_id),
            'right': extract_lineup_changes(enriched_data, team2, is_home=False,
                                            team_id=away_team_id, opponent_team_id=home_team_id)
        },
        'last_match_events': {
            'left': extract_last_match_events(enriched_data, is_home=True),
            'right': extract_last_match_events(enriched_data, is_home=False)
        },
        'history': extract_h2h_history(h2h_data, team1=team1, team2=team2),
        'stats_trends': {
            'left': extract_stats_trends(enriched_data, team1, is_home=True, team_id=home_team_id),
            'right': extract_stats_trends(enriched_data, team2, is_home=False, team_id=away_team_id)
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

    left_trends_window = _get_stats_trends_window(enriched_data, is_home=True)
    right_trends_window = _get_stats_trends_window(enriched_data, is_home=False)
    trends_window = max(left_trends_window, right_trends_window)
    stats_trends_label = 'Статистические тренды'
    if trends_window > 0:
        trends_word = _ru_plural(trends_window, 'игра', 'игры', 'игр')
        stats_trends_label = f"{stats_trends_label}\nОкно: последние {trends_window} {trends_word}"

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
            'label': 'Изменения состава',
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
            'label': stats_trends_label,
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

    # Адаптивный рендер:
    # Core rows — всегда видимы (с placeholder если нет данных).
    # Optional rows — скрываются если обе стороны пусты.
    adaptive_rows = []
    for row, left_has_data, right_has_data in row_states:
        label = row.get('label', '')
        is_core = label in CORE_LABELS or any(label.startswith(f"{core}\n") for core in CORE_LABELS)
        if row.get('colspan'):
            if left_has_data:
                adaptive_rows.append(row)
            elif is_core:
                row = dict(row)
                row['left'] = 'Нет данных'
                adaptive_rows.append(row)
            continue
        if left_has_data or right_has_data:
            row = dict(row)
            if not left_has_data:
                row['left'] = 'Недостаточно данных'
            if not right_has_data:
                row['right'] = 'Недостаточно данных'
            adaptive_rows.append(row)
        elif is_core:
            row = dict(row)
            row['left'] = 'Недостаточно данных'
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
