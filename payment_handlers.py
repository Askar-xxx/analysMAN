import logging
import urllib.parse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup  # Добавлен импорт
from telegram.ext import (
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler
)
import database
from states import WAITING_CUSTOM_DEPOSIT
from keyboards import deposit_options_keyboard
from utils import safe_edit_message
from config import MANAGER_USERNAME
from datetime import datetime

logger = logging.getLogger(__name__)


async def handle_deposit_menu(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    """Меню пополнения баланса"""
    from keyboards import deposit_menu_keyboard  # Импорт внутри функции
    
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    balance = database.get_user_balance(user_id)
    text = f"""
💳 *ПОПОЛНЕНИЕ БАЛАНСА*

💰 Текущий баланс: *{balance} руб.*

🎁 *Выберите сумму для пополнения:*

• *150 руб.* - 1 анализ матча
• *300 руб.* +150 бонус = 450 руб. (3 анализа)
• *600 руб.* - 4 анализа матча
• *800 руб.* +300 бонус = 1100 руб. (7+ анализов)

💡 *Как работает пополнение:*
1. Выберите сумму
2. Вас перекинет на менеджера в Telegram
3. Оплатите выбранную сумму
4. Получите подтверждение и бонусы!

⏱️ *Пополнение происходит вручную администратором в течение 15 минут*

👇 *Выберите сумму:*
"""
    await safe_edit_message(
        query,
        text,
        deposit_menu_keyboard()
    )


async def handle_deposit_amount(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора суммы пополнения"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    username = update.effective_user.username or "нет username"
    deposit_data = query.data
    if deposit_data == 'deposit_custom':
        await handle_custom_deposit_start(query, context)
        return
    deposit_options = {
        'deposit_150': {'amount': 150, 'bonus': 0, 'total': 150,
                        'description': '150 руб. (1 анализ)'},
        'deposit_300': {'amount': 300, 'bonus': 150, 'total': 450,
                        'description': '300 руб. +150 бонус = 450 руб.'},
        'deposit_600': {'amount': 600, 'bonus': 0, 'total': 600,
                        'description': '600 руб. (4 анализа)'},
        'deposit_800': {'amount': 800, 'bonus': 300, 'total': 1100,
                        'description': '800 руб. +300 бонус = 1100 руб.'}
    }
    if deposit_data not in deposit_options:
        await query.answer("❌ Неверная сумма!", show_alert=True)
        return
    option = deposit_options[deposit_data]
    await process_deposit_option(update, context, user_id, username, option)


async def handle_custom_deposit_start(query, context):
    """Начало обработки своей суммы"""
    await safe_edit_message(
        query,
        "⚙️ *ДРУГАЯ СУММА*\n\n"
        "Введите сумму для пополнения (минимум 100 руб.):\n"
        "Пример: 500",
        keyboards.back_to_main_keyboard()
    )
    context.user_data['awaiting_custom_deposit'] = True
    return WAITING_CUSTOM_DEPOSIT


async def handle_custom_deposit_amount(update: Update,
                                       context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода своей суммы"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "нет username"
    if not context.user_data.get('awaiting_custom_deposit'):
        await update.message.reply_text("Выберите сумму из меню.")
        return ConversationHandler.END
    try:
        custom_amount = int(update.message.text.strip())
        if custom_amount < 100:
            await update.message.reply_text(
                "❌ Минимальная сумма 100 руб.\n"
                "Пожалуйста, введите сумму от 100 руб.:"
            )
            return WAITING_CUSTOM_DEPOSIT
        if custom_amount > 10000:
            await update.message.reply_text(
                "❌ Максимальная сумма 10 000 руб."
                "\nПожалуйста, введите меньшую сумму:"
            )
            return WAITING_CUSTOM_DEPOSIT
        # Рассчитываем бонус для своей суммы
        bonus = 0
        if custom_amount >= 800:
            bonus = 300
        elif custom_amount >= 500:
            bonus = 200
        elif custom_amount >= 300:
            bonus = 150
        total_amount = custom_amount + bonus
        option = {
            'amount': custom_amount,
            'bonus': bonus,
            'total': total_amount,
            'description': f'Своя сумма {custom_amount} руб.'
        }
        await process_deposit_option(update, context, user_id, username,
                                     option)
        context.user_data['awaiting_custom_deposit'] = False
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text(
            "❌ Пожалуйста, введите числовую сумму:\nПример: 500"
        )
        return WAITING_CUSTOM_DEPOSIT


async def process_deposit_option(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE,
                                 user_id, username, option):
    """Обработка опции пополнения"""
    # Сохраняем данные о пополнении
    context.user_data['deposit_amount'] = option['amount']
    context.user_data['deposit_bonus'] = option['bonus']
    context.user_data['deposit_total'] = option['total']
    # Автоматическое сообщение для менеджера
    manager_message = (
        f"💸 *Заявка на пополнение:*\n\n"
        f"👤 Пользователь: @{username} (ID: {user_id})\n"
        f"💰 Сумма: {option['amount']} руб.\n"
        f"🎁 Бонус: {option['bonus']} руб.\n"
        f"📊 Итого: {option['total']} руб.\n"
        f"📝 Описание: {option['description']}\n\n"
        f"⏱️ Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    # URL для перехода к менеджеру с авто-сообщением
    manager_url = f"https://t.me/{MANAGER_USERNAME[1:]}?text=" + urllib.parse.quote(manager_message)
    text = f"""
✅ *ВЫБРАНА СУММА ПОПОЛНЕНИЯ*

💰 *Сумма:* {option['amount']} руб.
🎁 *Бонус:* {option['bonus']} руб.
📊 *Итого на счет:* {option['total']} руб.
📝 *Описание:* {option['description']}

👇 *Действия:*

1️⃣ *Нажмите на кнопку ниже* для перехода к менеджеру
2️⃣ *Отправьте сообщение* менеджеру (оно будет автоматически заполнено)
3️⃣ *Произведите оплату* по реквизитам менеджера
4️⃣ *Дождитесь подтверждения* (обычно в течение 15 минут)

💡 *После подтверждения баланс будет пополнен автоматически*

👨‍💼 *Менеджер:* {MANAGER_USERNAME}
"""
    keyboard = [
        [InlineKeyboardButton(f"📨 Перейти к менеджеру ({MANAGER_USERNAME})", url=manager_url)],
        [InlineKeyboardButton("🔄 Проверить пополнение", callback_data='check_deposit')],
        [InlineKeyboardButton("◀️ Выбрать другую сумму", callback_data='deposit')],
        [InlineKeyboardButton("🏠 В главное меню", callback_data='back_to_menu')]
    ]
    if hasattr(update, 'callback_query'):
        await safe_edit_message(
            update.callback_query,
            text,
            InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def check_deposit_status(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    """Проверка статуса пополнения"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    balance = database.get_user_balance(user_id)
    text = f"""
🔄 *ПРОВЕРКА ПОПОЛНЕНИЯ*

💰 Текущий баланс: *{balance} руб.*

📊 Если ваш баланс не изменился после оплаты:
1. Убедитесь, что вы отправили сообщение менеджеру
2. Проверьте, прошла ли оплата
3. Подождите еще несколько минут

⚠️ *Пополнение происходит вручную администратором*
⏱️ *Время обработки:* до 15 минут

👨‍💼 *Связь с менеджером:* {MANAGER_USERNAME}

👇 *Другие действия:*
"""

    await safe_edit_message(
        query,
        text,
        keyboards.deposit_options_keyboard()
    )


def setup_payment_handlers(application):
    """Настройка обработчиков платежей"""
    # Conversation handler для своей суммы
    custom_deposit_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(
            handle_deposit_amount, pattern='^deposit_custom$')],
        states={
            WAITING_CUSTOM_DEPOSIT: [MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                handle_custom_deposit_amount)],
        },
        fallbacks=[CallbackQueryHandler(handle_deposit_menu,
                                        pattern='^deposit$')],
    )
    application.add_handler(custom_deposit_handler)
