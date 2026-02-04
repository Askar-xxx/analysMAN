import logging
from telegram import Update
from telegram.ext import ContextTypes
import database
from config import MAIN_ADMIN_ID

logger = logging.getLogger(__name__)

def check_admin(user_id):
    """Проверка, является ли пользователь администратором"""
    return database.is_admin(user_id) or user_id == MAIN_ADMIN_ID

async def safe_edit_message(query, text, reply_markup=None, parse_mode='HTML'):
    """Безопасное редактирование сообщения"""
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except Exception as e:
        if "Message is not modified" in str(e):
            pass
        else:
            logger.error(f"Error editing message: {e}")

async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправка главного меню"""
    from keyboards import main_menu_keyboard  # Исправлено: импорт внутри функции
    
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    database.get_or_create_user(user_id, username)
    is_admin_user = check_admin(user_id)
    
    welcome_text = f"""
🎉 *Добро пожаловать в бот "Спортивная аналитика"!* 🎉

Приветствую, {update.effective_user.mention_html()}! 👋

Я ваш персональный помощник в мире спортивной аналитики и мероприятий.

👇 *Готовы начать? Выберите действие ниже:*
"""
    
    if hasattr(update, 'callback_query'):
        await safe_edit_message(
            update.callback_query,
            welcome_text,
            main_menu_keyboard(is_admin_user),
            parse_mode='HTML'
        )
    else:
        await update.message.reply_html(
            welcome_text,
            reply_markup=main_menu_keyboard(is_admin_user)
        )

def format_match_info(match, include_analysis=False):
    """Форматирование информации о матче"""
    sport_emoji = {'football': '⚽', 'basketball': '🏀', 'hockey': '🏒'}.get(match['sport'], '🎯')
    
    text = f"{sport_emoji} *Матч:* {match['team1']} vs {match['team2']}\n"
    text += f"📅 *Дата:* {match['match_date']}\n"
    text += f"⏰ *Время:* {match['match_time']}\n"
    
    if include_analysis and match['analysis_text']:
        text += f"\n📊 *Анализ:*\n{match['analysis_text']}\n"
    
    return text