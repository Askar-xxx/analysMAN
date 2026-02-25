import logging
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler
import database
import keyboards
from utils import (
    safe_edit_message,
    safe_answer_callback,
    send_main_menu,
    format_match_info,
    markdown_to_html
)
from datetime import datetime, timedelta
import time


MENU_MAIN = 'main'
MENU_MY_ANALYSIS = 'my_analysis'
MENU_PURCHASED_SPORT = 'purchased_sport'
MENU_PURCHASED_DATE = 'purchased_date'
MENU_CATEGORY_SPORTS = 'category_sports'
MENU_SPORT_SELECTION = 'sport_selection'
MENU_DATE_SELECTION = 'date_selection'
MENU_MATCHES_LIST = 'matches_list'
MENU_MATCH_DETAIL = 'match_detail'
MENU_DEPOSIT = 'deposit'

logger = logging.getLogger(__name__)


async def _cleanup_topup_step_images(query, context):
    """Удаляет служебные STEP_скриншоты второго UX из истории чата."""
    message_ids = context.user_data.pop('topup_step_image_ids', [])
    if not message_ids:
        return

    bot = query.message.get_bot()
    chat_id = query.message.chat_id
    for message_id in message_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            # Игнорируем: сообщение могло быть удалено вручную/автоматически.
            pass


def _is_webhook_analysis_nav_message(query) -> bool:
    """
    Проверяет, что callback пришёл из сообщения-навигатора анализа webhook-сценария.

    Для таких сообщений первая кнопка обычно `analysis_back_*`,
    вторая — `back_to_menu`.
    """
    markup = getattr(query.message, 'reply_markup', None)
    if not markup or not getattr(markup, 'inline_keyboard', None):
        return False

    callback_data_values = []
    for row in markup.inline_keyboard:
        for button in row:
            cb = getattr(button, 'callback_data', None)
            if cb:
                callback_data_values.append(cb)

    has_analysis_back = any(cb.startswith('analysis_back_') for cb in callback_data_values)
    has_main_menu = 'back_to_menu' in callback_data_values
    return has_analysis_back and has_main_menu


def _remember_analysis_thread(context, conclusion_message_id: int, related_message_ids):
    """Сохраняет связку сообщений анализа для последующей очистки при навигации."""
    related = []
    for mid in related_message_ids or []:
        if isinstance(mid, int) and mid > 0:
            related.append(mid)

    context.user_data['analysis_thread'] = {
        'conclusion_message_id': conclusion_message_id,
        'related_message_ids': related
    }


def _parse_analysis_callback_data(data: str, prefix: str):
    """
    Парсит callback формата:
      <prefix><match_id>
      <prefix><match_id>_<sport>_<date>
    Возвращает (match_id, callback_suffix, back_callback_data).
    """
    raw = str(data or '')
    if not raw.startswith(prefix):
        return None, '', 'back'

    payload = raw[len(prefix):]
    parts = payload.split('_')
    if not parts or not parts[0].isdigit():
        return None, '', 'back'

    match_id = int(parts[0])
    callback_suffix = ''
    # По умолчанию «Назад» ведёт к странице матча (а не к списку)
    back_callback_data = f"match_{match_id}"

    if len(parts) >= 3:
        sport = parts[1]
        date_str = '_'.join(parts[2:])
        if sport and date_str:
            callback_suffix = f"{sport}_{date_str}"
            back_callback_data = f"analysis_back_{sport}_{date_str}"

    return match_id, callback_suffix, back_callback_data


async def _cleanup_analysis_thread_messages(query, context):
    """
    Удаляет intro/photo сообщения анализа, если пользователь уходит с экрана анализа.

    Работает в двух режимах:
    1) Точный: по сохранённым message_id (on-demand/show_analysis flow).
    2) Fallback: для webhook-кнопки `analysis_back_*` удаляет 2 предыдущих сообщения.
    """
    data = query.data or ''
    if (
        data not in ('back', 'back_to_menu')
        and not data.startswith('analysis_back_')
        and not data.startswith('match_')
    ):
        return

    bot = query.message.get_bot()
    chat_id = query.message.chat_id
    current_message_id = query.message.message_id

    tracked = context.user_data.get('analysis_thread')
    if (
        tracked
        and tracked.get('conclusion_message_id') == current_message_id
    ):
        for message_id in tracked.get('related_message_ids', []):
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception:
                pass
        context.user_data.pop('analysis_thread', None)
        return

    # Fallback: webhook-сообщение с analysis_back_ не имеет доступа к context.user_data.
    if data.startswith('analysis_back_') or (
        data == 'back_to_menu' and _is_webhook_analysis_nav_message(query)
    ):
        for delta in (1, 2):
            target_id = current_message_id - delta
            if target_id <= 0:
                continue
            try:
                await bot.delete_message(chat_id=chat_id, message_id=target_id)
            except Exception:
                pass


def _build_post_topup_keyboard(context):
    """Клавиатура после успешного пополнения с быстрым возвратом к матчу."""
    match_id = context.user_data.get('post_topup_match_id')
    if match_id:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🎯 Вернуться к матчу",
                callback_data=f'return_to_match_{match_id}'
            )],
            [InlineKeyboardButton("🏠 В главное меню", callback_data='back_to_menu')]
        ])
    return keyboards.main_menu_keyboard()


def _remember_post_topup_target(context):
    """
    Сохраняет цель возврата после пополнения только для сценария покупки матча.
    """
    history = context.user_data.get('menu_history', [])
    last_menu = history[-1] if history else None
    match_id = context.user_data.get('current_match_id')
    if match_id and last_menu in (MENU_MATCHES_LIST, MENU_MATCH_DETAIL):
        context.user_data['post_topup_match_id'] = match_id
        context.user_data['post_topup_match_source'] = context.user_data.get(
            'match_source', 'browse'
        )
        return

    context.user_data.pop('post_topup_match_id', None)
    context.user_data.pop('post_topup_match_source', None)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await send_main_menu(update, context)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Основной обработчик кнопок"""
    query = update.callback_query
    await safe_answer_callback(query)
    user_id = update.effective_user.id
    username = update.effective_user.username
    database.get_or_create_user(user_id, username)
    # Сохраняем текущее меню для навигации назад
    if not context.user_data.get('menu_history'):
        context.user_data['menu_history'] = []
    # Скриншоты шага пополнения показываем только в рамках второго UX.
    # Не удаляем их при повторном входе во 2-й шаг и при проверке баланса.
    if (
        not query.data.startswith('confirm_code_copy_')
        and not query.data.startswith('check_balance_')
    ):
        await _cleanup_topup_step_images(query, context)
    await _cleanup_analysis_thread_messages(query, context)
    # Обработка различных callback_data
    if query.data in ('back', 'go_back'):
        # Возвращаемся назад по истории
        await go_back(update, context)
        return
    elif query.data == 'back_to_menu':
        # Очищаем историю и возвращаемся в главное меню
        context.user_data['menu_history'] = []
        await send_main_menu(update, context)
    elif query.data == 'category_sports':
        # Сохраняем предыдущее меню
        context.user_data['menu_history'].append(MENU_MAIN)
        await handle_category_sports(query)
    elif query.data == 'my_analysis':
        # Сохраняем предыдущее меню
        context.user_data['menu_history'].append(MENU_MAIN)
        await handle_my_analysis(update, query, user_id)
    elif query.data == 'support':
        # Сохраняем предыдущее меню
        context.user_data['menu_history'].append(MENU_MAIN)
        await handle_support(query)
    elif query.data == 'how_it_works':
        # Сохраняем предыдущее меню
        context.user_data['menu_history'].append(MENU_MAIN)
        await handle_how_it_works(query)
    elif query.data.startswith('hiw_page_'):
        page = int(query.data.split('_')[-1])
        await handle_how_it_works(query, page=page)
    elif query.data == 'noop':
        await query.answer()
    elif query.data.startswith('sport_'):
        sport = query.data.split('_')[1]
        # Сохраняем предыдущее меню
        context.user_data['menu_history'].append(MENU_CATEGORY_SPORTS)
        logger.info(f"Добавлено MENU_CATEGORY_SPORTS в history. Текущий history: {context.user_data['menu_history']}")
        await handle_sport_selection(query, context, sport)
    elif query.data.startswith('choose_date_'):
        parts = query.data.split('_')
        sport = parts[2]
        date_str = parts[3]
        # Сохраняем предыдущее меню
        context.user_data['menu_history'].append(MENU_DATE_SELECTION)
        context.user_data['current_sport'] = sport
        context.user_data['current_date'] = date_str
        context.user_data['match_source'] = 'browse'
        await handle_date_selection(query, context, sport, date_str)
    elif query.data.startswith('analysis_back_'):
        parts = query.data.split('_')
        sport = parts[2]
        date_str = parts[3]
        await handle_analysis_back_to_matches(query, context, sport, date_str)
    elif query.data.startswith('match_'):
        match_id = int(query.data.split('_')[1])
        # Сохраняем предыдущее меню и текущий матч с учетом источника
        match_source = context.user_data.get('match_source', 'browse')
        # Не дублируем запись если возвращаемся из анализа к тому же матчу
        history = context.user_data.get('menu_history', [])
        already_on_match = (
            context.user_data.get('current_match_id') == match_id
            and history and history[-1] in (MENU_MATCHES_LIST, MENU_PURCHASED_DATE)
        )
        if not already_on_match:
            if match_source == 'purchased':
                history.append(MENU_PURCHASED_DATE)
            else:
                history.append(MENU_MATCHES_LIST)
        context.user_data['current_match_id'] = match_id
        await handle_match_detail(query, user_id, match_id, match_source=match_source)
    elif query.data.startswith('buy_'):
        match_id = int(query.data.split('_')[1])
        # Сохраняем текущее меню (детали матча) в историю
        context.user_data['menu_history'].append(MENU_MATCH_DETAIL)
        await handle_purchase(query, user_id)
    elif query.data.startswith('show_table_'):
        match_id, callback_suffix, back_callback_data = _parse_analysis_callback_data(
            query.data, 'show_table_'
        )
        if match_id is not None:
            await handle_show_table(
                query, context, user_id, match_id,
                callback_suffix=callback_suffix,
                back_callback_data=back_callback_data
            )
        else:
            await safe_edit_message(
                query,
                "❌ Не удалось открыть таблицу анализа.",
                keyboards.main_menu_keyboard()
            )
    elif query.data.startswith('show_text_'):
        match_id, callback_suffix, back_callback_data = _parse_analysis_callback_data(
            query.data, 'show_text_'
        )
        if match_id is not None:
            await handle_show_text_analysis(
                query, context, user_id, match_id,
                callback_suffix=callback_suffix,
                back_callback_data=back_callback_data
            )
        else:
            await safe_edit_message(
                query,
                "❌ Не удалось открыть текстовый анализ.",
                keyboards.main_menu_keyboard()
            )
    elif query.data.startswith('show_analysis_'):
        # Обратная совместимость со старым callback.
        match_id = int(query.data.split('_')[2])
        await handle_show_table(
            query, context, user_id, match_id,
            callback_suffix='',
            back_callback_data='back'
        )
    elif query.data.startswith('purchased_sport_'):
        sport = query.data.split('_')[2]
        # Сохраняем предыдущее меню
        context.user_data['menu_history'].append(MENU_MY_ANALYSIS)
        await handle_purchased_sport(query, user_id, sport)
    elif query.data.startswith('purchased_date_'):
        parts = query.data.split('_')
        sport = parts[2]
        date_str = parts[3]
        # Сохраняем предыдущее меню
        context.user_data['menu_history'].append(MENU_PURCHASED_SPORT)
        context.user_data['current_sport'] = sport
        context.user_data['current_date'] = date_str
        context.user_data['match_source'] = 'purchased'
        await handle_purchased_date(query, user_id, sport, date_str)
    elif query.data == 'deposit':
        _remember_post_topup_target(context)
        await handle_deposit_menu(query, context, user_id)
    elif query.data.startswith('return_to_match_'):
        match_id = int(query.data.split('_')[-1])
        context.user_data['current_match_id'] = match_id
        match_source = context.user_data.get('post_topup_match_source', 'browse')
        context.user_data['match_source'] = match_source
        context.user_data.pop('post_topup_match_id', None)
        context.user_data.pop('post_topup_match_source', None)
        await handle_match_detail(
            query, user_id, match_id, match_source=match_source
        )
    elif query.data.startswith('confirm_code_copy_'):
        token = query.data.split('confirm_code_copy_')[1]
        await handle_confirm_code_copy(query, context, user_id, token)
    elif query.data.startswith('check_balance_'):
        token = query.data.split('check_balance_')[1]
        await handle_check_balance_status(query, user_id, token, context)
    elif query.data.startswith('check_topup_'):
        token = query.data.split('check_topup_')[1]
        await handle_check_topup(query, user_id, token, context)
    elif query.data.startswith('find_topup_by_amount_'):
        token = query.data.split('find_topup_by_amount_')[1]
        await handle_find_topup_by_amount(query, user_id, token, context)
    else:
        await safe_edit_message(
            query,
            "Неизвестная команда.",
            keyboards.main_menu_keyboard()
        )


async def handle_category_sports(query):
    """Обработка выбора категории спорта"""
    sports_text = """
🎯 <b>ВЫБЕРИТЕ ВИД СПОРТА</b>

Выберите интересующий вас вид спорта для просмотра доступных матчей и анализов:

⚽ <b>Футбол</b> - Европейские лиги, Кубки, международные матчи
🏀 <b>Баскетбол</b> - НБА, Евролига, национальные чемпионаты
🏒 <b>Хоккей</b> - КХЛ, НХЛ, международные турниры

👇 Выберите вид спорта ниже:
"""
    keyboard = [
        [
            InlineKeyboardButton("⚽ Футбол", callback_data='sport_football'),
            InlineKeyboardButton("🏀 Баскетбол",
                                 callback_data='sport_basketball'),
            InlineKeyboardButton("🏒 Хоккей", callback_data='sport_hockey')
        ],
        [InlineKeyboardButton("◀️ Назад", callback_data='back')],
        [InlineKeyboardButton("🏠 В главное меню", callback_data='back_to_menu')]
    ]
    await safe_edit_message(
        query,
        sports_text,
        InlineKeyboardMarkup(keyboard)
    )


async def handle_sport_selection(query, context, sport):
    """Обработка выбора конкретного спорта"""
    print(f"   → Выбран спорт: {sport}")
    if sport not in ['football', 'basketball', 'hockey']:
        await safe_edit_message(
            query,
            "Этот вид спорта пока не поддерживается.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data='go_back')]
            ])
        )
        return
    if sport in ['basketball', 'hockey']:
        await safe_edit_message(
            query,
            "🚧 Данный вид спорта находится в разработке.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data='go_back')]
            ])
        )
        return
    dates = database.get_available_dates_with_matches(sport)
    if not dates:
        await safe_edit_message(
            query,
            "На ближайшую неделю матчей по футболу нет.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data='go_back')]
            ])
        )
        return
    # Сохраняем текущий спорт
    context.user_data['current_sport'] = sport
    sport_names = {'football': '⚽ Футбол', 'basketball': '🏀 Баскетбол',
                   'hockey': '🏒 Хоккей'}
    sport_display = sport_names.get(sport, sport)
    text = f"{sport_display}\n\nВыберите дату для просмотра матчей:\n\n"
    await safe_edit_message(
        query,
        text,
        keyboards.dates_keyboard_with_back(dates, sport)
    )


async def handle_date_selection_back(query, context, sport):
    """Возврат к выбору даты"""
    sport_name = {'football': 'футболу', 'basketball': 'баскетболу', 'hockey': 'хоккею'}.get(sport, sport)
    dates = database.get_available_dates_with_matches(sport)
    if not dates:
        await safe_edit_message(
            query,
            f"На ближайшую неделю матчей по {sport_name} нет.",
            keyboards.main_menu_keyboard()
        )
        return
    text = f"Выберите дату для просмотра матчей по {sport_name}:\n\n"
    await safe_edit_message(
        query,
        text,
        keyboards.dates_keyboard_with_back(dates, sport)
    )


async def handle_date_selection(query, context, sport, date_str):
    """Обработка выбора даты"""
    print(f"   → Выбрана дата: {date_str} для спорта: {sport}")
    matches = database.get_matches_by_date_filtered(sport, date_str)
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
    sport_names = {'football': '⚽ Футбол', 'basketball': '🏀 Баскетбол',
                   'hockey': '🏒 Хоккей'}
    sport_display = sport_names.get(sport, sport)
    text = f"{sport_display} <b>Матчи на {date_label}:</b>\n\n"
    for match in matches:
        text += f"• {match['team1']} vs {match['team2']} в {match['match_time']}\n"
    text += "\n👇 <b>Выберите матч для просмотра анализа:</b>"
    keyboard = []
    for match in matches:
        button_text = f"{match['team1']} vs {match['team2']} ({match['match_time']})"
        callback_data = f"match_{match['id']}"
        keyboard.append([InlineKeyboardButton(button_text,
                                              callback_data=callback_data)])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data='back')])
    keyboard.append([InlineKeyboardButton("🏠 В главное меню",
                                          callback_data='back_to_menu')])
    await safe_edit_message(
        query,
        text,
        InlineKeyboardMarkup(keyboard)
    )


async def handle_analysis_back_to_matches(query, context, sport, date_str):
    """
    Возврат из экрана готового анализа к списку матчей.

    Удаляем хвост истории (детали матча/список), чтобы дальнейший «Назад»
    шёл симметрично: матчи -> даты -> спорт.
    """
    history = context.user_data.get('menu_history', [])
    while history and history[-1] in (
        MENU_MATCH_DETAIL, MENU_MATCHES_LIST, MENU_MAIN
    ):
        history.pop()

    context.user_data['current_sport'] = sport
    context.user_data['current_date'] = date_str
    context.user_data['match_source'] = 'browse'
    await handle_date_selection(query, context, sport, date_str)


async def go_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат на предыдущее меню"""
    if not context.user_data.get('menu_history') or len(context.user_data['menu_history']) == 0:
        # Если истории нет, возвращаемся в главное меню
        await send_main_menu(update, context)
        return
    # Получаем предыдущее меню
    previous_menu = context.user_data['menu_history'].pop()
    logger.info(f"go_back: previous_menu={previous_menu}, remaining_history={context.user_data['menu_history']}")
    user_id = update.effective_user.id
    query = update.callback_query
    try:
        if previous_menu == MENU_MAIN:
            await send_main_menu(update, context)
        elif previous_menu == MENU_MY_ANALYSIS:
            await handle_my_analysis(update, query, user_id)
        elif previous_menu == MENU_CATEGORY_SPORTS:
            await handle_category_sports(query)
        elif previous_menu == MENU_SPORT_SELECTION:
            sport = context.user_data.get('current_sport')
            if sport:
                await handle_sport_selection_back(query, context, sport)
            else:
                await handle_category_sports(query)
        elif previous_menu == MENU_PURCHASED_SPORT:
            sport = context.user_data.get('current_sport')
            if sport:
                await handle_purchased_sport_back(query, user_id, sport)
            else:
                await handle_my_analysis(update, query, user_id)
        elif previous_menu == MENU_DATE_SELECTION:
            sport = context.user_data.get('current_sport')
            if sport:
                await handle_date_selection_back(query, context, sport)
            else:
                await handle_category_sports(query)
        elif previous_menu == MENU_MATCHES_LIST:
            sport = context.user_data.get('current_sport')
            date_str = context.user_data.get('current_date')
            if sport and date_str:
                await handle_date_selection(query, context, sport, date_str)
            elif sport:
                await handle_sport_selection_back(query, context, sport)
            else:
                await handle_category_sports(query)
        elif previous_menu == MENU_PURCHASED_DATE:
            sport = context.user_data.get('current_sport')
            date_str = context.user_data.get('current_date')
            if sport and date_str:
                await handle_purchased_date(query, user_id, sport, date_str)
            elif sport:
                await handle_purchased_sport_back(query, user_id, sport)
            else:
                await handle_my_analysis(update, query, user_id)
        elif previous_menu == MENU_MATCH_DETAIL:
            # Возврат к деталям матча
            match_id = context.user_data.get('current_match_id')
            if match_id:
                match_source = context.user_data.get('match_source', 'browse')
                await handle_match_detail(
                    query, user_id, match_id, match_source=match_source
                )
            else:
                await send_main_menu(update, context)
        else:
            # По умолчанию возвращаемся в главное меню
            await send_main_menu(update, context)
    except Exception:
        # В случае ошибки возвращаемся в главное меню
        await send_main_menu(update, context)


async def handle_match_detail(query, user_id, match_id, match_source='browse'):
    """Обработка детальной страницы матча с проверкой баланса."""
    from config import ANALYSIS_PRICE_RUB

    match = database.get_match_by_id(match_id)
    if not match:
        await safe_edit_message(query, "Матч не найден.",
                                keyboards.main_menu_keyboard())
        return

    has_purchased = database.has_purchased_analysis(user_id, match_id)
    user_balance = database.get_user_balance(user_id)
    price = ANALYSIS_PRICE_RUB
    text = format_match_info(match)

    if has_purchased:
        if match_source == 'purchased':
            text += "\n\n🎛️ Выберите формат просмотра:"
        else:
            text += "\n\n✅ Вы уже приобрели этот анализ.\nВыберите формат просмотра:"
    elif user_balance >= price:
        text += (
            f"\n\nУ вас: <b>{user_balance}</b> 💎 | "
            f"Стоимость: <b>{price}</b> 💎\n"
            "Нажмите «Купить анализ» для мгновенной покупки с баланса."
        )
    else:
        text += (
            f"\n\nУ вас: <b>{user_balance}</b> 💎 | "
            f"Стоимость: <b>{price}</b> 💎\n"
            "Недостаточно 💎. Пополните баланс для покупки анализа."
        )

    keyboard = keyboards.match_detail_keyboard(
        match_id, has_purchased, user_balance, price
    )
    await safe_edit_message(query, text, keyboard, parse_mode='HTML')


async def handle_purchase(query, user_id):
    """Покупка анализа с баланса (мгновенная оплата)."""
    from config import ANALYSIS_PRICE_RUB

    await safe_answer_callback(query)

    match_id = int(query.data.split('_')[1])
    match = database.get_match_by_id(match_id)
    if not match:
        await safe_edit_message(
            query, "❌ Матч не найден.", keyboards.main_menu_keyboard()
        )
        return

    match_dict = dict(match) if not isinstance(match, dict) else match

    # Уже куплен?
    if database.has_purchased_analysis(user_id, match_id):
        text = (
            f"✅ Вы уже приобрели анализ для этого матча!\n\n"
            f"🏆 {match_dict['team1']} vs {match_dict['team2']}\n\n"
            "Откройте раздел «Мои анализы» чтобы посмотреть его."
        )
        await safe_edit_message(
            query, text, keyboards.main_menu_keyboard(), parse_mode='HTML'
        )
        return

    # Проверка баланса
    price = ANALYSIS_PRICE_RUB
    user_balance = database.get_user_balance(user_id)
    if user_balance < price:
        text = (
            f"❌ <b>Недостаточно 💎</b>\n\n"
            f"У вас: <b>{user_balance}</b> 💎\n"
            f"💵 Стоимость анализа: <b>{price}</b> 💎\n\n"
            "Пополните баланс и вернитесь к покупке."
        )
        keyboard = [
            [InlineKeyboardButton("💰 Пополнить баланс",
                                  callback_data='deposit')],
            [InlineKeyboardButton("◀️ Назад", callback_data='back')],
            [InlineKeyboardButton("🏠 В главное меню",
                                  callback_data='back_to_menu')]
        ]
        await safe_edit_message(
            query, text, InlineKeyboardMarkup(keyboard), parse_mode='HTML'
        )
        return

    # Списываем с баланса и создаём paid purchase
    success, message = database.purchase_analysis(user_id, match_id)
    if not success:
        await safe_edit_message(
            query,
            f"❌ Ошибка покупки: {message}",
            keyboards.main_menu_keyboard()
        )
        return

    # Мгновенная генерация анализа
    await safe_edit_message(
        query,
        f"⏳ <b>Генерируем анализ...</b>\n\n"
        f"🏆 {match_dict['team1']} vs {match_dict['team2']}\n\n"
        "<b>Текстовый анализ</b>\n"
        "⏳ 1/2 Сбор и обогащение данных\n"
        "▫️ 2/2 Генерация текста\n\n"
        "<b>Таблица</b>\n"
        "▫️ 1/2 Подготовка таблицы\n"
        "▫️ 2/2 Рендер изображения\n\n"
        "<b>Финал</b>\n"
        "▫️ Отправка результата\n\n"
        "⏱ Обычно это занимает <b>30-60 секунд</b>.",
        None,
        parse_mode='HTML'
    )

    from webhook_server import generate_and_send_analysis
    await generate_and_send_analysis(
        user_id, match_id, match_dict,
        instruction_message_id=query.message.message_id
    )


async def _load_match_for_analysis(query, user_id, match_id):
    """Проверяет доступ к анализу и возвращает match_dict."""
    if not database.has_purchased_analysis(user_id, match_id):
        await safe_edit_message(
            query,
            "❌ Вы не приобретали анализ для этого матча.",
            keyboards.main_menu_keyboard()
        )
        return None

    match = database.get_match_by_id(match_id)
    if not match:
        await safe_edit_message(
            query,
            "❌ Матч не найден.",
            keyboards.main_menu_keyboard()
        )
        return None

    return dict(match) if not isinstance(match, dict) else match


def _build_analysis_context(match_dict: dict, enriched_data: dict) -> str:
    """Строит текстовый контекст для генерации анализа."""
    from match_data_fetcher import build_enriched_context
    return build_enriched_context(match_dict, enriched_data)


def _fetch_enriched_data(match_dict: dict) -> dict:
    """Собирает обогащённые данные по матчу."""
    from match_data_fetcher import MatchDataFetcher
    team1 = match_dict.get('team1', '?')
    team2 = match_dict.get('team2', '?')
    logger.info(f"[DATA] Начинаем сбор enriched данных для {team1} vs {team2}")
    t0 = time.time()
    fetcher = MatchDataFetcher()
    data = fetcher.fetch_match_data(match_dict)
    elapsed = time.time() - t0
    errors = data.get('errors', [])
    keys = [k for k in data if k != 'errors']
    logger.info(
        f"[DATA] Enriched данные собраны за {elapsed:.1f}с — "
        f"ключей: {len(keys)}, ошибок: {len(errors)}"
    )
    if errors:
        for err in errors:
            logger.warning(f"[DATA]   ошибка: {err}")
    return data


async def _ensure_analysis_text(match_id: int, match_dict: dict, enriched_data: dict = None) -> tuple:
    """
    Гарантирует, что analysis_text существует.

    Returns:
        (analysis_text, enriched_data)
    """
    team1 = match_dict.get('team1', '?')
    team2 = match_dict.get('team2', '?')
    analysis_text = (match_dict.get('analysis_text') or '').strip()
    if analysis_text:
        logger.info(
            f"[TEXT] Текст анализа для {team1} vs {team2} "
            f"загружен из БД ({len(analysis_text)} символов)"
        )
        return analysis_text, (enriched_data or {})

    logger.info(f"[TEXT] Текст анализа для {team1} vs {team2} отсутствует — генерируем")

    if enriched_data is None:
        enriched_data = _fetch_enriched_data(match_dict)

    enriched_context = _build_analysis_context(match_dict, enriched_data)
    logger.info(f"[TEXT] Контекст для LLM собран ({len(enriched_context)} символов)")

    from ai_generator import generate_match_text_analysis
    t0 = time.time()
    analysis_text = await generate_match_text_analysis(match_dict, enriched_context)
    elapsed = time.time() - t0
    logger.info(
        f"[TEXT] Генерация завершена за {elapsed:.1f}с — "
        f"результат: {len(analysis_text)} символов"
    )

    match_dict['analysis_text'] = analysis_text
    database.update_match_analysis(match_id, analysis_text)
    return analysis_text, enriched_data


def _ensure_analysis_table_png(match_id: int, match_dict: dict, enriched_data: dict = None) -> tuple:
    """
    Гарантирует, что таблица анализа существует в кэше.

    Returns:
        (png_path, enriched_data)
    """
    import os

    cached_png_path = match_dict.get('analysis_png_path')
    if cached_png_path and os.path.exists(cached_png_path):
        return cached_png_path, (enriched_data or {})

    if enriched_data is None:
        enriched_data = _fetch_enriched_data(match_dict)

    from analysis_formatter import build_table_data
    from image_renderer import render_analysis_table
    import shutil

    table_data = build_table_data(match_dict, enriched_data)
    temp_png = render_analysis_table(match_dict, table_data)

    target_path = f"analysis_cache/analysis_{match_id}.webp"
    os.makedirs("analysis_cache", exist_ok=True)
    shutil.copy(temp_png, target_path)

    try:
        os.remove(temp_png)
    except Exception:
        pass

    if not os.path.exists(target_path):
        raise RuntimeError(f"Файл таблицы не создан: {target_path}")

    match_dict['analysis_png_path'] = target_path
    database.update_match_analysis(
        match_id,
        match_dict.get('analysis_text', ''),
        target_path
    )
    return target_path, enriched_data


async def handle_show_table(
    query, context, user_id, match_id,
    callback_suffix: str = '', back_callback_data: str = 'back'
):
    """Показывает таблицу анализа отдельным экраном."""
    # Удаляем сообщения предыдущего треда (на случай повторного нажатия «Таблица»)
    thread = context.user_data.pop('analysis_thread', None)
    if thread:
        bot = query.message.get_bot()
        chat_id = query.message.chat_id
        for mid in thread.get('related_message_ids', []):
            try:
                await bot.delete_message(chat_id=chat_id, message_id=mid)
            except Exception:
                pass

    match_dict = await _load_match_for_analysis(query, user_id, match_id)
    if not match_dict:
        return

    team1 = match_dict.get('team1', '?')
    team2 = match_dict.get('team2', '?')
    logger.info(f"[TABLE] Запрос таблицы для {team1} vs {team2} (match_id={match_id})")

    # Если пользователь уже на фото-экране таблицы и снова нажал «Таблица»,
    # ничего не делаем, чтобы не засорять чат промежуточными сообщениями.
    if getattr(query.message, 'photo', None):
        logger.info(f"[TABLE] Фото уже открыто, пропускаем повторную отрисовку (match_id={match_id})")
        return

    await safe_edit_message(query, "⏳ Подготавливаем таблицу анализа...", None)

    try:
        t0 = time.time()
        png_path, _ = _ensure_analysis_table_png(match_id, match_dict)
        elapsed = time.time() - t0
        logger.info(f"[TABLE] Таблица готова за {elapsed:.1f}с — {png_path}")
    except Exception as e:
        logger.error(f"[TABLE] Ошибка подготовки таблицы: {e}", exc_info=True)
        await handle_show_text_analysis(
            query, context, user_id, match_id,
            callback_suffix=callback_suffix,
            back_callback_data=back_callback_data
        )
        return

    try:
        chat_id = query.message.chat_id
        bot = query.message.get_bot()
        related_message_ids = []

        with open(png_path, 'rb') as photo:
            sent_photo = await bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                reply_markup=keyboards.analysis_view_keyboard(
                    match_id=match_id,
                    back_callback_data=back_callback_data,
                    callback_suffix=callback_suffix
                )
            )
            related_message_ids.append(sent_photo.message_id)

        _remember_analysis_thread(
            context,
            conclusion_message_id=sent_photo.message_id,
            related_message_ids=related_message_ids
        )

        try:
            await query.message.delete()
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Ошибка отправки таблицы: {e}", exc_info=True)
        await safe_edit_message(
            query,
            "❌ Не удалось показать таблицу. Попробуйте снова.",
            keyboards.analysis_view_keyboard(
                match_id=match_id,
                back_callback_data=back_callback_data,
                callback_suffix=callback_suffix
            )
        )


async def handle_show_text_analysis(
    query, context, user_id, match_id,
    callback_suffix: str = '', back_callback_data: str = 'back'
):
    """Показывает текстовый анализ отдельным экраном."""
    # Удаляем фото от предыдущего просмотра таблицы (если было переключение)
    thread = context.user_data.pop('analysis_thread', None)
    if thread:
        bot = query.message.get_bot()
        chat_id = query.message.chat_id
        for mid in thread.get('related_message_ids', []):
            try:
                await bot.delete_message(chat_id=chat_id, message_id=mid)
            except Exception:
                pass

    match_dict = await _load_match_for_analysis(query, user_id, match_id)
    if not match_dict:
        return

    team1 = match_dict.get('team1', 'Команда 1')
    team2 = match_dict.get('team2', 'Команда 2')
    logger.info(f"[TEXT] Запрос текстового анализа для {team1} vs {team2} (match_id={match_id})")

    analysis_text = (match_dict.get('analysis_text') or '').strip()
    enriched_data = None
    if not analysis_text:
        logger.info("[TEXT] Текст в БД отсутствует, запускаем генерацию...")
        await safe_edit_message(
            query,
            "⏳ Генерируем текстовый анализ...\n\nЭто может занять 30-60 секунд.",
            None
        )
        try:
            enriched_data = _fetch_enriched_data(match_dict)
            analysis_text, _ = await _ensure_analysis_text(
                match_id, match_dict, enriched_data=enriched_data
            )
        except Exception as e:
            logger.error(f"[TEXT] Ошибка генерации текстового анализа: {e}", exc_info=True)
            analysis_text = "❌ Текстовый анализ временно недоступен. Попробуйте позже."
    else:
        logger.info(
            f"[TEXT] Текст загружен из БД ({len(analysis_text)} символов)"
        )
    date_str = match_dict.get('match_date', '')
    time_str = match_dict.get('match_time', '')

    header = (
        f"<b>📝 Текстовый анализ</b>\n\n"
        f"<b>{team1} vs {team2}</b>\n"
        f"{date_str} {time_str} МСК\n\n"
    )
    text = (header + markdown_to_html(analysis_text)).strip()

    await safe_edit_message(
        query,
        text,
        keyboards.analysis_view_keyboard(
            match_id=match_id,
            back_callback_data=back_callback_data,
            callback_suffix=callback_suffix
        ),
        parse_mode='HTML'
    )


async def handle_show_analysis(query, context, user_id, match_id):
    """Back compatibility: старый сценарий ведём на экран таблицы."""
    await handle_show_table(query, context, user_id, match_id)


async def handle_my_analysis(update: Update, query, user_id):
    """Обработка кнопки 'Мои анализы'"""
    # Получаем все купленные матчи
    purchased_matches = database.get_purchased_matches_by_user(user_id)
    if not purchased_matches:
        text = "📭 <b>У вас пока нет купленных анализов</b>\n\n"
        text += "Выберите спорт в главном меню, чтобы приобрести анализы матчей."
        keyboard = [
            [InlineKeyboardButton("◀️ Назад", callback_data='back')],
            [InlineKeyboardButton("🏠 В главное меню",
                                  callback_data='back_to_menu')]
        ]
        await safe_edit_message(
            query,
            text,
            InlineKeyboardMarkup(keyboard)
        )
        return
    # Группируем по видам спорта
    sports_with_counts = {}
    for match in purchased_matches:
        sport = match['sport']
        sports_with_counts[sport] = sports_with_counts.get(sport, 0) + 1
    text = "📊 <b>ВАШИ КУПЛЕННЫЕ АНАЛИЗЫ</b>\n\n"
    text += f"Всего анализов: {len(purchased_matches)}\n\n"
    text += "👇 <b>Выберите вид спорта для просмотра:</b>\n"
    await safe_edit_message(
        query,
        text,
        keyboards.purchased_sports_keyboard(sports_with_counts)
    )


async def handle_purchased_sport(query, user_id, sport):
    """Обработка выбора спорта для купленных анализов"""
    sport_names = {'football': '⚽ Футбол', 'basketball': '🏀 Баскетбол',
                   'hockey': '🏒 Хоккей'}
    sport_display = sport_names.get(sport, sport)
    # Получаем даты купленных матчей по этому спорту
    dates = database.get_purchased_dates_by_sport(user_id, sport)
    if not dates:
        text = f"📭 *{sport_display}*\n\n"
        text += "У вас нет купленных анализов по этому виду спорта."
        keyboard = [
            [InlineKeyboardButton("◀️ Назад", callback_data='back')],
            [InlineKeyboardButton("🏠 В главное меню",
                                  callback_data='back_to_menu')]
        ]
        await safe_edit_message(
            query,
            text,
            InlineKeyboardMarkup(keyboard)
        )
        return
    text = f"📅 *{sport_display} - ВЫБЕРИТЕ ДАТУ*\n\n"
    text += f"Всего дат с анализами: {len(dates)}\n\n"
    await safe_edit_message(
        query,
        text,
        keyboards.purchased_dates_keyboard_with_back(dates, sport)
    )


async def handle_purchased_sport_back(query, user_id, sport):
    """Возврат к выбору даты для купленного спорта"""
    await handle_purchased_sport(query, user_id, sport)


async def handle_purchased_date(query, user_id, sport, date_str):
    """Обработка выбора даты для купленных анализов"""
    sport_names = {'football': '⚽ Футбол', 'basketball': '🏀 Баскетбол',
                   'hockey': '🏒 Хоккей'}
    sport_display = sport_names.get(sport, sport)
    # Получаем матчи на эту дату
    matches = database.get_purchased_matches_by_sport(user_id, sport)
    # Фильтруем по дате
    date_matches = [m for m in matches if m['match_date'] == date_str]
    if not date_matches:
        text = f"📭 *{sport_display} - {date_str}*\n\n"
        text += "На эту дату нет купленных анализов."
        keyboard = [
            [InlineKeyboardButton("◀️ Назад",
                                  callback_data='back')],
            [InlineKeyboardButton("🏠 В главное меню",
                                  callback_data='back_to_menu')]
        ]
        await safe_edit_message(
            query,
            text,
            InlineKeyboardMarkup(keyboard)
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
    text = f"{sport_display} <b>Матчи на {date_label}:</b>\n\n"
    for match in date_matches:
        text += f"• {match['team1']} vs {match['team2']} ({match['match_time']})\n"
    text += "\n👇 <b>Выберите матч для просмотра анализа:</b>"
    # Создаем клавиатуру с матчами
    keyboard = []
    for match in date_matches:
        button_text = f"{match['team1']} vs {match['team2']} ({match['match_time']})"
        callback_data = f"match_{match['id']}"
        keyboard.append([InlineKeyboardButton(button_text,
                                              callback_data=callback_data)])
    keyboard.append([InlineKeyboardButton(
        "◀️ Назад", callback_data='back')])
    keyboard.append([InlineKeyboardButton("🏠 В главное меню",
                                          callback_data='back_to_menu')])
    await safe_edit_message(
        query,
        text,
        InlineKeyboardMarkup(keyboard)
    )


async def admin_clean_purchases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Админ команда для очистки таблицы purchases.

    Usage:
        /clean_purchases pending - удалить только pending покупки
        /clean_purchases expired - удалить истекшие pending покупки (>30 мин)
        /clean_purchases all - удалить все покупки (осторожно!)
    """
    user_id = update.effective_user.id

    # Проверка прав админа
    if not database.is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав администратора")
        return

    # Парсинг аргументов
    args = context.args
    if not args:
        text = (
            "📋 Использование:\n\n"
            "/clean_purchases pending - удалить pending покупки\n"
            "/clean_purchases expired - удалить истекшие (>30 мин)\n"
            "/clean_purchases all - удалить ВСЕ покупки ⚠️"
        )
        await update.message.reply_text(text)
        return

    mode = args[0].lower()

    conn = database.get_db_connection()
    cursor = conn.cursor()

    if mode == 'pending':
        # Удалить все pending покупки
        cursor.execute('SELECT COUNT(*) FROM purchases WHERE status = "pending"')
        count_before = cursor.fetchone()[0]

        cursor.execute('DELETE FROM purchases WHERE status = "pending"')
        conn.commit()

        text = f"✅ Удалено pending покупок: {count_before}"
        logger.info(f"Admin {user_id} удалил {count_before} pending покупок")

    elif mode == 'expired':
        # Удалить истекшие pending покупки (expires_at < now)
        from datetime import datetime
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        cursor.execute('''
            SELECT COUNT(*) FROM purchases
            WHERE status = "pending" AND expires_at < ?
        ''', (now,))
        count_before = cursor.fetchone()[0]

        cursor.execute('''
            DELETE FROM purchases
            WHERE status = "pending" AND expires_at < ?
        ''', (now,))
        conn.commit()

        text = f"✅ Удалено истекших покупок: {count_before}"
        logger.info(f"Admin {user_id} удалил {count_before} истекших покупок")

    elif mode == 'all':
        # Удалить ВСЕ покупки (опасно!)
        cursor.execute('SELECT COUNT(*) FROM purchases')
        count_before = cursor.fetchone()[0]

        cursor.execute('DELETE FROM purchases')
        conn.commit()

        text = f"⚠️ УДАЛЕНО ВСЕХ ПОКУПОК: {count_before}\n\nЭто необратимо!"
        logger.warning(f"Admin {user_id} удалил ВСЕ покупки ({count_before} шт)")

    else:
        text = f"❌ Неизвестный режим: {mode}\n\nИспользуйте: pending, expired или all"
        conn.close()
        await update.message.reply_text(text)
        return

    conn.close()
    await update.message.reply_text(text)


async def handle_check_topup(query, user_id, token, context):
    """
    Ручная проверка оплаты через DA API.

    Вызывается кнопкой «Проверить оплату» если листенер был недоступен.
    Запрашивает последние донаты DA и ищет совпадение по token.
    Засчитывает полный amount_rub даже если DA удержала комиссию.
    """
    import re
    import requests as http_requests
    from config import DA_ACCESS_TOKEN, DA_PROFILE_URL

    # Проверяем, не обработан ли уже этот токен
    topup = database.get_any_topup_by_token(token)
    if not topup:
        await safe_edit_message(
            query,
            "❌ Код пополнения не найден. Возможно, срок действия истёк.\n\n"
            "Вернитесь в меню и создайте новый запрос.",
            keyboards.main_menu_keyboard()
        )
        return

    if topup['status'] == 'paid':
        balance = database.get_user_balance(user_id)
        await safe_edit_message(
            query,
            f"✅ <b>Оплата уже зачтена!</b>\n\n"
            f"У вас: <b>{balance}</b> 💎",
            _build_post_topup_keyboard(context),
            parse_mode='HTML'
        )
        return

    # Показываем "Проверяем..."
    await safe_edit_message(
        query,
        "🔄 <b>Проверяем оплату в DonationAlerts...</b>\n\n"
        "Это займёт несколько секунд.",
        None,
        parse_mode='HTML'
    )

    # Запрашиваем последние донаты DA API
    try:
        headers = {'Authorization': f'Bearer {DA_ACCESS_TOKEN}'}
        response = http_requests.get(
            'https://www.donationalerts.com/api/v1/alerts/donations?limit=30',
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        donations = response.json().get('data', [])
    except Exception as e:
        logger.error(f"Ошибка запроса DA API при check_topup: {e}")
        keyboard = [
            [InlineKeyboardButton("🔄 Попробовать ещё раз",
                                  callback_data=f'check_topup_{token}')],
            [InlineKeyboardButton("✅ Перейти к оплате", url=DA_PROFILE_URL)],
            [InlineKeyboardButton("🏠 В главное меню",
                                  callback_data='back_to_menu')]
        ]
        await safe_edit_message(
            query,
            "❌ <b>Не удалось связаться с DonationAlerts</b>\n\n"
            "Попробуйте ещё раз через минуту или обратитесь в поддержку.",
            InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
        return

    # Ищем донат с нашим токеном
    found_donation = None
    for donation in donations:
        msg = donation.get('message', '') or ''
        match = re.search(r'\b([A-Z0-9]{12})\b', msg.upper())
        if match and match.group(1) == token.upper():
            found_donation = donation
            break

    if not found_donation:
        keyboard = [
            [InlineKeyboardButton("🔄 Проверить ещё раз",
                                  callback_data=f'find_topup_by_amount_{token}')],
            [InlineKeyboardButton("✅ Перейти к оплате", url=DA_PROFILE_URL)],
            [InlineKeyboardButton("🏠 В главное меню",
                                  callback_data='back_to_menu')]
        ]
        await safe_edit_message(
            query,
            "⏳ <b>Оплата пока не найдена</b>\n\n"
            "Если вы уже отправили донат — подождите 1-2 минуты "
            "и нажмите «Проверить ещё раз».\n\n"
            "Если проблема повторяется — обратитесь в поддержку.",
            InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
        return

    # Найден — проверяем сумму с допуском 15% на комиссию
    received_kopeks = int(float(str(found_donation['amount'])) * 100)
    expected_kopeks = topup['amount_kopeks']
    min_acceptable = int(expected_kopeks * 0.85)

    if received_kopeks < min_acceptable:
        received_rub = received_kopeks / 100
        amount_rub = topup['amount_rub']
        keyboard = [
            [InlineKeyboardButton("✅ Перейти к оплате", url=DA_PROFILE_URL)],
            [InlineKeyboardButton("🏠 В главное меню",
                                  callback_data='back_to_menu')]
        ]
        await safe_edit_message(
            query,
            f"❌ <b>Недостаточная сумма</b>\n\n"
            f"Получено: <b>{received_rub:.2f}</b> 💎\n"
            f"Требуется: <b>{amount_rub}</b> 💎 "
            f"(с учётом комиссии: от {min_acceptable / 100:.2f} 💎)\n\n"
            "Пожалуйста, отправьте донат на полную сумму с тем же кодом.",
            InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
        return

    # Всё хорошо — засчитываем полный amount_rub (без вычета комиссии)
    donation_id = str(found_donation['id'])
    ok = database.complete_balance_topup(topup['id'], donation_id)
    if not ok:
        await safe_edit_message(
            query,
            "❌ Ошибка зачисления баланса. Обратитесь в поддержку.",
            keyboards.main_menu_keyboard()
        )
        return

    new_balance = database.get_user_balance(user_id)
    amount_rub = topup['amount_rub']
    analyses_word = (
        "анализ" if amount_rub == 1
        else "анализа" if 2 <= amount_rub <= 4
        else "анализов"
    )
    await safe_edit_message(
        query,
        f"✅ <b>Баланс пополнен!</b>\n\n"
        f"💰 Пополнено: <b>+{amount_rub}</b> 💎 ({amount_rub} {analyses_word})\n"
        f"У вас: <b>{new_balance}</b> 💎\n\n"
        "Выберите матч для покупки анализа!",
        _build_post_topup_keyboard(context),
        parse_mode='HTML'
    )
    logger.info(
        f"✅ [check_topup] Баланс user={user_id} пополнен на {amount_rub} руб. "
        f"через ручную проверку. donation_id={donation_id}"
    )


async def handle_find_topup_by_amount(query, user_id, token, context):
    """
    Поиск доната по сумме для случая, когда пользователь нажал кнопку
    «Не вставил код». Token уже известен из callback_data — ищем
    подходящий незасчитанный донат в последних 30 записях DA.
    """
    import requests as http_requests
    from config import DA_ACCESS_TOKEN, DA_PROFILE_URL, SUPPORT_USERNAME

    topup = database.get_any_topup_by_token(token)
    if not topup:
        await safe_edit_message(
            query,
            "❌ Код пополнения не найден. Возможно, срок действия истёк.\n\n"
            "Создайте новый запрос через «Пополнить баланс».",
            keyboards.main_menu_keyboard()
        )
        return

    if topup['status'] == 'paid':
        balance = database.get_user_balance(user_id)
        await safe_edit_message(
            query,
            f"✅ <b>Оплата уже зачтена!</b>\n\n"
            f"У вас: <b>{balance}</b> 💎",
            _build_post_topup_keyboard(context),
            parse_mode='HTML'
        )
        return

    await safe_edit_message(
        query,
        "🔍 <b>Ищем ваш донат в DonationAlerts...</b>",
        None,
        parse_mode='HTML'
    )

    try:
        headers = {'Authorization': f'Bearer {DA_ACCESS_TOKEN}'}
        response = http_requests.get(
            'https://www.donationalerts.com/api/v1/alerts/donations?limit=30',
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        donations = response.json().get('data', [])
    except Exception as e:
        logger.error(f"Ошибка DA API при find_topup_by_amount: {e}")
        keyboard = [
            [InlineKeyboardButton("🔄 Попробовать ещё раз",
                                  callback_data=f'find_topup_by_amount_{token}')],
            [InlineKeyboardButton("🏠 В главное меню",
                                  callback_data='back_to_menu')]
        ]
        await safe_edit_message(
            query,
            "❌ <b>Не удалось связаться с DonationAlerts</b>\n\nПопробуйте позже.",
            InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
        return

    # Ищем кандидатов только в окне конкретного topup:
    # [created_at .. expires_at + 10 минут].
    try:
        topup_created_dt = datetime.strptime(
            str(topup['created_at'])[:19], '%Y-%m-%d %H:%M:%S'
        )
        topup_deadline_dt = datetime.strptime(
            str(topup['expires_at'])[:19], '%Y-%m-%d %H:%M:%S'
        ) + timedelta(minutes=10)
    except Exception:
        logger.error(
            "Не удалось распарсить окно topup для find_topup_by_amount: "
            f"token={token}, created_at={topup['created_at']}, expires_at={topup['expires_at']}"
        )
        await safe_edit_message(
            query,
            "❌ <b>Не удалось выполнить безопасную проверку</b>\n\n"
            "Пожалуйста, создайте новый запрос на пополнение и повторите оплату с кодом.",
            keyboards.main_menu_keyboard(),
            parse_mode='HTML'
        )
        return

    candidates = []
    for donation in donations:
        donation_id = str(donation.get('id', ''))
        received_kopeks = int(float(str(donation.get('amount', 0))) * 100)
        if received_kopeks <= 0:
            continue

        # Фильтрация по времени доната.
        created_at_str = donation.get('created_at', '')
        if not created_at_str:
            continue
        try:
            donation_dt = datetime.strptime(created_at_str[:19], '%Y-%m-%d %H:%M:%S')
        except Exception:
            continue

        if donation_dt < topup_created_dt or donation_dt > topup_deadline_dt:
            continue

        # Пропускаем донаты, уже связанные с каким-либо токеном
        if not donation_id or database.is_donation_event_used(donation_id):
            continue

        candidates.append((donation_dt, donation))

    if not candidates:
        keyboard = [
            [InlineKeyboardButton("🔄 Проверить ещё раз",
                                  callback_data=f'find_topup_by_amount_{token}')],
            [InlineKeyboardButton("✅ Перейти к оплате", url=DA_PROFILE_URL)],
            [InlineKeyboardButton("🏠 В главное меню",
                                  callback_data='back_to_menu')]
        ]
        support_text = f"@{SUPPORT_USERNAME}" if SUPPORT_USERNAME else "поддержку"
        await safe_edit_message(
            query,
            "⏳ <b>Незасчитанный донат не найден</b>\n\n"
            "Мы проверяем только безопасное окно вашего запроса пополнения.\n"
            "Если платёж был без кода и не найден — обратитесь в "
            f"{support_text} с суммой и временем доната.",
            InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
        return

    if len(candidates) > 1:
        keyboard = [
            [InlineKeyboardButton("🔄 Проверить ещё раз",
                                  callback_data=f'find_topup_by_amount_{token}')],
            [InlineKeyboardButton("🏠 В главное меню",
                                  callback_data='back_to_menu')]
        ]
        support_text = f"@{SUPPORT_USERNAME}" if SUPPORT_USERNAME else "поддержку"
        await safe_edit_message(
            query,
            "⚠️ <b>Найдено несколько возможных донатов</b>\n\n"
            "Для безопасности автозачёт отключён, чтобы не зачислить чужой платёж.\n"
            f"Напишите в {support_text} и укажите сумму/время доната и ваш код.",
            InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
        logger.warning(
            f"[find_by_amount] Найдено несколько кандидатов: token={token}, count={len(candidates)}"
        )
        return

    # Кандидат ровно один — можно безопасно зачислить.
    _, best = candidates[0]
    donation_id = str(best['id'])
    received_rub = int(float(str(best['amount'])))  # целые рубли

    ok = database.complete_balance_topup(topup['id'], donation_id, received_rub)
    if not ok:
        await safe_edit_message(
            query,
            "❌ Ошибка зачисления баланса. Обратитесь в поддержку.",
            keyboards.main_menu_keyboard()
        )
        return

    new_balance = database.get_user_balance(user_id)
    analyses_word = (
        "анализ" if received_rub == 1
        else "анализа" if 2 <= received_rub <= 4
        else "анализов"
    )
    logger.info(
        f"✅ [find_by_amount] Баланс user={user_id} пополнен на {received_rub} руб. "
        f"donation_id={donation_id}"
    )
    await safe_edit_message(
        query,
        f"✅ <b>Баланс пополнен!</b>\n\n"
        f"💰 Пополнено: <b>+{received_rub}</b> 💎 ({received_rub} {analyses_word})\n"
        f"У вас: <b>{new_balance}</b> 💎\n\n"
        "Донат найден и успешно засчитан!\n"
        "В следующий раз указывайте код в комментарии к донату.",
        _build_post_topup_keyboard(context),
        parse_mode='HTML'
    )


async def _show_deposit_payment_screen(query, context, user_id, token):
    """Шаг 2: текущий UX оплаты (после подтверждения копирования кода)."""
    from config import DA_PROFILE_URL

    topup = database.get_topup_by_token(token)
    if not topup or topup['user_id'] != user_id:
        await safe_edit_message(
            query,
            "❌ Код пополнения не найден или истёк.\n\n"
            "Вернитесь в меню и создайте новый запрос.",
            keyboards.main_menu_keyboard()
        )
        return

    from config import ANALYSIS_PRICE_RUB
    balance = database.get_user_balance(user_id)
    price = int(ANALYSIS_PRICE_RUB)
    text = (
        "💰 <b>ПОПОЛНЕНИЕ БАЛАНСА</b>\n\n"
        f"У вас: <b>{balance}</b> 💎\n\n"
        "📋 <b>Инструкция:</b>\n"
        f"1️⃣ Скопируйте код: <code>{token}</code>\n"
        "2️⃣ Нажмите «Перейти к оплате»\n"
        "3️⃣ Отправьте донат на любую сумму в рублях\n"
        "4️⃣ ‼️ Вставьте код в поле <b>«Комментарий»</b>\n"
        "5️⃣ Нажмите «Проверить баланс»\n\n"
        f"✅ 1 анализ = {price} 💎\n"
        "💱 1 руб. = 1 💎"
    )
    keyboard = [
        [InlineKeyboardButton("✅ Перейти к оплате", url=DA_PROFILE_URL)],
        [InlineKeyboardButton("🔄 Проверить баланс",
                              callback_data=f'check_balance_{token}')],
        [InlineKeyboardButton("🏠 В главное меню",
                              callback_data='back_to_menu')]
    ]
    bot = query.message.get_bot()
    chat_id = query.message.chat_id

    # Сначала отправляем 2 скриншота ШАГ_1 и ШАГ_2 (если файлы есть).
    base_dir = Path(__file__).resolve().parent
    step_images = [
        ("ШАГ 1", base_dir / 'assets' / 'STEP_1.png'),
        ("ШАГ 2", base_dir / 'assets' / 'STEP_2.png'),
    ]
    for caption, image_path in step_images:
        if not image_path.exists():
            logger.warning(f"Файл скриншота не найден: {image_path}")
            continue
        try:
            with image_path.open('rb') as image_file:
                sent_photo = await bot.send_photo(
                    chat_id=chat_id,
                    photo=image_file,
                    caption=caption
                )
                context.user_data.setdefault('topup_step_image_ids', []).append(
                    sent_photo.message_id
                )
        except Exception as e:
            logger.warning(f"Не удалось отправить скриншот {image_path}: {e}")

    # Затем отправляем привычный текст/кнопки отдельным сообщением.
    sent_message = await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

    # Удаляем прошлое сообщение с чекбоксом, чтобы порядок в чате был правильный.
    try:
        await query.message.delete()
    except Exception:
        pass

    # Сохраняем message_id нового сообщения для редактирования при зачислении.
    database.update_topup_instruction_message(token, sent_message.message_id)


async def handle_confirm_code_copy(query, context, user_id, token):
    """Переход на шаг оплаты после чекбокса «Я скопировал код»."""
    await _show_deposit_payment_screen(query, context, user_id, token)


async def handle_deposit_menu(query, context, user_id):
    """
    Пополнение баланса: показывает уникальный код, который нужно вставить
    в комментарий доната на DonationAlerts.

    Если у пользователя есть действующий pending топап — показывает тот же
    код, чтобы он не потерял его при повторном входе в меню.
    Новый токен создаётся только если старый истёк или отсутствует.
    """
    existing = database.get_pending_topup_by_user(user_id)
    if existing:
        token = existing['token']
    else:
        token = database.create_balance_topup(user_id, amount_rub=0)

    return_match_id = context.user_data.get('post_topup_match_id')
    return_match_source = context.user_data.get('post_topup_match_source', 'browse')
    database.update_topup_return_target(
        token,
        match_id=return_match_id,
        match_source=return_match_source
    )

    balance = database.get_user_balance(user_id)
    top_pointer_line = "👇👇👇👇👇"
    bottom_pointer_line = "☝️☝️☝️☝️☝️"
    code_lines = (
        f"<code>{token}</code>\n"
        f"<code>{token}</code>\n"
        f"<code>{token}</code>"
    )

    text = (
        "💰 <b>ПОПОЛНЕНИЕ БАЛАНСА</b>\n\n"
        f"У вас: <b>{balance}</b> 💎\n\n"
        "━━━━━━━━━━━━━━━━━\n\n"
        "⚠️ <b>ШАГ 1: СКОПИРУЙТЕ ВАШ КОД</b>\n"
        "⚠️ <b>ШАГ 2: ВСТАВЬТЕ В КОММЕНТАРИИ К ДОНАТУ</b>\n\n"
        f"{top_pointer_line}\n{code_lines}\n{bottom_pointer_line}\n\n"
        "<b>⚠️ НЕ СКОПИРОВАЛ КОД — 💎 НЕ ЗАЧИСЛЯТСЯ ⚠️</b>\n"
        "<i>Код действует 30 минут.</i>\n\n"
        "После копирования нажмите кнопку ниже."
    )
    keyboard = [
        [InlineKeyboardButton("Я СКОПИРОВАЛ КОД",
                              callback_data=f'confirm_code_copy_{token}')],
        [InlineKeyboardButton("🏠 В главное меню",
                              callback_data='back_to_menu')]
    ]
    await safe_edit_message(
        query, text, InlineKeyboardMarkup(keyboard), parse_mode='HTML'
    )


def _build_how_it_works_pages() -> list[str]:
    """Возвращает список страниц раздела «Как это работает»."""
    return [
        # 1. Общие сведения
        (
            "♣ Ваш выбор — начало персональной аналитики.\n\n"
            "Выбираете вид спорта, дату и матч — бот собирает данные и "
            "готовит структурированный разбор под конкретную игру.\n\n"
            "☰ Как это выглядит на практике:\n\n"
            "• <i>Шаг 1: выбираете спорт (футбол, баскетбол или хоккей).</i>\n"
            "• <i>Шаг 2: выбираете дату и нужный матч.</i>\n"
            "• <i>Шаг 3: получаете анализ в формате карточки и текста.</i>\n\n"
            "☰ Важно:\n\n"
            "• <i>Мы не даём советы по ставкам и коэффициентам.</i>\n"
            "• <i>Только факты, контекст и аналитический вывод по данным.</i>\n"
            "• <i>Купленные материалы сохраняются в разделе «Мои анализы».</i>\n\n"
            "Дальше покажем, что именно бот собирает и как считает итог. 💠"
        ),
        # 2. БД
        (
            "🗂 После выбора матча бот запускает сбор данных.\n\n"
            "☰ Что собираем из источников и БД:\n\n"
            "• <i>Турнирное положение команд и общую форму.</i>\n"
            "• <i>Личные встречи (H2H) и динамику последних матчей.</i>\n"
            "• <i>Статистику по ключевым метрикам, доступным в источнике.</i>\n"
            "• <i>Контекст матча: дата, время, лига, участники.</i>\n\n"
            "☰ Как это устроено в боте:\n\n"
            "• <i>Матчи подгружаются автоматически планировщиком.</i>\n"
            "• <i>Витрина показывает ближайшие события без ручного обновления.</i>\n"
            "• <i>Перед выдачей анализ строится только по фактически найденным данным.</i>\n\n"
            "Итог: сначала база и проверка контекста, потом передача в ИИ."
        ),
        # 3. ИИ
        (
            "⌘ Как работает ИИ с предоставленными данными?\n\n"
            "Модель выступает как спортивный аналитик: принимает собранный "
            "контекст матча и строит вывод на цифрах, а не на эмоциях.\n\n"
            "☰ Что делает ИИ:\n\n"
            "• <i>Сопоставляет форму команд и очные встречи.</i>\n"
            "• <i>Находит сильные и слабые зоны по статистике.</i>\n"
            "• <i>Учитывает турнирную ситуацию и плотность календаря.</i>\n"
            "• <i>Формирует итоговый аналитический вывод.</i>\n\n"
            "☰ В каком виде получаете результат:\n\n"
            "• <i>Карточка-таблица для быстрого чтения.</i>\n"
            "• <i>Текстовый разбор с пояснениями.</i>\n\n"
            "Без магии: сначала данные, потом модель, потом понятный результат."
        ),
        # 4. Открыты для предложений
        (
            "⇆ Мы развиваем бота и открыты к вашим предложениям.\n\n"
            "Сервис живой: регулярно улучшаем качество анализа, "
            "обработку данных и удобство навигации в меню.\n\n"
            "☰ Что дорабатываем постоянно:\n\n"
            "• <i>Качество и полноту данных по матчам.</i>\n"
            "• <i>Формат карточек и текстовых объяснений.</i>\n"
            "• <i>Скорость генерации и стабильность выдачи.</i>\n"
            "• <i>Новые сценарии меню и полезные функции.</i>\n\n"
            "☰ Если есть идеи:\n\n"
            "• <i>Напишите в техподдержку прямо из главного меню.</i>\n"
            "• <i>Все конструктивные предложения рассматриваются и учитываются.</i>\n\n"
            "Бот развивается постоянно: приоритет — точность данных и удобство использования."
        ),
        # 5. Цель
        (
            "❖ <b>Миссия BetWise</b>\n\n"
            "Сделать спортивную аналитику доступной и понятной: "
            "чтобы пользователь быстро получал контекст матча и принимал решения на фактах.\n\n"
            "☰ Зачем создан проект:\n\n"
            "• <i>Сократить время на самостоятельный сбор информации по матчу.</i>\n"
            "• <i>Собрать ключевые данные в одном месте и в едином формате.</i>\n"
            "• <i>Дать понятный аналитический вывод без информационного шума.</i>\n\n"
            "☰ Какую пользу получает пользователь:\n\n"
            "• <i>Быстрый доступ к структурированному разбору матча.</i>\n"
            "• <i>Прозрачную логику анализа на базе статистики и контекста.</i>\n"
            "• <i>Удобный доступ к купленным материалам в разделе «Мои анализы».</i>\n\n"
            "Если возникнут вопросы или предложения, используйте кнопку «Техподдержка»."
        ),
    ]


def _how_it_works_keyboard(page: int, total: int) -> InlineKeyboardMarkup:
    """Клавиатура пагинации для раздела «Как это работает»."""
    prev_callback = f"hiw_page_{page - 1}" if page > 0 else "noop"
    next_callback = f"hiw_page_{page + 1}" if page < total - 1 else "noop"
    nav_buttons = [
        InlineKeyboardButton("Пред.", callback_data=prev_callback),
        InlineKeyboardButton(f"{page + 1} из {total}", callback_data="noop"),
        InlineKeyboardButton("След.", callback_data=next_callback),
    ]
    return InlineKeyboardMarkup([
        nav_buttons,
        [InlineKeyboardButton("◀️ Назад", callback_data='go_back')]
    ])


def _how_it_works_image_path() -> Path | None:
    """Возвращает путь до image.png для экрана «Как это работает», если файл существует."""
    base_dir = Path(__file__).resolve().parent
    candidates = [
        base_dir / 'assets' / 'image.png',
        base_dir / 'image.png',
    ]
    for image_path in candidates:
        if image_path.exists():
            return image_path
    return None


async def _render_how_it_works_page(query, text: str, keyboard: InlineKeyboardMarkup):
    """
    Рендер экрана «Как это работает».
    Если image.png найден — показываем фото с подписью и клавиатурой.
    Иначе используем стандартный текстовый режим.
    """
    image_path = _how_it_works_image_path()
    if not image_path or len(text) > 1024:
        await safe_edit_message(query, text, keyboard, parse_mode='HTML')
        return

    bot = query.message.get_bot()
    chat_id = query.message.chat_id

    # Если уже на фото-сообщении, обновляем только подпись/кнопки.
    if getattr(query.message, 'photo', None):
        try:
            await query.edit_message_caption(
                caption=text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            return
        except Exception as e:
            if "Message is not modified" not in str(e):
                logger.warning("Не удалось обновить подпись how_it_works: %s", e)

    # Если текущее сообщение не фото — создаём новое фото-сообщение и удаляем старое.
    try:
        with image_path.open('rb') as image_file:
            await bot.send_photo(
                chat_id=chat_id,
                photo=image_file,
                caption=text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
        try:
            await query.message.delete()
        except Exception:
            pass
    except Exception as e:
        logger.warning("Не удалось отправить image.png для how_it_works: %s", e)
        await safe_edit_message(query, text, keyboard, parse_mode='HTML')


async def handle_how_it_works(query, page: int = 0):
    """Экран «Как это работает» — информационная брошюра с пагинацией."""
    pages = _build_how_it_works_pages()
    total = len(pages)
    page = max(0, min(page, total - 1))
    text = pages[page]
    keyboard = _how_it_works_keyboard(page, total)
    await _render_how_it_works_page(query, text, keyboard)


async def handle_support(query):
    """Экран техподдержки."""
    from config import SUPPORT_USERNAME

    username = (SUPPORT_USERNAME or '').strip().lstrip('@')
    if username:
        support_text = f"@{username}"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data='go_back')]
        ])
        text = (
            "🎧 <b>Техподдержка</b>\n\n"
            f"Если возникли вопросы или проблемы, напишите в {support_text}."
        )
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data='go_back')]
        ])
        text = (
            "🎧 <b>Техподдержка</b>\n\n"
            "Контакт поддержки пока не настроен.\n"
            "Напишите администратору бота."
        )

    await safe_edit_message(
        query,
        text,
        keyboard,
        parse_mode='HTML'
    )


async def handle_check_balance_status(query, user_id, token, context):
    """
    Проверка: был ли засчитан донат с данным токеном.

    Слушатель (WebSocket/polling) сам обрабатывает входящие донаты и
    меняет статус на 'paid'. Эта функция просто смотрит в БД.
    Если донат ещё не зачтен — предлагает подождать или обратиться в поддержку.
    """
    from config import DA_PROFILE_URL

    topup = database.get_any_topup_by_token(token)
    if not topup:
        await safe_edit_message(
            query,
            "❌ <b>Код не найден</b>\n\n"
            "Возможно, срок действия кода истёк.\n"
            "Вернитесь в меню и создайте новый запрос.",
            keyboards.main_menu_keyboard(),
            parse_mode='HTML'
        )
        return

    if topup['status'] == 'paid':
        balance = database.get_user_balance(user_id)
        credited = topup['amount_rub']
        analyses_word = (
            "анализ" if credited == 1
            else "анализа" if 2 <= credited <= 4
            else "анализов"
        )
        await safe_edit_message(
            query,
            f"✅ <b>Баланс пополнен!</b>\n\n"
            f"💰 Зачислено: <b>+{credited}</b> 💎 ({credited} {analyses_word})\n"
            f"У вас: <b>{balance}</b> 💎\n\n"
            "Выберите матч для приобретения анализа!",
            _build_post_topup_keyboard(context),
            parse_mode='HTML'
        )
        return

    # Статус pending — ещё не зачтено
    from config import SUPPORT_USERNAME
    support_text = (
        f"@{SUPPORT_USERNAME}" if SUPPORT_USERNAME else "администратора"
    )
    keyboard = [
        [InlineKeyboardButton("🔄 Проверить ещё раз",
                              callback_data=f'check_balance_{token}')],
        [InlineKeyboardButton("✅ Перейти к оплате", url=DA_PROFILE_URL)],
        [InlineKeyboardButton("🏠 В главное меню",
                              callback_data='back_to_menu')]
    ]
    await safe_edit_message(
        query,
        "⏳ <b>Оплата ещё не зачтена</b>\n\n"
        "Убедитесь, что:\n"
        f"• Вставили код <code>{token}</code> в комментарий к донату\n"
        "• Подождали 1-2 минуты после оплаты\n\n"
        "Если всё верно — нажмите «Проверить ещё раз».\n\n"
        "<i>Если отправили донат без кода — напишите "
        f"{support_text} и укажите:\n"
        f"• уникальный код: <code>{token}</code>\n"
        "• сумму и время доната.</i>",
        InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )


def setup_user_handlers(application):
    """Настройка обработчиков пользователей"""
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("clean_purchases", admin_clean_purchases))
    application.add_handler(CallbackQueryHandler(button_handler))


async def handle_sport_selection_back(query, context, sport):
    """Возврат к выбору дат для спорта"""
    dates = database.get_available_dates_with_matches(sport)
    if not dates:
        text = f"На ближайшую неделю матчей по {sport} нет."
        await safe_edit_message(
            query,
            text,
            keyboards.main_menu_keyboard()
        )
        return
    sport_names = {'football': '⚽ Футбол', 'basketball': '🏀 Баскетбол',
                   'hockey': '🏒 Хоккей'}
    sport_display = sport_names.get(sport, sport)
    text = f"{sport_display}\n\nВыберите дату для просмотра матчей:\n\n"
    await safe_edit_message(
        query,
        text,
        keyboards.dates_keyboard_with_back(dates, sport)
    )
