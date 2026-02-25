"""Тесты для ai_generator.py: проверка загрузки промпта, постобработки и построения контекста."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import clean_and_truncate  # noqa: E402
from ai_generator import (  # noqa: E402
    _build_match_context,
    _collect_quality_issues,
    _extract_missing_required_sections,
    _inject_section_before_conclusion,
)


class TestAnalysisPostprocessing:
    """Тесты постобработки анализа (clean_and_truncate используется в ai_generator)."""

    def test_long_analysis_truncated(self):
        """Длинный текст анализа сокращается до ≤900 символов (soft cap)."""
        analysis = (
            "1. Краткое введение о матче\n"
            "Важный матч чемпионата. " * 50 + "\n\n"
            "2. Обзор команды А\n"
            "Команда А показывает хорошую форму. " * 50 + "\n\n"
        )
        result = clean_and_truncate(
            analysis,
            target_max=800,
            soft_cap=900,
            hard_cap=1200
        )
        assert len(result) <= 900

    def test_banned_words_removed_from_analysis(self):
        """Запрещённые слова удаляются из текста анализа."""
        analysis = (
            "1. Краткое введение о матче\n"
            "Коэффициент на победу составляет 1.5.\n"
            "Ставка на тотал больше.\n"
            "Прогноз экспертов благоприятный.\n"
            "Команда показывает стабильную игру."
        )
        result = clean_and_truncate(analysis)
        assert "коэффициент" not in result.lower()
        assert "ставк" not in result.lower()
        assert "прогноз" not in result.lower()
        assert "команда" in result.lower()

    def test_prompt_file_exists(self):
        """Файл ANALYSIS_PROMPT.md существует в корне проекта."""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        prompt_path = os.path.join(project_root, "ANALYSIS_PROMPT.md")
        assert os.path.exists(prompt_path), f"Файл не найден: {prompt_path}"

    def test_prompt_file_not_empty(self):
        """Файл ANALYSIS_PROMPT.md не пустой."""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        prompt_path = os.path.join(project_root, "ANALYSIS_PROMPT.md")
        with open(prompt_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert len(content) > 100, "Файл промпта слишком короткий"

    def test_prompt_contains_required_sections(self):
        """Файл промпта содержит обязательные разделы."""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        prompt_path = os.path.join(project_root, "ANALYSIS_PROMPT.md")
        with open(prompt_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "⚽ **Контекст матча**" in content
        assert "🧠 **Психологические факторы**" in content
        assert "2800" in content
        assert "мск" in content.lower()
        assert "venue" in content.lower() or "стадион" in content.lower()

    def test_quality_check_accepts_emoji_headings(self):
        """Эмодзи в заголовках не ломают проверку обязательных секций."""
        text = (
            "⚽ **Контекст матча**\n"
            "Матч 1 проходит 02.03.2026, команды имеют 45 очков и 41 очко.\n\n"
            "📈 **Форма и турнирная ситуация**\n"
            "За 5 туров: 3 победы, 1 ничья, 1 поражение, в таблице 4 и 6 место.\n\n"
            "📊 **Статистика и игровые паттерны**\n"
            "xG 1.8 против 1.2, владение 58%, 14 ударов, 6 в створ, 5 угловых.\n\n"
            "🧠 **Психологические факторы**\n"
            "Есть серия из 7 матчей без поражений и фактор реванша после 1:2.\n\n"
            "🔑 **Вывод**\n"
            "Команды подходят с плотной формой: 10 и 12 очков в последних 5 турах."
        )
        issues = _collect_quality_issues(text)
        missing_sections = [i for i in issues if "обязательный блок" in i]
        assert missing_sections == []

    def test_quality_check_flags_local_time_phrase(self):
        """Фраза про местное время должна считаться ошибкой качества."""
        text = (
            "⚽ **Контекст матча**\n"
            "Матч начнется в 20:00 по местному времени.\n\n"
            "📈 **Форма и турнирная ситуация**\nТекст.\n\n"
            "📊 **Статистика и игровые паттерны**\nТекст.\n\n"
            "🧠 **Психологические факторы**\nТекст.\n\n"
            "🔑 **Вывод**\nТекст с 2 фактами: 10 очков и 58% владения."
        )
        issues = _collect_quality_issues(text, match_time_msk="23:00")
        assert any("местное время" in issue.lower() for issue in issues)

    def test_quality_check_flags_missing_emoji_heading(self):
        """Если заголовок без эмодзи, quality-check должен это отметить."""
        text = (
            "**Контекст матча**\nТекст.\n\n"
            "📈 **Форма и турнирная ситуация**\nТекст.\n\n"
            "📊 **Статистика и игровые паттерны**\nТекст.\n\n"
            "🧠 **Психологические факторы**\nТекст.\n\n"
            "🔑 **Вывод**\nТекст с фактами: 2 гола, 14 ударов."
        )
        issues = _collect_quality_issues(text)
        assert any("должен содержать эмодзи" in issue.lower() for issue in issues)

    def test_quality_check_accepts_psychological_background_heading(self):
        """Синоним «Психологический фон» не должен считаться пропавшим блоком."""
        text = (
            "⚽ **Контекст матча**\n"
            "Матч 1 проходит 02.03.2026, команды имеют 45 и 41 очко.\n\n"
            "📈 **Форма и турнирная ситуация**\n"
            "За 5 туров: 3 победы, 1 ничья, 1 поражение.\n\n"
            "📊 **Статистика и игровые паттерны**\n"
            "xG 1.8 против 1.2, владение 58%, 14 ударов, 6 в створ.\n\n"
            "🧠 **Психологический фон матча**\n"
            "После поражения 1:2 у гостей есть фактор реванша.\n\n"
            "🔑 **Вывод**\n"
            "По цифрам: 58% владения и 14 ударов создают базу для плотного матча."
        )
        issues = _collect_quality_issues(text)
        assert not any("психологические факторы" in issue.lower() for issue in issues)

    def test_extract_missing_required_sections_from_issues(self):
        """Парсер missing-секций корректно выделяет названия блоков."""
        issues = [
            "отсутствует обязательный блок «психологические факторы»",
            "отсутствует обязательный блок «вывод»",
            "заголовок «контекст матча» должен содержать эмодзи",
        ]
        missing = _extract_missing_required_sections(issues)
        assert "психологические факторы" in missing
        assert "вывод" in missing
        assert "контекст матча" not in missing

    def test_inject_section_before_conclusion(self):
        """Fallback-блок вставляется перед «Выводом», а не в самый конец."""
        source = (
            "⚽ **Контекст матча**\n"
            "Контекст.\n\n"
            "🔑 **Вывод**\n"
            "Финал."
        )
        block = (
            "🧠 **Психологические факторы**\n"
            "Психологический фон."
        )
        result = _inject_section_before_conclusion(source, block)
        assert result.index("🧠 **Психологические факторы**") < result.index("🔑 **Вывод**")

    def test_normal_length_text_not_truncated(self):
        """Текст в целевом диапазоне (1400-1900) не обрезается."""
        analysis = "Хороший анализ матча. " * 60  # ~1320 символов
        result = clean_and_truncate(analysis)
        assert len(result) > 500


class TestBuildMatchContext:
    """Тесты построения контекста из данных матча."""

    def test_full_match_data(self):
        """Все заполненные поля включаются в контекст."""
        match_data = {
            'sport': 'football',
            'team1': 'Arsenal',
            'team2': 'Chelsea',
            'match_date': '2026-02-15',
            'match_time': '23:00',
            'league': 'English Premier League',
            'venue': 'Emirates Stadium',
        }
        context = _build_match_context(match_data)
        assert 'футбол' in context
        assert 'Arsenal' in context
        assert 'Chelsea' in context
        assert '2026-02-15' in context
        assert '23:00' in context
        assert 'English Premier League' in context
        assert 'Emirates Stadium' in context

    def test_minimal_match_data(self):
        """Минимальный набор полей (team1, team2, sport) работает."""
        match_data = {
            'sport': 'hockey',
            'team1': 'ЦСКА',
            'team2': 'СКА',
        }
        context = _build_match_context(match_data)
        assert 'хоккей' in context
        assert 'ЦСКА' in context
        assert 'СКА' in context
        assert 'Лига' not in context
        assert 'Стадион' not in context

    def test_none_fields_skipped(self):
        """Поля со значением None пропускаются."""
        match_data = {
            'sport': 'basketball',
            'team1': 'Lakers',
            'team2': 'Celtics',
            'league': None,
            'venue': None,
            'match_time': None,
        }
        context = _build_match_context(match_data)
        assert 'Лига' not in context
        assert 'Стадион' not in context
        assert 'Время' not in context
        assert 'Lakers' in context

    def test_empty_string_fields_skipped(self):
        """Поля с пустой строкой пропускаются."""
        match_data = {
            'sport': 'football',
            'team1': 'Barcelona',
            'team2': 'Real Madrid',
            'league': '',
            'venue': '',
        }
        context = _build_match_context(match_data)
        assert 'Лига' not in context
        assert 'Стадион' not in context

    def test_unknown_sport_passed_as_is(self):
        """Неизвестный вид спорта передаётся без преобразования."""
        match_data = {
            'sport': 'tennis',
            'team1': 'Player A',
            'team2': 'Player B',
        }
        context = _build_match_context(match_data)
        assert 'tennis' in context

    def test_empty_dict(self):
        """Пустой dict возвращает пустую строку."""
        context = _build_match_context({})
        assert context == ''
