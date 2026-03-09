import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import user_handlers


def run_async(coro):
    return asyncio.run(coro)


class FakeBot:
    def __init__(self):
        self.sent_messages = []
        self.sent_photos = []

    async def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)
        return SimpleNamespace(message_id=999)

    async def send_photo(self, **kwargs):
        self.sent_photos.append(kwargs)
        return SimpleNamespace(message_id=700 + len(self.sent_photos))


class FakeMessage:
    def __init__(self, bot=None):
        self.message_id = 111
        self.chat_id = 222
        self.photo = None
        self.reply_markup = None
        self._bot = bot or FakeBot()
        self.deleted = False

    def get_bot(self):
        return self._bot

    async def delete(self):
        self.deleted = True


class FakeQuery:
    def __init__(self, data, message=None):
        self.data = data
        self.message = message or FakeMessage()
        self.answers = 0

    async def answer(self, *args, **kwargs):
        self.answers += 1


class FakeContext:
    def __init__(self, user_data=None):
        self.user_data = user_data or {}


def make_update(query_data, user_id=42, username="tester", message=None):
    query = FakeQuery(query_data, message=message)
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=user_id, username=username),
    )
    return update, query


def patch_common(monkeypatch):
    monkeypatch.setattr(user_handlers, "safe_answer_callback", AsyncMock())
    monkeypatch.setattr(user_handlers, "_is_callback_spam", lambda context, data: False)
    monkeypatch.setattr(user_handlers, "_cleanup_topup_step_images", AsyncMock())
    monkeypatch.setattr(user_handlers, "_cleanup_analysis_thread_messages", AsyncMock())
    monkeypatch.setattr(user_handlers.database, "get_or_create_user", lambda user_id, username: {"user_id": user_id})


def test_button_handler_back_to_menu_clears_history(monkeypatch):
    update, _ = make_update("back_to_menu")
    context = FakeContext({"menu_history": ["x", "y"]})
    patch_common(monkeypatch)
    send_main_menu = AsyncMock()
    monkeypatch.setattr(user_handlers, "send_main_menu", send_main_menu)

    run_async(user_handlers.button_handler(update, context))

    assert context.user_data["menu_history"] == []
    send_main_menu.assert_awaited_once_with(update, context)


def test_button_handler_spam_returns_before_cleanup_and_routing(monkeypatch):
    update, _ = make_update("deposit")
    context = FakeContext({"menu_history": []})
    cleanup_topup = AsyncMock()
    cleanup_analysis = AsyncMock()

    monkeypatch.setattr(user_handlers, "safe_answer_callback", AsyncMock())
    monkeypatch.setattr(user_handlers, "_is_callback_spam", lambda context, data: True)
    monkeypatch.setattr(user_handlers, "_cleanup_topup_step_images", cleanup_topup)
    monkeypatch.setattr(user_handlers, "_cleanup_analysis_thread_messages", cleanup_analysis)
    monkeypatch.setattr(
        user_handlers.database,
        "get_or_create_user",
        lambda user_id, username: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    run_async(user_handlers.button_handler(update, context))

    cleanup_topup.assert_not_awaited()
    cleanup_analysis.assert_not_awaited()


def test_button_handler_noop_answers_query(monkeypatch):
    update, query = make_update("noop")
    context = FakeContext({"menu_history": []})
    patch_common(monkeypatch)

    run_async(user_handlers.button_handler(update, context))

    assert query.answers == 1


def test_button_handler_category_sports_routes_and_pushes_history(monkeypatch):
    update, query = make_update("category_sports")
    context = FakeContext({"menu_history": []})
    patch_common(monkeypatch)
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_category_sports", handler)

    run_async(user_handlers.button_handler(update, context))

    assert context.user_data["menu_history"] == [user_handlers.MENU_MAIN]
    handler.assert_awaited_once_with(query)


def test_button_handler_support_routes_and_pushes_history(monkeypatch):
    update, query = make_update("support")
    context = FakeContext({"menu_history": []})
    patch_common(monkeypatch)
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_support", handler)

    run_async(user_handlers.button_handler(update, context))

    assert context.user_data["menu_history"] == [user_handlers.MENU_MAIN]
    handler.assert_awaited_once_with(query)


def test_button_handler_how_it_works_entry_routes_and_pushes_history(monkeypatch):
    update, query = make_update("how_it_works")
    context = FakeContext({"menu_history": []})
    patch_common(monkeypatch)
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_how_it_works", handler)

    run_async(user_handlers.button_handler(update, context))

    assert context.user_data["menu_history"] == [user_handlers.MENU_MAIN]
    handler.assert_awaited_once_with(query)


def test_button_handler_invalid_hiw_page_shows_stale_screen(monkeypatch):
    update, _ = make_update("hiw_page_bad")
    context = FakeContext({"menu_history": []})
    patch_common(monkeypatch)
    safe_edit = AsyncMock()
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers.button_handler(update, context))

    assert "устарел" in safe_edit.await_args.args[1].lower()


def test_button_handler_valid_hiw_page_routes(monkeypatch):
    update, query = make_update("hiw_page_2")
    context = FakeContext({"menu_history": []})
    patch_common(monkeypatch)
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_how_it_works", handler)

    run_async(user_handlers.button_handler(update, context))

    handler.assert_awaited_once_with(query, page=2)


def test_button_handler_terms_from_hiw_routes_and_pushes_history(monkeypatch):
    update, query = make_update("terms_from_hiw")
    context = FakeContext({"menu_history": []})
    patch_common(monkeypatch)
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_terms_screen", handler)

    run_async(user_handlers.button_handler(update, context))

    assert context.user_data["menu_history"] == [user_handlers.MENU_HOW_IT_WORKS]
    handler.assert_awaited_once_with(query)


def test_button_handler_terms_from_deposit_routes_and_pushes_history(monkeypatch):
    update, query = make_update("terms_from_deposit")
    context = FakeContext({"menu_history": []})
    patch_common(monkeypatch)
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_terms_screen", handler)

    run_async(user_handlers.button_handler(update, context))

    assert context.user_data["menu_history"] == [user_handlers.MENU_DEPOSIT]
    handler.assert_awaited_once_with(query)


def test_button_handler_invalid_sport_answers_only(monkeypatch):
    update, query = make_update("sport_volleyball")
    context = FakeContext({"menu_history": []})
    patch_common(monkeypatch)

    run_async(user_handlers.button_handler(update, context))

    assert query.answers == 1
    assert context.user_data["menu_history"] == []


def test_button_handler_valid_sport_routes_and_pushes_category_history(monkeypatch):
    update, query = make_update("sport_football")
    context = FakeContext({"menu_history": []})
    patch_common(monkeypatch)
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_sport_selection", handler)

    run_async(user_handlers.button_handler(update, context))

    assert context.user_data["menu_history"] == [user_handlers.MENU_CATEGORY_SPORTS]
    handler.assert_awaited_once_with(query, context, "football")


def test_button_handler_analysis_back_routes(monkeypatch):
    update, query = make_update("analysis_back_football_2026-03-04")
    context = FakeContext({"menu_history": []})
    patch_common(monkeypatch)
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_analysis_back_to_matches", handler)

    run_async(user_handlers.button_handler(update, context))

    handler.assert_awaited_once_with(query, context, "football", "2026-03-04")


def test_button_handler_buy_invalid_id_shows_error(monkeypatch):
    update, _ = make_update("buy_bad")
    context = FakeContext({"menu_history": []})
    patch_common(monkeypatch)
    safe_edit = AsyncMock()
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers.button_handler(update, context))

    assert "покупка недоступна" in safe_edit.await_args.args[1].lower()


def test_button_handler_buy_routes_and_pushes_match_detail(monkeypatch):
    update, query = make_update("buy_15")
    context = FakeContext({"menu_history": []})
    patch_common(monkeypatch)
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_purchase", handler)

    run_async(user_handlers.button_handler(update, context))

    assert context.user_data["menu_history"] == [user_handlers.MENU_MATCH_DETAIL]
    handler.assert_awaited_once_with(query, 42)


def test_button_handler_match_routes_from_browse_and_pushes_matches_list(monkeypatch):
    update, query = make_update("match_15")
    context = FakeContext({"menu_history": [], "match_source": "browse"})
    patch_common(monkeypatch)
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_match_detail", handler)

    run_async(user_handlers.button_handler(update, context))

    assert context.user_data["menu_history"] == [user_handlers.MENU_MATCHES_LIST]
    assert context.user_data["current_match_id"] == 15
    handler.assert_awaited_once_with(query, 42, 15, match_source="browse")


def test_button_handler_match_does_not_duplicate_history_for_same_match(monkeypatch):
    update, query = make_update("match_15")
    context = FakeContext(
        {
            "menu_history": [user_handlers.MENU_PURCHASED_DATE],
            "match_source": "purchased",
            "current_match_id": 15,
        }
    )
    patch_common(monkeypatch)
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_match_detail", handler)

    run_async(user_handlers.button_handler(update, context))

    assert context.user_data["menu_history"] == [user_handlers.MENU_PURCHASED_DATE]
    handler.assert_awaited_once_with(query, 42, 15, match_source="purchased")


def test_button_handler_show_table_routes_with_suffix(monkeypatch):
    update, query = make_update("show_table_15_football_2026-03-04")
    context = FakeContext({"menu_history": []})
    patch_common(monkeypatch)
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_show_table", handler)

    run_async(user_handlers.button_handler(update, context))

    handler.assert_awaited_once_with(
        query,
        context,
        42,
        15,
        callback_suffix="football_2026-03-04",
        back_callback_data="analysis_back_football_2026-03-04",
    )


def test_button_handler_show_text_routes_with_suffix(monkeypatch):
    update, query = make_update("show_text_15_football_2026-03-04")
    context = FakeContext({"menu_history": []})
    patch_common(monkeypatch)
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_show_text_analysis", handler)

    run_async(user_handlers.button_handler(update, context))

    handler.assert_awaited_once_with(
        query,
        context,
        42,
        15,
        callback_suffix="football_2026-03-04",
        back_callback_data="analysis_back_football_2026-03-04",
    )


def test_button_handler_show_text_invalid_payload(monkeypatch):
    update, _ = make_update("show_text_bad")
    context = FakeContext({"menu_history": []})
    patch_common(monkeypatch)
    safe_edit = AsyncMock()
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers.button_handler(update, context))

    assert "текстовый анализ" in safe_edit.await_args.args[1].lower()


def test_button_handler_show_analysis_invalid_id_shows_stale_screen(monkeypatch):
    update, _ = make_update("show_analysis_bad")
    context = FakeContext({"menu_history": []})
    patch_common(monkeypatch)
    safe_edit = AsyncMock()
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers.button_handler(update, context))

    safe_edit.assert_awaited_once()
    assert safe_edit.await_args.args[2] is not None


def test_button_handler_show_analysis_back_compat(monkeypatch):
    update, query = make_update("show_analysis_18")
    context = FakeContext({"menu_history": []})
    patch_common(monkeypatch)
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_show_table", handler)

    run_async(user_handlers.button_handler(update, context))

    handler.assert_awaited_once_with(
        query,
        context,
        42,
        18,
        callback_suffix="",
        back_callback_data="back",
    )


def test_button_handler_purchased_sport_routes_and_pushes_history(monkeypatch):
    update, query = make_update("purchased_sport_football")
    context = FakeContext({"menu_history": []})
    patch_common(monkeypatch)
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_purchased_sport", handler)

    run_async(user_handlers.button_handler(update, context))

    assert context.user_data["menu_history"] == [user_handlers.MENU_MY_ANALYSIS]
    handler.assert_awaited_once_with(query, 42, "football")


def test_button_handler_deposit_remembers_target_and_routes(monkeypatch):
    update, query = make_update("deposit")
    context = FakeContext({"menu_history": [], "current_match_id": 77, "match_source": "browse"})
    remembered = {"called": False}
    handler = AsyncMock()
    patch_common(monkeypatch)
    monkeypatch.setattr(
        user_handlers,
        "_remember_post_topup_target",
        lambda ctx: remembered.update({"called": ctx is context}),
    )
    monkeypatch.setattr(user_handlers, "handle_deposit_menu", handler)

    run_async(user_handlers.button_handler(update, context))

    assert remembered["called"] is True
    handler.assert_awaited_once_with(query, context, 42)


def test_button_handler_confirm_code_copy_routes(monkeypatch):
    update, query = make_update("confirm_code_copy_TOKN1234ABCD")
    context = FakeContext({"menu_history": []})
    patch_common(monkeypatch)
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_confirm_code_copy", handler)

    run_async(user_handlers.button_handler(update, context))

    handler.assert_awaited_once_with(query, context, 42, "TOKN1234ABCD")


def test_button_handler_confirm_code_copy_skips_topup_cleanup(monkeypatch):
    update, query = make_update("confirm_code_copy_TOKN1234ABCD")
    context = FakeContext({"menu_history": []})
    cleanup_topup = AsyncMock()
    cleanup_analysis = AsyncMock()
    handler = AsyncMock()

    monkeypatch.setattr(user_handlers, "safe_answer_callback", AsyncMock())
    monkeypatch.setattr(user_handlers, "_is_callback_spam", lambda context, data: False)
    monkeypatch.setattr(user_handlers, "_cleanup_topup_step_images", cleanup_topup)
    monkeypatch.setattr(user_handlers, "_cleanup_analysis_thread_messages", cleanup_analysis)
    monkeypatch.setattr(user_handlers.database, "get_or_create_user", lambda user_id, username: {"user_id": user_id})
    monkeypatch.setattr(user_handlers, "handle_confirm_code_copy", handler)

    run_async(user_handlers.button_handler(update, context))

    cleanup_topup.assert_not_awaited()
    cleanup_analysis.assert_awaited_once_with(query, context)
    handler.assert_awaited_once_with(query, context, 42, "TOKN1234ABCD")


def test_button_handler_check_topup_and_find_by_amount_route(monkeypatch):
    update1, query1 = make_update("check_topup_TOKN1234ABCD")
    update2, query2 = make_update("find_topup_by_amount_TOKN1234ABCD")
    context1 = FakeContext({"menu_history": []})
    context2 = FakeContext({"menu_history": []})
    patch_common(monkeypatch)
    check_handler = AsyncMock()
    find_handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "handle_check_topup", check_handler)
    monkeypatch.setattr(user_handlers, "handle_find_topup_by_amount", find_handler)

    run_async(user_handlers.button_handler(update1, context1))
    run_async(user_handlers.button_handler(update2, context2))

    check_handler.assert_awaited_once_with(query1, 42, "TOKN1234ABCD", context1)
    find_handler.assert_awaited_once_with(query2, 42, "TOKN1234ABCD", context2)


def test_button_handler_check_balance_skips_topup_cleanup(monkeypatch):
    update, query = make_update("check_balance_TOKN1234ABCD")
    context = FakeContext({"menu_history": []})
    cleanup_topup = AsyncMock()
    cleanup_analysis = AsyncMock()
    handler = AsyncMock()

    monkeypatch.setattr(user_handlers, "safe_answer_callback", AsyncMock())
    monkeypatch.setattr(user_handlers, "_is_callback_spam", lambda context, data: False)
    monkeypatch.setattr(user_handlers, "_cleanup_topup_step_images", cleanup_topup)
    monkeypatch.setattr(user_handlers, "_cleanup_analysis_thread_messages", cleanup_analysis)
    monkeypatch.setattr(user_handlers.database, "get_or_create_user", lambda user_id, username: {"user_id": user_id})
    monkeypatch.setattr(user_handlers, "handle_check_balance_status", handler)

    run_async(user_handlers.button_handler(update, context))

    cleanup_topup.assert_not_awaited()
    cleanup_analysis.assert_awaited_once_with(query, context)
    handler.assert_awaited_once_with(query, 42, "TOKN1234ABCD", context)


def test_button_handler_return_to_match_invalid_id_shows_stale_screen(monkeypatch):
    update, _ = make_update("return_to_match_bad")
    context = FakeContext({"menu_history": []})
    patch_common(monkeypatch)
    safe_edit = AsyncMock()
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers.button_handler(update, context))

    safe_edit.assert_awaited_once()
    assert safe_edit.await_args.args[2] is not None


def test_button_handler_unknown_command_uses_safe_edit(monkeypatch):
    update, _ = make_update("mystery")
    context = FakeContext({"menu_history": []})
    patch_common(monkeypatch)
    safe_edit = AsyncMock()
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers.button_handler(update, context))

    assert "неизвестная команда" in safe_edit.await_args.args[1].lower()


def test_show_deposit_payment_screen_invalid_token(monkeypatch):
    query = FakeQuery("confirm_code_copy_TOKN1234ABCD")
    context = FakeContext({})
    safe_edit = AsyncMock()

    monkeypatch.setattr(user_handlers.database, "get_topup_by_token", lambda token: None)
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers._show_deposit_payment_screen(query, context, 42, "TOKN1234ABCD"))

    assert "не найден" in safe_edit.await_args.args[1].lower()


def test_show_deposit_payment_screen_rejects_foreign_topup(monkeypatch):
    query = FakeQuery("confirm_code_copy_TOKN1234ABCD")
    context = FakeContext({})
    safe_edit = AsyncMock()

    monkeypatch.setattr(user_handlers.database, "get_topup_by_token", lambda token: {"user_id": 99, "id": 1})
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(user_handlers._show_deposit_payment_screen(query, context, 42, "TOKN1234ABCD"))

    safe_edit.assert_awaited_once()
    assert safe_edit.await_args.args[2] is not None


def test_show_deposit_payment_screen_sends_message_and_updates_instruction(monkeypatch, tmp_path):
    bot = FakeBot()
    message = FakeMessage(bot=bot)
    query = FakeQuery("confirm_code_copy_TOKN1234ABCD", message=message)
    context = FakeContext({})
    updated = {}

    monkeypatch.setattr(user_handlers.database, "get_topup_by_token", lambda token: {"user_id": 42, "id": 1})
    monkeypatch.setattr(user_handlers.database, "get_user_balance", lambda user_id: 7)
    monkeypatch.setattr(
        user_handlers.database,
        "update_topup_instruction_message",
        lambda token, message_id: updated.update({"token": token, "message_id": message_id}),
    )
    monkeypatch.setattr(user_handlers, "Path", Path)
    monkeypatch.setattr(user_handlers.config if hasattr(user_handlers, "config") else user_handlers, "__doc__", getattr(user_handlers, "__doc__", None), raising=False)

    original_exists = Path.exists

    def fake_exists(self):
        if str(self).endswith("STEP_1.png") or str(self).endswith("STEP_2.png"):
            return False
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)

    run_async(user_handlers._show_deposit_payment_screen(query, context, 42, "TOKN1234ABCD"))

    assert len(bot.sent_messages) == 1
    assert "TOKN1234ABCD" in bot.sent_messages[0]["text"]
    callbacks = [
        button.callback_data
        for row in bot.sent_messages[0]["reply_markup"].inline_keyboard
        for button in row
        if getattr(button, "callback_data", None)
    ]
    assert "terms_from_deposit" not in callbacks
    assert updated == {"token": "TOKN1234ABCD", "message_id": 999}
    assert message.deleted is True


def test_show_deposit_payment_screen_sends_step_images_and_tracks_ids(monkeypatch, tmp_path):
    bot = FakeBot()
    message = FakeMessage(bot=bot)
    query = FakeQuery("confirm_code_copy_TOKN1234ABCD", message=message)
    context = FakeContext({})
    updated = {}
    original_file = user_handlers.__file__
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    (assets_dir / "STEP_1.png").write_bytes(b"step1")
    (assets_dir / "STEP_2.png").write_bytes(b"step2")

    monkeypatch.setattr(user_handlers, "__file__", str(tmp_path / "user_handlers.py"))
    monkeypatch.setattr(user_handlers.database, "get_topup_by_token", lambda token: {"user_id": 42, "id": 1})
    monkeypatch.setattr(user_handlers.database, "get_user_balance", lambda user_id: 3)
    monkeypatch.setattr(
        user_handlers.database,
        "update_topup_instruction_message",
        lambda token, message_id: updated.update({"token": token, "message_id": message_id}),
    )

    try:
        run_async(user_handlers._show_deposit_payment_screen(query, context, 42, "TOKN1234ABCD"))
    finally:
        monkeypatch.setattr(user_handlers, "__file__", original_file)

    assert [photo["caption"] for photo in bot.sent_photos] == ["ШАГ 1", "ШАГ 2"]
    assert context.user_data["topup_step_image_ids"] == [701, 702]
    assert updated == {"token": "TOKN1234ABCD", "message_id": 999}


def test_handle_confirm_code_copy_delegates_to_payment_screen(monkeypatch):
    query = FakeQuery("confirm_code_copy_TOKN1234ABCD")
    context = FakeContext({})
    handler = AsyncMock()
    monkeypatch.setattr(user_handlers, "_show_deposit_payment_screen", handler)

    run_async(user_handlers.handle_confirm_code_copy(query, context, 42, "TOKN1234ABCD"))

    handler.assert_awaited_once_with(query, context, 42, "TOKN1234ABCD")


def test_build_post_topup_keyboard_uses_return_button_when_target_exists():
    keyboard = user_handlers._build_post_topup_keyboard(
        FakeContext({"post_topup_match_id": 88})
    )

    assert keyboard.inline_keyboard[0][0].callback_data == "return_to_match_88"


def test_remember_post_topup_target_clears_stale_target_outside_match_flow():
    context = FakeContext(
        {
            "menu_history": [user_handlers.MENU_MAIN],
            "current_match_id": 91,
            "post_topup_match_id": 55,
            "post_topup_match_source": "purchased",
        }
    )

    user_handlers._remember_post_topup_target(context)

    assert "post_topup_match_id" not in context.user_data
    assert "post_topup_match_source" not in context.user_data
