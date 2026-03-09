import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import config
import user_handlers


def run_async(coro):
    return asyncio.run(coro)


class FakeMessage:
    def __init__(self):
        self.message_id = 700
        self.chat_id = 800
        self.photo = None

    def get_bot(self):
        return SimpleNamespace()


class FakeQuery:
    def __init__(self, data="buy_1"):
        self.data = data
        self.message = FakeMessage()

    async def answer(self, *args, **kwargs):
        return None


def test_handle_purchase_with_balance_starts_generation(monkeypatch):
    query = FakeQuery("buy_12")
    safe_edit = AsyncMock()
    generate = AsyncMock()

    monkeypatch.setattr(config, "ANALYSIS_PRICE_RUB", 150, raising=False)
    monkeypatch.setattr(user_handlers, "safe_answer_callback", AsyncMock())
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)
    monkeypatch.setattr(
        user_handlers.database,
        "get_match_by_id",
        lambda match_id: {
            "id": match_id,
            "team1": "Arsenal",
            "team2": "Chelsea",
            "analysis_text": None,
        },
    )
    monkeypatch.setattr(user_handlers.database, "has_purchased_analysis", lambda user_id, match_id: False)
    monkeypatch.setattr(user_handlers.database, "get_user_balance", lambda user_id: 200)
    monkeypatch.setattr(user_handlers.database, "purchase_analysis", lambda user_id, match_id: (True, "ok"))
    monkeypatch.setitem(
        sys.modules,
        "webhook_server",
        SimpleNamespace(
            generate_and_send_analysis=generate,
            _build_generation_progress_text=lambda match, statuses: f"progress:{match['team1']}",
        ),
    )

    run_async(user_handlers.handle_purchase(query, 42))

    assert safe_edit.await_args_list[0].args[1] == "progress:Arsenal"
    generate.assert_awaited_once_with(
        42,
        12,
        {"id": 12, "team1": "Arsenal", "team2": "Chelsea", "analysis_text": None},
        instruction_message_id=700,
    )


def test_handle_purchase_rejects_insufficient_balance(monkeypatch):
    query = FakeQuery("buy_12")
    safe_edit = AsyncMock()

    monkeypatch.setattr(config, "ANALYSIS_PRICE_RUB", 150, raising=False)
    monkeypatch.setattr(user_handlers, "safe_answer_callback", AsyncMock())
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)
    monkeypatch.setattr(
        user_handlers.database,
        "get_match_by_id",
        lambda match_id: {"id": match_id, "team1": "A", "team2": "B"},
    )
    monkeypatch.setattr(user_handlers.database, "has_purchased_analysis", lambda user_id, match_id: False)
    monkeypatch.setattr(user_handlers.database, "get_user_balance", lambda user_id: 10)

    run_async(user_handlers.handle_purchase(query, 42))

    assert "Недостаточно" in safe_edit.await_args.args[1]
    button = safe_edit.await_args.args[2].inline_keyboard[0][0]
    assert button.callback_data == "deposit"
    assert safe_edit.await_args.args[2].inline_keyboard[1][0].callback_data == "terms_from_match_detail"


def test_handle_purchase_when_already_owned_shows_existing_message(monkeypatch):
    query = FakeQuery("buy_12")
    safe_edit = AsyncMock()

    monkeypatch.setattr(user_handlers, "safe_answer_callback", AsyncMock())
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)
    monkeypatch.setattr(
        user_handlers.database,
        "get_match_by_id",
        lambda match_id: {"id": match_id, "team1": "A", "team2": "B"},
    )
    monkeypatch.setattr(user_handlers.database, "has_purchased_analysis", lambda user_id, match_id: True)

    run_async(user_handlers.handle_purchase(query, 42))

    assert "уже приобрели" in safe_edit.await_args.args[1].lower()


def test_handle_my_analysis_empty_state(monkeypatch):
    query = FakeQuery("my_analysis")
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=42))
    safe_edit = AsyncMock()

    monkeypatch.setattr(user_handlers.database, "get_purchased_matches_by_user", lambda user_id: [])
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers.handle_my_analysis(update, query, 42))

    assert "нет купленных анализов" in safe_edit.await_args.args[1].lower()


def test_handle_my_analysis_groups_purchased_matches_by_sport(monkeypatch):
    query = FakeQuery("my_analysis")
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=42))
    safe_edit = AsyncMock()

    monkeypatch.setattr(
        user_handlers.database,
        "get_purchased_matches_by_user",
        lambda user_id: [
            {"sport": "football"},
            {"sport": "football"},
            {"sport": "hockey"},
        ],
    )
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers.handle_my_analysis(update, query, 42))

    keyboard = safe_edit.await_args.args[2]
    labels = [row[0].text for row in keyboard.inline_keyboard[:-2]]
    assert any("(2" in label for label in labels)
    assert any("(1" in label for label in labels)


def test_handle_purchased_date_filters_matches_by_selected_day(monkeypatch):
    query = FakeQuery("purchased_date_football_2026-03-03")
    safe_edit = AsyncMock()

    monkeypatch.setattr(
        user_handlers.database,
        "get_purchased_matches_by_sport",
        lambda user_id, sport: [
            {"id": 1, "team1": "A", "team2": "B", "match_time": "10:00", "match_date": "2026-03-03"},
            {"id": 2, "team1": "C", "team2": "D", "match_time": "11:00", "match_date": "2026-03-04"},
        ],
    )
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers.handle_purchased_date(query, 42, "football", "2026-03-03"))

    text = safe_edit.await_args.args[1]
    keyboard = safe_edit.await_args.args[2]
    assert "A vs B" in text
    assert "C vs D" not in text
    assert keyboard.inline_keyboard[0][0].callback_data == "match_1"
