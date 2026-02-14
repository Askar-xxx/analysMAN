import logging
import os
import json
from datetime import datetime
from openai import AsyncOpenAI
from config import DEEPSEEK_API_KEY
from utils import clean_and_truncate

logger = logging.getLogger(__name__)

# Загрузка промпта из внешнего файла
PROMPT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ANALYSIS_PROMPT.md")
if not os.path.exists(PROMPT_FILE):
    raise FileNotFoundError(
        f"Файл промпта не найден: {PROMPT_FILE}\n"
        "Создайте файл ANALYSIS_PROMPT.md в корне проекта."
    )

with open(PROMPT_FILE, "r", encoding="utf-8") as f:
    ANALYSIS_PROMPT_TEMPLATE = f.read()

client = AsyncOpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)

SPORT_NAMES = {
    'football': 'футбол',
    'basketball': 'баскетбол',
    'hockey': 'хоккей'
}

# Маппинг полей БД → читаемые метки для контекста.
# Для добавления нового поля — просто добавить строку сюда.
# Формат: (ключ_в_dict, метка, опциональный_трансформер)


def _format_h2h(h2h_json: str, h2h_fetched_at: str) -> str:
    """
    Форматирует историю личных встреч (H2H) в компактный текст.

    Args:
        h2h_json: JSON строка с данными H2H от API
        h2h_fetched_at: Timestamp когда данные были получены

    Returns:
        Компактный текст: последние 5 матчей с датой и счётом,
        агрегаты (W/D/L, avg goals), источник и timestamp.
        Если данных нет - возвращает "Данных нет"
    """
    if not h2h_json:
        return "Данных нет"

    try:
        data = json.loads(h2h_json)
        events = data.get('events', [])

        if not events:
            return "Данных нет (история встреч отсутствует)"

        # Берём последние 5 матчей
        recent_events = events[:5]

        # Форматируем матчи
        matches_list = []
        for event in recent_events:
            date = event.get('dateEvent', 'N/A')
            home = event.get('strHomeTeam', 'N/A')
            away = event.get('strAwayTeam', 'N/A')
            home_score = event.get('intHomeScore', '?')
            away_score = event.get('intAwayScore', '?')
            matches_list.append(f"{date}: {home} {home_score}-{away_score} {away}")

        # Агрегаты (считаем для первой команды в списке)
        if recent_events:
            first_team = recent_events[0].get('strHomeTeam')
            wins = sum(
                1 for e in recent_events
                if (e.get('strHomeTeam') == first_team and
                    int(e.get('intHomeScore', 0) or 0) > int(e.get('intAwayScore', 0) or 0))
                or (e.get('strAwayTeam') == first_team and
                    int(e.get('intAwayScore', 0) or 0) > int(e.get('intHomeScore', 0) or 0))
            )
            draws = sum(
                1 for e in recent_events
                if e.get('intHomeScore') == e.get('intAwayScore')
            )
            losses = len(recent_events) - wins - draws

            # Форматируем timestamp
            try:
                ts = datetime.fromisoformat(h2h_fetched_at).strftime('%d.%m.%Y %H:%M')
            except Exception:
                ts = h2h_fetched_at[:16] if h2h_fetched_at else 'N/A'

            result = (
                f"Последние {len(recent_events)} встреч:\n"
                + "\n".join(f"  {m}" for m in matches_list)
                + f"\nБаланс: {wins}W-{draws}D-{losses}L"
                + f"\nИсточник: TheSportsDB, обновлено {ts}"
            )
            return result

        return "Данных недостаточно"

    except Exception as e:
        logger.error(f"Ошибка форматирования H2H: {e}")
        return "Ошибка обработки данных H2H"


def _format_standings(standings_json: str, standings_fetched_at: str,
                      team1: str, team2: str) -> str:
    """
    Форматирует турнирную таблицу в компактный текст для двух команд.

    Args:
        standings_json: JSON строка с данными таблицы от API
        standings_fetched_at: Timestamp когда данные были получены
        team1: Название команды-хозяина (для поиска в таблице)
        team2: Название команды-гостя (для поиска в таблице)

    Returns:
        Компактный текст: позиция, очки, форма (W-L-D), goal_diff для обеих команд.
        Источник и timestamp. Если данных нет - возвращает "Данных нет"
    """
    if not standings_json:
        return "Данных нет"

    try:
        data = json.loads(standings_json)

        # Проверка на table_missing
        if data.get('table_missing'):
            return "Данных нет (таблица недоступна для этой лиги)"

        table = data.get('table', [])
        if not table:
            return "Данных нет (таблица пуста)"

        # Ищем обе команды в таблице
        team1_data = None
        team2_data = None

        for entry in table:
            team_name = entry.get('strTeam', '')
            if team_name == team1:
                team1_data = entry
            elif team_name == team2:
                team2_data = entry

        # Форматируем результат
        lines = []

        if team1_data:
            lines.append(
                f"{team1_data['strTeam']}: "
                f"#{team1_data.get('intRank', '?')} место, "
                f"{team1_data.get('intPoints', '?')} очков, "
                f"форма {team1_data.get('strForm', '?')}, "
                f"разница {team1_data.get('intGoalDifference', '?')} "
                f"({team1_data.get('intGoalsFor', '?')}-{team1_data.get('intGoalsAgainst', '?')})"
            )

        if team2_data:
            lines.append(
                f"{team2_data['strTeam']}: "
                f"#{team2_data.get('intRank', '?')} место, "
                f"{team2_data.get('intPoints', '?')} очков, "
                f"форма {team2_data.get('strForm', '?')}, "
                f"разница {team2_data.get('intGoalDifference', '?')} "
                f"({team2_data.get('intGoalsFor', '?')}-{team2_data.get('intGoalsAgainst', '?')})"
            )

        if not lines:
            return "Данных нет (команды не найдены в топ-5 таблицы)"

        # Форматируем timestamp
        try:
            ts = datetime.fromisoformat(standings_fetched_at).strftime('%d.%m.%Y %H:%M')
        except Exception:
            ts = standings_fetched_at[:16] if standings_fetched_at else 'N/A'

        result = (
            "\n".join(lines)
            + f"\nИсточник: TheSportsDB, обновлено {ts}"
        )
        return result

    except Exception as e:
        logger.error(f"Ошибка форматирования standings: {e}")
        return "Ошибка обработки данных таблицы"


CONTEXT_FIELDS = [
    ('sport', 'Вид спорта', lambda v: SPORT_NAMES.get(v, v)),
    ('team1', 'Команда хозяев', None),
    ('team2', 'Команда гостей', None),
    ('match_date', 'Дата', None),
    ('match_time', 'Время (МСК)', None),
    ('league', 'Лига / Турнир', None),
    ('venue', 'Стадион', None),
    ('status', 'Статус', None),
    ('round', 'Тур', None),
    ('home_score', 'Счёт хозяев', None),
    ('away_score', 'Счёт гостей', None),
]


def _extract_team_standings(standings_json: str, team_name: str) -> str:
    """
    Извлекает данные конкретной команды из standings.

    Returns:
        Строка с позицией, очками, формой. Пример: "#5 место, 43 очка, форма WWWWL"
        Пустая строка если команда не найдена.
    """
    if not standings_json:
        return ""

    try:
        data = json.loads(standings_json)
        if data.get('table_missing'):
            return ""

        table = data.get('table', [])
        for entry in table:
            if entry.get('strTeam') == team_name:
                rank = entry.get('intRank', '?')
                points = entry.get('intPoints', '?')
                form = entry.get('strForm', '?')
                goal_diff = entry.get('intGoalDifference', '?')
                return f"#{rank} место, {points} очков, форма {form}, разница {goal_diff}"

        return ""  # Команда не в топ-5
    except Exception as e:
        logger.error(f"Ошибка извлечения standings для {team_name}: {e}")
        return ""


def _build_match_context(match_data: dict) -> str:
    """Динамически строит текстовый блок контекста из доступных полей матча.

    Пропускает поля с None/пустым значением.
    Для расширения — добавить строку в CONTEXT_FIELDS.
    Специальная обработка: h2h_json и standings_json используют форматтеры.
    """
    lines = []

    # Извлекаем standings для обеих команд заранее
    standings_json = match_data.get('standings_json')
    team1 = match_data.get('team1', '')
    team2 = match_data.get('team2', '')
    team1_standings = _extract_team_standings(standings_json, team1)
    team2_standings = _extract_team_standings(standings_json, team2)

    for key, label, transform in CONTEXT_FIELDS:
        value = match_data.get(key)
        if value is None or value == '':
            continue

        # Специальная обработка для H2H
        if key == 'h2h_json':
            h2h_fetched_at = match_data.get('h2h_fetched_at', '')
            formatted_h2h = _format_h2h(value, h2h_fetched_at)
            if formatted_h2h and "Данных нет" not in formatted_h2h:
                lines.append(f"- {label}:\n{formatted_h2h}")
            continue

        # Специальная обработка для team1 - добавляем standings если есть
        if key == 'team1':
            team_info = f"{value}"
            if team1_standings:
                team_info += f" ({team1_standings})"
            lines.append(f"- {label}: {team_info}")
            continue

        # Специальная обработка для team2 - добавляем standings если есть
        if key == 'team2':
            team_info = f"{value}"
            if team2_standings:
                team_info += f" ({team2_standings})"
            lines.append(f"- {label}: {team_info}")
            continue

        # Пропускаем standings_json - данные уже интегрированы в team1/team2
        if key == 'standings_json':
            continue

        # Обычная обработка
        if transform:
            value = transform(value)
        lines.append(f"- {label}: {value}")

    return "\n".join(lines)


async def generate_match_analysis(match_data: dict) -> str:
    """
    Генерирует анализ матча через DeepSeek API.

    Принимает dict с данными матча (из БД). Обязательные ключи: team1, team2, sport.
    Возвращает текст анализа на русском (1400-1900 символов).
    ГАРАНТИРУЕТ, что анализ не превысит 3800 символов.
    Выбрасывает исключение при ошибке API.
    """
    MAX_ANALYSIS_LENGTH = 3800
    TARGET_LENGTH = "1400-1900"

    # sqlite3.Row не поддерживает .get() — конвертируем в dict
    if not isinstance(match_data, dict):
        match_data = dict(match_data)

    team1 = match_data.get('team1', '')
    team2 = match_data.get('team2', '')

    match_context = _build_match_context(match_data)

    prompt = f"""Напиши компактный аналитический обзор предстоящего матча.

Данные матча:
{match_context}

{ANALYSIS_PROMPT_TEMPLATE}

Замени "команда A" на {team1}, "команда B" на {team2}."""

    system_message = (
        f"Ты — профессиональный спортивный аналитик. "
        f"Пишешь КОМПАКТНЫЕ объективные обзоры матчей на русском языке "
        f"строго в пределах {TARGET_LENGTH} символов. "
        f"АБСОЛЮТНЫЙ МАКСИМУМ: {MAX_ANALYSIS_LENGTH} символов. "
        f"Никогда не даёшь прогнозы на результат, не упоминаешь букмекерские "
        f"коэффициенты и не советуешь ставки. Используешь максимум 4 эмодзи. "
        f"Если текст превышает 2200 символов — обязательно сокращаешь до целевого диапазона."
    )

    response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt}
        ],
        max_tokens=1400,
        temperature=0.7
    )

    analysis_text = response.choices[0].message.content.strip()

    # ПОСТ-ОБРАБОТКА: очистка, фильтрация, сокращение
    analysis_text = clean_and_truncate(analysis_text)

    return analysis_text


async def generate_match_analysis_with_context(match_data: dict, enriched_context: str) -> str:
    """
    Генерирует анализ матча через DeepSeek API с готовым обогащённым контекстом.

    Используется для on-demand fetching: enriched_context формируется через
    MatchDataFetcher и build_enriched_context() вместо чтения из БД.

    Args:
        match_data: dict с базовыми данными матча (team1, team2, sport, league и т.д.)
        enriched_context: Готовый текстовый контекст с H2H/standings/form

    Returns:
        Текст анализа на русском (1400-1900 символов, макс 3800)
    """
    MAX_ANALYSIS_LENGTH = 3800
    TARGET_LENGTH = "1400-1900"

    # sqlite3.Row не поддерживает .get() — конвертируем в dict
    if not isinstance(match_data, dict):
        match_data = dict(match_data)

    team1 = match_data.get('team1', '')
    team2 = match_data.get('team2', '')
    sport = match_data.get('sport', 'football')
    sport_name = SPORT_NAMES.get(sport, sport)

    # Базовая информация о матче (без H2H/standings - они в enriched_context)
    basic_info = []
    basic_info.append(f"- Вид спорта: {sport_name}")
    basic_info.append(f"- Команда хозяев: {team1}")
    basic_info.append(f"- Команда гостей: {team2}")

    if match_data.get('match_date'):
        basic_info.append(f"- Дата: {match_data['match_date']}")
    if match_data.get('match_time'):
        basic_info.append(f"- Время: {match_data['match_time']}")
    if match_data.get('league'):
        basic_info.append(f"- Лига: {match_data['league']}")
    if match_data.get('venue'):
        basic_info.append(f"- Стадион: {match_data['venue']}")
    if match_data.get('round'):
        basic_info.append(f"- Тур: {match_data['round']}")

    basic_info_str = '\n'.join(basic_info)

    # Формирование промпта с обогащённым контекстом
    prompt = f"""Напиши компактный аналитический обзор предстоящего матча.

Данные матча:
{basic_info_str}

ОБОГАЩЁННЫЕ ДАННЫЕ (ИСПОЛЬЗУЙ ИХ ДЛЯ ЗАПОЛНЕНИЯ ТАБЛИЦЫ):
{enriched_context}

ИНСТРУКЦИИ ПО ФОРМАТУ:
{ANALYSIS_PROMPT_TEMPLATE}

ВАЖНО: Используй данные из секций === выше === для заполнения таблицы!
НЕ копируй плейсхолдеры типа "[позиция (зона), очки]" — замени их на РЕАЛЬНЫЕ данные из секций!
Замени "команда A" на {team1}, "команда B" на {team2}."""

    system_message = (
        f"Ты — профессиональный спортивный аналитик. "
        f"Пишешь КОМПАКТНЫЕ объективные обзоры матчей на русском языке "
        f"строго в пределах {TARGET_LENGTH} символов. "
        f"АБСОЛЮТНЫЙ МАКСИМУМ: {MAX_ANALYSIS_LENGTH} символов. "
        f"Никогда не даёшь прогнозы на результат, не упоминаешь букмекерские "
        f"коэффициенты и не советуешь ставки. Используешь максимум 4 эмодзи. "
        f"Если текст превышает 2200 символов — обязательно сокращаешь до целевого диапазона."
    )

    response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt}
        ],
        max_tokens=1400,
        temperature=0.7
    )

    analysis_text = response.choices[0].message.content.strip()

    # ПОСТ-ОБРАБОТКА: очистка, фильтрация, сокращение
    analysis_text = clean_and_truncate(analysis_text)

    return analysis_text
