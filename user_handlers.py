import logging
from telegram import Update
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler
import database
from states import *
import keyboards
from utils import safe_edit_message, send_main_menu, format_match_info
from datetime import datetime, timedelta
import urllib.parse
from config import MANAGER_USERNAME

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await send_main_menu(update, context)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Основной обработчик кнопок"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    database.get_or_create_user(user_id, username)
    
    # Обработка различных callback_data
    if query.data == 'back_to_menu':
        await send_main_menu(update, context)
    
    elif query.data == 'support':
        await handle_support(query)
    
    elif query.data == 'category_sports':
        await handle_category_sports(query)
    
    elif query.data.startswith('sport_'):
        await handle_sport_selection(query, context)
    
    elif query.data.startswith('choose_date_'):
        await handle_date_selection(query, context)
    
    elif query.data.startswith('match_'):
        await handle_match_detail(query, user_id)
    
    elif query.data.startswith('buy_'):
        await handle_purchase(query, user_id)
    
    elif query.data == 'my_stats':
        await handle_my_stats(query, user_id)
    
    elif query.data == 'balance':
        await handle_balance(query, user_id)
    
    elif query.data in ['deposit', 'deposit_150', 'deposit_300', 'deposit_600', 'deposit_800']:
        from handlers.payment_handlers import handle_deposit_menu, handle_deposit_amount
        if query.data == 'deposit':
            await handle_deposit_menu(update, context)
        else:
            await handle_deposit_amount(update, context)
    
    elif query.data == 'deposit_custom':
        from handlers.payment_handlers import handle_deposit_amount
        await handle_deposit_amount(update, context)
    
    elif query.data == 'check_deposit':
        from handlers.payment_handlers import check_deposit_status
        await check_deposit_status(update, context)
    
    else:
        await safe_edit_message(
            query,
            "Неизвестная команда.",
            keyboards.main_menu_keyboard()
        )

async def handle_support(query):
    """Обработка кнопки поддержки"""
    support_text = """
👨‍💼 *Служба поддержки*

Если у вас возникли вопросы или проблемы:

📞 *Контакты:*
• Telegram: @support_username
• Email: support@example.com
• Сайт: example.com

⏰ *Время работы:*
Круглосуточно, 24/7

💡 *Часто задаваемые вопросы:*
• Как пополнить баланс? - Через меню "Пополнить баланс"
• Как купить анализ? - Выберите спорт → матч → "Купить анализ"
• Где моя статистика? - В меню "Моя статистика"

Мы всегда рады помочь! 😊
"""
    
    await safe_edit_message(
        query,
        support_text,
        keyboards.support_keyboard()
    )

async def handle_category_sports(query):
    """Обработка выбора категории спорта"""
    sports_text = """
🎯 *ВЫБЕРИТЕ ВИД СПОРТА*

Выберите интересующий вас вид спорта для просмотра доступных матчей и анализов:

⚽ *Футбол* - Европейские лиги, Кубки, международные матчи
🏀 *Баскетбол* - НБА, Евролига, национальные чемпионаты
🏒 *Хоккей* - КХЛ, НХЛ, международные турниры

💡 *Каждый анализ включает:*
• Статистику команд
• Составы и травмы
• Тактические схемы
• Прогноз эксперта
• Рекомендации по ставкам

👇 Выберите вид спорта ниже:
"""
    
    await safe_edit_message(
        query,
        sports_text,
        keyboards.sports_keyboard()
    )

async def handle_sport_selection(query, context):
    """Обработка выбора конкретного спорта"""
    sport = query.data.split('_')[1]  # football, basketball, hockey
    
    if sport not in ['football', 'basketball', 'hockey']:
        await safe_edit_message(
            query,
            "Этот вид спорта пока не поддерживается.",
            keyboards.main_menu_keyboard()
        )
        return
    
    dates = database.get_available_dates_with_matches(sport)
    
    if not dates:
        await safe_edit_message(
            query,
            f"На ближайшую неделю матчей по {sport} нет.",
            keyboards.main_menu_keyboard()
        )
        return
    
    # Сохраняем даты в контексте
    context.user_data['available_dates'] = dates
    context.user_data['current_sport'] = sport
    
    text = f"Выберите дату для просмотра матчей по {sport}:\n\n"
    
    await safe_edit_message(
        query,
        text,
        keyboards.dates_keyboard(dates, sport)
    )

async def handle_date_selection(query, context):
    """Обработка выбора даты"""
    parts = query.data.split('_')
    sport = parts[2]
    date_str = parts[3]
    
    matches = database.get_matches_by_date(sport, date_str)
    
    if not matches:
        await safe_edit_message(
            query,
            f"На {date_str} матчей нет.",
            keyboards.main_menu_keyboard()
        )
        return
    
    # Форматируем дату для отображения
    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
    today = datetime.now().date()
    
    if date_obj.date() == today:
        date_label = "⏳ Сегодня"
    elif date_obj.date() == today + timedelta(days=1):
        date_label = "🕐 Завтра"
    else:
        date_label = date_obj.strftime("%d.%m.%Y")
    
    text = f"Матчи на {date_label}:\n\n"
    
    for match in matches:
        text += f"• {match['team1']} vs {match['team2']} в {match['match_time']}\n"
    
    text += "\nВыберите матч для просмотра анализа:"
    
    await safe_edit_message(
        query,
        text,
        keyboards.matches_keyboard(matches, date_str, sport)
    )

async def handle_match_detail(query, user_id):
    """Обработка детальной страницы матча"""
    match_id = int(query.data.split('_')[1])
    match = database.get_match_by_id(match_id)
    
    if not match:
        await safe_edit_message(query, "Матч не найден.", keyboards.main_menu_keyboard())
        return
    
    has_purchased = database.has_purchased_analysis(user_id, match_id)
    user_balance = database.get_user_balance(user_id)
    
    text = format_match_info(match)
    
    if has_purchased:
        text += f"\n📊 *Анализ:*\n{match['analysis_text']}\n\n"
        text += f"✅ Вы уже приобрели этот анализ"
    else:
        text += f"\n💰 *Цена анализа:* {match['price']} руб.\n\n"
        if match['analysis_text']:
            text += "Для просмотра анализа необходимо приобрести его."
        else:
            text += "❌ Анализ для этого матча еще не готов."
    
    await safe_edit_message(
        query,
        text,
        keyboards.match_detail_keyboard(match_id, has_purchased, match['price'], user_balance)
    )

async def handle_purchase(query, user_id):
    """Обработка покупки анализа"""
    match_id = int(query.data.split('_')[1])
    match = database.get_match_by_id(match_id)
    
    if not match:
        await safe_edit_message(
            query,
            "❌ Матч не найден.",
            keyboards.main_menu_keyboard()
        )
        return
    
    if not match['analysis_text']:
        await safe_edit_message(
            query,
            "❌ Анализ для этого матча еще не готов.",
            keyboards.main_menu_keyboard()
        )
        return
    
    if database.has_purchased_analysis(user_id, match_id):
        await safe_edit_message(
            query,
            f"✅ Вы уже приобрели анализ для этого матча!\n\n{match['team1']} vs {match['team2']}",
            keyboards.main_menu_keyboard()
        )
        return
    
    success, message = database.purchase_analysis(user_id, match_id)
    
    if success:
        text = f"✅ Покупка успешна!\n\n"
        text += f"🏆 Матч: {match['team1']} vs {match['team2']}\n"
        text += f"💰 Списано: {match['price']} руб.\n"
        text += f"💳 Новый баланс: {database.get_user_balance(user_id)} руб.\n\n"
        text += f"📊 Анализ:\n{match['analysis_text']}"
    else:
        text = f"❌ Не удалось купить анализ:\n{message}\n\n"
        text += f"💰 Ваш баланс: {database.get_user_balance(user_id)} руб.\n"
        text += f"💵 Нужно: {match['price']} руб."
    
    await safe_edit_message(
        query,
        text,
        keyboards.main_menu_keyboard()
    )

async def handle_my_stats(query, user_id):
    """Обработка просмотра статистики"""
    stats = database.get_user_stats(user_id)
    
    if stats:
        text = f"📊 *Ваша статистика:*\n\n"
        text += f"💰 Баланс: {stats['balance']} руб.\n"
        text += f"📈 Куплено аналитик: {stats['total_analysis_bought']}\n"
        text += f"🎫 Всего покупок: {stats['purchased_count']}"
    else:
        text = "📊 *Ваша статистика:*\n\nБаланс: 0 руб.\nКуплено аналитик: 0"
    
    await safe_edit_message(
        query,
        text,
        keyboards.main_menu_keyboard()
    )

async def handle_balance(query, user_id):
    """Обработка просмотра баланса"""
    balance = database.get_user_balance(user_id)
    
    await safe_edit_message(
        query,
        f"💰 *Ваш баланс:* {balance} руб.",
        keyboards.main_menu_keyboard()
    )

def setup_user_handlers(application):
    """Настройка обработчиков пользователей"""
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
