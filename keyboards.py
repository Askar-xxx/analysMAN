from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from datetime import datetime, timedelta


def main_menu_keyboard():
    """Главное меню"""
    keyboard = [
        [InlineKeyboardButton("🎯 ВЫБРАТЬ СПОРТ",
                              callback_data='category_sports')],
        [
            InlineKeyboardButton("📊 Мои анализы", callback_data='my_analysis'),
            InlineKeyboardButton("Приобрести 💎", callback_data='deposit')
        ],
        [
            InlineKeyboardButton("⚙️ Как это работает", callback_data='how_it_works'),
            InlineKeyboardButton("🎧 Техподдержка", callback_data='support')
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def back_to_main_keyboard():
    """Клавиатура с кнопкой назад в главное меню"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ В главное меню",
                              callback_data='back_to_menu')]
    ])


def analysis_view_keyboard(
    match_id=None,
    back_callback_data='back',
    callback_suffix='',
    active_view: str = None
):
    """Клавиатура для просмотра таблицы/текстового анализа."""
    keyboard = []

    if match_id is not None:
        suffix = f"_{callback_suffix}" if callback_suffix else ""
        table_callback = f"show_table_{match_id}{suffix}"
        text_callback = f"show_text_{match_id}{suffix}"
        if active_view == 'table':
            table_callback = "noop"
        elif active_view == 'text':
            text_callback = "noop"
        keyboard.append([
            InlineKeyboardButton("📋 Таблица", callback_data=table_callback),
            InlineKeyboardButton("📝 Текст", callback_data=text_callback)
        ])

    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=back_callback_data)])
    keyboard.append([InlineKeyboardButton("🏠 В главное меню", callback_data='back_to_menu')])
    return InlineKeyboardMarkup(keyboard)


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
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
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


def match_detail_keyboard(match_id, has_purchased, user_balance=0, price=1):
    """Клавиатура для детальной страницы матча."""
    if has_purchased:
        keyboard = [
            [
                InlineKeyboardButton("📋 Таблица",
                                     callback_data=f'show_table_{match_id}'),
                InlineKeyboardButton("📝 Текст",
                                     callback_data=f'show_text_{match_id}'),
            ],
            [InlineKeyboardButton("◀️ Назад", callback_data='back')],
            [InlineKeyboardButton("🏠 В главное меню", callback_data='back_to_menu')]
        ]
    elif user_balance >= price:
        keyboard = [
            [InlineKeyboardButton("✅ Приобрести анализ",
                                  callback_data=f'buy_{match_id}')],
            [InlineKeyboardButton("◀️ Назад", callback_data='back')],
            [InlineKeyboardButton("🏠 В главное меню", callback_data='back_to_menu')]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("Приобрести 💎",
                                  callback_data='deposit')],
            [InlineKeyboardButton("◀️ Назад", callback_data='back')],
            [InlineKeyboardButton("🏠 В главное меню", callback_data='back_to_menu')]
        ]
    return InlineKeyboardMarkup(keyboard)


def back_to_purchased_sports_keyboard():
    """Клавиатура для возврата к выбору спорта (покупки)"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Назад к выбору спорта",
                              callback_data='back_to_purchased_sports')],
        [InlineKeyboardButton("🏠 В главное меню",
                              callback_data='back_to_menu')]
    ])


def dates_keyboard_with_back(dates, current_sport='football'):
    """Клавиатура с датами матчей и кнопкой назад"""
    keyboard = []
    today = datetime.now().strftime('%Y-%m-%d')
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
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
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data='back')])
    keyboard.append([InlineKeyboardButton("🏠 В главное меню",
                                          callback_data='back_to_menu')])
    return InlineKeyboardMarkup(keyboard)


def purchased_sports_keyboard(sports_with_counts):
    """Клавиатура с видами спорта для купленных анализов"""
    keyboard = []
    sport_names = {'football': '⚽ Футбол', 'basketball': '🏀 Баскетбол',
                   'hockey': '🏒 Хоккей'}
    for sport, count in sports_with_counts.items():
        sport_display = sport_names.get(sport, sport)
        button_text = f"{sport_display} ({count} анализов)"
        callback_data = f"purchased_sport_{sport}"
        keyboard.append([InlineKeyboardButton(button_text,
                                              callback_data=callback_data)])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data='back')])
    keyboard.append([InlineKeyboardButton("🏠 В главное меню",
                                          callback_data='back_to_menu')])
    return InlineKeyboardMarkup(keyboard)


def purchased_dates_keyboard_with_back(dates, sport):
    """Клавиатура с датами купленных анализов"""
    keyboard = []
    today = datetime.now().date()
    for date_str in dates:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        if date_obj.date() == today:
            date_label = "⏳ Сегодня"
        elif date_obj.date() == today + timedelta(days=1):
            date_label = "🕐 Завтра"
        else:
            date_label = date_obj.strftime("%d.%m.%Y")
        button_text = f"{date_label}"
        callback_data = f"purchased_date_{sport}_{date_str}"
        keyboard.append([InlineKeyboardButton(button_text,
                                              callback_data=callback_data)])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data='back')])
    keyboard.append([InlineKeyboardButton("🏠 В главное меню",
                                          callback_data='back_to_menu')])
    return InlineKeyboardMarkup(keyboard)
