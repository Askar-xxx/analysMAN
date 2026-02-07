import logging
import re
import unicodedata
from telegram import Update
from telegram.ext import ContextTypes
import database

logger = logging.getLogger(__name__)

# Запрещённые корни слов (регистронезависимо)
BANNED_ROOTS = re.compile(
    r'\b\S*(?:коэффициент|ставк|прогноз)\S*\b',
    re.IGNORECASE
)

# Разрешённые эмодзи (спорт, аналитика)
ALLOWED_EMOJI = {'⚽', '🏀', '🏒', '📊', '📈', '📅', '⏰', '🔥', '⭐', '🎯',
                 '🏆', '💪', '👀', '📝', '🔑', '⚡', '🛡️', '⚔️', '🥅', '🎾'}
MAX_EMOJI_TOTAL = 4
MAX_EMOJI_PER_SECTION = 1


def _is_emoji(char: str) -> bool:
    """Проверяет, является ли символ эмодзи."""
    return unicodedata.category(char) in ('So', 'Sk') or char in ALLOWED_EMOJI


def _limit_emoji(text: str) -> str:
    """Ограничивает эмодзи: макс 1 на раздел, макс 4 всего."""
    # Разбиваем по разделам (нумерованные заголовки 1. 2. ... 6.)
    section_pattern = re.compile(r'(?=^\d+\.)', re.MULTILINE)
    sections = section_pattern.split(text)

    total_emoji_count = 0
    result_sections = []

    for section in sections:
        section_emoji_count = 0
        chars = []
        for char in section:
            if _is_emoji(char):
                if section_emoji_count < MAX_EMOJI_PER_SECTION and total_emoji_count < MAX_EMOJI_TOTAL:
                    chars.append(char)
                    section_emoji_count += 1
                    total_emoji_count += 1
                # Иначе пропускаем эмодзи
            else:
                chars.append(char)
        result_sections.append(''.join(chars))

    return ''.join(result_sections)


def _truncate_sentences(text: str, target: int) -> str:
    """Сокращает текст до целевой длины, убирая предложения с конца."""
    if len(text) <= target:
        return text
    # Разбиваем на предложения
    sentences = re.split(r'(?<=[.!?])\s+', text)
    result = []
    current_len = 0
    for sentence in sentences:
        if current_len + len(sentence) + 1 > target and result:
            break
        result.append(sentence)
        current_len += len(sentence) + 1
    return ' '.join(result)


def clean_and_truncate(text: str) -> str:
    """
    Постобработка текста анализа:
    - Удаляет запрещённые слова (коэффициент, ставка, прогноз)
    - Ограничивает эмодзи (макс 1 на раздел, макс 4 всего)
    - Soft cap 2000: сокращает предложения до целевой длины 1200-1800
    - Hard cap 3800: обрезает по последнему \\n
    - Логирует длину до/после и флаг truncated
    """
    TARGET_MAX = 1800
    SOFT_CAP = 2000
    HARD_CAP = 3800

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

    # 3. Soft cap: если > 2000, сокращаем предложения до целевой длины
    if len(text) > SOFT_CAP:
        text = _truncate_sentences(text, TARGET_MAX)
        truncated = True

    # 4. Hard cap: если всё ещё > 3800, обрезаем по последнему \n
    if len(text) > HARD_CAP:
        cut = text[:HARD_CAP]
        last_newline = cut.rfind('\n')
        if last_newline > HARD_CAP // 2:
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
    """Отправка главного меню с балансом"""
    from keyboards import main_menu_keyboard
    user_id = update.effective_user.id
    username = update.effective_user.username
    database.get_or_create_user(user_id, username)
    balance = database.get_user_balance(user_id)
    welcome_text = f"""
🎉 *Добро пожаловать в бот "Спортивная аналитика"!* 🎉

Приветствую, {update.effective_user.mention_html()}! 👋

💰 *Ваш баланс:* {balance} руб.

Я ваш персональный помощник в мире спортивной аналитики и мероприятий.

👇 *Готовы начать? Выберите действие ниже:*
"""
    if hasattr(update, 'callback_query') and update.callback_query:
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


def format_match_info(match, include_analysis=False):
    """Форматирование информации о матче"""
    sport_emoji = {'football': '⚽',
                   'basketball': '🏀',
                   'hockey': '🏒'}.get(match['sport'], '🎯')
    text = f"{sport_emoji} *Матч:* {match['team1']} vs {match['team2']}\n"
    text += f"📅 *Дата:* {match['match_date']}\n"
    text += f"⏰ *Время:* {match['match_time']}\n"
    if include_analysis and match['analysis_text']:
        text += f"\n📊 *Анализ:*\n{match['analysis_text']}\n"
    return text
