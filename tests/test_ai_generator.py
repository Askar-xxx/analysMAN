"""Тесты для ai_generator.py: проверка загрузки промпта и постобработки."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import clean_and_truncate  # noqa: E402


class TestAnalysisPostprocessing:
    """Тесты постобработки анализа (clean_and_truncate используется в ai_generator)."""

    def test_long_analysis_truncated(self):
        """Длинный текст анализа сокращается до ≤2000 символов."""
        # Имитация длинного ответа от AI
        analysis = (
            "1. Краткое введение о матче\n"
            "Важный матч чемпионата. " * 50 + "\n\n"
            "2. Обзор команды А\n"
            "Команда А показывает хорошую форму. " * 50 + "\n\n"
            "3. Обзор команды Б\n"
            "Команда Б борется за выживание. " * 50 + "\n\n"
        )
        result = clean_and_truncate(analysis)
        assert len(result) <= 2000

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
        # Полезный контент сохраняется
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
        assert "Краткое введение" in content
        assert "Ключевые игроки" in content
        assert "Тактические особенности" in content

    def test_normal_length_text_not_truncated(self):
        """Текст в целевом диапазоне (1200-1800) не обрезается."""
        analysis = "Хороший анализ матча. " * 60  # ~1320 символов
        result = clean_and_truncate(analysis)
        # Текст не должен быть значительно короче оригинала (кроме удалений)
        assert len(result) > 500
