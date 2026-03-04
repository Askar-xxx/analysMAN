import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import user_handlers


def run_async(coro):
    return asyncio.run(coro)


class FakeBot:
    def __init__(self):
        self.deleted = []
        self.sent_photos = []

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))

    async def send_photo(self, chat_id, photo, reply_markup):
        self.sent_photos.append(
            {"chat_id": chat_id, "name": getattr(photo, "name", ""), "reply_markup": reply_markup}
        )
        return SimpleNamespace(message_id=321)


class FakeMessage:
    def __init__(self, bot=None, photo=None):
        self.message_id = 123
        self.chat_id = 456
        self.photo = photo
        self._bot = bot or FakeBot()

    def get_bot(self):
        return self._bot

    async def delete(self):
        return None


class FakeQuery:
    def __init__(self, message=None):
        self.message = message or FakeMessage()

    async def answer(self, *args, **kwargs):
        return None


class FakeContext:
    def __init__(self, user_data=None):
        self.user_data = user_data or {}


def test_load_match_for_analysis_rejects_missing_purchase(monkeypatch):
    query = FakeQuery()
    safe_edit = AsyncMock()

    monkeypatch.setattr(user_handlers.database, "has_purchased_analysis", lambda user_id, match_id: False)
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    result = run_async(user_handlers._load_match_for_analysis(query, 42, 10))

    assert result is None
    assert "не приобретали" in safe_edit.await_args.args[1].lower()


def test_load_match_for_analysis_rejects_missing_match(monkeypatch):
    query = FakeQuery()
    safe_edit = AsyncMock()

    monkeypatch.setattr(user_handlers.database, "has_purchased_analysis", lambda user_id, match_id: True)
    monkeypatch.setattr(user_handlers.database, "get_match_by_id", lambda match_id: None)
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    result = run_async(user_handlers._load_match_for_analysis(query, 42, 10))

    assert result is None
    assert "матч не найден" in safe_edit.await_args.args[1].lower()


def test_handle_show_table_falls_back_to_text_when_png_build_fails(monkeypatch):
    query = FakeQuery()
    context = FakeContext()
    fallback = AsyncMock()

    monkeypatch.setattr(
        user_handlers,
        "_load_match_for_analysis",
        AsyncMock(return_value={"id": 10, "team1": "A", "team2": "B"}),
    )
    monkeypatch.setattr(user_handlers, "_ensure_analysis_table_png", lambda match_id, match_dict: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(user_handlers, "handle_show_text_analysis", fallback)

    run_async(user_handlers.handle_show_table(query, context, 42, 10, "football_2026-03-04", "analysis_back_football_2026-03-04"))

    fallback.assert_awaited_once_with(
        query,
        context,
        42,
        10,
        callback_suffix="football_2026-03-04",
        back_callback_data="analysis_back_football_2026-03-04",
    )


def test_handle_show_table_sends_photo_and_remembers_thread(monkeypatch, tmp_path):
    png_path = tmp_path / "table.webp"
    png_path.write_bytes(b"img")
    bot = FakeBot()
    query = FakeQuery(FakeMessage(bot=bot))
    context = FakeContext({"analysis_thread": {"related_message_ids": [111, 123]}})

    monkeypatch.setattr(
        user_handlers,
        "_load_match_for_analysis",
        AsyncMock(return_value={"id": 10, "team1": "A", "team2": "B"}),
    )
    monkeypatch.setattr(user_handlers, "_ensure_analysis_table_png", lambda match_id, match_dict: (str(png_path), {}))

    run_async(user_handlers.handle_show_table(query, context, 42, 10))

    assert bot.deleted == [(456, 111)]
    assert len(bot.sent_photos) == 1
    assert context.user_data["analysis_thread"]["conclusion_message_id"] == 321
    assert context.user_data["analysis_thread"]["related_message_ids"] == [321]


def test_handle_show_text_analysis_uses_existing_analysis(monkeypatch):
    query = FakeQuery()
    context = FakeContext({"analysis_thread": {"related_message_ids": [200]}})
    safe_edit = AsyncMock()

    monkeypatch.setattr(
        user_handlers,
        "_load_match_for_analysis",
        AsyncMock(
            return_value={
                "id": 10,
                "team1": "A",
                "team2": "B",
                "match_date": "2026-03-03",
                "match_time": "20:00",
                "analysis_text": "**ready**",
            }
        ),
    )
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)

    run_async(
        user_handlers.handle_show_text_analysis(
            query,
            context,
            42,
            10,
            callback_suffix="football_2026-03-03",
            back_callback_data="analysis_back_football_2026-03-03",
        )
    )

    text = safe_edit.await_args.args[1]
    assert "A vs B" in text
    assert "<b>ready</b>" in text


def test_handle_show_text_analysis_handles_generation_failure(monkeypatch):
    query = FakeQuery()
    context = FakeContext()
    safe_edit = AsyncMock()

    monkeypatch.setattr(
        user_handlers,
        "_load_match_for_analysis",
        AsyncMock(
            return_value={
                "id": 10,
                "team1": "A",
                "team2": "B",
                "match_date": "2026-03-03",
                "match_time": "20:00",
                "analysis_text": "",
            }
        ),
    )
    monkeypatch.setattr(user_handlers, "safe_edit_message", safe_edit)
    monkeypatch.setattr(user_handlers, "_fetch_enriched_data", lambda match_dict: (_ for _ in ()).throw(RuntimeError("fetch failed")))

    run_async(user_handlers.handle_show_text_analysis(query, context, 42, 10))

    texts = [call.args[1] for call in safe_edit.await_args_list]
    assert any("генерируем текстовый анализ" in text.lower() for text in texts)
    assert "временно недоступен" in texts[-1].lower()
