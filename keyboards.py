from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from datetime import datetime


def main_menu_keyboard(is_admin=False):
    """Главное меню"""
    keyboard = [
        # Кнопки выбора спорта
        [InlineKeyboardButton("🎯 ВЫБРАТЬ СПОРТ",
                              callback_data='category_sports')],
        # Разделитель
        [InlineKeyboardButton("─" * 15, callback_data='separator')],
        # Личный кабинет пользователя
        [
            InlineKeyboardButton("📊 Моя статистика", callback_data='my_stats'),
            InlineKeyboardButton("💰 Баланс", callback_data='balance')
        ],
        # Финансовые операции
        [
            InlineKeyboardButton("💳 Пополнить баланс",
                                 callback_data='deposit'),
            InlineKeyboardButton("👨‍💼 Поддержка", callback_data='support')
        ]
    ]
    # Добавляем админ-панель если пользователь админ
    if is_admin:
        keyboard.append([InlineKeyboardButton("⚙️ Админ-панель",
                                              callback_data='admin_panel')])
    return InlineKeyboardMarkup(keyboard)


def deposit_menu_keyboard():
    """Меню пополнения баланса"""
    keyboard = [
        [InlineKeyboardButton("💳 150 руб. (1 анализ)",
                              callback_data='deposit_150')],
        [InlineKeyboardButton("💰 300 руб. +150 бонус = 450",
                              callback_data='deposit_300')],
        [InlineKeyboardButton("💎 600 руб. (4 анализа)",
                              callback_data='deposit_600')],
        [InlineKeyboardButton("🔥 800 руб. +300 бонус = 1100",
                              callback_data='deposit_800')],
        [InlineKeyboardButton("⚙️ Другая сумма",
                              callback_data='deposit_custom')],
        [InlineKeyboardButton("◀️ Назад", callback_data='back_to_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)


def admin_main_keyboard():
    """Главное меню админ-панели"""
    keyboard = [
        [InlineKeyboardButton("➕ Создать матч",
                              callback_data='admin_create_match')],
        [InlineKeyboardButton("📝 Добавить анализ",
                              callback_data='admin_add_analysis')],
        [InlineKeyboardButton("📋 Все матчи",
                              callback_data='admin_all_matches')],
        [InlineKeyboardButton("🗑️ Удалить матч",
                              callback_data='admin_delete_match')],
        [InlineKeyboardButton("👥 Все пользователи",
                              callback_data='admin_all_users')],
        [InlineKeyboardButton("👨‍💼 Управление админами",
                              callback_data='admin_manage_admins')],
        [InlineKeyboardButton("💰 Пополнить баланс",
                              callback_data='admin_add_balance')],
        [InlineKeyboardButton("◀️ В главное меню",
                              callback_data='back_to_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)


def back_to_main_keyboard():
    """Клавиатура с кнопкой назад в главное меню"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ В главное меню",
                              callback_data='back_to_menu')]
    ])


def back_to_admin_keyboard():
    """Клавиатура с кнопкой назад в админ-панель"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Назад в админ-панель",
                              callback_data='admin_back')]
    ])


def sports_keyboard():
    """Клавиатура выбора спорта"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚽ Футбол", callback_data='sport_football'),
            InlineKeyboardButton("🏀 Баскетбол",
                                 callback_data='sport_basketball'),
            InlineKeyboardButton("🏒 Хоккей", callback_data='sport_hockey')
        ],
        [InlineKeyboardButton("◀️ Назад", callback_data='back_to_menu')]
    ])


def dates_keyboard(dates, current_sport='football'):
    """Клавиатура с датами матчей"""
    keyboard = []
    today = datetime.now().strftime('%Y-%m-%d')
    tomorrow = (datetime.now().utcnow() + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    for date_str in dates:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        if date_str == today:
            date_label = "⏳ Сегодня"
        elif date_str == tomorrow:
            date_label = "🕐 Завтра"
        else:
            date_label = date_obj.strftime("%d.%m.%Y")
        button_text = f"{date_label}"
        callback_data = f"choose_date_{current_sport}_{date_str}"
        keyboard.append([InlineKeyboardButton(button_text,
                                              callback_data=callback_data)])
    keyboard.append([InlineKeyboardButton("◀️ Назад",
                                          callback_data='category_sports')])
    return InlineKeyboardMarkup(keyboard)


def matches_keyboard(matches, date_str, sport):
    """Клавиатура с матчами на определенную дату"""
    keyboard = []
    for match in matches:
        button_text = f"{match['team1']} vs {match['team2']} ({match['match_time']})"
        callback_data = f"match_{match['id']}"
        keyboard.append([InlineKeyboardButton(button_text,
                                              callback_data=callback_data)])
    keyboard.append([InlineKeyboardButton("◀️ Назад к выбору даты",
                                          callback_data=f'sport_{sport}')])
    keyboard.append([InlineKeyboardButton("🏠 В главное меню",
                                          callback_data='back_to_menu')])
    return InlineKeyboardMarkup(keyboard)


def match_detail_keyboard(match_id, has_purchased, price, user_balance):
    """Клавиатура для детальной страницы матча"""
    if has_purchased:
        keyboard = [
            [InlineKeyboardButton("◀️ Назад к матчам",
                                  callback_data='sport_football')],
            [InlineKeyboardButton("🏠 В главное меню",
                                  callback_data='back_to_menu')]
        ]
    else:
        if user_balance >= price:
            keyboard = [
                [InlineKeyboardButton(f"✅ Купить анализ за {price} руб.",
                                      callback_data=f'buy_{match_id}')],
                [InlineKeyboardButton("◀️ Назад к матчам",
                                      callback_data='sport_football')],
                [InlineKeyboardButton("🏠 В главное меню",
                                      callback_data='back_to_menu')]
            ]
        else:
            keyboard = [
                [InlineKeyboardButton("💳 Пополнить баланс",
                                      callback_data='deposit')],
                [InlineKeyboardButton("◀️ Назад к матчу",
                                      callback_data=f'match_{match_id}')],
                [InlineKeyboardButton("🏠 В главное меню",
                                      callback_data='back_to_menu')]
            ]
    return InlineKeyboardMarkup(keyboard)


def admin_manage_admins_keyboard():
    """Клавиатура управления админами"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить админа",
                              callback_data='admin_add_admin')],
        [InlineKeyboardButton("🗑️ Удалить админа",
                              callback_data='admin_remove_admin')],
        [InlineKeyboardButton("◀️ Назад", callback_data='admin_back')]
    ])


def support_keyboard():
    """Клавиатура поддержки"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Пополнить баланс", callback_data='deposit')],
        [InlineKeyboardButton("🏠 В главное меню",
                              callback_data='back_to_menu')]
    ])


def deposit_options_keyboard():
    """Клавиатура опций пополнения после выбора суммы"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Пополнить баланс", callback_data='deposit')],
        [InlineKeyboardButton("📊 Моя статистика", callback_data='my_stats')],
        [InlineKeyboardButton("🏠 В главное меню",
                              callback_data='back_to_menu')]
    ])
