import logging
from telegram import Update
from telegram.ext import ContextTypes
import database
from gpt_analysis import generate_match_analysis

logger = logging.getLogger(__name__)


async def safe_edit_message(query, text, reply_markup=None, parse_mode='HTML'):
    """Безопасное редактирование сообщения"""
    try:
        if query is None:
            logger.error("Query is None in safe_edit_message")
            return None
        if not hasattr(query, 'edit_message_text'):
            logger.error(f"Query has no edit_message_text: {type(query)}")
            return None
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


async def get_or_generate_analysis(match):
    """Получить или сгенерировать анализ для матча."""
    if match['analysis_text']:
        return match['analysis_text']
    analysis_text = await generate_match_analysis(match)
    if analysis_text:
        database.update_match_analysis(match['id'], analysis_text)
    return analysis_text
