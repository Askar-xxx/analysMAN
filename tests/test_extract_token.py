# -*- coding: utf-8 -*-
"""
Тесты utils.extract_token_from_message.

- Нормальный токен находится
- Токен в нижнем регистре тоже находится (uppercase-нормализация)
- Пустая строка → None
- None → None
- Строка без токена → None
- Токен короче 12 символов → None
- Токен длиннее 12 символов → None (не частичное совпадение)
- Несколько токенов в строке → возвращает первый
- Токен в середине длинного текста → находится
- Строка длиной 500+ символов → не падает, токен находится если в первых 500
- Токен за пределами 500 символов → не находится (DoS защита)
"""
from utils import extract_token_from_message


class TestExtractTokenBasic:
    def test_plain_token_found(self):
        """Токен без лишнего текста → находится."""
        assert extract_token_from_message("ABCDEF123456") == "ABCDEF123456"

    def test_token_in_sentence(self):
        """Токен внутри фразы → находится."""
        assert extract_token_from_message("Оплата ABCDEF123456 спасибо") == "ABCDEF123456"

    def test_token_lowercase_normalized(self):
        """Сообщение в нижнем регистре → токен нормализуется в upper."""
        assert extract_token_from_message("код abcdef123456") == "ABCDEF123456"

    def test_token_mixed_case(self):
        """Смешанный регистр → нормализуется."""
        assert extract_token_from_message("AbCdEf123456") == "ABCDEF123456"

    def test_digits_only_token(self):
        """Токен из одних цифр (12 штук) → находится."""
        assert extract_token_from_message("123456789012") == "123456789012"

    def test_letters_only_token(self):
        """Токен из одних букв → находится."""
        assert extract_token_from_message("ABCDEFGHIJKL") == "ABCDEFGHIJKL"


class TestExtractTokenNegative:
    def test_empty_string_returns_none(self):
        """Пустая строка → None."""
        assert extract_token_from_message("") is None

    def test_none_returns_none(self):
        """None → None."""
        assert extract_token_from_message(None) is None

    def test_no_token_in_message(self):
        """Обычный текст без токена → None."""
        assert extract_token_from_message("просто так задонатил, спасибо") is None

    def test_token_too_short_not_matched(self):
        """11 символов — не токен."""
        assert extract_token_from_message("ABCDEF12345") is None

    def test_token_too_long_not_matched_as_whole(self):
        """13 символов подряд — не совпадают как целое слово."""
        # \b требует границу слова — 13-символьное слово не даст 12-символьный match
        assert extract_token_from_message("ABCDEF1234567") is None

    def test_token_embedded_in_longer_word_not_matched(self):
        """Токен внутри длинного слова без пробела — не находится."""
        assert extract_token_from_message("XABCDEF123456Y") is None

    def test_special_chars_only(self):
        """Строка из спецсимволов → None."""
        assert extract_token_from_message("!!! ??? ###") is None


class TestExtractTokenMultiple:
    def test_first_token_returned_when_multiple(self):
        """Несколько токенов в строке → возвращается первый."""
        result = extract_token_from_message("AAAAAA111111 BBBBBB222222")
        assert result == "AAAAAA111111"

    def test_token_after_noise(self):
        """Шум перед токеном не мешает."""
        assert extract_token_from_message("re: fwd: привет! ZZZZZZ999999 ok") == "ZZZZZZ999999"


class TestExtractTokenLengthLimit:
    def test_token_at_start_of_long_message(self):
        """Токен в начале строки 10000 символов → находится."""
        msg = "LONGMSG12345 " + "x" * 10000
        assert extract_token_from_message(msg) == "LONGMSG12345"

    def test_token_within_first_500_chars(self):
        """Токен в позиции ~490 → находится (в пределах лимита 500)."""
        msg = "a " * 240 + "WITHIN500123" + " b" * 100
        # "a " * 240 = 480 символов, токен начинается на позиции 480
        assert extract_token_from_message(msg) == "WITHIN500123"

    def test_token_exactly_at_boundary(self):
        """
        Токен начинается ровно на позиции 488 — последние 12 символов вписываются в 500.
        488 + 12 = 500, значит токен полностью попадает в [:500].
        """
        prefix = "x" * 487 + " "  # 488 символов
        msg = prefix + "BOUNDARY1234"
        assert len(prefix) == 488
        assert len(msg[:500]) == 500
        assert extract_token_from_message(msg) == "BOUNDARY1234"

    def test_token_one_char_past_boundary_not_found(self):
        """
        Токен начинается на позиции 489 — последний символ (501-й) вылетает за [:500].
        Неполный токен не совпадает с regex → None.
        """
        prefix = "x" * 488 + " "  # 489 символов
        msg = prefix + "BOUNDARY1234"
        assert len(prefix) == 489
        assert extract_token_from_message(msg) is None

    def test_token_beyond_500_chars_not_found(self):
        """Токен после 500-го символа → не находится (DoS защита)."""
        msg = "x" * 600 + " FARBEYOND12"
        assert extract_token_from_message(msg) is None

    def test_very_long_message_no_token(self):
        """Строка 100000 символов без токена → не зависает, возвращает None."""
        msg = "абвгд " * 20000
        assert extract_token_from_message(msg) is None
