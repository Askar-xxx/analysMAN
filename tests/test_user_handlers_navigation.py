import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import user_handlers


def run_async(coro):
    return asyncio.run(coro)


class FakeMessage:
    def __init__(self):
        self.message_id = 555
        self.chat_id = 777
        self.photo = None
        self.reply_markup = None

    def get_bot(self):
        return SimpleNamespace()

    async def delete(self):
        return None


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.message = FakeMessage()
        self.answered = []

    async def answer(self, *args, **kwargs):
        self.answered.append((args, kwargs))


class FakeContext:
    def __init__(self, user_data=None):
        self.user_data = user_data or {}


def make_update(query_data, user_id=42, username="tester"):
    query = FakeQuery(query_data)
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=user_id, username=username),
    )
    return update, query


def test_parse_analysis_callback_data_supports_plain_and_suffix_formats():
    match_id, suffix, back = user_handlers._parse_analysis_callback_data("show_table_15", "show_table_")
    assert (match_id, suffix, back) == (15, "", "match_15")

    match_id, suffix, back = user_handlers._parse_analysis_callback_data(
        "show_text_15_football_2026-03-04",
        "show_text_",
    )
    assert (match_id, suffix, back) == (
        15,
        "football_2026-03-04",
        "analysis_back_football_2026-03-04",
    )

    match_id, suffix, back = user_handlers._parse_analysis_callback_data("show_text_bad", "show_text_")
    assert (match_id, suffix, back) == (None, "", "back")


def test_button_handler_choose_date_updates_context_and_history(monkeypatch):
    update, query = make_update("choose_date_football_2026-03-04")
    context = FakeContext({"menu_history": []})

    monkeypatch.setattr(user_handlers, "safe_answer_callback", AsyncMock())
    monkeypatch.setattr(user_handlers, "_is_callback_spam", lambda context, data: False)
    monkeypatch.setattr(user_handlers, "_cleanup_topup_step_images", AsyncMock())
    monkeypatch.setattr(user_handlers, "_cleanup_analysis_thread_messages", AsyncMock())
    monkeypatch.setattr(user_handlers.database, "get_or_create_user", lambda user_id, username: {"user_id": user_id})
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_date_selection", handler)

    run_async(user_handlers.button_handler(update, context))

    assert context.user_data["menu_history"] == [user_handlers.MENU_DATE_SELECTION]
    assert context.user_data["current_sport"] == "football"
    assert context.user_data["current_date"] == "2026-03-04"
    assert context.user_data["match_source"] == "browse"
    handler.assert_awaited_once_with(query, context, "football", "2026-03-04")


def test_button_handler_purchased_date_updates_context_and_history(monkeypatch):
    update, query = make_update("purchased_date_football_2026-03-04")
    context = FakeContext({"menu_history": []})

    monkeypatch.setattr(user_handlers, "safe_answer_callback", AsyncMock())
    monkeypatch.setattr(user_handlers, "_is_callback_spam", lambda context, data: False)
    monkeypatch.setattr(user_handlers, "_cleanup_topup_step_images", AsyncMock())
    monkeypatch.setattr(user_handlers, "_cleanup_analysis_thread_messages", AsyncMock())
    monkeypatch.setattr(user_handlers.database, "get_or_create_user", lambda user_id, username: {"user_id": user_id})
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_purchased_date", handler)

    run_async(user_handlers.button_handler(update, context))

    assert context.user_data["menu_history"] == [user_handlers.MENU_PURCHASED_SPORT]
    assert context.user_data["current_sport"] == "football"
    assert context.user_data["current_date"] == "2026-03-04"
    assert context.user_data["match_source"] == "purchased"
    handler.assert_awaited_once_with(query, 42, "football", "2026-03-04")


def test_button_handler_match_invalid_id_shows_stale_message(monkeypatch):
    update, query = make_update("match_bad")
    context = FakeContext({"menu_history": []})

    monkeypatch.setattr(user_handlers, "safe_answer_callback", AsyncMock())
    monkeypatch.setattr(user_handlers, "_is_callback_spam", lambda context, data: False)
    monkeypatch.setattr(user_handlers, "_cleanup_topup_step_images", AsyncMock())
    monkeypatch.setattr(user_handlers, "_cleanup_analysis_thread_messages", AsyncMock())
    monkeypatch.setattr(user_handlers.database, "get_or_create_user", lambda user_id, username: {"user_id": user_id})
    safe_edit = AsyncMock()
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers.button_handler(update, context))

    safe_edit.assert_awaited_once()
    assert "устарела" in safe_edit.await_args.args[1]


def test_button_handler_return_to_match_restores_post_topup_target(monkeypatch):
    update, query = make_update("return_to_match_91")
    context = FakeContext(
        {
            "menu_history": [],
            "post_topup_match_id": 91,
            "post_topup_match_source": "purchased",
        }
    )

    monkeypatch.setattr(user_handlers, "safe_answer_callback", AsyncMock())
    monkeypatch.setattr(user_handlers, "_is_callback_spam", lambda context, data: False)
    monkeypatch.setattr(user_handlers, "_cleanup_topup_step_images", AsyncMock())
    monkeypatch.setattr(user_handlers, "_cleanup_analysis_thread_messages", AsyncMock())
    monkeypatch.setattr(user_handlers.database, "get_or_create_user", lambda user_id, username: {"user_id": user_id})
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_match_detail", handler)

    run_async(user_handlers.button_handler(update, context))

    assert context.user_data["current_match_id"] == 91
    assert context.user_data["match_source"] == "purchased"
    assert "post_topup_match_id" not in context.user_data
    assert "post_topup_match_source" not in context.user_data
    handler.assert_awaited_once_with(query, 42, 91, match_source="purchased")


def test_handle_analysis_back_to_matches_cleans_history_tail(monkeypatch):
    query = FakeQuery("analysis_back_football_2026-03-04")
    context = FakeContext(
        {
            "menu_history": [
                user_handlers.MENU_MAIN,
                user_handlers.MENU_MATCHES_LIST,
                user_handlers.MENU_MATCH_DETAIL,
            ]
        }
    )
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_date_selection", handler)

    run_async(user_handlers.handle_analysis_back_to_matches(query, context, "football", "2026-03-04"))

    assert context.user_data["menu_history"] == []
    assert context.user_data["current_sport"] == "football"
    assert context.user_data["current_date"] == "2026-03-04"
    assert context.user_data["match_source"] == "browse"
    handler.assert_awaited_once_with(query, context, "football", "2026-03-04")


def test_go_back_without_history_returns_to_main_menu(monkeypatch):
    update, _ = make_update("back")
    context = FakeContext({})
    send_main_menu = AsyncMock()
    monkeypatch.setattr(user_handlers, "send_main_menu", send_main_menu)

    run_async(user_handlers.go_back(update, context))

    send_main_menu.assert_awaited_once_with(update, context)


def test_go_back_uses_previous_menu_without_pushing_new_entries(monkeypatch):
    update, query = make_update("back")
    context = FakeContext(
        {
            "menu_history": [user_handlers.MENU_DATE_SELECTION],
            "current_sport": "football",
        }
    )
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_date_selection_back", handler)
    monkeypatch.setattr(user_handlers, "send_main_menu", AsyncMock())

    run_async(user_handlers.go_back(update, context))

    assert context.user_data["menu_history"] == []
    handler.assert_awaited_once_with(query, context, "football")


def test_go_back_from_matches_list_without_date_falls_back_to_sport_selection(monkeypatch):
    update, query = make_update("back")
    context = FakeContext(
        {
            "menu_history": [user_handlers.MENU_MATCHES_LIST],
            "current_sport": "football",
        }
    )
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_sport_selection_back", handler)
    monkeypatch.setattr(user_handlers, "send_main_menu", AsyncMock())

    run_async(user_handlers.go_back(update, context))

    assert context.user_data["menu_history"] == []
    handler.assert_awaited_once_with(query, context, "football")


def test_go_back_from_match_detail_without_match_id_returns_main_menu(monkeypatch):
    update, _ = make_update("back")
    context = FakeContext(
        {
            "menu_history": [user_handlers.MENU_MATCH_DETAIL],
            "match_source": "browse",
        }
    )
    send_main_menu = AsyncMock()
    monkeypatch.setattr(user_handlers, "send_main_menu", send_main_menu)

    run_async(user_handlers.go_back(update, context))

    assert context.user_data["menu_history"] == []
    send_main_menu.assert_awaited_once_with(update, context)


def test_go_back_from_deposit_routes_to_deposit_menu(monkeypatch):
    update, query = make_update("back")
    context = FakeContext({"menu_history": [user_handlers.MENU_DEPOSIT]})
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_deposit_menu", handler)

    run_async(user_handlers.go_back(update, context))

    assert context.user_data["menu_history"] == []
    handler.assert_awaited_once_with(query, context, 42)


def test_go_back_from_how_it_works_routes_to_how_it_works(monkeypatch):
    update, query = make_update("back")
    context = FakeContext({"menu_history": [user_handlers.MENU_HOW_IT_WORKS]})
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_how_it_works", handler)

    run_async(user_handlers.go_back(update, context))

    assert context.user_data["menu_history"] == []
    handler.assert_awaited_once_with(query)
