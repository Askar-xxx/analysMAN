import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import bot_profile


def test_build_dynamic_description_variants(monkeypatch):
    monkeypatch.setattr(bot_profile, "datetime", FakeDateTime)
    assert bot_profile.build_dynamic_description([]) == bot_profile.FALLBACK_DESCRIPTION

    description = bot_profile.build_dynamic_description(
        [
            {"team1": "A", "team2": "B", "match_time": "12:00", "match_date": "2026-03-07"},
            {"team1": "C", "team2": "D", "match_time": "14:00", "match_date": "2026-03-08"},
        ]
    )

    assert "🔥 Самые интересные матчи с AI-разбором:" in description
    assert "A - B — Сегодня, 12:00" in description
    assert "C - D — Завтра, 14:00" in description
    assert "Нажмите Start и выберите матч!" in description


def test_update_dynamic_description_uses_selected_matches(monkeypatch):
    now = datetime(2026, 3, 7, 12, 0)
    bot = AsyncMock()
    candidates = [
        {"team1": "A", "team2": "B", "match_time": "12:00", "match_date": "2026-03-07"},
        {"team1": "C", "team2": "D", "match_time": "14:00", "match_date": "2026-03-08"},
    ]
    selected = [candidates[1]]
    logged = []

    monkeypatch.setattr(bot_profile.database, "get_visible_profile_candidates", lambda **kwargs: candidates)
    monkeypatch.setattr(bot_profile, "select_profile_matches", lambda matches, now, limit=3: selected)
    monkeypatch.setattr(bot_profile, "datetime", FakeDateTime)
    monkeypatch.setattr(
        bot_profile,
        "get_profile_score_breakdown",
        lambda match, now: {"catalog_score": 42, "time_boost": 3, "profile_score": 45},
    )
    monkeypatch.setattr(bot_profile.logger, "info", lambda message, *args: logged.append((message, args)))

    description = asyncio.run(bot_profile.update_dynamic_description(bot, now=now))

    bot.set_my_description.assert_awaited_once_with(description=description)
    assert "C - D — Завтра, 14:00" in description
    assert any(
        entry[0].startswith("Description selected:")
        and entry[1][0] == "C"
        and entry[1][1] == "D"
        and entry[1][4] == 42
        and entry[1][5] == 3
        and entry[1][6] == 45
        for entry in logged
    )


class FakeDateTime:
    @staticmethod
    def now():
        return datetime(2026, 3, 7, 12, 0)

    @staticmethod
    def strptime(value, fmt):
        return datetime.strptime(value, fmt)
