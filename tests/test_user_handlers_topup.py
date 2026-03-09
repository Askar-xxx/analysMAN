import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import config
import requests
import user_handlers


def run_async(coro):
    return asyncio.run(coro)


class FakeMessage:
    def __init__(self):
        self.message_id = 900
        self.chat_id = 901
        self.photo = None

    def get_bot(self):
        return SimpleNamespace()


class FakeQuery:
    def __init__(self, data="deposit"):
        self.data = data
        self.message = FakeMessage()

    async def answer(self, *args, **kwargs):
        return None


class FakeContext:
    def __init__(self, user_data=None):
        self.user_data = user_data or {}


def test_handle_deposit_menu_reuses_pending_topup_and_saves_return_target(monkeypatch):
    query = FakeQuery("deposit")
    context = FakeContext({"post_topup_match_id": 55, "post_topup_match_source": "purchased"})
    safe_edit = AsyncMock()
    captured = {}

    monkeypatch.setattr(user_handlers.database, "get_pending_topup_by_user", lambda user_id: {"token": "TOKEN1234567"})
    monkeypatch.setattr(user_handlers.database, "create_balance_topup", lambda user_id, amount_rub=0: "NEWTOKEN1234")
    monkeypatch.setattr(user_handlers.database, "get_user_balance", lambda user_id: 5)
    monkeypatch.setattr(
        user_handlers.database,
        "update_topup_return_target",
        lambda token, match_id=None, match_source="browse": captured.update(
            {"token": token, "match_id": match_id, "match_source": match_source}
        ),
    )
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers.handle_deposit_menu(query, context, 42))

    assert captured == {"token": "TOKEN1234567", "match_id": 55, "match_source": "purchased"}
    assert "TOKEN1234567" in safe_edit.await_args.args[1]
    assert safe_edit.await_args.args[2].inline_keyboard[1][0].callback_data == "terms_from_deposit"


def test_handle_deposit_menu_creates_new_topup_when_pending_missing(monkeypatch):
    query = FakeQuery("deposit")
    context = FakeContext({})
    safe_edit = AsyncMock()
    captured = {}

    monkeypatch.setattr(user_handlers.database, "get_pending_topup_by_user", lambda user_id: None)
    monkeypatch.setattr(user_handlers.database, "create_balance_topup", lambda user_id, amount_rub=0: "NEWTOKEN1234")
    monkeypatch.setattr(user_handlers.database, "get_user_balance", lambda user_id: 11)
    monkeypatch.setattr(
        user_handlers.database,
        "update_topup_return_target",
        lambda token, match_id=None, match_source="browse": captured.update(
            {"token": token, "match_id": match_id, "match_source": match_source}
        ),
    )
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers.handle_deposit_menu(query, context, 42))

    assert captured == {"token": "NEWTOKEN1234", "match_id": None, "match_source": "browse"}
    assert "NEWTOKEN1234" in safe_edit.await_args.args[1]
    assert safe_edit.await_args.args[2].inline_keyboard[1][0].callback_data == "terms_from_deposit"


def test_handle_check_balance_status_shows_not_found(monkeypatch):
    query = FakeQuery("check_balance_TOKEN")
    context = FakeContext()
    safe_edit = AsyncMock()

    monkeypatch.setattr(user_handlers.database, "get_any_topup_by_token", lambda token: None)
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers.handle_check_balance_status(query, 42, "TOKEN", context))

    assert "Код не найден" in safe_edit.await_args.args[1]


def test_handle_check_balance_status_shows_paid_state_with_return_button(monkeypatch):
    query = FakeQuery("check_balance_TOKEN")
    context = FakeContext({"post_topup_match_id": 15})
    safe_edit = AsyncMock()

    monkeypatch.setattr(
        user_handlers.database,
        "get_any_topup_by_token",
        lambda token: {"status": "paid", "amount_rub": 2},
    )
    monkeypatch.setattr(user_handlers.database, "get_user_balance", lambda user_id: 9)
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers.handle_check_balance_status(query, 42, "TOKEN", context))

    assert "+2" in safe_edit.await_args.args[1]
    keyboard = safe_edit.await_args.args[2]
    assert keyboard.inline_keyboard[0][0].callback_data == "return_to_match_15"


def test_handle_check_balance_status_shows_pending_retry(monkeypatch):
    query = FakeQuery("check_balance_TOKEN")
    context = FakeContext()
    safe_edit = AsyncMock()

    monkeypatch.setattr(config, "DA_PROFILE_URL", "https://example.com/pay", raising=False)
    monkeypatch.setattr(config, "SUPPORT_USERNAME", "support_name", raising=False)
    monkeypatch.setattr(
        user_handlers.database,
        "get_any_topup_by_token",
        lambda token: {"status": "pending", "amount_rub": 0},
    )
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers.handle_check_balance_status(query, 42, "TOKEN", context))

    text = safe_edit.await_args.args[1]
    keyboard = safe_edit.await_args.args[2]
    assert "ещё не зачтена" in text.lower()
    assert "@support_name" in text
    assert keyboard.inline_keyboard[0][0].callback_data == "check_balance_TOKEN"


def test_button_handler_routes_check_balance_callback(monkeypatch):
    query = FakeQuery("check_balance_TOKEN")
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=42, username="tester"),
    )
    context = FakeContext({"menu_history": []})
    handler = AsyncMock()

    monkeypatch.setattr(user_handlers, "safe_answer_callback", AsyncMock())
    monkeypatch.setattr(user_handlers, "_is_callback_spam", lambda context, data: False)
    monkeypatch.setattr(user_handlers, "_cleanup_topup_step_images", AsyncMock())
    monkeypatch.setattr(user_handlers, "_cleanup_analysis_thread_messages", AsyncMock())
    monkeypatch.setattr(user_handlers.database, "get_or_create_user", lambda user_id, username: {"user_id": user_id})
    monkeypatch.setattr(user_handlers, "handle_check_balance_status", handler)

    run_async(user_handlers.button_handler(update, context))

    handler.assert_awaited_once_with(query, 42, "TOKEN", context)


def test_handle_check_topup_reports_missing_token(monkeypatch):
    query = FakeQuery("check_topup_TOKN1234ABCD")
    context = FakeContext()
    safe_edit = AsyncMock()

    monkeypatch.setattr(user_handlers.database, "get_any_topup_by_token", lambda token: None)
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers.handle_check_topup(query, 42, "TOKN1234ABCD", context))

    assert "не найден" in safe_edit.await_args.args[1].lower()


def test_handle_check_topup_reports_not_found_donation(monkeypatch):
    query = FakeQuery("check_topup_TOKN1234ABCD")
    context = FakeContext()
    safe_edit = AsyncMock()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": []}

    monkeypatch.setattr(config, "DA_ACCESS_TOKEN", "token", raising=False)
    monkeypatch.setattr(config, "DA_PROFILE_URL", "https://example.com/pay", raising=False)
    monkeypatch.setattr(user_handlers.database, "get_any_topup_by_token", lambda token: {"status": "pending", "amount_kopeks": 10000, "amount_rub": 100, "id": 1})
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers.handle_check_topup(query, 42, "TOKN1234ABCD", context))

    assert "пока не найдена" in safe_edit.await_args_list[-1].args[1].lower()


def test_handle_check_topup_hides_insufficient_amount_fallback(monkeypatch):
    query = FakeQuery("check_topup_TOKN1234ABCD")
    context = FakeContext()
    safe_edit = AsyncMock()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "d1", "amount": "50", "message": "TOKN1234ABCD"}]}

    monkeypatch.setattr(config, "DA_ACCESS_TOKEN", "token", raising=False)
    monkeypatch.setattr(config, "DA_PROFILE_URL", "https://example.com/pay", raising=False)
    monkeypatch.setattr(
        user_handlers.database,
        "get_any_topup_by_token",
        lambda token: {"status": "pending", "amount_kopeks": 10000, "amount_rub": 100, "id": 1},
    )
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers.handle_check_topup(query, 42, "TOKN1234ABCD", context))

    text = safe_edit.await_args_list[-1].args[1].lower()
    assert "пока не зачислено" in text
    assert "недостаточная сумма" not in text


def test_handle_check_topup_completes_successfully(monkeypatch):
    query = FakeQuery("check_topup_TOKN1234ABCD")
    context = FakeContext({"post_topup_match_id": 77})
    safe_edit = AsyncMock()
    completed = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "d1", "amount": "90", "message": "TOKN1234ABCD"}]}

    monkeypatch.setattr(config, "DA_ACCESS_TOKEN", "token", raising=False)
    monkeypatch.setattr(
        user_handlers.database,
        "get_any_topup_by_token",
        lambda token: {"status": "pending", "amount_kopeks": 10000, "amount_rub": 100, "id": 1},
    )
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(
        user_handlers.database,
        "complete_balance_topup",
        lambda topup_id, donation_id: completed.update({"topup_id": topup_id, "donation_id": donation_id}) or True,
    )
    monkeypatch.setattr(user_handlers.database, "get_user_balance", lambda user_id: 105)
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers.handle_check_topup(query, 42, "TOKN1234ABCD", context))

    assert completed == {"topup_id": 1, "donation_id": "d1"}
    assert "баланс пополнен" in safe_edit.await_args_list[-1].args[1].lower()


def test_handle_find_topup_by_amount_handles_no_candidates(monkeypatch):
    query = FakeQuery("find_topup_by_amount_TOKEN")
    context = FakeContext()
    safe_edit = AsyncMock()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": []}

    monkeypatch.setattr(config, "DA_ACCESS_TOKEN", "token", raising=False)
    monkeypatch.setattr(config, "DA_PROFILE_URL", "https://example.com/pay", raising=False)
    monkeypatch.setattr(config, "SUPPORT_USERNAME", "support", raising=False)
    monkeypatch.setattr(
        user_handlers.database,
        "get_any_topup_by_token",
        lambda token: {
            "status": "pending",
            "id": 1,
            "created_at": "2026-03-03 10:00:00",
            "expires_at": "2026-03-03 10:30:00",
        },
    )
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(user_handlers.database, "is_donation_event_used", lambda donation_id: False)
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers.handle_find_topup_by_amount(query, 42, "TOKEN", context))

    assert "не найден" in safe_edit.await_args_list[-1].args[1].lower()


def test_handle_find_topup_by_amount_handles_multiple_candidates(monkeypatch):
    query = FakeQuery("find_topup_by_amount_TOKEN")
    context = FakeContext()
    safe_edit = AsyncMock()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {"id": "d1", "amount": "50", "created_at": "2026-03-03 10:05:00"},
                    {"id": "d2", "amount": "60", "created_at": "2026-03-03 10:10:00"},
                ]
            }

    monkeypatch.setattr(config, "DA_ACCESS_TOKEN", "token", raising=False)
    monkeypatch.setattr(config, "SUPPORT_USERNAME", "support", raising=False)
    monkeypatch.setattr(
        user_handlers.database,
        "get_any_topup_by_token",
        lambda token: {
            "status": "pending",
            "id": 1,
            "created_at": "2026-03-03 10:00:00",
            "expires_at": "2026-03-03 10:30:00",
        },
    )
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(user_handlers.database, "is_donation_event_used", lambda donation_id: False)
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers.handle_find_topup_by_amount(query, 42, "TOKEN", context))

    assert "несколько возможных" in safe_edit.await_args_list[-1].args[1].lower()


def test_handle_find_topup_by_amount_completes_unique_candidate(monkeypatch):
    query = FakeQuery("find_topup_by_amount_TOKEN")
    context = FakeContext({"post_topup_match_id": 10})
    safe_edit = AsyncMock()
    completed = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "d1", "amount": "4", "created_at": "2026-03-03 10:05:00"}]}

    monkeypatch.setattr(config, "DA_ACCESS_TOKEN", "token", raising=False)
    monkeypatch.setattr(
        user_handlers.database,
        "get_any_topup_by_token",
        lambda token: {
            "status": "pending",
            "id": 1,
            "created_at": "2026-03-03 10:00:00",
            "expires_at": "2026-03-03 10:30:00",
        },
    )
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(user_handlers.database, "is_donation_event_used", lambda donation_id: False)
    monkeypatch.setattr(
        user_handlers.database,
        "complete_balance_topup",
        lambda topup_id, donation_id, received_rub=None: completed.update(
            {"topup_id": topup_id, "donation_id": donation_id, "received_rub": received_rub}
        ) or True,
    )
    monkeypatch.setattr(user_handlers.database, "get_user_balance", lambda user_id: 6)
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers.handle_find_topup_by_amount(query, 42, "TOKEN", context))

    assert completed == {"topup_id": 1, "donation_id": "d1", "received_rub": 4}
    assert "донат найден" in safe_edit.await_args_list[-1].args[1].lower()
