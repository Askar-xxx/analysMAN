import logging
import os
import json
import re
import unicodedata
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

REQUIRED_ANALYSIS_SECTIONS = [
    "контекст матча",
    "форма и турнирная ситуация",
    "статистика и игровые паттерны",
    "психологические факторы",
    "вывод",
]

REQUIRED_EMOJI_HEADINGS = {
    "контекст матча": "⚽",
    "форма и турнирная ситуация": "📈",
    "статистика и игровые паттерны": "📊",
    "психологические факторы": "🧠",
    "вывод": "🔑",
}

SECTION_ROOT_VARIANTS = {
    "контекст матча": [("контекст", "матч")],
    "форма и турнирная ситуация": [("форм", "турнир"), ("форм", "таблиц")],
    "статистика и игровые паттерны": [("статист", "игр"), ("статист", "паттерн"), ("статист", "тенденц")],
    "психологические факторы": [("психолог", "фактор"), ("психолог", "фон"), ("ментал", "фактор")],
    "вывод": [("вывод",), ("итог",)],
}

PSYCH_SECTION = "психологические факторы"
PSYCH_SCORE_PATTERN = re.compile(r'(?<!\d)(\d{1,3})\s*/\s*100')
PSYCH_BETTING_TERMS = re.compile(
    r'\b(?:коэффициент\w*|ставк\w*|букмекер\w*|тотал\w*|фора\w*)\b',
    re.IGNORECASE
)
PSYCH_CAUSAL_MARKERS = (
    "поэтому",
    "на фоне",
    "это может",
    "давлен",
    "мотивац",
    "реванш",
    "дерби",
    "серия",
)
PSYCH_CATEGORY_KEYWORDS = {
    "tournament_pressure": ("мотивац", "турнир", "таблиц", "очки", "зона", "давлен", "плей"),
    "derby_tension": ("дерби", "принципиал", "сопернич", "противостоя"),
    "revenge_motivation": ("реванш", "ответн"),
    "form_pressure": ("серия", "форма", "без побед", "поражен", "неудач", "динамик"),
    "injury_uncertainty": ("травм", "кадров", "состав", "дисквалиф", "ротац", "потер"),
}
PSYCH_MIN_ACCEPTABLE_CHARS = 150
PSYCH_MIN_CAUSAL_CHARS = 100


def _normalize_for_checks(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", (text or "")).casefold()
    return "".join(ch for ch in normalized if unicodedata.category(ch)[0] != "C")


def _line_matches_section(normalized_line: str, section: str) -> bool:
    """Проверяет, соответствует ли строка секции по набору корневых вариантов."""
    normalized_section = _normalize_for_checks(section)
    variants = SECTION_ROOT_VARIANTS.get(section, [(normalized_section,)])
    for variant in variants:
        if all(root in normalized_line for root in variant):
            return True
    return False


def _normalize_kickoff_time_mentions(text: str, match_time_msk: str = "") -> str:
    """Нормализует формулировки про локальное время к формату МСК."""
    if not text:
        return text
    normalized = text
    if match_time_msk:
        normalized = re.sub(
            r'\b\d{1,2}:\d{2}\s+по\s+местному\s+времени\b',
            f'{match_time_msk} МСК',
            normalized,
            flags=re.IGNORECASE
        )
    normalized = re.sub(
        r'\bпо\s+местному\s+времени\b',
        'по московскому времени (МСК)',
        normalized,
        flags=re.IGNORECASE
    )
    return normalized


def _find_missing_sections(text: str) -> list[str]:
    """Возвращает список названий обязательных секций, отсутствующих в тексте."""
    normalized_text = _normalize_for_checks(text or "")
    missing = []
    for section in REQUIRED_ANALYSIS_SECTIONS:
        if not _line_matches_section(normalized_text, section):
            missing.append(section)
    return missing


def _extract_context_fact_lines(enriched_context: str, limit: int = 3) -> list[str]:
    """Вытаскивает короткие фактические строки с цифрами из контекста."""
    facts = []
    for raw in (enriched_context or '').splitlines():
        line = raw.strip().lstrip('-').strip()
        if not line or line.startswith('==='):
            continue
        if len(line) > 120:
            continue
        if re.search(r'\d', line):
            if line not in facts:
                facts.append(line)
        if len(facts) >= limit:
            break
    return facts


def _fallback_conclusion(match_data: dict, enriched_context: str = "") -> str:
    """Резервный вывод без обращения к LLM, но с привязкой к фактам."""
    team1 = match_data.get('team1', 'Хозяева')
    team2 = match_data.get('team2', 'Гости')
    facts = _extract_context_fact_lines(enriched_context, limit=3)
    fact_sentence = ""
    if facts:
        fact_sentence = (
            " По данным контекста: "
            + "; ".join(facts[:2])
            + "."
        )

    base = (
        f"Матч {team1} — {team2} проходит в условиях, когда обе команды "
        "располагают схожим набором данных по результативности и дисциплине."
    )
    return f"🔑 **Вывод**\n{base}{fact_sentence}"


def _extract_psych_signals(enriched_context: str) -> list[str]:
    """Извлекает строки сигналов (дерби, мотивация, реванш) из enriched_context."""
    lines = []
    in_psych_block = False
    for raw in (enriched_context or '').splitlines():
        stripped = raw.strip()
        if '=== ПСИХОЛОГИЧЕСКИЕ ФАКТОРЫ ===' in stripped:
            in_psych_block = True
            continue
        if in_psych_block:
            if stripped.startswith('==='):
                break
            if stripped and not stripped.startswith('Уверенность модели'):
                lines.append(stripped)
    return lines


def _looks_like_heading(line: str) -> bool:
    """Проверяет, что строка похожа на заголовок секции.

    Заголовок: emoji + **Название секции** (и ничего существенного после).
    НЕ заголовок: длинная строка с ** внутри (bold-имена команд).
    """
    stripped = line.strip()
    if not stripped:
        return False
    # Строка вида: [emoji] **Текст** [необязательно пробелы] — и всё (длина ≤ 60)
    if re.match(r'^[^\w\s]*\s*\*\*[^*]+\*\*\s*$', stripped) and len(stripped) <= 60:
        return True
    # Короткая строка (до 40 символов) без точки — возможный голый заголовок
    if len(stripped) <= 40 and not stripped.endswith('.') and '**' not in stripped:
        return True
    return False


def _is_section_heading_line(line: str, section: str) -> bool:
    """Проверяет, что строка является заголовком конкретной секции."""
    if not _line_matches_section(_normalize_for_checks(line), section):
        return False
    stripped = line.strip()
    if stripped.startswith("==="):
        return False
    return _looks_like_heading(line)


def _ensure_section_emojis(text: str) -> str:
    """Проверяет заголовки секций и добавляет недостающие emoji."""
    if not text:
        return text
    lines = text.splitlines()
    result = []
    for line in lines:
        if _looks_like_heading(line):
            normalized_line = _normalize_for_checks(line)
            for section, emoji in REQUIRED_EMOJI_HEADINGS.items():
                if _line_matches_section(normalized_line, section) and emoji not in line:
                    stripped = line.lstrip()
                    if '**' in stripped:
                        line = line.replace('**', f'{emoji} **', 1)
                    else:
                        section_title = section[:1].upper() + section[1:]
                        indent = line[:len(line) - len(stripped)]
                        line = f"{indent}{emoji} **{section_title}**"
                    break
        result.append(line)
    return '\n'.join(result)


def _extract_section_body(text: str, section: str) -> str | None:
    """Извлекает тело секции (без заголовка). None если секция не найдена."""
    lines = (text or "").splitlines()
    section_start = None
    for idx, line in enumerate(lines):
        if _is_section_heading_line(line, section):
            section_start = idx
            break
    if section_start is None:
        return None

    body_lines = []
    for idx in range(section_start + 1, len(lines)):
        if any(_is_section_heading_line(lines[idx], s) for s in REQUIRED_ANALYSIS_SECTIONS if s != section):
            break
        body_lines.append(lines[idx])

    return "\n".join(body_lines).strip()


def _count_sentences(text: str) -> int:
    """Считает количество предложений по точкам/!/? с учётом аббревиатур."""
    if not text:
        return 0
    # Разбиваем по концам предложений, фильтруем пустые
    parts = re.split(r'[.!?]+(?:\s|$)', text.strip())
    return len([p for p in parts if p.strip() and len(p.strip()) > 3])


def _is_section_thin(text: str, section: str, min_chars: int = 250,
                     min_sentences: int = 3) -> bool:
    """Проверяет, что секция присутствует, но содержит слишком мало текста.

    Секция считается «тонкой» если её тело короче min_chars
    ИЛИ содержит менее min_sentences предложений.
    """
    body = _extract_section_body(text, section)
    if body is None:
        return False
    section_key = _normalize_for_checks(section)
    body_len = len(body)
    sentences_count = _count_sentences(body)

    if section_key == _normalize_for_checks(PSYCH_SECTION):
        normalized_body = _normalize_for_checks(body)
        has_causal_marker = any(marker in normalized_body for marker in PSYCH_CAUSAL_MARKERS)
        if sentences_count >= 2 and body_len >= PSYCH_MIN_ACCEPTABLE_CHARS:
            return False
        if sentences_count >= 1 and body_len >= PSYCH_MIN_CAUSAL_CHARS and has_causal_marker:
            return False
        return True

    return body_len < min_chars or sentences_count < min_sentences


def _remove_section(text: str, section: str) -> str:
    """Удаляет секцию (заголовок + тело) из текста."""
    lines = (text or "").splitlines()
    section_start = None
    section_end = len(lines)
    for idx, line in enumerate(lines):
        if section_start is None and _is_section_heading_line(line, section):
            section_start = idx
            continue
        if section_start is not None:
            if any(_is_section_heading_line(line, s) for s in REQUIRED_ANALYSIS_SECTIONS if s != section):
                section_end = idx
                break
    if section_start is None:
        return text
    before = "\n".join(lines[:section_start]).rstrip()
    after = "\n".join(lines[section_end:]).lstrip()
    if before and after:
        return f"{before}\n\n{after}"
    return before or after


def _count_section_headings(text: str, section: str) -> int:
    """Возвращает количество заголовков секции в тексте."""
    return sum(1 for line in (text or "").splitlines() if _is_section_heading_line(line, section))


def _extract_psych_score(signal: str) -> int | None:
    """Извлекает score X/100 из сигнала."""
    match = PSYCH_SCORE_PATTERN.search(signal or "")
    if not match:
        return None
    return max(0, min(100, int(match.group(1))))


def _clean_psych_signal_text(signal: str) -> str:
    """Очищает сигнал от технического шума и score."""
    cleaned = re.sub(r'^\s*[-•*]\s*', '', signal or '').strip()
    cleaned = PSYCH_SCORE_PATTERN.sub('', cleaned)
    cleaned = PSYCH_BETTING_TERMS.sub('', cleaned)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)
    return cleaned.strip(" -—–:;,.")


def _resolve_psych_category(signal_text: str) -> str | None:
    """Определяет каноническую категорию сигнала."""
    normalized = _normalize_for_checks(signal_text)
    for category, keywords in PSYCH_CATEGORY_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            return category
    return None


def _extract_psych_detail(signal_text: str) -> str:
    """Пытается вытащить короткую фактическую деталь из сигнала."""
    parts = re.split(r'\s*[—–-]\s*|\s*:\s*', signal_text, maxsplit=1)
    detail = parts[1] if len(parts) == 2 else signal_text
    detail = detail.strip().strip(".")
    if len(detail) > 110:
        detail = detail[:107].rstrip() + "..."
    return detail


def _score_to_psych_level(score: int) -> str | None:
    """Переводит score сигнала в уровень акцента текста."""
    if score < 20:
        return None
    if score < 40:
        return "mild"
    if score < 65:
        return "medium"
    return "strong"


def _render_psych_sentence(
    category: str,
    level: str,
    team1: str,
    team2: str,
    detail: str = "",
) -> str:
    """Рендерит одно fallback-предложение по категории сигнала."""
    templates = {
        "tournament_pressure": {
            "mild": f"Турнирный фон немного повышает значимость матча для {team1} и {team2}.",
            "medium": f"Турнирная ситуация добавляет матчу {team1} — {team2} ощутимого напряжения.",
            "strong": (
                "Высокая турнирная цена встречи усиливает "
                "психологическое давление на обе команды."
            ),
        },
        "derby_tension": {
            "mild": "В паре чувствуется принципиальность, которая может усилить эмоции в ключевых эпизодах.",
            "medium": "Принципиальный характер противостояния повышает эмоциональный накал матча.",
            "strong": "Фактор дерби создает повышенное эмоциональное давление и влияет на ритм решений.",
        },
        "revenge_motivation": {
            "mild": "Легкий мотив реванша добавляет встрече дополнительной внутренней концентрации.",
            "medium": "Тема реванша заметно усиливает мотивацию и влияет на психологический настрой.",
            "strong": "Сильный мотив реванша повышает внутреннее давление и может менять риск-профиль по ходу игры.",
        },
        "form_pressure": {
            "mild": "Последние результаты формируют умеренный фон ожиданий перед этой встречей.",
            "medium": "Текущая серия результатов усиливает психологическое давление на обе стороны.",
            "strong": "Контекст последних матчей делает эмоциональную устойчивость одним из ключевых факторов игры.",
        },
        "injury_uncertainty": {
            "mild": "Кадровый контекст добавляет небольшую неопределенность в привычные игровые роли.",
            "medium": "Изменения в составе повышают неопределенность и требуют быстрой психологической адаптации.",
            "strong": (
                "Существенные кадровые потери усиливают риск "
                "психологической нестабильности в стрессовых эпизодах."
            ),
        },
    }
    sentence = templates.get(category, {}).get(level, "")
    if not sentence:
        return ""

    detail = detail.strip()
    if detail and len(detail) >= 18:
        detail = PSYCH_BETTING_TERMS.sub('', detail).strip(" ,.;:-")
        if detail:
            sentence = sentence.rstrip(".") + f" На фоне {detail}."

    return sentence


def render_psychological_fallback(
    signals: list[str],
    team1: str,
    team2: str,
    context: dict | None = None,
) -> str:
    """Рендерит human-friendly fallback для секции «Психологические факторы»."""
    deduped_by_category: dict[str, dict[str, str | int]] = {}
    for raw_signal in signals or []:
        score = _extract_psych_score(raw_signal)
        effective_score = score if score is not None else 35
        level = _score_to_psych_level(effective_score)
        if not level:
            continue

        cleaned_signal = _clean_psych_signal_text(raw_signal)
        if not cleaned_signal:
            continue
        category = _resolve_psych_category(cleaned_signal)
        if not category:
            continue

        candidate = {
            "score": effective_score,
            "level": level,
            "detail": _extract_psych_detail(cleaned_signal),
        }
        current = deduped_by_category.get(category)
        if current is None or int(candidate["score"]) > int(current["score"]):
            deduped_by_category[category] = candidate

    sentences: list[str] = []
    if deduped_by_category:
        if len(deduped_by_category) > 1:
            sentences.append(
                f"В матче {team1} — {team2} психологический фон формируется сразу несколькими факторами."
            )
        else:
            sentences.append(
                f"В матче {team1} — {team2} психологический фактор может заметно повлиять на ход игры."
            )

        ordered = sorted(
            deduped_by_category.items(),
            key=lambda item: int(item[1]["score"]),
            reverse=True,
        )
        for category, data in ordered[:3]:
            sentence = _render_psych_sentence(
                category=category,
                level=str(data["level"]),
                team1=team1,
                team2=team2,
                detail=str(data["detail"]),
            )
            if sentence:
                sentences.append(sentence)

    if len(sentences) < 2:
        league = ""
        round_info = ""
        if isinstance(context, dict):
            league = str(context.get("league", "")).strip()
            round_info = str(context.get("round", "")).strip()
        context_part = ""
        if league and round_info:
            context_part = f" в рамках {league}, {round_info}"
        elif league:
            context_part = f" в рамках {league}"
        sentences = [
            (
                f"В матче {team1} — {team2} психологический фон выглядит "
                "достаточно ровным, без явного перекоса по мотивации."
            ),
            (
                f"Даже при нейтральном контексте{context_part} многое будет "
                "зависеть от реакции команд на первые сложные эпизоды."
            ),
        ]

    text = " ".join(sentences[:4]).strip()
    text = PSYCH_SCORE_PATTERN.sub('', text)
    text = PSYCH_BETTING_TERMS.sub('', text)
    text = text.replace("•", "")
    return re.sub(r'\s{2,}', ' ', text).strip()


def _build_missing_section_block(section: str, match_data: dict, enriched_context: str) -> str:
    """Генерирует локальный fallback-блок для отсутствующей секции без LLM."""
    normalized_section = _normalize_for_checks(section)
    team1 = match_data.get('team1', 'Хозяева')
    team2 = match_data.get('team2', 'Гости')
    section_title = section[:1].upper() + section[1:]
    section_emoji = REQUIRED_EMOJI_HEADINGS.get(normalized_section, "📌")
    heading = f"{section_emoji} **{section_title}**"

    if normalized_section == _normalize_for_checks(PSYCH_SECTION):
        signals = _extract_psych_signals(enriched_context)
        logger.info("psych_fallback_template_used")
        base = render_psychological_fallback(signals, team1, team2, context=match_data)
    else:
        facts = _extract_context_fact_lines(enriched_context, limit=2)
        base = (
            f"По блоку «{section_title}» в данных {team1} — {team2} зафиксированы ключевые опорные "
            "факты, которые нужно учитывать в общей картине матча."
        )
        if facts:
            base += " " + "; ".join(facts[:2]) + "."

    return f"{heading}\n{base}"


def _inject_section_before_conclusion(text: str, block: str) -> str:
    """Вставляет блок перед «Вывод», если он есть, иначе дописывает в конец."""
    lines = (text or "").splitlines()
    conclusion_idx = None
    for idx, line in enumerate(lines):
        normalized_line = _normalize_for_checks(line)
        if _line_matches_section(normalized_line, "вывод"):
            conclusion_idx = idx
            break

    if conclusion_idx is None:
        return f"{(text or '').rstrip()}\n\n{block}".strip()

    before = "\n".join(lines[:conclusion_idx]).rstrip()
    after = "\n".join(lines[conclusion_idx:]).lstrip()
    return f"{before}\n\n{block}\n\n{after}".strip()


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
    analysis_text = clean_and_truncate(
        analysis_text,
        target_max=800,
        soft_cap=900,
        hard_cap=1200
    )

    return analysis_text


async def generate_match_text_analysis(
    match_data: dict, enriched_context: str
) -> str:
    """
    Генерирует связный текстовый анализ матча (единый текст).

    Args:
        match_data: dict с базовыми данными матча
        enriched_context: Готовый текстовый контекст с обогащёнными данными

    Returns:
        str: текст анализа в целевом диапазоне длины
    """
    if not isinstance(match_data, dict):
        match_data = dict(match_data)

    team1 = match_data.get('team1', '')
    team2 = match_data.get('team2', '')
    sport = match_data.get('sport', 'football')
    sport_name = SPORT_NAMES.get(sport, sport)

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
    match_time_msk = str(match_data.get('match_time', '')).strip()
    time_rule_line = ""
    if match_time_msk:
        time_rule_line = (
            f"\nВремя матча указывай только как {match_time_msk} МСК. "
            "Не используй локальное время и не пересчитывай часовые пояса."
        )

    prompt = f"""Данные матча:
{basic_info_str}

ОБОГАЩЁННЫЕ ДАННЫЕ:
{enriched_context}

{ANALYSIS_PROMPT_TEMPLATE}

Команда A = {team1}, Команда B = {team2}.{time_rule_line}"""

    system_message = (
        "Ты — профессиональный спортивный аналитик. "
        "Пишешь объёмные, связные и фактурные обзоры матчей на русском языке. "
        "Целевой объём: 1900–2400 символов. Абсолютный максимум: 2800 символов. "
        "Если текст длиннее — сокращай, сохраняя ключевые факты. "
        "Формат ответа: только готовый текст анализа с заголовками разделов в точном порядке. "
        "ОБЯЗАТЕЛЬНО включи ВСЕ 5 заголовков с эмодзи ТОЧНО ТАК:\n"
        "⚽ **Контекст матча**\n"
        "📈 **Форма и турнирная ситуация**\n"
        "📊 **Статистика и игровые паттерны**\n"
        "🧠 **Психологические факторы**\n"
        "🔑 **Вывод**\n"
        "КАЖДАЯ секция должна содержать минимум 2 предложения текста. "
        "Не даёшь прогноз исхода, не упоминаешь букмекерские коэффициенты и не советуешь ставки. "
        "Названия команд выделяй жирным: **Ливерпуль**, **Арсенал** и т.д. "
        "Указывай время матча только в МСК и не используй формулировку «по местному времени»."
    )

    response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt}
        ],
        max_tokens=1600,
        temperature=0.7
    )

    # Диагностика ответа DeepSeek — максимально безопасная
    try:
        choices_count = len(response.choices) if response.choices else 0
        finish_reason = response.choices[0].finish_reason if choices_count else 'N/A'
        raw_content = response.choices[0].message.content if choices_count else None
    except (IndexError, AttributeError, TypeError) as parse_err:
        logger.error("Не удалось распарсить ответ DeepSeek: %s, response=%s", parse_err, response)
        raise ValueError(f"DeepSeek API: ошибка парсинга ответа: {parse_err}")

    logger.info(
        "DeepSeek response: choices=%s, finish_reason=%s, content_len=%s",
        choices_count,
        finish_reason,
        len(raw_content) if raw_content else 0,
    )
    if not raw_content:
        logger.error(
            "DeepSeek вернул пустой ответ: choices=%s, finish_reason=%s, model=%s",
            choices_count, finish_reason, getattr(response, 'model', 'unknown'),
        )
        raise ValueError("DeepSeek API вернул пустой ответ")
    raw_text = raw_content.strip()
    analysis_text = raw_text
    analysis_text = _normalize_kickoff_time_mentions(analysis_text, match_time_msk)
    analysis_text = _ensure_section_emojis(analysis_text)

    psych_heading_count = _count_section_headings(analysis_text, PSYCH_SECTION)
    if psych_heading_count > 1:
        logger.info("psych_duplicate_heading_detected count=%s", psych_heading_count)

    # Структурные гарантии: вставляем fallback-блоки для пропущенных секций
    missing = _find_missing_sections(analysis_text)

    # Вставляем недостающие секции (кроме «Вывод» — для него отдельная логика)
    injected = []
    for section in missing:
        if _normalize_for_checks(section) == _normalize_for_checks("вывод"):
            continue
        if _normalize_for_checks(section) == _normalize_for_checks(PSYCH_SECTION):
            logger.info("psych_missing_after_model")
        block = _build_missing_section_block(section, match_data, enriched_context)
        analysis_text = _inject_section_before_conclusion(analysis_text, block)
        injected.append(section)

    if injected:
        logger.info("Добавлены fallback-блоки: %s", ", ".join(injected))

    # Проверка содержательности секции «Психологические факторы»
    psych_section = PSYCH_SECTION
    if psych_section not in missing and _is_section_thin(analysis_text, psych_section):
        logger.info("psych_thin_after_model")
        logger.info("Секция «Психологические факторы» слишком скудная — заменяем fallback-блоком")
        analysis_text = _remove_section(analysis_text, psych_section)
        block = _build_missing_section_block(psych_section, match_data, enriched_context)
        analysis_text = _inject_section_before_conclusion(analysis_text, block)

    # Гарантия наличия блока «Вывод»
    if "вывод" not in _normalize_for_checks(analysis_text):
        analysis_text = f"{analysis_text.rstrip()}\n\n{_fallback_conclusion(match_data, enriched_context)}"

    # Финальная очистка
    analysis_text = clean_and_truncate(
        analysis_text,
        target_max=2800,
        soft_cap=3400,
        hard_cap=3600
    )

    # Повторная гарантия emoji в заголовках (после всех манипуляций)
    analysis_text = _ensure_section_emojis(analysis_text)

    return analysis_text


async def generate_match_analysis_with_context(
    match_data: dict, enriched_context: str
) -> dict:
    """
    Backward compatibility wrapper.

    Возвращает dict {'intro': ..., 'conclusion': ...} на основе нового
    единого текстового анализа.
    """
    full_text = await generate_match_text_analysis(match_data, enriched_context)
    if not full_text:
        return {'intro': '', 'conclusion': ''}

    paragraphs = [p.strip() for p in full_text.split('\n\n') if p.strip()]

    # Ищем первый параграф, который содержит реальный текст (не только заголовок)
    intro_idx = 0
    for i, p in enumerate(paragraphs):
        lines = [line_text.strip() for line_text in p.splitlines() if line_text.strip()]
        is_only_heading = len(lines) == 1 and lines[0].startswith('**')
        if not is_only_heading:
            intro_idx = i
            break

    if len(paragraphs) > intro_idx + 1:
        intro = '\n\n'.join(paragraphs[:intro_idx + 1])
        conclusion = '\n\n'.join(paragraphs[intro_idx + 1:])
    else:
        intro = full_text
        conclusion = ''

    return {'intro': intro, 'conclusion': conclusion}
