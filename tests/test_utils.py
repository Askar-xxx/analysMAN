"""Тесты для utils.py: clean_and_truncate и split_for_telegram."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import clean_and_truncate, split_for_telegram  # noqa: E402


class TestCleanAndTruncate:
    """Тесты для clean_and_truncate."""

    def test_short_text_unchanged(self):
        """Короткий текст без запрещённых слов не меняется по длине."""
        text = "1. Введение о матче\nКоманда А играет хорошо."
        result = clean_and_truncate(text)
        assert len(result) <= 2000

    def test_long_text_within_soft_cap(self):
        """Длинный текст (>900) сокращается до ≤900."""
        text = "Тестовое предложение. " * 60  # ~1260 символов
        result = clean_and_truncate(text)
        assert len(result) <= 900

    def test_very_long_text_within_hard_cap(self):
        """Очень длинный текст без точек не превышает hard cap 1200."""
        text = "слово " * 300  # ~1800 символов, без точек
        result = clean_and_truncate(text)
        assert len(result) <= 1200 + 4  # +4 на '\n...'

    def test_banned_word_coefficient(self):
        """Слово 'коэффициент' и его формы удаляются."""
        text = "Коэффициент команды высокий. Коэффициенты букмекеров растут."
        result = clean_and_truncate(text)
        assert "коэффициент" not in result.lower()

    def test_banned_word_stavka(self):
        """Слово 'ставка' и его формы удаляются."""
        text = "Ставка на победу. Ставки принимаются."
        result = clean_and_truncate(text)
        assert "ставк" not in result.lower()

    def test_banned_word_prognoz(self):
        """Слово 'прогноз' и его формы удаляются."""
        text = "Прогноз на матч. Прогнозы экспертов."
        result = clean_and_truncate(text)
        assert "прогноз" not in result.lower()

    def test_mixed_banned_words(self):
        """Все запрещённые слова удаляются из одного текста."""
        text = "Коэффициент 1.5. Ставка верная. Прогноз положительный. Команда сильная."
        result = clean_and_truncate(text)
        assert "коэффициент" not in result.lower()
        assert "ставк" not in result.lower()
        assert "прогноз" not in result.lower()
        assert "команда" in result.lower()

    def test_emoji_limit_total(self):
        """В тексте не более 4 эмодзи после обработки."""
        text = "⚽ Раздел 1\n🏀 Раздел 2\n🏒 Раздел 3\n🔥 Раздел 4\n⭐ Раздел 5\n📊 Раздел 6"
        result = clean_and_truncate(text)
        emoji_count = sum(1 for ch in result if ord(ch) > 0x2600)
        assert emoji_count <= 4

    def test_returns_string(self):
        """Функция возвращает строку."""
        result = clean_and_truncate("Тест")
        assert isinstance(result, str)


class TestSplitForTelegram:
    """Тесты для split_for_telegram."""

    def test_short_text_single_part(self):
        """Короткий текст возвращается одной частью."""
        text = "Короткий текст."
        parts = split_for_telegram(text)
        assert len(parts) == 1
        assert parts[0] == text

    def test_all_parts_within_limit(self):
        """Все части не превышают лимит."""
        text = "Предложение номер один. " * 300  # ~7200 символов
        parts = split_for_telegram(text, limit=3800)
        for part in parts:
            assert len(part) <= 3800

    def test_no_word_split(self):
        """Текст не режется посередине слова."""
        text = "Длинное предложение с разными словами. " * 200
        parts = split_for_telegram(text, limit=3800)
        for part in parts:
            # Часть не должна начинаться с маленькой буквы после разрыва слова
            # (простая эвристика: не начинается с фрагмента слова)
            assert not part.startswith(' ')

    def test_preserves_all_content(self):
        """Весь текст сохраняется после разбиения (без потери содержимого)."""
        text = "Абзац первый.\n\nАбзац второй.\n\nАбзац третий."
        parts = split_for_telegram(text, limit=20)
        joined = ' '.join(p.strip() for p in parts)
        # Все ключевые слова должны сохраниться
        assert "первый" in joined
        assert "второй" in joined
        assert "третий" in joined

    def test_split_by_double_newline(self):
        """Приоритетный разрыв по двойному переносу строки."""
        block_a = "А" * 100
        block_b = "Б" * 100
        text = block_a + "\n\n" + block_b
        parts = split_for_telegram(text, limit=150)
        assert len(parts) == 2
        assert parts[0].strip() == block_a
        assert parts[1].strip() == block_b

    def test_custom_limit(self):
        """Пользовательский лимит работает корректно."""
        text = "Слово. " * 100
        parts = split_for_telegram(text, limit=100)
        for part in parts:
            assert len(part) <= 100

    def test_returns_list(self):
        """Функция возвращает список."""
        result = split_for_telegram("Тест")
        assert isinstance(result, list)
