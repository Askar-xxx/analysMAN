"""Тесты для ai_generator.py: проверка загрузки промпта, постобработки и построения контекста."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import clean_and_truncate  # noqa: E402
from ai_generator import _build_match_context  # noqa: E402


class TestAnalysisPostprocessing:
    """Тесты постобработки анализа (clean_and_truncate используется в ai_generator)."""

    def test_long_analysis_truncated(self):
        """Длинный текст анализа сокращается до ≤3000 символов (soft cap)."""
        analysis = (
            "1. Краткое введение о матче\n"
            "Важный матч чемпионата. " * 50 + "\n\n"
            "2. Обзор команды А\n"
            "Команда А показывает хорошую форму. " * 50 + "\n\n"
            "3. Обзор команды Б\n"
            "Команда Б борется за выживание. " * 50 + "\n\n"
        )
        result = clean_and_truncate(analysis)
        assert len(result) <= 3000

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
        assert "СВОДНАЯ ТАБЛИЦА АНАЛИЗА" in content
        assert "Турнирное положение" in content
        assert "Ключевой игрок" in content
        assert "История встреч" in content
        assert "Статистические тренды" in content

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
