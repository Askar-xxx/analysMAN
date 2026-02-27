"""Тесты для ai_generator.py: проверка загрузки промпта, постобработки и построения контекста."""
import asyncio
import sys
import os
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai_generator  # noqa: E402
from utils import clean_and_truncate  # noqa: E402
from ai_generator import (  # noqa: E402
    _build_match_context,
    _find_missing_sections,
    _inject_section_before_conclusion,
    _build_missing_section_block,
    _extract_psych_signals,
    _ensure_section_emojis,
    _is_section_thin,
    _remove_section,
    _count_sentences,
    render_psychological_fallback,
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

    def test_find_missing_sections_all_present(self):
        """Все 5 секций на месте — missing пуст."""
        text = (
            "⚽ **Контекст матча**\nТекст.\n\n"
            "📈 **Форма и турнирная ситуация**\nТекст.\n\n"
            "📊 **Статистика и игровые паттерны**\nТекст.\n\n"
            "🧠 **Психологические факторы**\nТекст.\n\n"
            "🔑 **Вывод**\nТекст."
        )
        assert _find_missing_sections(text) == []

    def test_find_missing_sections_detects_missing(self):
        """Пропущенная секция обнаруживается."""
        text = (
            "⚽ **Контекст матча**\nТекст.\n\n"
            "📈 **Форма и турнирная ситуация**\nТекст.\n\n"
            "📊 **Статистика и игровые паттерны**\nТекст.\n\n"
            "🔑 **Вывод**\nТекст."
        )
        missing = _find_missing_sections(text)
        assert "психологические факторы" in missing

    def test_find_missing_sections_accepts_synonym(self):
        """Синоним «Психологический фон» распознаётся."""
        text = (
            "⚽ **Контекст матча**\nТекст.\n\n"
            "📈 **Форма и турнирная ситуация**\nТекст.\n\n"
            "📊 **Статистика и игровые паттерны**\nТекст.\n\n"
            "🧠 **Психологический фон матча**\nТекст.\n\n"
            "🔑 **Вывод**\nТекст."
        )
        missing = _find_missing_sections(text)
        assert "психологические факторы" not in missing

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

    def test_remove_section_single_heading(self):
        """Удаление секции с одним заголовком вырезает весь блок до следующего раздела."""
        source = (
            "⚽ **Контекст матча**\n"
            "Контекст.\n\n"
            "🧠 **Психологические факторы**\n"
            "Старый психологический текст.\n\n"
            "🔑 **Вывод**\n"
            "Финал."
        )
        result = _remove_section(source, "психологические факторы")
        assert "🧠 **Психологические факторы**" not in result
        assert "Старый психологический текст" not in result
        assert "⚽ **Контекст матча**" in result
        assert "🔑 **Вывод**" in result

    def test_remove_section_duplicate_heading_replacement_has_single_heading(self):
        """При двойном заголовке 🧠 после replacement остается только один заголовок."""
        source = (
            "⚽ **Контекст матча**\n"
            "Контекст.\n\n"
            "🧠 **Психологические факторы**\n"
            "Первый кусок.\n\n"
            "🧠 **Психологические факторы**\n"
            "Второй кусок.\n\n"
            "🔑 **Вывод**\n"
            "Финал."
        )
        removed = _remove_section(source, "психологические факторы")
        replacement = (
            "🧠 **Психологические факторы**\n"
            "Новый fallback-текст."
        )
        result = _inject_section_before_conclusion(removed, replacement)
        assert result.count("🧠 **Психологические факторы**") == 1
        assert "Первый кусок" not in result
        assert "Второй кусок" not in result

    def test_remove_section_to_eof(self):
        """Удаление последней секции работает корректно до конца текста (EOF)."""
        source = (
            "⚽ **Контекст матча**\n"
            "Контекст.\n\n"
            "🧠 **Психологические факторы**\n"
            "Последний блок без следующего заголовка."
        )
        result = _remove_section(source, "психологические факторы")
        assert "🧠 **Психологические факторы**" not in result
        assert "Последний блок" not in result
        assert result.strip() == "⚽ **Контекст матча**\nКонтекст."

    def test_normal_length_text_not_truncated(self):
        """Текст в целевом диапазоне (1400-1900) не обрезается."""
        analysis = "Хороший анализ матча. " * 60  # ~1320 символов
        result = clean_and_truncate(analysis)
        assert len(result) > 500

    def test_extract_psych_signals_parses_block(self):
        """Парсер извлекает сигналы из enriched_context."""
        context = (
            "=== ФОРМА ===\nНекие данные.\n\n"
            "=== ПСИХОЛОГИЧЕСКИЕ ФАКТОРЫ ===\n"
            "Дерби: 75/100 — историческое противостояние\n"
            "Мотивация: 60/100 — борьба за еврокубки\n"
            "Уверенность модели факторов: высокая (80/100)\n\n"
            "=== ДРУГОЙ БЛОК ===\nДругие данные."
        )
        signals = _extract_psych_signals(context)
        assert len(signals) == 2
        assert "Дерби" in signals[0]
        assert "Мотивация" in signals[1]

    def test_extract_psych_signals_empty_when_no_block(self):
        """Если блока психологических факторов нет — пустой список."""
        context = "=== ФОРМА ===\nДанные формы."
        assert _extract_psych_signals(context) == []

    def test_build_missing_psych_block_with_signals(self):
        """Fallback психологических факторов использует реальные сигналы."""
        match_data = {'team1': 'Arsenal', 'team2': 'Chelsea'}
        context = (
            "=== ПСИХОЛОГИЧЕСКИЕ ФАКТОРЫ ===\n"
            "Дерби: 80/100 — лондонское дерби\n"
        )
        block = _build_missing_section_block(
            "психологические факторы", match_data, context
        )
        assert "🧠 **Психологические факторы**" in block
        assert "лондонское дерби" in block
        assert "/100" not in block
        assert "•" not in block

    def test_build_missing_psych_block_without_signals(self):
        """Fallback без сигналов — честное сообщение, а не шаблон."""
        match_data = {'team1': 'Arsenal', 'team2': 'Chelsea', 'league': 'EPL'}
        block = _build_missing_section_block(
            "психологические факторы", match_data, ""
        )
        assert "психологический фон" in block.lower()
        assert "EPL" in block

    def test_render_psychological_fallback_strong_signals(self):
        """Сильные сигналы дают 2-4 связных предложения без скриптового шума."""
        signals = [
            "Дерби: 82/100 — лондонское дерби",
            "Мотивация: 71/100 — борьба за верхнюю часть таблицы",
            "Реванш: 58/100 — память о поражении в первом круге",
        ]
        text = render_psychological_fallback(signals, "Arsenal", "Chelsea")
        assert 2 <= _count_sentences(text) <= 4
        assert "/100" not in text
        assert "•" not in text
        assert not any(line.strip().startswith("-") for line in text.splitlines())
        lowered = text.lower()
        assert "коэффициент" not in lowered
        assert "ставк" not in lowered
        assert "букмекер" not in lowered

    def test_render_psychological_fallback_weak_signals(self):
        """Слабые сигналы дают нейтральный человеческий текст без мусора."""
        signals = [
            "Дерби: 12/100 — нейтральная пара",
            "Мотивация: 18/100 — минимальный фоновый фактор",
        ]
        text = render_psychological_fallback(signals, "Arsenal", "Chelsea")
        assert 2 <= _count_sentences(text) <= 4
        assert "/100" not in text
        assert "данных недостаточно" not in text.lower()
        assert "психологический фон" in text.lower()

    def test_render_psychological_fallback_dedup_categories(self):
        """Смешанные сигналы не дублируют одну и ту же мысль разными фразами."""
        signals = [
            "Мотивация: 58/100 — борьба за топ-4",
            "Турнирная мотивация: 61/100 — минимальный разрыв по очкам",
            "Давление таблицы: 54/100 — цена ошибки растет",
            "Серия: 63/100 — три матча без побед",
        ]
        text = render_psychological_fallback(signals, "Arsenal", "Chelsea")
        assert 2 <= _count_sentences(text) <= 4
        detail_hits = sum(
            phrase in text.lower()
            for phrase in ("борьба за топ-4", "минимальный разрыв по очкам", "цена ошибки растет")
        )
        assert detail_hits <= 1
        assert "/100" not in text

    def test_render_psychological_fallback_soft_block_conclusion_phrases(self):
        """Fallback 🧠 не должен звучать как финальный вывод с решающими клише."""
        signals = [
            "Мотивация: 76/100 — каждая ошибка может стать решающей",
            "Давление таблицы: 69/100 — в итоге именно такие эпизоды часто все определяют",
            "Реванш: 64/100 — это может стать решающим фактором в концовке",
        ]
        text = render_psychological_fallback(signals, "Arsenal", "Chelsea")
        lowered = text.lower()
        assert "может стать решающ" not in lowered
        assert "в итоге именно" not in lowered
        assert "решающей" not in lowered

    def test_psych_soft_block_handles_rockovaya_phrases(self):
        """Soft-block удаляет формулы вида «каждая ошибка может стать роковой»."""
        source = (
            "Каждая ошибка может стать роковой, и это может стать решающим фактором "
            "в концовке при высокой плотности борьбы."
        )
        result = ai_generator._apply_psych_soft_block(source)
        lowered = result.lower()
        assert "роков" not in lowered
        assert "решающ" not in lowered
        assert (
            "эмоциональную цену ошибок" in lowered
            or "осторожности и темпе" in lowered
        )

    def test_render_psychological_fallback_lexical_repetition_limited(self):
        """Повторы ключевой лексики в fallback 🧠 ограничены локальным постпроцессингом."""
        signals = [
            "Турнирная мотивация: 84/100 — давление и давление после серии ошибок добавляют напряжение",
            "Серия: 79/100 — дополнительное давление повышает напряжение в концовке",
            "Реванш: 74/100 — мотивация и мотивация держатся на максимуме",
        ]
        text = render_psychological_fallback(signals, "Arsenal", "Chelsea")
        lowered = text.lower()
        assert len(re.findall(r"\bдавлен\w*\b", lowered)) <= 2
        assert len(re.findall(r"\bнапряж\w*\b", lowered)) <= 2
        assert len(re.findall(r"\bмотивац\w*\b", lowered)) <= 2

    def test_render_psychological_fallback_openings_vary_by_dominant_category(self):
        """Старт fallback 🧠 зависит от доминирующей категории сигнала."""
        cases = [
            ["Дерби: 84/100 — принципиальное противостояние"],
            ["Турнирная мотивация: 86/100 — высокая цена очков в таблице"],
            ["Реванш: 82/100 — желание ответить за поражение в первом круге"],
            ["Серия: 78/100 — четыре матча без побед усиливают фон"],
            ["Травмы: 76/100 — несколько потерь в стартовом составе"],
        ]
        openings = []
        for signals in cases:
            text = render_psychological_fallback(signals, "Arsenal", "Chelsea")
            opening = re.split(r"[.!?]+", text, maxsplit=1)[0].strip()
            openings.append(opening)
        assert len(set(openings)) >= 4

    def test_psych_section_source_logged_as_model(self, monkeypatch, caplog):
        """Если секция 🧠 от модели валидна, логируется psych_section_source=model."""
        raw_text = (
            "⚽ **Контекст матча**\nКонтекст матча в полном объеме.\n\n"
            "📈 **Форма и турнирная ситуация**\nФорма команд описана достаточно подробно.\n\n"
            "📊 **Статистика и игровые паттерны**\nСтатистика подтверждает равный характер пары.\n\n"
            "🧠 **Психологические факторы**\n"
            "Турнирная плотность на верхних местах добавляет эмоциональную нагрузку в каждом эпизоде, "
            "поэтому обе стороны будут аккуратнее управлять риском после потерь мяча. "
            "На фоне серии без побед важной становится реакция на неудачные отрезки и контроль темпа в концовке.\n\n"
            "🔑 **Вывод**\nФинальный вывод по матчу."
        )
        fake_response = SimpleNamespace(
            choices=[SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=raw_text),
            )],
            model="deepseek-chat",
        )
        monkeypatch.setattr(
            ai_generator.client.chat.completions,
            "create",
            AsyncMock(return_value=fake_response),
        )
        match_data = {"team1": "Arsenal", "team2": "Chelsea", "sport": "football"}

        with caplog.at_level("INFO"):
            asyncio.run(ai_generator.generate_match_text_analysis(match_data, ""))
        messages = [rec.getMessage() for rec in caplog.records]
        assert any("psych_section_source=model" in msg for msg in messages)

    def test_psych_section_source_logged_as_missing_repair(self, monkeypatch, caplog):
        """Если секция 🧠 отсутствует у модели, логируется psych_section_source=missing_repair."""
        raw_text = (
            "⚽ **Контекст матча**\nКонтекст матча в полном объеме.\n\n"
            "📈 **Форма и турнирная ситуация**\nФорма команд описана достаточно подробно.\n\n"
            "📊 **Статистика и игровые паттерны**\nСтатистика подтверждает равный характер пары.\n\n"
            "🔑 **Вывод**\nФинальный вывод по матчу."
        )
        fake_response = SimpleNamespace(
            choices=[SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=raw_text),
            )],
            model="deepseek-chat",
        )
        monkeypatch.setattr(
            ai_generator.client.chat.completions,
            "create",
            AsyncMock(return_value=fake_response),
        )
        match_data = {"team1": "Arsenal", "team2": "Chelsea", "sport": "football"}
        enriched_context = (
            "=== ПСИХОЛОГИЧЕСКИЕ ФАКТОРЫ ===\n"
            "Дерби: 82/100 — лондонское противостояние\n"
            "Мотивация: 74/100 — борьба за еврокубки\n"
        )

        with caplog.at_level("INFO"):
            asyncio.run(ai_generator.generate_match_text_analysis(match_data, enriched_context))
        messages = [rec.getMessage() for rec in caplog.records]
        assert any("psych_section_source=missing_repair" in msg for msg in messages)
        assert any("reasons=psych_missing_after_model,psych_fallback_template_used" in msg for msg in messages)

    def test_psych_section_source_logged_as_fallback_template_for_thin(self, monkeypatch, caplog):
        """Если секция 🧠 слишком короткая, логируется psych_section_source=fallback_template."""
        raw_text = (
            "⚽ **Контекст матча**\nКонтекст матча в полном объеме.\n\n"
            "📈 **Форма и турнирная ситуация**\nФорма команд описана достаточно подробно.\n\n"
            "📊 **Статистика и игровые паттерны**\nСтатистика подтверждает равный характер пары.\n\n"
            "🧠 **Психологические факторы**\nКоротко.\n\n"
            "🔑 **Вывод**\nФинальный вывод по матчу."
        )
        fake_response = SimpleNamespace(
            choices=[SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=raw_text),
            )],
            model="deepseek-chat",
        )
        monkeypatch.setattr(
            ai_generator.client.chat.completions,
            "create",
            AsyncMock(return_value=fake_response),
        )
        match_data = {"team1": "Arsenal", "team2": "Chelsea", "sport": "football"}
        enriched_context = (
            "=== ПСИХОЛОГИЧЕСКИЕ ФАКТОРЫ ===\n"
            "Серия: 79/100 — три матча без побед\n"
        )

        with caplog.at_level("INFO"):
            asyncio.run(ai_generator.generate_match_text_analysis(match_data, enriched_context))
        messages = [rec.getMessage() for rec in caplog.records]
        assert any("psych_section_source=fallback_template" in msg for msg in messages)
        assert any("reasons=psych_thin_after_model,psych_fallback_template_used" in msg for msg in messages)

    def test_ensure_section_emojis_adds_missing_key(self):
        """Заголовок «Вывод» без emoji 🔑 получает его автоматически."""
        text = "\n".join([
            "⚽ **Контекст матча**",
            "Текст контекста.",
            "",
            "📈 **Форма и турнирная ситуация**",
            "Текст формы.",
            "",
            "📊 **Статистика и игровые паттерны**",
            "Текст статистики.",
            "",
            "🧠 **Психологические факторы**",
            "Текст психологии.",
            "",
            "**Вывод**",
            "Текст вывода.",
        ])
        result = _ensure_section_emojis(text)
        assert "🔑 **Вывод**" in result
        assert result.count("⚽") == 1
        assert result.count("🔑") == 1

    def test_ensure_section_emojis_bare_heading(self):
        """Заголовок без ** и без emoji — оборачивается и получает emoji."""
        text = "\n".join([
            "⚽ **Контекст матча**",
            "Текст.",
            "",
            "  Вывод",
            "Текст вывода.",
        ])
        result = _ensure_section_emojis(text)
        assert "🔑 **Вывод**" in result

    def test_thin_psych_section_one_meaningful_sentence_not_thin(self):
        """Качественная секция 🧠 в одном длинном предложении не считается thin."""
        text = "\n".join([
            "⚽ **Контекст матча**",
            "Текст контекста достаточной длины.",
            "",
            "🧠 **Психологические факторы**",
            "Матч не является дерби в классическом понимании, но исторически "
            "очные встречи проходят в жёсткой борьбе, о чём свидетельствует "
            "в среднем 7.0 карточек и около 24.0 фолов за игру.",
            "",
            "🔑 **Вывод**",
            "Текст вывода.",
        ])
        assert not _is_section_thin(text, "психологические факторы")

    def test_thin_psych_section_very_short(self):
        """Секция 🧠 с коротким текстом считается thin."""
        text = "\n".join([
            "⚽ **Контекст матча**",
            "Текст.",
            "",
            "🧠 **Психологические факторы**",
            "Коротко.",
            "",
            "🔑 **Вывод**",
            "Текст вывода.",
        ])
        assert _is_section_thin(text, "психологические факторы")

    def test_thin_psych_section_formal_one_sentence(self):
        """Пустая/формальная секция 🧠 должна считаться thin."""
        text = "\n".join([
            "⚽ **Контекст матча**",
            "Текст.",
            "",
            "🧠 **Психологические факторы**",
            "Матч важный и эмоциональный.",
            "",
            "🔑 **Вывод**",
            "Текст вывода.",
        ])
        assert _is_section_thin(text, "психологические факторы")

    def test_normal_psych_section_not_replaced(self):
        """Нормальная секция 🧠 с 3+ предложениями НЕ считается thin."""
        long_body = (
            "Психологический фон матча определяется рядом факторов. "
            "Обе команды подходят к встрече с серьёзной мотивацией, "
            "что подтверждается их турнирным положением. "
            "Дополнительное давление на хозяев оказывает необходимость "
            "набирать очки для борьбы за зону еврокубков. "
            "Гости, напротив, могут играть раскрепощённо без турнирного давления."
        )
        text = "\n".join([
            "⚽ **Контекст матча**",
            "Текст контекста.",
            "",
            "🧠 **Психологические факторы**",
            long_body,
            "",
            "🔑 **Вывод**",
            "Текст вывода.",
        ])
        assert not _is_section_thin(text, "психологические факторы")

    def test_short_quality_psych_section_not_replaced(self):
        """Короткая, но содержательная секция 🧠 (2 предложения) не считается thin."""
        body = (
            "Турнирная плотность на верхних местах повышает давление в каждом эпизоде, "
            "поэтому команды будут осторожнее управлять риском после потерь мяча. "
            "На фоне недавней серии без побед эмоциональная устойчивость может стать ключевым фактором в концовке."
        )
        text = "\n".join([
            "⚽ **Контекст матча**",
            "Текст контекста.",
            "",
            "🧠 **Психологические факторы**",
            body,
            "",
            "🔑 **Вывод**",
            "Текст вывода.",
        ])
        assert not _is_section_thin(text, "психологические факторы")

    def test_pipeline_order_thin_check_happens_before_final_truncate(self, monkeypatch):
        """Thin-check секции 🧠 выполняется до финального truncate."""
        raw_text = (
            "⚽ **Контекст матча**\nКонтекст матча в полном объеме.\n\n"
            "📈 **Форма и турнирная ситуация**\nФорма команд описана достаточно подробно.\n\n"
            "📊 **Статистика и игровые паттерны**\nСтатистика подтверждает равный характер пары.\n\n"
            "🧠 **Психологические факторы**\n"
            "УНИКАЛЬНЫЙ_ПСИХ_МАРКЕР Турнирная плотность увеличивает внутреннее давление и цену ошибки. "
            "На фоне серии без побед это может повлиять на эмоциональный контроль в концовке.\n\n"
            "🔑 **Вывод**\nФинальный вывод по матчу."
        )
        fake_response = SimpleNamespace(
            choices=[SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=raw_text),
            )],
            model="deepseek-chat",
        )
        monkeypatch.setattr(
            ai_generator.client.chat.completions,
            "create",
            AsyncMock(return_value=fake_response),
        )

        call_order = []
        original_is_section_thin = ai_generator._is_section_thin

        def fake_is_section_thin(text, section, min_chars=250, min_sentences=3):
            if section == "психологические факторы":
                call_order.append("thin")
                assert "УНИКАЛЬНЫЙ_ПСИХ_МАРКЕР" in text
            return original_is_section_thin(
                text, section, min_chars=min_chars, min_sentences=min_sentences
            )

        def fake_clean_and_truncate(text, target_max=2800, soft_cap=3400, hard_cap=3600):
            call_order.append("clean")
            return text.replace("УНИКАЛЬНЫЙ_ПСИХ_МАРКЕР ", "")

        monkeypatch.setattr(ai_generator, "_is_section_thin", fake_is_section_thin)
        monkeypatch.setattr(ai_generator, "clean_and_truncate", fake_clean_and_truncate)

        match_data = {"team1": "Arsenal", "team2": "Chelsea", "sport": "football"}
        result = asyncio.run(ai_generator.generate_match_text_analysis(match_data, ""))

        assert "thin" in call_order
        assert "clean" in call_order
        assert call_order.index("thin") < call_order.index("clean")
        assert "УНИКАЛЬНЫЙ_ПСИХ_МАРКЕР" not in result

    def test_count_sentences(self):
        """Подсчёт предложений работает корректно."""
        assert _count_sentences("Одно предложение.") == 1
        assert _count_sentences("Первое предложение. Второе предложение. Третье.") == 3
        assert _count_sentences("") == 0


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
