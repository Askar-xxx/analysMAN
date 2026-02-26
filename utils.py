import logging
import re
import unicodedata
from telegram.error import BadRequest
from telegram import Update
from telegram.ext import ContextTypes
import database

logger = logging.getLogger(__name__)


def markdown_to_html(text: str) -> str:
    """
    Конвертирует базовый Markdown в HTML для отправки через Telegram parse_mode='HTML'.

    Поддерживает:
    - **bold** → <b>bold</b>
    - _italic_ → <i>italic</i>

    Экранирует HTML-спецсимволы (&, <, >) перед конвертацией.
    """
    if not text:
        return text
    # Экранируем HTML-спецсимволы
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    # **bold** (re.DOTALL чтобы работало и для многострочного текста)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text, flags=re.DOTALL)
    # _italic_ (одиночные подчёркивания)
    text = re.sub(r'(?<!\w)_(.+?)_(?!\w)', r'<i>\1</i>', text, flags=re.DOTALL)
    return text


# Запрещённые корни слов (регистронезависимо)
BANNED_ROOTS = re.compile(
    r'\b\S*(?:коэффициент|ставк|прогноз)\S*\b',
    re.IGNORECASE
)

# Разрешённые эмодзи (спорт, аналитика)
ALLOWED_EMOJI = {'⚽', '🏀', '🏒', '📊', '📈', '📅', '⏰', '🔥', '⭐', '🎯',
                 '🏆', '💪', '👀', '📝', '🔑', '⚡', '🛡️', '⚔️', '🥅', '🎾',
                 '🧠', '🧩', '🏟'}
MAX_EMOJI_TOTAL = 8
MAX_EMOJI_PER_SECTION = 2
# Emoji заголовков секций — не считаются в лимит и не дедуплицируются
SECTION_HEADING_EMOJI = {'⚽', '📈', '📊', '🧠', '🔑'}


def _is_emoji(char: str) -> bool:
    """Проверяет, является ли символ эмодзи."""
    return unicodedata.category(char) in ('So', 'Sk') or char in ALLOWED_EMOJI


def _is_section_heading(line: str) -> bool:
    """
    Определяет заголовок раздела для лимита эмодзи.
    Поддерживает numbered, markdown heading, markdown bold.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if re.match(r'^\d+\.\s+', stripped):
        return True
    if re.match(r'^#{1,3}\s+', stripped):
        return True
    if re.match(r'^(?:[^\w\s]+\s*)?\*\*[^*\n]{2,80}\*\*$', stripped):
        return True
    if re.match(r'^[^:\n]{2,48}:$', stripped):
        return True
    return False


def _limit_emoji(text: str) -> str:
    """Ограничивает эмодзи: макс N на раздел, макс M всего, без повторов."""
    total_emoji_count = 0
    section_emoji_count = 0
    used_emoji = set()
    result_lines = []

    for line in text.splitlines(keepends=True):
        is_heading = _is_section_heading(line)
        if is_heading:
            section_emoji_count = 0
        chars = []
        for char in line:
            if _is_emoji(char):
                # Emoji заголовков секций в заголовочной строке — пропускаем без лимита
                if is_heading and char in SECTION_HEADING_EMOJI:
                    chars.append(char)
                    continue
                # Emoji заголовков секций в теле текста — всегда убираем
                if char in SECTION_HEADING_EMOJI:
                    continue
                # Дедупликация: повторные emoji убираем
                if char in used_emoji:
                    continue
                # Лимит на секцию и общий
                if (
                    section_emoji_count < MAX_EMOJI_PER_SECTION
                    and total_emoji_count < MAX_EMOJI_TOTAL
                ):
                    chars.append(char)
                    section_emoji_count += 1
                    total_emoji_count += 1
                    used_emoji.add(char)
            else:
                chars.append(char)
        result_lines.append(''.join(chars))

    return ''.join(result_lines)


def _truncate_sentences(text: str, target: int) -> str:
    """Сокращает текст до целевой длины, сохраняя блок «Вывод»."""
    if len(text) <= target:
        return text

    def _truncate_with_structure(source: str, limit: int) -> str:
        """Сокращает текст, сохраняя исходные переносы и разделители."""
        if len(source) <= limit:
            return source

        if limit <= 0:
            return ""

        chunks = re.split(r'(?<=[.!?…])(\s+)', source)
        if len(chunks) == 1:
            return source[:limit].rstrip()

        result = []
        current_len = 0
        idx = 0
        while idx < len(chunks):
            sentence = chunks[idx]
            separator = chunks[idx + 1] if idx + 1 < len(chunks) else ''
            segment = sentence + separator
            if current_len + len(segment) > limit and result:
                break
            if current_len + len(sentence) > limit and result:
                break
            if current_len + len(segment) <= limit:
                result.append(segment)
                current_len += len(segment)
            else:
                result.append(sentence)
                current_len += len(sentence)
                break
            idx += 2

        compact = ''.join(result).rstrip()
        if compact:
            return compact
        return source[:limit].rstrip()

    # Ищем последний блок «Вывод» (с эмодзи или без)
    conclusion_match = re.search(
        r'(\n\s*(?:🔑\s*)?\*{0,2}(?:Вывод|вывод)\*{0,2}.*)',
        text, re.DOTALL
    )

    if conclusion_match:
        body = text[:conclusion_match.start()].rstrip()
        conclusion = text[conclusion_match.start():].lstrip('\n')
        # Сокращаем только тело, оставляя место для вывода
        body_target = target - len(conclusion) - 2  # \n\n между блоками
        if body_target > 0:
            truncated_body = _truncate_with_structure(body, body_target)
            if truncated_body:
                return f"{truncated_body}\n\n{conclusion}".strip()
            return conclusion.strip()
        return text
    # Fallback: без блока вывода — режем как раньше
    return _truncate_with_structure(text, target)


def clean_and_truncate(
    text: str,
    target_max: int = 2800,
    soft_cap: int = 3400,
    hard_cap: int = 3600
) -> str:
    """
    Постобработка текста анализа:
    - Удаляет запрещённые слова (коэффициент, ставка, прогноз)
    - Ограничивает эмодзи (макс 1 на раздел, макс 5 всего)
    - Soft cap: сокращает предложения до целевой длины target_max
    - Hard cap: обрезает по последнему \\n
    - Логирует длину до/после и флаг truncated
    """
    original_length = len(text)
    truncated = False

    # 1. Удаляем запрещённые слова
    text = BANNED_ROOTS.sub('', text)
    # Убираем двойные пробелы после удаления
    text = re.sub(r'  +', ' ', text)
    # Убираем пустые строки-дубли
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 2. Ограничиваем эмодзи
    text = _limit_emoji(text)

    # 3. Soft cap: если текст слишком длинный, сокращаем по предложениям.
    if len(text) > soft_cap:
        text = _truncate_sentences(text, target_max)
        truncated = True

    # 4. Hard cap: если всё ещё слишком длинный, обрезаем аккуратно.
    if len(text) > hard_cap:
        cut = text[:hard_cap]
        last_newline = cut.rfind('\n')
        if last_newline > hard_cap // 2:
            text = cut[:last_newline] + '\n...'
        else:
            text = cut + '\n...'
        truncated = True

    final_length = len(text)
    logger.info(
        f"clean_and_truncate: original={original_length}, "
        f"final={final_length}, truncated={truncated}"
    )

    return text.strip()


def split_for_telegram(text: str, limit: int = 3800) -> list[str]:
    """
    Разбивает текст на части, каждая ≤ limit символов.
    Приоритет разрыва:
      1. По последнему \\n\\n в пределах лимита
      2. По последнему предложению (точка/воскл./вопр.)
      3. По последнему пробелу
    Не режет посередине слова.
    """
    if len(text) <= limit:
        return [text]

    parts = []
    remaining = text

    while len(remaining) > limit:
        chunk = remaining[:limit]

        # 1. Ищем последний двойной перенос строки
        split_pos = chunk.rfind('\n\n')

        # 2. Если не нашли — ищем конец предложения
        if split_pos == -1 or split_pos < limit // 4:
            match = None
            for m in re.finditer(r'[.!?]\s', chunk):
                match = m
            if match and match.end() > limit // 4:
                split_pos = match.end()
            else:
                split_pos = -1

        # 3. Если не нашли — ищем последний пробел
        if split_pos == -1 or split_pos < limit // 4:
            split_pos = chunk.rfind(' ')

        # Крайний случай: нет пробелов — режем по лимиту
        if split_pos == -1 or split_pos < limit // 4:
            split_pos = limit

        parts.append(remaining[:split_pos].rstrip())
        remaining = remaining[split_pos:].lstrip()

    if remaining.strip():
        parts.append(remaining.strip())

    return parts


async def safe_answer_callback(query, text=None, show_alert=False, cache_time=None):
    """
    Безопасный ответ на callback query.
    Не роняет обработчик на устаревшем query id.
    """
    try:
        if query is None or not hasattr(query, 'answer'):
            return False

        kwargs = {}
        if text is not None:
            kwargs['text'] = text
        if show_alert:
            kwargs['show_alert'] = show_alert
        if cache_time is not None:
            kwargs['cache_time'] = cache_time

        await query.answer(**kwargs)
        return True
    except BadRequest as e:
        err = str(e).lower()
        if (
            "query is too old" in err
            or "response timeout expired" in err
            or "query id is invalid" in err
        ):
            logger.warning("Игнорируем устаревший callback query: %s", e)
            return False
        logger.error("Ошибка ответа на callback query: %s", e)
        return False
    except Exception as e:
        logger.error("Неожиданная ошибка query.answer: %s", e)
        return False


async def safe_edit_message(query, text, reply_markup=None, parse_mode='HTML'):
    """Безопасное редактирование сообщения с гарантией соблюдения лимита Telegram"""
    # Telegram лимит: 4096 символов
    MAX_MESSAGE_LENGTH = 4096

    try:
        if query is None:
            logger.error("Query is None in safe_edit_message")
            return None
        if not hasattr(query, 'edit_message_text'):
            logger.error(f"Query has no edit_message_text: {type(query)}")
            return None

        # Проверяем, является ли сообщение фото
        if hasattr(query, 'message') and query.message and query.message.photo:
            # Для фото сначала пробуем менять подпись — это стабильнее и не засоряет чат.
            if len(text) <= 1024:
                try:
                    await query.edit_message_caption(
                        caption=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode
                    )
                    return True
                except Exception as e:
                    err = str(e).lower()
                    if "message is not modified" in err:
                        return True
                    # Fallback ниже: удаляем фото и отправляем текст.
                    logger.warning("Не удалось обновить подпись фото, fallback на send_message: %s", e)

            # Если подпись слишком длинная или caption-edit не сработал —
            # удаляем фото и отправляем новое текстовое сообщение.
            chat_id = query.message.chat_id
            try:
                await query.message.delete()
            except Exception:
                pass
            bot = query.message.get_bot()
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
            return True

        # ФИНАЛЬНАЯ ПРОВЕРКА: если текст всё равно слишком длинный - обрезаем
        if len(text) > MAX_MESSAGE_LENGTH:
            logger.error(
                f"КРИТИЧНО! Сообщение слишком длинное ({len(text)} символов), "
                f"принудительно обрезаем до {MAX_MESSAGE_LENGTH}"
            )
            # Обрезаем с запасом для безопасности
            text = text[:MAX_MESSAGE_LENGTH - 150]
            # Находим последнюю точку для красивого обрыва
            last_period = text.rfind('.')
            if last_period > MAX_MESSAGE_LENGTH - 300:
                text = text[:last_period + 1]
            text += "\n\n⚠️ (текст сокращён)"

        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
        return True
    except Exception as e:
        if "Message is not modified" in str(e):
            pass
        elif "Message to edit not found" in str(e):
            logger.warning(f"Message not found for editing: {e}")
        elif "There is no text in the message to edit" in str(e):
            # Сообщение с фото или другой контент - удаляем и отправляем новое
            try:
                chat_id = query.message.chat_id
                await query.message.delete()
                bot = query.message.get_bot()
                await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
            except Exception as ex:
                logger.error(f"Failed to delete/resend message: {ex}")
            return False
        elif "Message_too_long" in str(e) or "message is too long" in str(e).lower():
            # Экстренная защита: если всё же возникла эта ошибка
            logger.error(f"КРИТИЧЕСКАЯ ОШИБКА: Message_too_long несмотря на проверки! Длина: {len(text)}")
            # Пробуем отправить короткое сообщение об ошибке
            try:
                await query.edit_message_text(
                    text="⚠️ Ошибка: сообщение слишком длинное. Обратитесь к администратору.",
                    reply_markup=reply_markup
                )
            except Exception:
                pass
            return False
        else:
            logger.error(f"Error editing message: {e}")
        return False


async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправка главного меню с балансом 💎"""
    from keyboards import main_menu_keyboard
    user_id = update.effective_user.id
    username = update.effective_user.username
    user = database.get_or_create_user(user_id, username)
    balance = database.get_user_balance(user_id)
    from config import ANALYSIS_PRICE_RUB
    is_new = (user['total_analysis_bought'] == 0
              and balance == int(ANALYSIS_PRICE_RUB))
    bonus_amount = int(ANALYSIS_PRICE_RUB)
    bonus_line = (
        f"\n🎁 <b>Вам начислено {bonus_amount} 💎 — первый анализ бесплатно!</b>"
        if is_new else ""
    )
    welcome_text = f"""
🎉 <b>Добро пожаловать в бот "Спортивная аналитика"!</b> 🎉

Приветствую, {update.effective_user.mention_html()}! 👋

<b>У вас:</b> {balance} 💎{bonus_line}

Я ваш персональный помощник в мире спортивной аналитики и мероприятий.

👇 <b>Готовы начать? Выберите действие ниже:</b>
"""
    if hasattr(update, 'callback_query') and update.callback_query:
        # safe_edit_message теперь автоматически обрабатывает случай с фото
        await safe_edit_message(
            update.callback_query,
            welcome_text,
            main_menu_keyboard(),
            parse_mode='HTML'
        )
    else:
        await update.message.reply_html(
            welcome_text,
            reply_markup=main_menu_keyboard()
        )


def extract_token_from_message(message: str) -> str | None:
    """
    Извлекает 12-символьный токен покупки из комментария к донату.

    Обрезает сообщение до 500 символов перед обработкой,
    чтобы защититься от DoS через огромные строки.
    """
    if not message:
        return None
    # Ограничиваем длину перед regex чтобы не нагружать CPU
    truncated = message[:500].upper()
    match = re.search(r'\b([A-Z0-9]{12})\b', truncated)
    return match.group(1) if match else None


def format_match_info(match, include_analysis=False):
    """Форматирование информации о матче"""
    sport_emoji = {'football': '⚽',
                   'basketball': '🏀',
                   'hockey': '🏒'}.get(match['sport'], '🎯')
    text = f"{sport_emoji} <b>Матч:</b> {match['team1']} vs {match['team2']}\n"
    text += f"📅 <b>Дата:</b> {match['match_date']}\n"
    text += f"⏰ <b>Время:</b> {match['match_time']}\n"
    if include_analysis and match['analysis_text']:
        text += f"\n📊 <b>Анализ:</b>\n{match['analysis_text']}\n"
    return text
