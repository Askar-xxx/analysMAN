import logging
import database
import keyboards
from telegram import Update
from telegram.ext import (
    ContextTypes,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler
)
from states import *
from utils import safe_edit_message, check_admin, send_main_menu
from config import MAIN_ADMIN_ID
from datetime import datetime

logger = logging.getLogger(__name__)

# ==================== КОМАНДЫ АДМИНИСТРАТОРА ====================


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /admin для доступа к админ-панели"""
    user_id = update.effective_user.id
    if not check_admin(user_id):
        await update.message.reply_text("⛔ У вас нет прав администратора!")
        return
    await update.message.reply_text(
        "👨‍💼 Админ-панель:\nВыберите действие:",
        reply_markup=keyboards.admin_main_keyboard()
    )


async def admin_button_handler(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок админ-панели"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not check_admin(user_id):
        await query.answer("⛔ У вас нет прав администратора!", show_alert=True)
        return
    if query.data == 'admin_panel':
        await safe_edit_message(
            query,
            "👨‍💼 Админ-панель:\nВыберите действие:",
            keyboards.admin_main_keyboard()
        )
    elif query.data == 'admin_back':
        await safe_edit_message(
            query,
            "👨‍💼 Админ-панель:\nВыберите действие:",
            keyboards.admin_main_keyboard()
        )
    elif query.data == 'admin_all_matches':
        await admin_all_matches(query)
    elif query.data == 'admin_all_users':
        await admin_all_users(query)
    elif query.data == 'admin_manage_admins':
        await admin_manage_admins(query)
    elif query.data == 'admin_add_balance':
        await admin_add_balance_info(query)
    elif query.data == 'admin_add_admin':
        await admin_add_admin_info(query, user_id)
    elif query.data == 'admin_remove_admin':
        await admin_remove_admin_info(query, user_id)
    else:
        await safe_edit_message(
            query,
            "Неизвестная команда.",
            keyboards.admin_main_keyboard()
        )

# ==================== ФУНКЦИИ АДМИН-ПАНЕЛИ ====================


async def admin_all_matches(query):
    """Показать все матчи"""
    matches = database.get_all_matches()
    if matches:
        text = "📋 *Все матчи:*\n\n"
        for match in matches:
            sport_emoji = {'football': '⚽', 'basketball': '🏀', 'hockey': '🏒'}.get(match['sport'], '🎯')
            has_analysis = "✅" if match['analysis_text'] else "❌"
            text += f"{sport_emoji} {has_analysis} ID: {match['id']}\n"
            text += f"   {match['team1']} vs {match['team2']}\n"
            text += f"   Дата: {match['match_date']} {match['match_time']}\n"
            text += f"   Анализ: {'Есть' if match['analysis_text'] else 'Нет'}\n\n"
    else:
        text = "📭 В базе нет матчей."
    await safe_edit_message(
        query,
        text,
        keyboards.back_to_admin_keyboard()
    )


async def admin_all_users(query):
    """Показать всех пользователей"""
    users = database.get_all_users()
    if users:
        text = "👥 *Все пользователи:*\n\n"
        for user in users:
            is_admin = "👑" if check_admin(user['user_id']) else "👤"
            text += f"{is_admin} ID: {user['user_id']}\n"
            text += f"   👤 @{user['username'] if user['username'] else 'нет'}\n"
            text += f"   💰 Баланс: {user['balance']} руб.\n"
            text += f"   📊 Куплено аналитик: {user['total_analysis_bought']}\n"
            text += f"   📅 Зарегистрирован: {user['created_at'][:10]}\n\n"
    else:
        text = "📭 В базе нет пользователей."
    await safe_edit_message(
        query,
        text,
        keyboards.back_to_admin_keyboard()
    )


async def admin_manage_admins(query):
    """Управление администраторами"""
    admins = database.get_all_admins()
    text = "👨‍💼 *Управление администраторами*\n\n"
    text += f"👑 Главный админ: {MAIN_ADMIN_ID}\n\n"
    if admins:
        text += "📋 *Список администраторов:*\n"
        for admin in admins:
            is_main = "👑" if admin['user_id'] == MAIN_ADMIN_ID else "👨‍💼"
            added_by = f"@{admin['added_by_username']}" if admin['added_by_username'] else admin['added_by']
            text += f"{is_main} ID: {admin['user_id']}\n"
            text += f"   👤 @{admin['username'] if admin['username'] else 'нет'}\n"
            text += f"   📅 Добавлен: {admin['added_at'][:10]}\n"
            text += f"   🤝 Кем: {added_by}\n\n"
    else:
        text += "📭 Нет дополнительных администраторов.\n\n"
    text += "Выберите действие:"
    await safe_edit_message(
        query,
        text,
        keyboards.admin_manage_admins_keyboard()
    )


async def admin_add_balance_info(query):
    """Информация о пополнении баланса"""
    await safe_edit_message(
        query,
        "💰 *Пополнение баланса пользователя*\n\n"
        "Используйте команду:\n"
        "/add_balance <user_id> <сумма>\n\n"
        "Пример:\n"
        "/add_balance 123456789 1000",
        keyboards.back_to_admin_keyboard()
    )


async def admin_add_admin_info(query, current_user_id):
    """Информация о добавлении администратора"""
    if current_user_id != MAIN_ADMIN_ID:
        await query.answer("⛔ Только главный администратор может добавлять админов!", show_alert=True)
        return
    await safe_edit_message(
        query,
        "➕ *Добавление администратора*\n\n"
        "Используйте команду:\n"
        "/addadmin <user_id>\n\n"
        "Пример:\n"
        "/addadmin 123456789",
        keyboards.back_to_admin_keyboard()
    )


async def admin_remove_admin_info(query, current_user_id):
    """Информация об удалении администратора"""
    if current_user_id != MAIN_ADMIN_ID:
        await query.answer("⛔ Только главный администратор может удалять админов!", show_alert=True)
        return
    admins = database.get_all_admins()
    if not admins or len(admins) <= 1:
        await safe_edit_message(
            query,
            "❌ Нет дополнительных администраторов для удаления.",
            keyboards.admin_main_keyboard()
        )
        return
    text = "🗑️ *Удаление администратора*\n\n"
    text += "Список администраторов:\n"
    for admin in admins:
        if admin['user_id'] != MAIN_ADMIN_ID:
            text += f"🆔 ID: {admin['user_id']} - @{admin['username'] if admin['username'] else 'нет'}\n"
    text += "\nИспользуйте команду:\n"
    text += "/removeadmin <user_id>\n\n"
    text += "Пример:\n"
    text += "/removeadmin 123456789"
    await safe_edit_message(query, text, keyboards.back_to_admin_keyboard())

# ==================== КОМАНДЫ ДЛЯ АДМИНИСТРАТОРОВ ====================


async def add_balance_command(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    """Команда /add_balance для пополнения баланса пользователя"""
    user_id = update.effective_user.id
    if not check_admin(user_id):
        await update.message.reply_text("⛔ У вас нет прав администратора!")
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "Использование: /add_balance <user_id> <сумма>\n"
            "Пример: /add_balance 123456789 1000"
        )
        return
    try:
        target_user_id = int(context.args[0])
        amount = int(context.args[1])
        if amount <= 0:
            await update.message.reply_text("❌ Сумма должна быть положительной!")
            return
        database.add_balance(target_user_id, amount)
        new_balance = database.get_user_balance(target_user_id)
        await update.message.reply_text(
            f"✅ Баланс пользователя {target_user_id} пополнен на {amount} руб.\n"
            f"💰 Новый баланс: {new_balance} руб."
        )
    except ValueError:
        await update.message.reply_text("❌ Ошибка: user_id и amount должны быть числами!")


async def add_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /addadmin для добавления администратора"""
    user_id = update.effective_user.id
    if user_id != MAIN_ADMIN_ID:
        await update.message.reply_text("⛔ Только главный администратор может использовать эту команду!")
        return
    if len(context.args) < 1:
        await update.message.reply_text(
            "Использование: /addadmin <user_id>\n"
            "Пример: /addadmin 123456789"
        )
        return
    try:
        new_admin_id = int(context.args[0])
        if new_admin_id == user_id:
            await update.message.reply_text("❌ Вы уже являетесь администратором!")
            return
        username = None
        success = database.add_admin(
            user_id=new_admin_id,
            username=username,
            added_by=user_id
        )
        if success:
            await update.message.reply_text(f"✅ Пользователь {new_admin_id} добавлен в администраторы!")
        else:
            await update.message.reply_text("❌ Не удалось добавить администратора.")    
    except ValueError:
        await update.message.reply_text("❌ user_id должен быть числом!")


async def remove_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /removeadmin для удаления администратора"""
    user_id = update.effective_user.id
    if user_id != MAIN_ADMIN_ID:
        await update.message.reply_text("⛔ Только главный администратор может использовать эту команду!")
        return
    if len(context.args) < 1:
        await update.message.reply_text(
            "Использование: /removeadmin <user_id>\n"
            "Пример: /removeadmin 123456789"
        )
        return
    try:
        target_admin_id = int(context.args[0])
        if target_admin_id == MAIN_ADMIN_ID:
            await update.message.reply_text("❌ Нельзя удалить главного администратора!")
            return
        if target_admin_id == user_id:
            await update.message.reply_text("❌ Нельзя удалить себя!")
            return
        if not database.is_admin(target_admin_id):
            await update.message.reply_text("❌ Этот пользователь не является администратором!")
            return
        database.remove_admin(target_admin_id)
        await update.message.reply_text(f"✅ Администратор {target_admin_id} успешно удален!")   
    except ValueError:
        await update.message.reply_text("❌ user_id должен быть числом!")

# ==================== СОЗДАНИЕ МАТЧА ====================


async def admin_create_match_start(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    """Начало создания матча"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not check_admin(user_id):
        await query.answer("⛔ У вас нет прав администратора!", show_alert=True)
        return
    text = "🏟️ *Создание нового матча*\n\n"
    text += "Выберите вид спорта:\n"
    text += "1. Футбол\n"
    text += "2. Баскетбол\n"
    text += "3. Хоккей\n\n"
    text += "Введите номер или название:"
    await safe_edit_message(query, text)
    return WAITING_SPORT


async def admin_receive_sport(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    """Получение вида спорта"""
    user_id = update.effective_user.id
    if not check_admin(user_id):
        await update.message.reply_text("⛔ У вас нет прав администратора!")
        return ConversationHandler.END
    sport_input = update.message.text.strip().lower()
    sport_map = {
        '1': 'football', 'футбол': 'football', 'football': 'football',
        '2': 'basketball', 'баскетбол': 'basketball', 'basketball': 'basketball',
        '3': 'hockey', 'хоккей': 'hockey', 'hockey': 'hockey'
    }
    sport = sport_map.get(sport_input)
    if not sport:
        await update.message.reply_text("❌ Неверный вид спорта. Введите корректно:")
        return WAITING_SPORT
    context.user_data['new_match'] = {'sport': sport}
    sport_names = {'football': '⚽ Футбол', 'basketball': '🏀 Баскетбол', 'hockey': '🏒 Хоккей'}
    await update.message.reply_text(
        f"✅ Вид спорта: {sport_names[sport]}\n\nВведите название первой команды:"
    )
    return WAITING_TEAM1


async def admin_receive_team1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение первой команды"""
    user_id = update.effective_user.id
    if not check_admin(user_id):
        await update.message.reply_text("⛔ У вас нет прав администратора!")
        return ConversationHandler.END
    team1 = update.message.text.strip()
    context.user_data['new_match']['team1'] = team1
    await update.message.reply_text(
        f"✅ Команда 1: {team1}\n\nВведите название второй команды:"
    )
    return WAITING_TEAM2


async def admin_receive_team2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение второй команды"""
    user_id = update.effective_user.id
    if not check_admin(user_id):
        await update.message.reply_text("⛔ У вас нет прав администратора!")
        return ConversationHandler.END
    team2 = update.message.text.strip()
    context.user_data['new_match']['team2'] = team2
    await update.message.reply_text(
        f"✅ Команда 2: {team2}\n\n"
        f"Введите дату матча в формате ГГГГ-ММ-ДД (например {datetime.now().strftime('%Y-%m-%d')}):"
    )
    return WAITING_DATE


async def admin_receive_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение даты матча"""
    user_id = update.effective_user.id
    if not check_admin(user_id):
        await update.message.reply_text("⛔ У вас нет прав администратора!")
        return ConversationHandler.END
    match_date = update.message.text.strip()
    try:
        datetime.strptime(match_date, '%Y-%m-%d')
    except ValueError:
        await update.message.reply_text("❌ Неверный формат даты. Введите в формате ГГГГ-ММ-ДД:")
        return WAITING_DATE
    context.user_data['new_match']['match_date'] = match_date
    await update.message.reply_text(
        f"✅ Дата: {match_date}\n\nВведите время матча в формате ЧЧ:ММ (например 20:00):"
    )
    return WAITING_TIME


async def admin_receive_time(update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
    """Получение времени матча и сохранение"""
    user_id = update.effective_user.id
    if not check_admin(user_id):
        await update.message.reply_text("⛔ У вас нет прав администратора!")
        return ConversationHandler.END
    match_time = update.message.text.strip()
    try:
        datetime.strptime(match_time, '%H:%M')
    except ValueError:
        await update.message.reply_text("❌ Неверный формат времени. Введите в формате ЧЧ:ММ:")
        return WAITING_TIME
    new_match = context.user_data['new_match']
    match_id = database.create_match(
        sport=new_match['sport'],
        team1=new_match['team1'],
        team2=new_match['team2'],
        match_date=new_match['match_date'],
        match_time=match_time
    )
    sport_names = {'football': '⚽ Футбол', 'basketball': '🏀 Баскетбол', 'hockey': '🏒 Хоккей'}
    text = f"✅ *Матч успешно создан!*\n\n"
    text += f"ID: {match_id}\n"
    text += f"Вид спорта: {sport_names[new_match['sport']]}\n"
    text += f"Матч: {new_match['team1']} vs {new_match['team2']}\n"
    text += f"Дата: {new_match['match_date']}\n"
    text += f"Время: {match_time}\n"
    text += f"Цена анализа: 150 руб.\n\n"
    text += "Теперь вы можете добавить анализ к этому матчу."
    await update.message.reply_text(text)
    await update.get_bot().send_message(
        chat_id=update.effective_chat.id,
        text="👨‍💼 Админ-панель:\nВыберите действие:",
        reply_markup=keyboards.admin_main_keyboard()
    )
    context.user_data.clear()
    return ConversationHandler.END

# ==================== ДОБАВЛЕНИЕ АНАЛИЗА ====================


async def admin_add_analysis_start(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    """Начало добавления анализа"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not check_admin(user_id):
        await query.answer("⛔ У вас нет прав администратора!", show_alert=True)
        return ConversationHandler.END
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM matches WHERE analysis_text IS NULL OR analysis_text = '' ORDER BY match_date")
    matches = cursor.fetchall()
    conn.close()
    if matches:
        text = "📋 *Матчи без анализа:*\n\n"
        for match in matches:
            sport_emoji = {'football': '⚽', 'basketball': '🏀', 'hockey': '🏒'}.get(match['sport'], '🎯')
            text += f"{sport_emoji} ID: {match['id']} - {match['team1']} vs {match['team2']} ({match['match_date']})\n"
        text += "\nВведите ID матча для добавления анализа:"
    else:
        text = "✅ Все матчи имеют анализ."
        await safe_edit_message(query, text, keyboards.admin_main_keyboard())
        return ConversationHandler.END
    await safe_edit_message(query, text)
    return WAITING_MATCH_ID


async def admin_receive_match_id(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE):
    """Получение ID матча для анализа"""
    user_id = update.effective_user.id
    if not check_admin(user_id):
        await update.message.reply_text("⛔ У вас нет прав администратора!")
        return ConversationHandler.END
    match_id = update.message.text.strip()
    if not match_id.isdigit():
        await update.message.reply_text("❌ Введите числовой ID матча:")
        return WAITING_MATCH_ID
    match = database.get_match_by_id(int(match_id))
    if not match:
        await update.message.reply_text(f"❌ Матч с ID {match_id} не найден. Введите корректный ID:")
        return WAITING_MATCH_ID
    context.user_data['analysis_match_id'] = int(match_id)
    context.user_data['analysis_match'] = match
    sport_emoji = {'football': '⚽', 'basketball': '🏀', 'hockey': '🏒'}.get(match['sport'], '🎯')
    text = f"{sport_emoji} *Выбран матч:*\n\n"
    text += f"ID: {match['id']}\n"
    text += f"Матч: {match['team1']} vs {match['team2']}\n"
    text += f"Дата: {match['match_date']} {match['match_time']}\n\n"
    text += "Отправьте текст анализа для этого матча:"
    await update.message.reply_text(text)
    return WAITING_ANALYSIS


async def admin_receive_analysis_text(update: Update,
                                      context: ContextTypes.DEFAULT_TYPE):
    """Получение текста анализа и сохранение"""
    user_id = update.effective_user.id
    if not check_admin(user_id):
        await update.message.reply_text("⛔ У вас нет прав администратора!")
        return ConversationHandler.END
    analysis_text = update.message.text.strip()
    match_id = context.user_data['analysis_match_id']
    match = context.user_data['analysis_match']
    database.update_match_analysis(match_id, analysis_text)
    sport_emoji = {'football': '⚽', 'basketball': '🏀', 'hockey': '🏒'}.get(match['sport'], '🎯')
    text = f"✅ *Анализ успешно добавлен!*\n\n"
    text += f"{sport_emoji} Матч: {match['team1']} vs {match['team2']}\n"
    text += f"Анализ: {analysis_text[:200]}..." if len(analysis_text) > 200 else f"Анализ: {analysis_text}"
    await update.message.reply_text(text)
    await update.get_bot().send_message(
        chat_id=update.effective_chat.id,
        text="👨‍💼 Админ-панель:\nВыберите действие:",
        reply_markup=keyboards.admin_main_keyboard()
    )
    context.user_data.clear()
    return ConversationHandler.END

# ==================== УДАЛЕНИЕ МАТЧА ====================


async def admin_delete_match_start(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    """Начало удаления матча"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not check_admin(user_id):
        await query.answer("⛔ У вас нет прав администратора!", show_alert=True)
        return ConversationHandler.END
    matches = database.get_all_matches()
    if matches:
        text = "🗑️ *Удаление матча*\n\n"
        text += "Список матчей:\n"
        for match in matches:
            sport_emoji = {'football': '⚽', 'basketball': '🏀', 'hockey': '🏒'}.get(match['sport'], '🎯')
            text += f"{sport_emoji} ID: {match['id']} - {match['team1']} vs {match['team2']}\n"
        text += "\nВведите ID матча для удаления:"
    else:
        text = "📭 В базе нет матчей для удаления."
        await safe_edit_message(query, text, keyboards.admin_main_keyboard())
        return ConversationHandler.END
    await safe_edit_message(query, text)
    return WAITING_DELETE_MATCH_ID


async def admin_receive_delete_match_id(update: Update,
                                        context: ContextTypes.DEFAULT_TYPE):
    """Получение ID матча для удаления"""
    user_id = update.effective_user.id
    if not check_admin(user_id):
        await update.message.reply_text("⛔ У вас нет прав администратора!")
        return ConversationHandler.END
    match_id = update.message.text.strip()
    if not match_id.isdigit():
        await update.message.reply_text("❌ Введите числовой ID матча:")
        return WAITING_DELETE_MATCH_ID
    match = database.get_match_by_id(int(match_id))
    if not match:
        await update.message.reply_text(f"❌ Матч с ID {match_id} не найден. Введите корректный ID:")
        return WAITING_DELETE_MATCH_ID
    database.delete_match(int(match_id))
    sport_emoji = {'football': '⚽', 'basketball': '🏀', 'hockey': '🏒'}.get(match['sport'], '🎯')
    text = f"✅ *Матч успешно удален!*\n\n"
    text += f"{sport_emoji} Матч: {match['team1']} vs {match['team2']}\n"
    text += f"Дата: {match['match_date']} {match['match_time']}\n"
    await update.message.reply_text(text)
    await update.get_bot().send_message(
        chat_id=update.effective_chat.id,
        text="👨‍💼 Админ-панель:\nВыберите действие:",
        reply_markup=keyboards.admin_main_keyboard()
    )
    return ConversationHandler.END

# ==================== ОТМЕНА ДИАЛОГА ====================


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена диалога"""
    user_id = update.effective_user.id
    if not check_admin(user_id):
        await update.message.reply_text("⛔ У вас нет прав администратора!")
        return ConversationHandler.END
    await update.message.reply_text("Действие отменено.")
    context.user_data.clear()
    await update.get_bot().send_message(
        chat_id=update.effective_chat.id,
        text="👨‍💼 Админ-панель:\nВыберите действие:",
        reply_markup=keyboards.admin_main_keyboard()
    )
    return ConversationHandler.END


def setup_admin_handlers(application):
    """Настройка обработчиков администратора"""
    # Команды
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("add_balance", add_balance_command))
    application.add_handler(CommandHandler("addadmin", add_admin_command))
    application.add_handler(CommandHandler("removeadmin",
                                           remove_admin_command))
    # Обработчики кнопок админ-панели
    application.add_handler(CallbackQueryHandler(admin_button_handler,
                                                 pattern='^admin_'))
    # Conversation handlers для админских функций
    create_match_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_create_match_start,
                                           pattern='^admin_create_match$')],
        states={
            WAITING_SPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND,
                                           admin_receive_sport)],
            WAITING_TEAM1: [MessageHandler(filters.TEXT & ~filters.COMMAND,
                                           admin_receive_team1)],
            WAITING_TEAM2: [MessageHandler(filters.TEXT & ~filters.COMMAND,
                                           admin_receive_team2)],
            WAITING_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND,
                                          admin_receive_date)],
            WAITING_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND,
                                          admin_receive_time)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    add_analysis_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_analysis_start,
                                           pattern='^admin_add_analysis$')],
        states={
            WAITING_MATCH_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND,
                                              admin_receive_match_id)],
            WAITING_ANALYSIS: [MessageHandler(filters.TEXT & ~filters.COMMAND,
                                              admin_receive_analysis_text)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    delete_match_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_delete_match_start,
                                           pattern='^admin_delete_match$')],
        states={
            WAITING_DELETE_MATCH_ID: [MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                admin_receive_delete_match_id)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    application.add_handler(create_match_handler)
    application.add_handler(add_analysis_handler)
    application.add_handler(delete_match_handler)
