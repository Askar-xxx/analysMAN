# -*- coding: utf-8 -*-
"""
Вспомогательный Flask-сервер и HTTP endpoints проекта.

Прямой webhook-flow оплаты анализа через DonationAlerts отключён.
Актуальная обработка донатов идёт через polling listener в da_polling.py.
"""
import logging
import time
import os
import re
from html import unescape
from datetime import datetime
from typing import Optional
from flask import Flask, jsonify
import asyncio
import database
from config import TOKEN, TABLE_RENDER_CACHE_VERSION
from telegram.error import BadRequest

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

PROGRESS_DONE_VISIBLE_SECONDS = 1.2
TABLE_PREPARE_TIMEOUT_SEC = 20
TABLE_RENDER_TIMEOUT_SEC = 30
ANALYSIS_JOB_SLOW_PATH_SECONDS = 120
TEXT_FALLBACK_MAX_LEN = 3900


def _env_flag_enabled(name: str) -> bool:
    """Возвращает True, если env-флаг включён (1/true/yes/on)."""
    value = str(os.getenv(name, '')).strip().lower()
    return value in {'1', 'true', 'yes', 'on'}


def _duration_ms(started_at: float) -> int:
    """Возвращает длительность в миллисекундах от переданного timestamp."""
    return int((time.monotonic() - started_at) * 1000)


def _log_structured_step(
    event: str,
    match_id: Optional[int],
    user_id: Optional[int],
    step: str,
    status: str,
    duration_ms: Optional[int] = None,
    level: str = 'info',
    **extra,
) -> None:
    """Пишет структурный лог шага pipeline в формате key=value."""
    parts = [
        f"event={event}",
        f"match_id={match_id}",
        f"user_id={user_id}",
        f"step={step}",
        f"status={status}",
    ]
    if duration_ms is not None:
        parts.append(f"duration_ms={duration_ms}")
    for key, value in extra.items():
        if value is None:
            continue
        parts.append(f"{key}={value}")
    message = " ".join(parts)
    if level == 'error':
        logger.error(message)
    elif level == 'warning':
        logger.warning(message)
    else:
        logger.info(message)


def _strip_html(text: str) -> str:
    """Убирает HTML-теги из текста для plain-text fallback."""
    no_tags = re.sub(r"<[^>]+>", "", text or "")
    return unescape(no_tags)


def _stage_icon(status: str) -> str:
    """Иконка состояния шага прогресса."""
    if status == 'done':
        return "✅"
    if status == 'run':
        return "⏳"
    if status == 'error':
        return "❌"
    return "▫️"


def _build_generation_progress_text(match_dict: dict, statuses: dict) -> str:
    """Формирует текст прогресса генерации для пользователя."""
    team1 = match_dict.get('team1', 'Команда 1')
    team2 = match_dict.get('team2', 'Команда 2')
    match_date = match_dict.get('match_date', '')
    match_time = match_dict.get('match_time', '')

    return (
        "⏳ <b>Генерируем анализ...</b>\n\n"
        f"🏆 {team1} vs {team2}\n"
        f"📅 {match_date} {match_time} МСК\n\n"
        "<b>Текстовый анализ</b>\n"
        f"{_stage_icon(statuses.get('text_data'))} 1/2 Сбор и обогащение данных\n"
        f"{_stage_icon(statuses.get('text_generate'))} 2/2 Генерация текста\n\n"
        "<b>Таблица</b>\n"
        f"{_stage_icon(statuses.get('table_prepare'))} 1/2 Подготовка таблицы\n"
        f"{_stage_icon(statuses.get('table_render'))} 2/2 Рендер изображения\n\n"
        "<b>Финал</b>\n"
        f"{_stage_icon(statuses.get('send'))} Отправка результата"
    )


async def _update_generation_progress(
    bot,
    user_id: int,
    instruction_message_id: int,
    match_dict: dict,
    statuses: dict,
    match_id: Optional[int] = None,
) -> bool:
    """Безопасно обновляет сообщение прогресса генерации."""
    if not instruction_message_id:
        return True

    started_at = time.monotonic()
    _log_structured_step(
        event='progress_update_start',
        match_id=match_id,
        user_id=user_id,
        step='progress_update',
        status='start',
    )
    text = _build_generation_progress_text(match_dict, statuses)
    try:
        if _env_flag_enabled('FORCE_PROGRESS_BADREQUEST'):
            raise BadRequest('forced progress bad request')
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=instruction_message_id,
            text=text,
            parse_mode='HTML'
        )
        _log_structured_step(
            event='progress_update_end',
            match_id=match_id,
            user_id=user_id,
            step='progress_update',
            status='ok',
            duration_ms=_duration_ms(started_at),
        )
        return True
    except BadRequest as e:
        err = str(e).lower()
        if "message is not modified" in err:
            _log_structured_step(
                event='progress_update_end',
                match_id=match_id,
                user_id=user_id,
                step='progress_update',
                status='ok',
                duration_ms=_duration_ms(started_at),
                reason='not_modified',
            )
            return True
        if (
            "can't parse entities" in err
            or "parse entities" in err
            or "entity offset" in err
        ):
            logger.warning(
                "Ошибка parse_mode у progress update (message_id=%s), fallback на plain text: %s",
                instruction_message_id,
                e
            )
            try:
                await bot.edit_message_text(
                    chat_id=user_id,
                    message_id=instruction_message_id,
                    text=_strip_html(text),
                )
            except Exception as fallback_error:
                logger.warning(
                    "Fallback progress update (plain text) тоже не удался (message_id=%s): %s",
                    instruction_message_id,
                    fallback_error
                )
            _log_structured_step(
                event='progress_update_end',
                match_id=match_id,
                user_id=user_id,
                step='progress_update',
                status='error',
                duration_ms=_duration_ms(started_at),
                level='warning',
                reason='bad_request_parse_mode',
            )
            return False
        logger.warning(
            "Не удалось обновить сообщение прогресса (message_id=%s): %s",
            instruction_message_id,
            e
        )
        _log_structured_step(
            event='progress_update_end',
            match_id=match_id,
            user_id=user_id,
            step='progress_update',
            status='error',
            duration_ms=_duration_ms(started_at),
            level='warning',
            reason='bad_request',
        )
        return False
    except Exception as e:
        logger.warning(
            "Не удалось обновить сообщение прогресса (message_id=%s): %s",
            instruction_message_id,
            e
        )
        _log_structured_step(
            event='progress_update_end',
            match_id=match_id,
            user_id=user_id,
            step='progress_update',
            status='error',
            duration_ms=_duration_ms(started_at),
            level='warning',
            reason='unexpected_error',
        )
        return False


def _build_enriched_data_summary(data: dict) -> dict:
    """Краткая сводка по собранным enriched-данным для логов."""
    if not isinstance(data, dict):
        return {'type': str(type(data))}

    standings = data.get('standings') or {}
    table = standings.get('table') or []
    team1_events = data.get('team1_last_match_events') or {}
    team2_events = data.get('team2_last_match_events') or {}

    return {
        'h2h': len(data.get('h2h') or []),
        'standings_rows': len(table),
        'team1_form': len(data.get('team1_form') or []),
        'team2_form': len(data.get('team2_form') or []),
        'team1_lineup': len(data.get('team1_last_match_lineup') or []),
        'team2_lineup': len(data.get('team2_last_match_lineup') or []),
        'team1_events': len(team1_events.get('subs', [])) + len(team1_events.get('cards', [])),
        'team2_events': len(team2_events.get('subs', [])) + len(team2_events.get('cards', [])),
        'current_event_stats': len(data.get('current_event_stats') or {}),
        'h2h_recent_stats': len(data.get('h2h_recent_stats') or []),
        'errors': len(data.get('errors') or []),
    }


def _count_context_blocks(enriched_context: str) -> int:
    """Считает количество секций в текстовом контексте."""
    return sum(1 for line in (enriched_context or '').splitlines() if line.strip().startswith("==="))


_MATCH_GENERATION_LOCKS = {}


def _get_match_generation_lock(match_id: int) -> asyncio.Lock:
    """
    Возвращает lock для конкретного match_id.
    Нужен, чтобы не запускать параллельную генерацию одного и того же матча.
    """
    lock = _MATCH_GENERATION_LOCKS.get(match_id)
    if lock is None:
        lock = asyncio.Lock()
        _MATCH_GENERATION_LOCKS[match_id] = lock
    return lock


def _load_match_with_cache(match_id: int, fallback_match_dict: dict) -> tuple[dict, str]:
    """
    Возвращает актуальные данные матча из БД и cached analysis_text.
    Если матч не найден в БД, использует fallback_match_dict.
    """
    db_match = database.get_match_by_id(match_id)
    if db_match:
        match_dict = dict(db_match)
    else:
        match_dict = dict(fallback_match_dict or {})
    cached_text = (match_dict.get('analysis_text') or '').strip()
    return match_dict, cached_text


async def _send_analysis_ready_message(
    bot,
    user_id: int,
    match_id: int,
    match_dict: dict,
    table_available: bool = True,
) -> None:
    """Отправляет пользователю экран выбора формата готового анализа."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    if _env_flag_enabled('FORCE_SEND_ERROR'):
        raise RuntimeError('forced send error')

    sport = match_dict.get('sport')
    match_date = match_dict.get('match_date')
    back_callback_data = (
        f"analysis_back_{sport}_{match_date}"
        if sport and match_date
        else 'back'
    )
    callback_suffix = f"_{sport}_{match_date}" if sport and match_date else ""

    first_row = []
    if table_available:
        first_row.append(
            InlineKeyboardButton(
                "📋 Таблица",
                callback_data=f"show_table_{match_id}{callback_suffix}"
            )
        )
    first_row.append(
        InlineKeyboardButton(
            "📝 Текст",
            callback_data=f"show_text_{match_id}{callback_suffix}"
        )
    )
    keyboard = [
        first_row,
        [InlineKeyboardButton("◀️ Назад", callback_data=back_callback_data)],
        [InlineKeyboardButton("🏠 В главное меню", callback_data='back_to_menu')]
    ]

    ready_text = (
        "✅ <b>Анализ готов</b>\n\n"
        f"🏆 {match_dict.get('team1', 'Команда 1')} vs {match_dict.get('team2', 'Команда 2')}\n"
        f"📅 {match_dict.get('match_date', '')} в {match_dict.get('match_time', '')} МСК\n\n"
        "🎛️ Выберите формат просмотра:"
    )
    if not table_available:
        ready_text += "\n\n⚠️ Текстовый анализ готов, таблица временно недоступна."
    await bot.send_message(
        chat_id=user_id,
        text=ready_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )


async def _cleanup_progress_message(bot, user_id: int, instruction_message_id: int) -> None:
    """Удаляет сообщение прогресса после успешного завершения."""
    if not instruction_message_id:
        return
    try:
        await bot.delete_message(chat_id=user_id, message_id=instruction_message_id)
        logger.info(f"Удалено сообщение с прогрессом (message_id={instruction_message_id})")
    except Exception as e:
        logger.warning(f"Не удалось удалить сообщение с прогрессом: {e}")


async def _finalize_generation_progress(
    bot,
    user_id: int,
    instruction_message_id: int,
    match_dict: dict,
    statuses: dict,
    match_id: Optional[int] = None,
) -> bool:
    """Показывает финальные галочки и только потом скрывает сообщение прогресса."""
    statuses['send'] = 'done'
    progress_ok = await _update_generation_progress(
        bot, user_id, instruction_message_id, match_dict, statuses, match_id=match_id
    )
    if instruction_message_id and PROGRESS_DONE_VISIBLE_SECONDS > 0:
        await asyncio.sleep(PROGRESS_DONE_VISIBLE_SECONDS)
    await _cleanup_progress_message(bot, user_id, instruction_message_id)
    return progress_ok


def _build_text_delivery_fallback(match_dict: dict, analysis_text: str) -> str:
    """Формирует текст fallback-сообщения с готовым анализом без таблицы."""
    team1 = match_dict.get('team1', 'Команда 1')
    team2 = match_dict.get('team2', 'Команда 2')
    match_date = match_dict.get('match_date', '')
    match_time = match_dict.get('match_time', '')
    body = (analysis_text or '').strip()
    if len(body) > TEXT_FALLBACK_MAX_LEN:
        body = body[:TEXT_FALLBACK_MAX_LEN].rstrip() + "\n\n…(текст сокращён)"
    return (
        "⚠️ Текстовый анализ готов, но финальный экран временно недоступен.\n\n"
        f"🏆 {team1} vs {team2}\n"
        f"📅 {match_date} {match_time} МСК\n\n"
        "📝 Текстовый анализ:\n\n"
        f"{body}"
    )


async def generate_and_send_analysis(user_id, match_id, match_dict, instruction_message_id=None):
    """
    Генерирует анализ и отправляет пользователю через Telegram.

    Args:
        user_id: Telegram user ID
        match_id: ID матча
        match_dict: Данные матча (dict)
        instruction_message_id: ID сообщения с инструкцией (для удаления)

    Returns:
        bool: True если успешно
    """
    total_started_at = time.monotonic()
    generation_job_acquired = False
    progress_ui_error_nonfatal = False
    result_mode = 'failed_before_text'
    analysis_text = ''
    bot = None
    try:
        # Импортируем здесь, чтобы избежать циклических зависимостей
        from match_data_fetcher import MatchDataFetcher, build_enriched_context
        from ai_generator import generate_match_text_analysis
        from telegram import Bot

        bot = Bot(token=TOKEN)
        progress_statuses = {
            'text_data': 'run',
            'text_generate': 'pending',
            'table_prepare': 'pending',
            'table_render': 'pending',
            'send': 'pending',
        }

        async def _safe_progress_update() -> None:
            nonlocal progress_ui_error_nonfatal
            ok = await _update_generation_progress(
                bot,
                user_id,
                instruction_message_id,
                match_dict,
                progress_statuses,
                match_id=match_id,
            )
            if not ok:
                progress_ui_error_nonfatal = True

        await _safe_progress_update()

        # Быстрый путь: если анализ уже сохранён в БД, DeepSeek не вызываем.
        match_dict, cached_analysis_text = _load_match_with_cache(match_id, match_dict)
        if cached_analysis_text:
            logger.info(
                "[CACHE] match_id=%s: анализ уже есть в БД (%s символов), "
                "пропускаем генерацию DeepSeek",
                match_id,
                len(cached_analysis_text)
            )
            progress_statuses.update({
                'text_data': 'done',
                'text_generate': 'done',
                'table_prepare': 'done',
                'table_render': 'done',
                'send': 'run',
            })
            await _safe_progress_update()
            await _send_analysis_ready_message(bot, user_id, match_id, match_dict)
            progress_ok = await _finalize_generation_progress(
                bot, user_id, instruction_message_id, match_dict, progress_statuses, match_id=match_id
            )
            if not progress_ok:
                progress_ui_error_nonfatal = True
            result_mode = 'full'
            return True

        # Защита от параллельной генерации одного и того же матча.
        match_lock = _get_match_generation_lock(match_id)
        if match_lock.locked():
            logger.info(
                "[LOCK] match_id=%s: генерация уже идёт, ждём готовый результат",
                match_id
            )

        async with match_lock:
            # Чистим lock из словаря сразу после захвата — он уже не нужен другим
            _MATCH_GENERATION_LOCKS.pop(match_id, None)
            # Double-check: пока ждали lock, анализ могли уже сгенерировать.
            match_dict, cached_analysis_text = _load_match_with_cache(match_id, match_dict)
            if cached_analysis_text:
                logger.info(
                    "[CACHE-AFTER-LOCK] match_id=%s: анализ уже готов, DeepSeek не вызываем",
                    match_id
                )
                progress_statuses.update({
                    'text_data': 'done',
                    'text_generate': 'done',
                    'table_prepare': 'done',
                    'table_render': 'done',
                    'send': 'run',
                })
                await _safe_progress_update()
                await _send_analysis_ready_message(bot, user_id, match_id, match_dict)
                progress_ok = await _finalize_generation_progress(
                    bot, user_id, instruction_message_id, match_dict, progress_statuses, match_id=match_id
                )
                if not progress_ok:
                    progress_ui_error_nonfatal = True
                result_mode = 'full'
                return True

            owner = f"user:{user_id}"
            generation_job_acquired = database.acquire_generation_job(
                match_id=match_id,
                owner=owner,
                stale_after_seconds=300
            )
            if not generation_job_acquired:
                logger.info(
                    "[DB-LOCK] match_id=%s: генерация уже выполняется в другом процессе, ждём кэш",
                    match_id
                )
                cached_ready = await asyncio.to_thread(
                    database.wait_for_match_analysis,
                    match_id,
                    90,
                    0.5
                )
                if cached_ready:
                    match_dict, cached_analysis_text = _load_match_with_cache(match_id, match_dict)
                    if cached_analysis_text:
                        progress_statuses.update({
                            'text_data': 'done',
                            'text_generate': 'done',
                            'table_prepare': 'done',
                            'table_render': 'done',
                            'send': 'run',
                        })
                        await _safe_progress_update()
                        await _send_analysis_ready_message(bot, user_id, match_id, match_dict)
                        progress_ok = await _finalize_generation_progress(
                            bot, user_id, instruction_message_id, match_dict, progress_statuses, match_id=match_id
                        )
                        if not progress_ok:
                            progress_ui_error_nonfatal = True
                        result_mode = 'full'
                        return True

                await bot.send_message(
                    chat_id=user_id,
                    text=(
                        "⏳ Анализ по этому матчу уже формируется.\n"
                        "Откройте «Мои анализы» через минуту."
                    )
                )
                await _cleanup_progress_message(bot, user_id, instruction_message_id)
                return True

            # Этап 1: Сбор обогащённых данных
            logger.info(f"Сбор данных для матча {match_id}...")
            enriched_data = {}
            enriched_context = "Обогащённые данные недоступны."
            data_started_at = time.monotonic()
            try:
                fetcher = MatchDataFetcher()
                enriched_data = fetcher.fetch_match_data(match_dict)
                enriched_context = build_enriched_context(match_dict, enriched_data)
                data_elapsed = time.monotonic() - data_started_at
                data_summary = _build_enriched_data_summary(enriched_data)
                context_chars = len(enriched_context or "")
                context_blocks = _count_context_blocks(enriched_context)
                logger.info(
                    "Данные собраны за %.1fs. summary=%s, context_chars=%s, context_blocks=%s",
                    data_elapsed,
                    data_summary,
                    context_chars,
                    context_blocks,
                )
                if enriched_data.get('errors'):
                    logger.warning("Ошибки enriched_data: %s", enriched_data.get('errors'))
            except Exception as e:
                data_elapsed = time.monotonic() - data_started_at
                logger.error(f"Ошибка сбора данных: {e}", exc_info=True)
                logger.error("Этап сбора данных завершился с ошибкой за %.1fs", data_elapsed)
                progress_statuses['text_data'] = 'error'
                await _safe_progress_update()
                raise

            progress_statuses['text_data'] = 'done'
            progress_statuses['text_generate'] = 'run'
            await _safe_progress_update()

            # Этап 2: Генерация текстового анализа
            _log_structured_step(
                event='text_generation_start',
                match_id=match_id,
                user_id=user_id,
                step='text_generation',
                status='start',
            )
            logger.info(f"Генерация анализа для матча {match_id}...")
            text_started_at = time.monotonic()
            try:
                analysis_text = await generate_match_text_analysis(match_dict, enriched_context)
            except Exception as e:
                _log_structured_step(
                    event='text_generation_end',
                    match_id=match_id,
                    user_id=user_id,
                    step='text_generation',
                    status='error',
                    duration_ms=_duration_ms(text_started_at),
                    level='error',
                    error_type=type(e).__name__,
                )
                progress_statuses['text_generate'] = 'error'
                await _safe_progress_update()
                raise

            text_elapsed = time.monotonic() - text_started_at
            logger.info(
                "Текстовый анализ сгенерирован за %.1fs (%s символов)",
                text_elapsed,
                len(analysis_text or "")
            )
            _log_structured_step(
                event='text_generation_end',
                match_id=match_id,
                user_id=user_id,
                step='text_generation',
                status='ok',
                duration_ms=_duration_ms(text_started_at),
            )
            progress_statuses['text_generate'] = 'done'
            progress_statuses['table_prepare'] = 'run'
            await _safe_progress_update()

            # Этап 3: Рендеринг PNG таблицы
            logger.info("Рендеринг PNG таблицы...")
            cached_png_path = None
            table_timeout = False
            table_error = False
            table_data = None
            temp_png = None
            from analysis_formatter import build_table_data
            from image_renderer import render_analysis_table
            import os
            import shutil

            _log_structured_step(
                event='table_prepare_start',
                match_id=match_id,
                user_id=user_id,
                step='table_prepare',
                status='start',
            )
            prepare_started_at = time.monotonic()
            try:
                table_data = await asyncio.wait_for(
                    asyncio.to_thread(build_table_data, match_dict, enriched_data),
                    timeout=TABLE_PREPARE_TIMEOUT_SEC,
                )
                rows_count = int(
                    table_data.get(
                        'raw_coverage_rows_count',
                        table_data.get('coverage_rows_count', 0)
                    )
                )
                missing_cells = int(table_data.get('raw_missing_cells_count', 0))
                logger.info(
                    "Таблица данных собрана: coverage_rows=%s, missing_cells=%s",
                    rows_count,
                    missing_cells
                )
                _log_structured_step(
                    event='table_prepare_end',
                    match_id=match_id,
                    user_id=user_id,
                    step='table_prepare',
                    status='ok',
                    duration_ms=_duration_ms(prepare_started_at),
                )
                progress_statuses['table_prepare'] = 'done'
                progress_statuses['table_render'] = 'run'
                await _safe_progress_update()
            except asyncio.TimeoutError:
                table_timeout = True
                logger.warning(
                    "event=table_stage_timeout match_id=%s user_id=%s stage=table_prepare timeout_sec=%s",
                    match_id,
                    user_id,
                    TABLE_PREPARE_TIMEOUT_SEC,
                )
                _log_structured_step(
                    event='table_prepare_end',
                    match_id=match_id,
                    user_id=user_id,
                    step='table_prepare',
                    status='error',
                    duration_ms=_duration_ms(prepare_started_at),
                    level='warning',
                    reason='timeout',
                )
                progress_statuses['table_prepare'] = 'error'
                progress_statuses['table_render'] = 'error'
                await _safe_progress_update()
            except Exception as e:
                table_error = True
                logger.error(f"Ошибка подготовки таблицы: {e}", exc_info=True)
                _log_structured_step(
                    event='table_prepare_end',
                    match_id=match_id,
                    user_id=user_id,
                    step='table_prepare',
                    status='error',
                    duration_ms=_duration_ms(prepare_started_at),
                    level='error',
                    error_type=type(e).__name__,
                )
                progress_statuses['table_prepare'] = 'error'
                progress_statuses['table_render'] = 'error'
                await _safe_progress_update()

            if table_data is not None:
                _log_structured_step(
                    event='table_render_start',
                    match_id=match_id,
                    user_id=user_id,
                    step='table_render',
                    status='start',
                )
                render_started_at = time.monotonic()
                try:
                    if _env_flag_enabled('FORCE_TABLE_TIMEOUT'):
                        # Быстрый детерминированный timeout для тестов/локальной диагностики.
                        await asyncio.wait_for(asyncio.sleep(0.05), timeout=0.01)
                    if _env_flag_enabled('FORCE_TABLE_ERROR'):
                        raise RuntimeError('forced table error')
                    temp_png = await asyncio.wait_for(
                        asyncio.to_thread(render_analysis_table, match_dict, table_data),
                        timeout=TABLE_RENDER_TIMEOUT_SEC,
                    )
                    target_path = (
                        f"analysis_cache/analysis_{match_id}_v{TABLE_RENDER_CACHE_VERSION}.webp"
                    )
                    os.makedirs("analysis_cache", exist_ok=True)
                    shutil.copy(temp_png, target_path)

                    if os.path.exists(target_path):
                        cached_png_path = target_path
                        logger.info(f"PNG таблица сохранена: {cached_png_path}")
                    else:
                        raise RuntimeError(f"Файл не был скопирован: {target_path}")

                    _log_structured_step(
                        event='table_render_end',
                        match_id=match_id,
                        user_id=user_id,
                        step='table_render',
                        status='ok',
                        duration_ms=_duration_ms(render_started_at),
                    )
                except asyncio.TimeoutError:
                    table_timeout = True
                    logger.warning(
                        "event=table_stage_timeout match_id=%s user_id=%s stage=table_render timeout_sec=%s",
                        match_id,
                        user_id,
                        TABLE_RENDER_TIMEOUT_SEC,
                    )
                    _log_structured_step(
                        event='table_render_end',
                        match_id=match_id,
                        user_id=user_id,
                        step='table_render',
                        status='error',
                        duration_ms=_duration_ms(render_started_at),
                        level='warning',
                        reason='timeout',
                    )
                    progress_statuses['table_render'] = 'error'
                    await _safe_progress_update()
                except Exception as e:
                    table_error = True
                    logger.error(f"Ошибка рендеринга PNG: {e}", exc_info=True)
                    _log_structured_step(
                        event='table_render_end',
                        match_id=match_id,
                        user_id=user_id,
                        step='table_render',
                        status='error',
                        duration_ms=_duration_ms(render_started_at),
                        level='error',
                        error_type=type(e).__name__,
                    )
                    progress_statuses['table_render'] = 'error'
                    await _safe_progress_update()
                finally:
                    if temp_png:
                        try:
                            os.remove(temp_png)
                        except Exception:
                            pass

            if progress_statuses.get('table_render') != 'error':
                progress_statuses['table_render'] = 'done'

            if cached_png_path:
                result_mode = 'full'
            elif table_timeout:
                result_mode = 'text_only_table_timeout'
            elif table_error:
                result_mode = 'text_only_table_error'
            else:
                result_mode = 'text_only_table_error'

            progress_statuses['send'] = 'run'
            await _safe_progress_update()

            # Сохраняем результаты в БД
            db_started_at = time.monotonic()
            if cached_png_path:
                database.update_match_analysis(match_id, analysis_text, cached_png_path)
            else:
                database.update_match_analysis(match_id, analysis_text)
            db_elapsed = time.monotonic() - db_started_at
            logger.info("Анализ и PNG путь сохранены в БД за %.1fs", db_elapsed)

            # Перечитываем матч из БД, чтобы отправлять пользователю консистентные данные.
            match_dict, _ = _load_match_with_cache(match_id, match_dict)

            # Этап 4: Отправка пользователю (выбор формата просмотра)
            send_started_at = time.monotonic()
            _log_structured_step(
                event='result_send_start',
                match_id=match_id,
                user_id=user_id,
                step='result_send',
                status='start',
            )
            try:
                await _send_analysis_ready_message(
                    bot,
                    user_id,
                    match_id,
                    match_dict,
                    table_available=bool(cached_png_path),
                )
                _log_structured_step(
                    event='result_send_end',
                    match_id=match_id,
                    user_id=user_id,
                    step='result_send',
                    status='ok',
                    duration_ms=_duration_ms(send_started_at),
                )
            except Exception as send_error:
                _log_structured_step(
                    event='result_send_end',
                    match_id=match_id,
                    user_id=user_id,
                    step='result_send',
                    status='error',
                    duration_ms=_duration_ms(send_started_at),
                    level='error',
                    error_type=type(send_error).__name__,
                )
                raise

            send_elapsed = time.monotonic() - send_started_at
            total_elapsed = time.monotonic() - total_started_at
            logger.info(
                "Экран выбора формата отправлен пользователю %s за %.1fs (полный pipeline %.1fs)",
                user_id,
                send_elapsed,
                total_elapsed
            )
            progress_ok = await _finalize_generation_progress(
                bot, user_id, instruction_message_id, match_dict, progress_statuses, match_id=match_id
            )
            if not progress_ok:
                progress_ui_error_nonfatal = True
            database.finish_generation_job(match_id, status='done')
            generation_job_acquired = False
            return True

    except Exception as e:
        if generation_job_acquired:
            database.finish_generation_job(
                match_id,
                status='error',
                error=str(e)[:500]
            )
        logger.error(f"Ошибка генерации/отправки анализа: {e}", exc_info=True)
        # Если текст уже есть, пытаемся отдать хотя бы его.
        try:
            from telegram import Bot
            if bot is None:
                bot = Bot(token=TOKEN)

            if analysis_text:
                if result_mode == 'full':
                    result_mode = 'text_only_table_error'
                result_mode = result_mode if result_mode != 'failed_before_text' else 'text_only_table_error'
                fallback_text = _build_text_delivery_fallback(match_dict, analysis_text)
                await bot.send_message(chat_id=user_id, text=fallback_text)
            else:
                error_text = (
                    "❌ <b>Ошибка генерации анализа</b>\n\n"
                    "К сожалению, произошла техническая ошибка при создании анализа. "
                    "Ваш заказ остаётся активным — попробуйте получить анализ через "
                    "раздел «Мои анализы» через несколько минут.\n\n"
                    "Если проблема повторится, обратитесь в поддержку."
                )
                await bot.send_message(
                    chat_id=user_id,
                    text=error_text,
                    parse_mode='HTML'
                )

            if instruction_message_id:
                try:
                    await bot.delete_message(chat_id=user_id, message_id=instruction_message_id)
                except Exception:
                    pass
        except Exception:
            pass
        return False
    finally:
        total_duration_ms = _duration_ms(total_started_at)
        if total_duration_ms >= ANALYSIS_JOB_SLOW_PATH_SECONDS * 1000:
            logger.warning(
                "event=analysis_job_slow_path match_id=%s user_id=%s duration_ms=%s threshold_sec=%s",
                match_id,
                user_id,
                total_duration_ms,
                ANALYSIS_JOB_SLOW_PATH_SECONDS,
            )
        logger.info(
            "event=analysis_result match_id=%s user_id=%s result_mode=%s progress_ui_error_nonfatal=%s duration_ms=%s",
            match_id,
            user_id,
            result_mode,
            progress_ui_error_nonfatal,
            total_duration_ms,
        )


@app.route('/webhook/donationalerts', methods=['POST'])
def donationalerts_webhook():
    """Legacy endpoint: прямой webhook-оплаты анализа отключён."""
    logger.warning("Получен запрос в legacy webhook DonationAlerts, но прямой payment-flow отключён.")
    return jsonify({'error': 'Legacy donation webhook disabled'}), 410


@app.route('/health', methods=['GET'])
def health_check():
    """Проверка работоспособности сервера"""
    return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat()}), 200


if __name__ == '__main__':
    logger.info("Запуск webhook сервера на порту 5000...")
    app.run(host='0.0.0.0', port=5000, debug=True)
