"""Тест для проверки форматирования H2H с fallback."""
from analysis_formatter import extract_h2h_history


def test_h2h_current_season():
    """H2H из текущего сезона - обычный вывод."""
    enriched_data = {
        'h2h': [
            {'date': '2025-10-20', 'home_team': 'Arsenal', 'away_team': 'Chelsea', 'score': '2:1'},
            {'date': '2026-01-15', 'home_team': 'Chelsea', 'away_team': 'Arsenal', 'score': '1:1'}
        ],
        'h2h_is_current_season': True
    }

    result = extract_h2h_history(enriched_data)

    assert len(result) == 2
    assert result[0] == "2025-10-20: Arsenal 2:1 Chelsea"
    assert result[1] == "2026-01-15: Chelsea 1:1 Arsenal"
    print("✓ Тест текущего сезона пройден")


def test_h2h_fallback_to_previous():
    """H2H fallback - с заголовком о прошлых сезонах."""
    enriched_data = {
        'h2h': [
            {'date': '2024-09-22', 'home_team': 'Rayo Vallecano', 'away_team': 'Atletico Madrid', 'score': '1:1'}
        ],
        'h2h_is_current_season': False
    }

    result = extract_h2h_history(enriched_data)

    # Ожидаем: заголовок + пустую строку + матч
    assert len(result) >= 4
    assert "не встречались" in result[0]
    assert "прошлых сезонов" in result[1]
    assert "2024-09-22: Rayo Vallecano 1:1 Atletico Madrid" in result[3]
    print("✓ Тест fallback пройден")


if __name__ == '__main__':
    test_h2h_current_season()
    test_h2h_fallback_to_previous()
    print("\n✅ Все тесты formatter прошли!")
