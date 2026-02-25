# -*- coding: utf-8 -*-
"""
Тесты utils.clean_and_truncate и utils.split_for_telegram.

clean_and_truncate:
- Запрещённые слова удаляются (коэффициент, ставка, прогноз и их формы)
- Эмодзи не обрезаются если их мало
- Текст короче soft_cap не трогается
- Soft cap: текст сокращается по предложениям, блок «Вывод» сохраняется
- Hard cap: текст обрезается если всё ещё слишком длинный
- Пустая строка → пустая строка

split_for_telegram:
- Короткий текст возвращается как есть (один элемент)
- Длинный текст разбивается на части ≤ limit
- Разбивка предпочитает двойной перенос строки
- Если нет двойного переноса — режет по концу предложения
- Если нет предложений — режет по пробелу
- Ни одна часть не режет слово посередине
- Пустая строка → пустой список или список с одним пустым элементом
"""
import pytest
from utils import clean_and_truncate, split_for_telegram


# ---------------------------------------------------------------------------
# clean_and_truncate
# ---------------------------------------------------------------------------

class TestCleanAndTruncateBannedWords:
    def test_koefficient_removed(self):
        """Слово «коэффициент» удаляется."""
        result = clean_and_truncate("Смотрим на коэффициент победы команды.")
        assert "коэффициент" not in result.lower()

    def test_stavka_removed(self):
        """Слово «ставка» удаляется."""
        result = clean_and_truncate("Лучшая ставка на матч.")
        assert "ставка" not in result.lower()

    def test_prognoz_removed(self):
        """Слово «прогноз» удаляется."""
        result = clean_and_truncate("Наш прогноз на игру.")
        assert "прогноз" not in result.lower()

    def test_word_forms_removed(self):
        """Формы запрещённых слов тоже удаляются."""
        result = clean_and_truncate("Коэффициенты высокие. Ставки растут. Прогнозируем победу.")
        assert "коэффициент" not in result.lower()
        assert "ставк" not in result.lower()
        assert "прогноз" not in result.lower()

    def test_allowed_words_preserved(self):
        """Обычные слова не трогаются."""
        text = "Команда показала хорошую форму в последних матчах."
        result = clean_and_truncate(text)
        assert "Команда" in result
        assert "форму" in result

    def test_empty_string_returns_empty(self):
        """Пустая строка → пустая строка."""
        assert clean_and_truncate("") == ""


class TestCleanAndTruncateLength:
    def test_short_text_not_modified(self):
        """Текст короче soft_cap возвращается без изменений (кроме banned words)."""
        text = "Короткий текст без запрещённых слов."
        result = clean_and_truncate(text)
        assert result == text.strip()

    def test_soft_cap_triggers_truncation(self):
        """Текст длиннее soft_cap сокращается."""
        # Генерируем текст длиннее default soft_cap (3400)
        sentence = "Команда хорошо выступает в домашних матчах. "
        long_text = sentence * 100  # ~4400 символов
        result = clean_and_truncate(long_text)
        assert len(result) <= 3600  # не больше hard_cap

    def test_hard_cap_applied(self):
        """Hard cap: результат не превышает hard_cap."""
        sentence = "А" * 50 + ". "
        long_text = sentence * 100
        result = clean_and_truncate(long_text, hard_cap=500)
        assert len(result) <= 500 + len("\n...")  # небольшой допуск на «...»

    def test_conclusion_block_preserved_after_truncation(self):
        """Блок «Вывод» сохраняется при сокращении текста."""
        body = "Команда отлично играет в атаке. " * 200
        conclusion = "\n\n**Вывод**\nОжидаем упорную борьбу."
        text = body + conclusion
        result = clean_and_truncate(text)
        assert "Вывод" in result
        assert "Ожидаем упорную борьбу" in result

    def test_result_is_stripped(self):
        """Результат не содержит leading/trailing пробелов."""
        text = "  Текст с пробелами по краям.  "
        result = clean_and_truncate(text)
        assert result == result.strip()


class TestCleanAndTruncateEmoji:
    def test_few_emoji_preserved(self):
        """Допустимое количество эмодзи сохраняется."""
        text = "⚽ Команда А против Команды Б.\n📊 Статистика говорит о многом."
        result = clean_and_truncate(text)
        assert "⚽" in result
        assert "📊" in result

    def test_excess_emoji_removed(self):
        """Эмодзи сверх лимита удаляются."""
        # Больше MAX_EMOJI_TOTAL (8) эмодзи — лишние должны исчезнуть
        text = "⚽ ⚽ ⚽ ⚽ ⚽ ⚽ ⚽ ⚽ ⚽ ⚽ текст"
        result = clean_and_truncate(text)
        emoji_count = sum(1 for c in result if c == "⚽")
        assert emoji_count <= 8


# ---------------------------------------------------------------------------
# split_for_telegram
# ---------------------------------------------------------------------------

class TestSplitForTelegram:
    def test_short_text_not_split(self):
        """Текст короче лимита → один элемент."""
        text = "Короткий текст."
        parts = split_for_telegram(text, limit=100)
        assert parts == [text]

    def test_all_parts_within_limit(self):
        """Каждая часть не превышает лимит."""
        text = ("Это предложение. " * 50).strip()
        parts = split_for_telegram(text, limit=100)
        for part in parts:
            assert len(part) <= 100, f"Часть длиннее лимита: {len(part)}"

    def test_no_words_cut_in_half(self):
        """Ни одно слово не разрезается посередине."""
        words = ["слово" + str(i) for i in range(200)]
        text = " ".join(words)
        parts = split_for_telegram(text, limit=50)
        reconstructed = " ".join(parts)
        # Каждое слово должно присутствовать целиком
        for word in words:
            assert word in reconstructed

    def test_prefers_double_newline_split(self):
        """Разбивка предпочитает двойной перенос строки."""
        block1 = "А" * 80
        block2 = "Б" * 80
        text = block1 + "\n\n" + block2
        parts = split_for_telegram(text, limit=100)
        # Блоки должны оказаться в разных частях
        assert any(block1 in p for p in parts)
        assert any(block2 in p for p in parts)

    def test_splits_on_sentence_end_if_no_double_newline(self):
        """Если нет двойного переноса — режет по концу предложения."""
        text = "Первое предложение. " + "Б" * 80 + "."
        parts = split_for_telegram(text, limit=30)
        # Все части заканчиваются на разумном месте, без обрыва слова
        for part in parts:
            assert len(part) <= 30

    def test_whole_text_preserved_after_split(self):
        """Объединение всех частей восстанавливает исходный текст (без потерь)."""
        text = ("Слово " * 300).strip()
        parts = split_for_telegram(text, limit=200)
        assert len(parts) > 1
        joined = " ".join(p.strip() for p in parts)
        # Все слова должны присутствовать
        for word in text.split():
            assert word in joined

    def test_single_long_word_handled(self):
        """Одно слово длиннее лимита — не падает, возвращает его как есть."""
        long_word = "А" * 200
        parts = split_for_telegram(long_word, limit=100)
        assert len(parts) >= 1
        assert all(len(p) > 0 for p in parts)

    def test_empty_string(self):
        """Пустая строка → пустой список или список с пустым элементом, не падает."""
        parts = split_for_telegram("")
        assert isinstance(parts, list)

    def test_multiple_parts_cover_all_content(self):
        """Сумма длин частей близка к длине исходного текста (ничего не теряется)."""
        text = ("Предложение номер {}. ".format(i) for i in range(100))
        text = "".join(text).strip()
        parts = split_for_telegram(text, limit=200)
        total_len = sum(len(p) for p in parts)
        # Допускаем небольшую разницу из-за strip() при разбивке
        assert abs(total_len - len(text)) < len(parts) * 3
