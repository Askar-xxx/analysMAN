import asyncio
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webhook_server  # noqa: E402


class RecordingBot:
    """Записывает вызовы Telegram Bot без реального API."""

    instances = []

    def __init__(self, *args, **kwargs):
        self.sent_messages = []
        self.edited_messages = []
        self.deleted_messages = []
        RecordingBot.instances.append(self)

    async def send_message(self, *args, **kwargs):
        self.sent_messages.append(kwargs)
        return SimpleNamespace(message_id=999)

    async def edit_message_text(self, *args, **kwargs):
        self.edited_messages.append(kwargs)
        return None

    async def delete_message(self, *args, **kwargs):
        self.deleted_messages.append(kwargs)
        return None


def _has_structured_log(caplog, event: str, status: Optional[str] = None) -> bool:
    for rec in caplog.records:
        msg = rec.getMessage()
        if f"event={event}" not in msg:
            continue
        if status is not None and f"status={status}" not in msg:
            continue
        return True
    return False


def _collect_sent_texts():
    texts = []
    for bot in RecordingBot.instances:
        for payload in bot.sent_messages:
            text = payload.get("text")
            if isinstance(text, str):
                texts.append(text)
    return texts


def _run_pipeline(timeout_sec: float = 2.0) -> bool:
    return asyncio.run(
        asyncio.wait_for(
            webhook_server.generate_and_send_analysis(
                user_id=1001,
                match_id=42,
                match_dict={
                    "id": 42,
                    "sport": "football",
                    "team1": "Arsenal",
                    "team2": "Chelsea",
                    "match_date": "2026-03-01",
                    "match_time": "20:00",
                },
                instruction_message_id=555,
            ),
            timeout=timeout_sec,
        )
    )


@pytest.fixture(autouse=True)
def _prepare_test_env(monkeypatch, tmp_path: Path):
    RecordingBot.instances.clear()
    webhook_server._MATCH_GENERATION_LOCKS.clear()

    for flag in (
        "FORCE_TABLE_TIMEOUT",
        "FORCE_TABLE_ERROR",
        "FORCE_PROGRESS_BADREQUEST",
        "FORCE_SEND_ERROR",
    ):
        monkeypatch.delenv(flag, raising=False)

    monkeypatch.setattr(webhook_server, "PROGRESS_DONE_VISIBLE_SECONDS", 0)
    monkeypatch.setattr(webhook_server.database, "acquire_generation_job", lambda **kwargs: True)
    monkeypatch.setattr(webhook_server.database, "finish_generation_job", lambda *args, **kwargs: None)
    monkeypatch.setattr(webhook_server.database, "wait_for_match_analysis", lambda *args, **kwargs: False)

    state = {
        "analysis_text": "",
        "analysis_png_path": None,
    }

    def _fake_load(match_id, fallback_match_dict):
        match = dict(fallback_match_dict)
        match["analysis_text"] = state["analysis_text"]
        if state["analysis_png_path"]:
            match["analysis_png_path"] = state["analysis_png_path"]
        return match, state["analysis_text"].strip()

    def _fake_update_match_analysis(match_id, text, png_path=None):
        state["analysis_text"] = text
        state["analysis_png_path"] = png_path

    monkeypatch.setattr(webhook_server, "_load_match_with_cache", _fake_load)
    monkeypatch.setattr(
        webhook_server.database, "update_match_analysis", _fake_update_match_analysis
    )

    import telegram
    import match_data_fetcher
    import ai_generator
    import analysis_formatter
    import image_renderer

    monkeypatch.setattr(telegram, "Bot", RecordingBot)
    monkeypatch.setattr(
        match_data_fetcher.MatchDataFetcher,
        "fetch_match_data",
        lambda self, match_dict: {"errors": []},
    )
    monkeypatch.setattr(
        match_data_fetcher,
        "build_enriched_context",
        lambda match_dict, enriched_data: "enriched context",
    )

    async def _fake_generate_text(match_dict, enriched_context):
        return "ТЕКСТОВЫЙ АНАЛИЗ"

    monkeypatch.setattr(ai_generator, "generate_match_text_analysis", _fake_generate_text)
    monkeypatch.setattr(
        analysis_formatter,
        "build_table_data",
        lambda match_dict, enriched_data: {
            "coverage_rows_count": 2,
            "raw_missing_cells_count": 0,
        },
    )

    temp_image = tmp_path / "table.webp"
    temp_image.write_bytes(b"fake-image")
    monkeypatch.setattr(
        image_renderer, "render_analysis_table", lambda match_dict, table_data: str(temp_image)
    )


def test_happy_path_full_result(caplog):
    caplog.set_level(logging.INFO)

    result = _run_pipeline()

    assert result is True
    assert _has_structured_log(caplog, "text_generation_end", "ok")
    assert _has_structured_log(caplog, "table_prepare_end", "ok")
    assert _has_structured_log(caplog, "table_render_end", "ok")
    assert _has_structured_log(caplog, "result_send_end", "ok")
    assert _has_structured_log(caplog, "progress_update_end")
    assert "result_mode=full" in caplog.text


def test_progress_badrequest_nonfatal(monkeypatch, caplog):
    monkeypatch.setenv("FORCE_PROGRESS_BADREQUEST", "1")
    caplog.set_level(logging.INFO)

    result = _run_pipeline()

    assert result is True
    assert "progress_ui_error_nonfatal=True" in caplog.text
    assert "result_mode=full" in caplog.text
    assert _has_structured_log(caplog, "progress_update_end", "error")
    assert len(_collect_sent_texts()) >= 1


def test_table_timeout_results_in_text_only(monkeypatch, caplog):
    monkeypatch.setenv("FORCE_TABLE_TIMEOUT", "1")
    caplog.set_level(logging.INFO)

    result = _run_pipeline()
    sent_texts = _collect_sent_texts()

    assert result is True
    assert "result_mode=text_only_table_timeout" in caplog.text
    assert "event=table_stage_timeout" in caplog.text
    assert len(sent_texts) >= 1
    assert any("таблица временно недоступна" in t.lower() for t in sent_texts)


def test_table_error_results_in_text_only(monkeypatch, caplog):
    monkeypatch.setenv("FORCE_TABLE_ERROR", "1")
    caplog.set_level(logging.INFO)

    result = _run_pipeline()
    sent_texts = _collect_sent_texts()

    assert result is True
    assert "result_mode=text_only_table_error" in caplog.text
    assert len(sent_texts) >= 1
    assert any("таблица временно недоступна" in t.lower() for t in sent_texts)


def test_send_error_falls_back_to_text(monkeypatch, caplog):
    monkeypatch.setenv("FORCE_SEND_ERROR", "1")
    caplog.set_level(logging.INFO)

    result = _run_pipeline()
    sent_texts = _collect_sent_texts()

    assert result is False
    assert len(sent_texts) >= 1
    assert any("финальный экран временно недоступен" in t.lower() for t in sent_texts)
    assert "result_mode=text_only_table_error" in caplog.text
