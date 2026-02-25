"""Тесты webhook_server.py: проверка кэш-пути без повторной генерации."""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webhook_server  # noqa: E402


class _DummyBot:
    """Заглушка Telegram Bot для unit-тестов."""

    def __init__(self, *args, **kwargs):
        pass

    async def send_message(self, *args, **kwargs):
        return None

    async def edit_message_text(self, *args, **kwargs):
        return None

    async def delete_message(self, *args, **kwargs):
        return None


class TestGenerateAndSendAnalysisCache:
    """Тесты кэш-пути generate_and_send_analysis."""

    @patch('telegram.Bot', _DummyBot)
    @patch('webhook_server.database.update_match_analysis')
    @patch('webhook_server._cleanup_progress_message', new_callable=AsyncMock)
    @patch('webhook_server._send_analysis_ready_message', new_callable=AsyncMock)
    @patch('webhook_server._update_generation_progress', new_callable=AsyncMock)
    @patch('ai_generator.generate_match_text_analysis', new_callable=AsyncMock)
    @patch('webhook_server.database.get_match_by_id')
    def test_uses_cached_analysis_without_deepseek(
        self,
        mock_get_match_by_id,
        mock_generate_text,
        mock_update_progress,
        mock_send_ready,
        mock_cleanup_progress,
        mock_update_match_analysis,
    ):
        """Если analysis_text уже есть в БД — DeepSeek не вызывается."""
        mock_get_match_by_id.return_value = {
            'id': 42,
            'sport': 'football',
            'team1': 'Arsenal',
            'team2': 'Chelsea',
            'match_date': '2026-03-01',
            'match_time': '20:00',
            'analysis_text': 'Готовый анализ из БД',
        }

        result = asyncio.run(
            webhook_server.generate_and_send_analysis(
                user_id=1001,
                match_id=42,
                match_dict={'id': 42, 'team1': 'Arsenal', 'team2': 'Chelsea'},
                instruction_message_id=555,
            )
        )

        assert result is True
        mock_generate_text.assert_not_awaited()
        mock_update_match_analysis.assert_not_called()
        mock_send_ready.assert_awaited_once()
        mock_cleanup_progress.assert_awaited_once()
        assert mock_update_progress.await_count >= 2

    @patch('telegram.Bot', _DummyBot)
    @patch('webhook_server.database.update_match_analysis')
    @patch('webhook_server._cleanup_progress_message', new_callable=AsyncMock)
    @patch('webhook_server._send_analysis_ready_message', new_callable=AsyncMock)
    @patch('webhook_server._update_generation_progress', new_callable=AsyncMock)
    @patch('ai_generator.generate_match_text_analysis', new_callable=AsyncMock)
    @patch('webhook_server.database.get_match_by_id')
    def test_double_check_after_lock_uses_cache_without_deepseek(
        self,
        mock_get_match_by_id,
        mock_generate_text,
        mock_update_progress,
        mock_send_ready,
        mock_cleanup_progress,
        mock_update_match_analysis,
    ):
        """Если кэш появился до генерации (double-check), DeepSeek тоже не вызывается."""
        mock_get_match_by_id.side_effect = [
            {
                'id': 42,
                'sport': 'football',
                'team1': 'Arsenal',
                'team2': 'Chelsea',
                'match_date': '2026-03-01',
                'match_time': '20:00',
                'analysis_text': '',
            },
            {
                'id': 42,
                'sport': 'football',
                'team1': 'Arsenal',
                'team2': 'Chelsea',
                'match_date': '2026-03-01',
                'match_time': '20:00',
                'analysis_text': 'Уже сгенерирован другим запросом',
            },
        ]

        result = asyncio.run(
            webhook_server.generate_and_send_analysis(
                user_id=1001,
                match_id=42,
                match_dict={'id': 42, 'team1': 'Arsenal', 'team2': 'Chelsea'},
                instruction_message_id=556,
            )
        )

        assert result is True
        mock_generate_text.assert_not_awaited()
        mock_update_match_analysis.assert_not_called()
        mock_send_ready.assert_awaited_once()
        mock_cleanup_progress.assert_awaited_once()
        assert mock_update_progress.await_count >= 2
