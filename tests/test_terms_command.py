import os
import sys
from types import SimpleNamespace

from telegram.ext import CommandHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import user_handlers  # noqa: E402


def test_setup_user_handlers_registers_terms_command():
    handlers = []

    class FakeApplication:
        def add_handler(self, handler):
            handlers.append(handler)

    user_handlers.setup_user_handlers(FakeApplication())

    terms_handlers = [
        handler for handler in handlers
        if isinstance(handler, CommandHandler) and "terms" in handler.commands
    ]
    assert len(terms_handlers) == 1


def test_build_terms_text_uses_support_fallback(monkeypatch):
    monkeypatch.setattr(config, "SUPPORT_USERNAME", "", raising=False)

    text = user_handlers._build_terms_text()

    assert "информационно-аналитический характер" in text
    assert "Возвраты" in text
    assert "в поддержку бота" in text


def test_terms_command_sends_reply_with_back_to_menu_keyboard(monkeypatch):
    import asyncio

    async def _run():
        monkeypatch.setattr(config, "SUPPORT_USERNAME", "support_name", raising=False)
        captured = {}

        class FakeMessage:
            async def reply_html(self, text, reply_markup):
                captured["text"] = text
                captured["reply_markup"] = reply_markup

        update = SimpleNamespace(message=FakeMessage())

        await user_handlers.terms(update, context=None)

        assert "@support_name" in captured["text"]
        assert captured["reply_markup"].inline_keyboard[0][0].callback_data == "back_to_menu"

    asyncio.run(_run())
