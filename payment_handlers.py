import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler
)
import database
import keyboards
from utils import safe_edit_message

logger = logging.getLogger(__name__)

# Определяем состояния внутри файла
WAITING_CUSTOM_DEPOSIT = 1


async def handle_deposit_menu(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    """Меню пополнения баланса"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    balance = database.get_user_balance(user_id)
    text = f"""
💳 *ПОПОЛНЕНИЕ БАЛАНСА*

💰 Текущий баланс: *{balance} руб.*

🎁 *Выберите сумму для пополнения:*

👇 *Доступные тарифы (все цены в рублях):*
"""
    await safe_edit_message(
        query,
        text,
        keyboards.deposit_menu_keyboard()
    )


async def handle_deposit_amount(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора суммы пополнения"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    username = update.effective_user.username or "нет username"
    deposit_data = query.data
    deposit_options = {
        'deposit_150': {'amount': 150, 'bonus': 0, 'total': 150,
                        'description': '150 руб. (1 анализ)'},
        'deposit_300': {'amount': 300, 'bonus': 150, 'total': 450,
                        'description': '300 руб. +150 бонус (3 анализа)'},
        'deposit_600': {'amount': 600, 'bonus': 0, 'total': 600,
                        'description': '600 руб. (4 анализа)'},
        'deposit_800': {'amount': 800, 'bonus': 300, 'total': 1100,
                        'description': '800 руб. +300 бонус (7+ анализов)'},
        'deposit_500': {'amount': 500, 'bonus': 200, 'total': 700,
                        'description': '500 руб. +200 бонус (4+ анализа)'},
        'deposit_1000': {'amount': 1000, 'bonus': 400, 'total': 1400,
                         'description': '1000 руб. +400 бонус (9+ анализов)'}
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
        "Введите сумму для пополнения (от 100 до 10 000 руб.):\n"
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
                "❌ Максимальная сумма 10 000 руб.\n"
                "Пожалуйста, введите меньшую сумму:"
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
        await process_deposit_option(update, context, user_id,
                                     username, option)
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
    # Текст с реквизитами
    payment_details = f"""
💳 *Реквизиты для оплаты:*

📱 *СБП (Система быстрых платежей):*
• Номер телефона: +7 999 123-45-67
• Банк: Тинькофф

💎 *ЮMoney (Яндекс.Деньги):*
• Номер кошелька: 4100 1234 5678 9012

📊 *Банковская карта:*
• Номер карты: 2200 1234 5678 9012
• Получатель: Иванов И.И.

⚠️ *ВАЖНО:*
1. При переводе укажите ваш Telegram ID: `{user_id}`
2. После оплаты нажмите кнопку "Проверить пополнение"
3. Баланс обновится в течение 15 минут
"""
    text = f"""
✅ *ВЫБРАНА СУММА ПОПОЛНЕНИЯ*

💰 *Сумма:* {option['amount']} руб.
🎁 *Бонус:* {option['bonus']} руб.
📊 *Итого на счет:* {option['total']} руб.
📝 *Описание:* {option['description']}

👇 *Действия:*

1️⃣ *Оплатите* {option['amount']} руб. по реквизитам ниже
2️⃣ *Обязательно укажите* в комментарии ваш ID: `{user_id}`
3️⃣ *После оплаты* нажмите "Проверить пополнение"
4️⃣ *Баланс обновится* автоматически в течение 15 минут

{payment_details}
"""
    keyboard = [
        [InlineKeyboardButton("🔄 Проверить пополнение",
                              callback_data='check_deposit')],
        [InlineKeyboardButton("◀️ Выбрать другую сумму",
                              callback_data='deposit')],
        [InlineKeyboardButton("🏠 В главное меню",
                              callback_data='back_to_menu')]
    ]
    if hasattr(update, 'callback_query'):
        print("   → Отправляем информацию о депозите")
        await safe_edit_message(
            update.callback_query,
            text,
            InlineKeyboardMarkup(keyboard)
        )
    else:
        print("   → Отправляем новое сообщение о депозите")
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

📊 *Статус:* Ожидание оплаты

⚠️ *Если вы оплатили, но баланс не изменился:*
1. Проверьте, что вы указали правильный ID: `{user_id}`
2. Проверьте, прошла ли оплата
3. Подождите 15 минут
4. Если проблема осталась, попробуйте оплатить снова

⏱️ *Обработка платежей:* до 15 минут

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
        per_message=True
    )
    application.add_handler(custom_deposit_handler)
