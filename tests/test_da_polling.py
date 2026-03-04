"""Тесты для da_polling.py с упором на живой topup-flow."""

import asyncio
import logging
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import da_polling
import pytest
import requests


def run_async(coro):
    return asyncio.run(coro)


class RecordingBot:
    """Простой бот-заглушка для проверки edit/send вызовов."""

    instances = []

    def __init__(self, *args, **kwargs):
        self.sent_messages = []
        self.edited_messages = []
        RecordingBot.instances.append(self)

    async def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)
        return SimpleNamespace(message_id=999)

    async def edit_message_text(self, **kwargs):
        self.edited_messages.append(kwargs)
        return None


@pytest.fixture(autouse=True)
def _clear_bot_instances():
    RecordingBot.instances.clear()
    yield
    RecordingBot.instances.clear()


@pytest.mark.parametrize(
    ("message", "expected_token"),
    [
        ("Мой код ABC123DEF456", "ABC123DEF456"),
        ("abc123def456", "ABC123DEF456"),
        ("код: XY12AB34CD56 спасибо", "XY12AB34CD56"),
        ("без кода", None),
        ("ABCDEF", None),
        ("ABCDEFGHIJKL1", None),
    ],
)
def test_process_donation_extracts_token_by_pattern(monkeypatch, message, expected_token):
    monkeypatch.setattr(da_polling.database, "get_purchase_by_token", lambda token: None, raising=False)
    captured = {"token": None}

    async def fake_handle_topup(topup, donation_id, amount_rub):
        return True

    def get_topup_by_token(token):
        captured["token"] = token
        return {"id": 1, "user_id": 42} if expected_token else None

    monkeypatch.setattr(da_polling.database, "get_topup_by_token", get_topup_by_token)
    monkeypatch.setattr(da_polling.database, "is_donation_event_used", lambda donation_id: False)
    monkeypatch.setattr(da_polling, "_handle_topup_donation", fake_handle_topup)

    result = run_async(
        da_polling.process_donation(
            {"id": "d1", "amount": 100, "message": message, "username": "tester"}
        )
    )

    if expected_token is None:
        assert result is False
        assert captured["token"] is None
    else:
        assert result is True
        assert captured["token"] == expected_token


def test_process_donation_returns_false_when_token_not_found_anywhere(monkeypatch):
    monkeypatch.setattr(da_polling.database, "get_purchase_by_token", lambda token: None, raising=False)
    monkeypatch.setattr(da_polling.database, "get_topup_by_token", lambda token: None)
    monkeypatch.setattr(da_polling.database, "is_donation_event_used", lambda donation_id: False)

    result = run_async(
        da_polling.process_donation(
            {"id": "d2", "amount": 50, "message": "код AAAABBBB1111", "username": "tester"}
        )
    )

    assert result is False


def test_process_donation_routes_to_topup_handler(monkeypatch):
    monkeypatch.setattr(da_polling.database, "get_purchase_by_token", lambda token: None, raising=False)
    monkeypatch.setattr(
        da_polling.database,
        "get_topup_by_token",
        lambda token: {"id": 5, "user_id": 77, "instruction_message_id": None},
    )
    monkeypatch.setattr(da_polling.database, "is_donation_event_used", lambda donation_id: False)
    handler = AsyncMock(return_value=True)
    monkeypatch.setattr(da_polling, "_handle_topup_donation", handler)

    result = run_async(
        da_polling.process_donation(
            {"id": "d3", "amount": "150", "message": "мой токен ZXCV1234QWER", "username": "tester"}
        )
    )

    assert result is True
    handler.assert_awaited_once()


def test_process_donation_is_idempotent_when_event_already_used(monkeypatch):
    monkeypatch.setattr(da_polling.database, "get_purchase_by_token", lambda token: None, raising=False)
    monkeypatch.setattr(da_polling.database, "get_topup_by_token", lambda token: None)
    monkeypatch.setattr(da_polling.database, "is_donation_event_used", lambda donation_id: True)

    result = run_async(
        da_polling.process_donation(
            {"id": "d4", "amount": "200", "message": "код MNBV1234LKJH", "username": "tester"}
        )
    )

    assert result is True


def test_process_donation_swallows_internal_exceptions(monkeypatch):
    monkeypatch.setattr(
        da_polling.database,
        "get_purchase_by_token",
        lambda token: (_ for _ in ()).throw(RuntimeError("boom")),
        raising=False,
    )

    result = run_async(
        da_polling.process_donation(
            {"id": "d5", "amount": "200", "message": "код QWER1234TYUI", "username": "tester"}
        )
    )

    assert result is False


def test_handle_topup_donation_happy_path_edits_instruction_message(monkeypatch):
    import telegram

    monkeypatch.setattr(telegram, "Bot", RecordingBot)
    monkeypatch.setattr(da_polling.database, "is_donation_event_used", lambda donation_id: False)
    monkeypatch.setattr(da_polling.database, "complete_balance_topup", lambda *args: True)
    monkeypatch.setattr(da_polling.database, "get_user_balance", lambda user_id: 250)

    topup = {
        "id": 10,
        "user_id": 123,
        "instruction_message_id": 555,
        "return_match_id": 88,
    }

    result = run_async(da_polling._handle_topup_donation(topup, "don-10", 250))

    assert result is True
    bot = RecordingBot.instances[-1]
    assert len(bot.edited_messages) == 1
    payload = bot.edited_messages[0]
    assert payload["chat_id"] == 123
    assert payload["message_id"] == 555
    button_texts = [btn.text for row in payload["reply_markup"].inline_keyboard for btn in row]
    assert "🎯 Вернуться к матчу" in button_texts


def test_handle_topup_donation_falls_back_to_send_message(monkeypatch):
    import telegram

    class FallbackBot(RecordingBot):
        async def edit_message_text(self, **kwargs):
            raise RuntimeError("edit failed")

    monkeypatch.setattr(telegram, "Bot", FallbackBot)
    monkeypatch.setattr(da_polling.database, "is_donation_event_used", lambda donation_id: False)
    monkeypatch.setattr(da_polling.database, "complete_balance_topup", lambda *args: True)
    monkeypatch.setattr(da_polling.database, "get_user_balance", lambda user_id: 100)

    topup = {"id": 11, "user_id": 456, "instruction_message_id": 777}

    result = run_async(da_polling._handle_topup_donation(topup, "don-11", 100))

    assert result is True
    bot = FallbackBot.instances[-1]
    assert len(bot.sent_messages) == 1


def test_handle_topup_donation_is_idempotent_and_handles_failed_completion(monkeypatch):
    import telegram

    monkeypatch.setattr(telegram, "Bot", RecordingBot)

    topup = {"id": 12, "user_id": 789, "instruction_message_id": None}

    monkeypatch.setattr(da_polling.database, "is_donation_event_used", lambda donation_id: True)
    assert run_async(da_polling._handle_topup_donation(topup, "don-12", 100)) is True

    monkeypatch.setattr(da_polling.database, "is_donation_event_used", lambda donation_id: False)
    monkeypatch.setattr(da_polling.database, "complete_balance_topup", lambda *args: False)
    assert run_async(da_polling._handle_topup_donation(topup, "don-12", 100)) is False


def test_is_transient_http_error_checks_only_5xx():
    assert da_polling._is_transient_http_error(SimpleNamespace(response=SimpleNamespace(status_code=500))) is True
    assert da_polling._is_transient_http_error(SimpleNamespace(response=SimpleNamespace(status_code=503))) is True
    assert da_polling._is_transient_http_error(SimpleNamespace(response=SimpleNamespace(status_code=400))) is False
    assert da_polling._is_transient_http_error(SimpleNamespace(response=SimpleNamespace(status_code=404))) is False
    assert da_polling._is_transient_http_error(SimpleNamespace(response=None)) is False


def test_log_network_error_warning_and_error_threshold(caplog):
    caplog.set_level(logging.WARNING)

    da_polling._log_network_error("temporary problem", 1, 5)
    da_polling._log_network_error("threshold problem", 5, 5)
    da_polling._log_network_error("still failing", 6, 5)

    warning_messages = [rec.getMessage() for rec in caplog.records if rec.levelno == logging.WARNING]
    error_messages = [rec.getMessage() for rec in caplog.records if rec.levelno == logging.ERROR]

    assert any("temporary problem" in msg for msg in warning_messages)
    assert any("threshold problem" in msg for msg in error_messages)
    assert any("still failing" in msg for msg in warning_messages)


def test_get_recent_donations_clamps_limit_and_uses_bearer_token(monkeypatch):
    calls = {"urls": []}

    class Response:
        def raise_for_status(self):
            calls["raised"] = True

        def json(self):
            return {"data": [{"id": i} for i in range(50)]}

    def fake_get(url, headers):
        calls["urls"].append(url)
        calls["headers"] = headers
        return Response()

    monkeypatch.setattr(da_polling.requests, "get", fake_get)
    monkeypatch.setattr(da_polling, "DA_ACCESS_TOKEN", "secret-token")

    defaultish = da_polling.get_recent_donations(limit=0)
    high = da_polling.get_recent_donations(limit=99)
    low = da_polling.get_recent_donations(limit=-5)

    assert len(defaultish) == 10
    assert len(low) == 1
    assert len(high) == 30
    assert "limit=30" in calls["urls"][1]
    assert "limit=1" in calls["urls"][2]
    assert calls["headers"] == {"Authorization": "Bearer secret-token"}
    assert calls["raised"] is True


def test_process_donation_returns_false_for_missing_required_fields(monkeypatch):
    monkeypatch.setattr(da_polling.database, "get_purchase_by_token", lambda token: None, raising=False)
    monkeypatch.setattr(da_polling.database, "get_topup_by_token", lambda token: None)
    monkeypatch.setattr(da_polling.database, "is_donation_event_used", lambda donation_id: False)

    assert run_async(da_polling.process_donation({"message": "ABC123DEF456", "amount": 10})) is False
    assert run_async(da_polling.process_donation({"id": "d6", "message": "ABC123DEF456"})) is False
    assert run_async(da_polling.process_donation({"id": "d7", "amount": 10})) is False


def test_process_donation_returns_false_without_message(monkeypatch):
    monkeypatch.setattr(da_polling.database, "get_purchase_by_token", lambda token: None, raising=False)
    monkeypatch.setattr(da_polling.database, "get_topup_by_token", lambda token: None)
    monkeypatch.setattr(da_polling.database, "is_donation_event_used", lambda donation_id: False)

    result = run_async(da_polling.process_donation({"id": "d8", "amount": 25, "username": "tester"}))

    assert result is False


def test_process_donation_returns_false_when_topup_expired_or_missing(monkeypatch):
    monkeypatch.setattr(da_polling.database, "get_purchase_by_token", lambda token: None, raising=False)
    monkeypatch.setattr(da_polling.database, "get_topup_by_token", lambda token: None)
    monkeypatch.setattr(da_polling.database, "is_donation_event_used", lambda donation_id: False)

    result = run_async(
        da_polling.process_donation(
            {"id": "d9", "amount": 25, "message": "токен TOPUP0000001", "username": "tester"}
        )
    )

    assert result is False


def test_process_donation_purchase_branch_smoke(monkeypatch):
    purchase = {"id": 1, "user_id": 5, "match_id": 9, "amount": 10000, "instruction_message_id": None}
    monkeypatch.setattr(da_polling.database, "get_purchase_by_token", lambda token: purchase, raising=False)
    monkeypatch.setattr(da_polling, "_handle_purchase_donation", AsyncMock(return_value=True))

    result = run_async(
        da_polling.process_donation(
            {"id": "d10", "amount": "100", "message": "PAYM1234TOKN", "username": "buyer"}
        )
    )

    assert result is True
    da_polling._handle_purchase_donation.assert_awaited_once()


def test_handle_topup_donation_sends_only_new_message_without_instruction_id(monkeypatch):
    import telegram

    monkeypatch.setattr(telegram, "Bot", RecordingBot)
    monkeypatch.setattr(da_polling.database, "is_donation_event_used", lambda donation_id: False)
    monkeypatch.setattr(da_polling.database, "complete_balance_topup", lambda *args: True)
    monkeypatch.setattr(da_polling.database, "get_user_balance", lambda user_id: 9)

    topup = {"id": 13, "user_id": 777, "instruction_message_id": None}

    result = run_async(da_polling._handle_topup_donation(topup, "don-13", 1))

    assert result is True
    bot = RecordingBot.instances[-1]
    assert bot.edited_messages == []
    assert len(bot.sent_messages) == 1
    assert "1 анализ" in bot.sent_messages[0]["text"]


def test_handle_topup_donation_omits_return_button_without_match(monkeypatch):
    import telegram

    monkeypatch.setattr(telegram, "Bot", RecordingBot)
    monkeypatch.setattr(da_polling.database, "is_donation_event_used", lambda donation_id: False)
    monkeypatch.setattr(da_polling.database, "complete_balance_topup", lambda *args: True)
    monkeypatch.setattr(da_polling.database, "get_user_balance", lambda user_id: 20)

    topup = {"id": 14, "user_id": 888, "instruction_message_id": 321, "return_match_id": None}

    result = run_async(da_polling._handle_topup_donation(topup, "don-14", 5))

    assert result is True
    buttons = [btn.text for row in RecordingBot.instances[-1].edited_messages[0]["reply_markup"].inline_keyboard for btn in row]
    assert "🎯 Вернуться к матчу" not in buttons


def test_handle_topup_donation_survives_edit_and_send_failures(monkeypatch):
    import telegram

    class BrokenBot(RecordingBot):
        async def edit_message_text(self, **kwargs):
            raise RuntimeError("edit failed")

        async def send_message(self, **kwargs):
            raise RuntimeError("send failed")

    monkeypatch.setattr(telegram, "Bot", BrokenBot)
    monkeypatch.setattr(da_polling.database, "is_donation_event_used", lambda donation_id: False)
    monkeypatch.setattr(da_polling.database, "complete_balance_topup", lambda *args: True)
    monkeypatch.setattr(da_polling.database, "get_user_balance", lambda user_id: 20)

    topup = {"id": 15, "user_id": 999, "instruction_message_id": 654}

    assert run_async(da_polling._handle_topup_donation(topup, "don-15", 4)) is True


@pytest.mark.parametrize(
    ("amount", "word"),
    [(1, "1 анализ"), (2, "2 анализа"), (5, "5 анализов")],
)
def test_handle_topup_donation_uses_correct_analysis_declension(monkeypatch, amount, word):
    import telegram

    monkeypatch.setattr(telegram, "Bot", RecordingBot)
    monkeypatch.setattr(da_polling.database, "is_donation_event_used", lambda donation_id: False)
    monkeypatch.setattr(da_polling.database, "complete_balance_topup", lambda *args: True)
    monkeypatch.setattr(da_polling.database, "get_user_balance", lambda user_id: amount)

    topup = {"id": 16, "user_id": 1001, "instruction_message_id": None}

    run_async(da_polling._handle_topup_donation(topup, f"don-{amount}", amount))

    assert word in RecordingBot.instances[-1].sent_messages[0]["text"]


def test_log_network_error_repeats_error_on_multiple_threshold(caplog):
    caplog.set_level(logging.WARNING)

    da_polling._log_network_error("problem", 20, 5)

    assert any(record.levelno == logging.ERROR and "problem" in record.getMessage() for record in caplog.records)


def test_poll_donations_processes_only_new_ids(monkeypatch):
    processed = []
    sleep_calls = {"count": 0}
    donations_batches = [
        [{"id": "1"}, {"id": "2"}],
        [{"id": "1"}, {"id": "2"}, {"id": "3"}],
    ]

    def fake_get_recent_donations(limit=10):
        return donations_batches.pop(0)

    async def fake_process_donation(donation):
        processed.append(donation["id"])
        return True

    async def fake_sleep(_):
        sleep_calls["count"] += 1
        if sleep_calls["count"] >= 2:
            raise asyncio.CancelledError()

    monkeypatch.setattr(da_polling, "get_recent_donations", fake_get_recent_donations)
    monkeypatch.setattr(da_polling, "process_donation", fake_process_donation)
    monkeypatch.setattr(da_polling.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        run_async(da_polling.poll_donations())

    assert processed == ["2", "1", "3"]


def test_poll_donations_logs_transient_http_error(monkeypatch):
    logged = []

    response = SimpleNamespace(status_code=500)
    error = requests.HTTPError("server error", response=response)

    def fake_get_recent_donations(limit=10):
        raise error

    def fake_log_network_error(msg, count, threshold):
        logged.append((msg, count, threshold))

    async def fake_sleep(_):
        raise asyncio.CancelledError()

    monkeypatch.setattr(da_polling, "get_recent_donations", fake_get_recent_donations)
    monkeypatch.setattr(da_polling, "_log_network_error", fake_log_network_error)
    monkeypatch.setattr(da_polling.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        run_async(da_polling.poll_donations())

    assert logged and logged[0][1] == 1 and logged[0][2] == 5


def test_poll_donations_refreshes_token_on_401(monkeypatch):
    calls = {"count": 0}
    response = SimpleNamespace(status_code=401)
    error = requests.HTTPError("unauthorized", response=response)

    def fake_get_recent_donations(limit=10):
        raise error

    def fake_refresh_access_token():
        calls["count"] += 1

    async def fake_sleep(_):
        raise asyncio.CancelledError()

    monkeypatch.setattr(da_polling, "get_recent_donations", fake_get_recent_donations)
    monkeypatch.setattr(da_polling.asyncio, "sleep", fake_sleep)
    monkeypatch.setitem(sys.modules, "da_oauth", SimpleNamespace(refresh_access_token=fake_refresh_access_token))

    with pytest.raises(asyncio.CancelledError):
        run_async(da_polling.poll_donations())

    assert calls["count"] == 1


def test_poll_donations_swallow_regular_exception_and_continue_to_sleep(monkeypatch):
    calls = {"count": 0}

    def fake_get_recent_donations(limit=10):
        calls["count"] += 1
        raise RuntimeError("boom")

    async def fake_sleep(_):
        raise asyncio.CancelledError()

    monkeypatch.setattr(da_polling, "get_recent_donations", fake_get_recent_donations)
    monkeypatch.setattr(da_polling.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        run_async(da_polling.poll_donations())

    assert calls["count"] == 1
