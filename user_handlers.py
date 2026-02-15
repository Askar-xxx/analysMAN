import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler
import database
import keyboards
from utils import safe_edit_message, send_main_menu, format_match_info
from datetime import datetime, timedelta

# Импорты из payment_handlers
from payment_handlers import (
    handle_deposit_menu,
    handle_deposit_amount,
)

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
    # Сохраняем текущее меню для навигации назад
    if not context.user_data.get('menu_history'):
        context.user_data['menu_history'] = []
    # Обработка различных callback_data
    if query.data == 'back':
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
    elif query.data.startswith('sport_'):
        sport = query.data.split('_')[1]
        # Сохраняем предыдущее меню
        context.user_data['menu_history'].append(MENU_CATEGORY_SPORTS)
        await handle_sport_selection(query, context, sport)
    elif query.data.startswith('choose_date_'):
        parts = query.data.split('_')
        sport = parts[2]
        date_str = parts[3]
        # Сохраняем предыдущее меню
        context.user_data['menu_history'].append(MENU_SPORT_SELECTION)
        context.user_data['current_sport'] = sport
        await handle_date_selection(query, context, sport, date_str)
    elif query.data.startswith('match_'):
        match_id = int(query.data.split('_')[1])
        # Сохраняем предыдущее меню и текущий матч
        context.user_data['menu_history'].append(MENU_DATE_SELECTION)
        context.user_data['current_match_id'] = match_id
        await handle_match_detail(query, user_id, match_id)
    elif query.data.startswith('buy_'):
        match_id = int(query.data.split('_')[1])
        # Сохраняем текущее меню (детали матча) в историю
        context.user_data['menu_history'].append(MENU_MATCH_DETAIL)
        await handle_purchase(query, user_id)
    elif query.data.startswith('show_analysis_'):
        match_id = int(query.data.split('_')[2])
        await handle_show_analysis(query, user_id, match_id)
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
        await handle_purchased_date(query, user_id, sport, date_str)
    elif query.data in ['deposit', 'deposit_150', 'deposit_300',
                        'deposit_600', 'deposit_800']:
        if query.data == 'deposit':
            # Сохраняем предыдущее меню
            context.user_data['menu_history'].append(MENU_MAIN)
            await handle_deposit_menu(update, context)
        else:
            await handle_deposit_amount(update, context)
    else:
        await safe_edit_message(
            query,
            "Неизвестная команда.",
            keyboards.main_menu_keyboard()
        )


async def handle_category_sports(query):
    """Обработка выбора категории спорта"""
    sports_text = """
🎯 *ВЫБЕРИТЕ ВИД СПОРТА*

Выберите интересующий вас вид спорта для просмотра доступных матчей и анализов:

⚽ *Футбол* - Европейские лиги, Кубки, международные матчи
🏀 *Баскетбол* - НБА, Евролига, национальные чемпионаты
🏒 *Хоккей* - КХЛ, НХЛ, международные турниры

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
    dates = database.get_available_dates_with_matches(sport)
    if not dates:
        await safe_edit_message(
            query,
            f"На ближайшую неделю матчей по {sport} нет.",
            keyboards.main_menu_keyboard()
        )
        return
    text = f"Выберите дату для просмотра матчей по {sport}:\n\n"
    await safe_edit_message(
        query,
        text,
        keyboards.dates_keyboard_with_back(dates, sport)
    )


async def handle_date_selection(query, context, sport, date_str):
    """Обработка выбора даты"""
    print(f"   → Выбрана дата: {date_str} для спорта: {sport}")
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
    sport_names = {'football': '⚽ Футбол', 'basketball': '🏀 Баскетбол',
                   'hockey': '🏒 Хоккей'}
    sport_display = sport_names.get(sport, sport)
    text = f"{sport_display} *Матчи на {date_label}:*\n\n"
    for match in matches:
        text += f"• {match['team1']} vs {match['team2']} в {match['match_time']}\n"
    text += "\n👇 *Выберите матч для просмотра анализа:*"
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


async def go_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат на предыдущее меню"""
    if not context.user_data.get('menu_history') or len(context.user_data['menu_history']) == 0:
        # Если истории нет, возвращаемся в главное меню
        await send_main_menu(update, context)
        return
    # Получаем предыдущее меню
    previous_menu = context.user_data['menu_history'].pop()
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
            sport = context.user_data.get('current_sport', 'football')
            await handle_sport_selection_back(query, context, sport)
        elif previous_menu == MENU_PURCHASED_SPORT:
            sport = context.user_data.get('current_sport', 'football')
            await handle_purchased_sport_back(query, user_id, sport)
        elif previous_menu == MENU_DATE_SELECTION:
            sport = context.user_data.get('current_sport', 'football')
            await handle_date_selection_back(query, context, sport)
        elif previous_menu == MENU_MATCH_DETAIL:
            # Возврат к деталям матча
            match_id = context.user_data.get('current_match_id')
            if match_id:
                await handle_match_detail(query, user_id, match_id)
            else:
                await send_main_menu(update, context)
        else:
            # По умолчанию возвращаемся в главное меню
            await send_main_menu(update, context)
    except Exception:
        # В случае ошибки возвращаемся в главное меню
        await send_main_menu(update, context)


async def handle_match_detail(query, user_id, match_id):
    """Обработка детальной страницы матча"""
    match = database.get_match_by_id(match_id)
    if not match:
        await safe_edit_message(query, "Матч не найден.",
                                keyboards.main_menu_keyboard())
        return
    has_purchased = database.has_purchased_analysis(user_id, match_id)
    user_balance = database.get_user_balance(user_id)
    text = format_match_info(match)

    if has_purchased:
        # Если анализ уже куплен - показываем кнопку для просмотра PNG
        text += "\n\n✅ Вы уже приобрели этот анализ"
        keyboard = [
            [InlineKeyboardButton("📊 Показать анализ", callback_data=f'show_analysis_{match_id}')],
            [InlineKeyboardButton("◀️ Назад", callback_data='back')],
            [InlineKeyboardButton("🏠 В главное меню", callback_data='back_to_menu')]
        ]
    else:
        text += f"\n💰 *Цена анализа:* {match['price']} руб.\n\n"
        text += "Для просмотра анализа необходимо приобрести его."
        keyboard = []
        if user_balance >= match['price']:
            btn_text = f"✅ Купить анализ за {match['price']} руб."
            keyboard.append([InlineKeyboardButton(
                btn_text, callback_data=f'buy_{match_id}')])
        else:
            keyboard.append([InlineKeyboardButton("💳 Пополнить баланс",
                                                  callback_data='deposit')])
        keyboard.append([InlineKeyboardButton("◀️ Назад",
                                              callback_data='back')])
        keyboard.append([InlineKeyboardButton("🏠 В главное меню",
                                              callback_data='back_to_menu')])

    await safe_edit_message(
        query,
        text,
        InlineKeyboardMarkup(keyboard)
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
    if database.has_purchased_analysis(user_id, match_id):
        await safe_edit_message(
            query,
            f"✅ Вы уже приобрели анализ для этого матча!\n\n{match['team1']} vs {match['team2']}",
            keyboards.main_menu_keyboard()
        )
        return

    # Конвертируем sqlite3.Row в dict для совместимости
    match_dict = dict(match) if not isinstance(match, dict) else match

    # Этап 1/2: Сбор обогащённых данных (ВСЕГДА, для PNG рендеринга)
    await safe_edit_message(
        query,
        f"⏳ Этап 1/2: Сбор данных для матча "
        f"{match_dict['team1']} vs {match_dict['team2']}...\n\n"
        f"Получаем H2H, турнирную таблицу, форму команд...",
        None
    )

    enriched_data = {}
    try:
        from match_data_fetcher import MatchDataFetcher, build_enriched_context
        fetcher = MatchDataFetcher()
        enriched_data = fetcher.fetch_match_data(match_dict)
        enriched_context = build_enriched_context(match_dict, enriched_data)
        logger.info(f"On-demand data fetched. Errors: {enriched_data.get('errors', [])}")
    except Exception as e:
        logger.error(f"Ошибка получения обогащённых данных: {e}", exc_info=True)
        enriched_context = "Обогащённые данные недоступны."

    # Этап 2/2: Подготовка анализа (если ещё не сгенерирован)
    analysis_text = match_dict.get('analysis_text')
    if not analysis_text:
        await safe_edit_message(
            query,
            f"⏳ Этап 2/2: Подготовка анализа для матча "
            f"{match_dict['team1']} vs {match_dict['team2']}...\n\n"
            f"Пожалуйста, подождите 10-15 секунд.",
            None
        )
        try:
            from ai_generator import generate_match_analysis_with_context
            analysis_text = await generate_match_analysis_with_context(match_dict, enriched_context)
            # Сохраняем анализ в БД, чтобы не генерировать повторно
            database.update_match_analysis(match_id, analysis_text)
        except Exception as e:
            logger.error(f"Ошибка генерации анализа: {e}", exc_info=True)
            await safe_edit_message(
                query,
                "❌ Не удалось сгенерировать анализ. Попробуйте позже.",
                keyboards.main_menu_keyboard()
            )
            return

    # Выполняем покупку (списание средств)
    success, message = database.purchase_analysis(user_id, match_id)
    if not success:
        text = f"❌ Не удалось купить анализ:\n{message}\n\n"
        text += f"💰 Ваш баланс: {database.get_user_balance(user_id)} руб.\n"
        text += f"💵 Нужно: {match_dict['price']} руб."
        await safe_edit_message(
            query,
            text,
            keyboards.main_menu_keyboard()
        )
        return

    # Этап 3: Рендеринг PNG таблицы
    await safe_edit_message(
        query,
        "⏳ Подготовка визуализации...",
        None
    )

    png_path = None
    try:
        from analysis_formatter import build_table_data
        from image_renderer import render_analysis_table

        # Формируем структурированные данные для таблицы
        table_data = build_table_data(match_dict, enriched_data)

        # Рендерим PNG
        png_path = render_analysis_table(match_dict, table_data)
        logger.info(f"PNG таблица создана: {png_path}")

    except Exception as e:
        logger.error(f"Ошибка рендеринга PNG: {e}", exc_info=True)
        # Fallback на текстовый анализ
        text = "✅ Покупка успешна\n\n"
        text += f"🏆 Матч: {match_dict['team1']} vs {match_dict['team2']}\n"
        text += f"💰 Списано: {match_dict['price']} руб.\n"
        text += f"💳 Новый баланс: {database.get_user_balance(user_id)} руб.\n\n"
        text += f"📊 Анализ:\n{analysis_text}"
        await safe_edit_message(
            query,
            text,
            keyboards.main_menu_keyboard()
        )
        return

    # Отправляем PNG как фото с краткой сводкой и кнопками
    try:
        # Формируем краткое введение на основе данных матча
        from datetime import datetime

        # Форматируем дату
        date_obj = datetime.strptime(match_dict['match_date'], '%Y-%m-%d')
        date_formatted = date_obj.strftime('%d %B %Y года').replace(
            'January', 'января').replace('February', 'февраля').replace(
            'March', 'марта').replace('April', 'апреля').replace(
            'May', 'мая').replace('June', 'июня').replace(
            'July', 'июля').replace('August', 'августа').replace(
            'September', 'сентября').replace('October', 'октября').replace(
            'November', 'ноября').replace('December', 'декабря')

        # Формируем краткое введение
        intro_text = (
            f"{match_dict['team1']} примет {match_dict['team2']}. "
            f"Матч пройдёт {date_formatted} в {match_dict['match_time']} "
            f"в рамках турнира {match_dict.get('league', 'N/A')}."
        )

        # Caption с заголовком и краткой сводкой (через двоеточие)
        caption = f"✅ Анализ матча: {intro_text}"

        # Отправляем фото с caption и кнопками в одном сообщении
        with open(png_path, 'rb') as photo:
            await query.message.reply_photo(
                photo=photo,
                caption=caption,
                reply_markup=keyboards.analysis_view_keyboard()
            )

        # Удаляем сообщение с прогрессом
        try:
            await query.message.delete()
        except Exception:
            pass  # Игнорируем ошибки удаления

        # Удаляем временный PNG файл
        try:
            import os
            os.remove(png_path)
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Ошибка отправки PNG: {e}", exc_info=True)
        # Fallback на текстовый анализ
        text = "✅ Покупка успешна\n\n"
        text += f"🏆 Матч: {match_dict['team1']} vs {match_dict['team2']}\n"
        text += f"💰 Списано: {match_dict['price']} руб.\n"
        text += f"💳 Новый баланс: {database.get_user_balance(user_id)} руб.\n\n"
        text += f"📊 Анализ:\n{analysis_text}"
        await safe_edit_message(
            query,
            text,
            keyboards.main_menu_keyboard()
        )


async def handle_show_analysis(query, user_id, match_id):
    """Отображение PNG анализа для уже купленного матча"""
    # Проверяем что анализ действительно куплен
    if not database.has_purchased_analysis(user_id, match_id):
        await safe_edit_message(
            query,
            "❌ Вы не приобретали анализ для этого матча.",
            keyboards.main_menu_keyboard()
        )
        return

    match = database.get_match_by_id(match_id)
    if not match:
        await safe_edit_message(
            query,
            "❌ Матч не найден.",
            keyboards.main_menu_keyboard()
        )
        return

    # Конвертируем в dict
    match_dict = dict(match) if not isinstance(match, dict) else match

    # Показываем прогресс
    await safe_edit_message(
        query,
        "⏳ Подготовка анализа для матча\n"
        f"{match_dict['team1']} vs {match_dict['team2']}...",
        None
    )

    # Получаем обогащённые данные
    enriched_data = {}
    try:
        from match_data_fetcher import MatchDataFetcher
        fetcher = MatchDataFetcher()
        enriched_data = fetcher.fetch_match_data(match_dict)
        logger.info(f"Data fetched for show_analysis. Errors: {enriched_data.get('errors', [])}")
    except Exception as e:
        logger.error(f"Ошибка получения данных для отображения: {e}", exc_info=True)

    # Рендерим PNG
    png_path = None
    try:
        from analysis_formatter import build_table_data
        from image_renderer import render_analysis_table

        table_data = build_table_data(match_dict, enriched_data)
        png_path = render_analysis_table(match_dict, table_data)
        logger.info(f"PNG создан для отображения: {png_path}")

    except Exception as e:
        logger.error(f"Ошибка рендеринга PNG для отображения: {e}", exc_info=True)
        # Fallback на текстовый анализ
        text = "📊 Анализ матча\n\n"
        text += f"{match_dict['team1']} vs {match_dict['team2']}\n"
        text += f"{match_dict['match_date']} в {match_dict['match_time']}\n\n"
        analysis_text = match_dict.get('analysis_text', '')
        if analysis_text:
            text += f"📊 Анализ:\n\n{analysis_text}"
        else:
            text += "Анализ недоступен"
        await safe_edit_message(
            query,
            text,
            keyboards.analysis_view_keyboard()
        )
        return

    # Отправляем PNG с краткой сводкой и кнопками
    try:
        # Формируем краткое введение на основе данных матча
        from datetime import datetime

        # Форматируем дату
        date_obj = datetime.strptime(match_dict['match_date'], '%Y-%m-%d')
        date_formatted = date_obj.strftime('%d %B %Y года').replace(
            'January', 'января').replace('February', 'февраля').replace(
            'March', 'марта').replace('April', 'апреля').replace(
            'May', 'мая').replace('June', 'июня').replace(
            'July', 'июля').replace('August', 'августа').replace(
            'September', 'сентября').replace('October', 'октября').replace(
            'November', 'ноября').replace('December', 'декабря')

        # Формируем краткое введение
        intro_text = (
            f"{match_dict['team1']} примет {match_dict['team2']}. "
            f"Матч пройдёт {date_formatted} в {match_dict['match_time']} "
            f"в рамках турнира {match_dict.get('league', 'N/A')}."
        )

        # Caption с заголовком и краткой сводкой (через двоеточие)
        caption = f"✅ Данные матча: {intro_text}"

        # Отправляем фото с caption и кнопками в одном сообщении
        with open(png_path, 'rb') as photo:
            await query.message.reply_photo(
                photo=photo,
                caption=caption,
                reply_markup=keyboards.analysis_view_keyboard()
            )

        # Удаляем сообщение с прогрессом
        try:
            await query.message.delete()
        except Exception:
            pass

        # Удаляем временный файл
        try:
            import os
            os.remove(png_path)
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Ошибка отправки PNG: {e}", exc_info=True)
        # Fallback
        text = "📊 Анализ матча\n\n"
        text += f"{match_dict['team1']} vs {match_dict['team2']}\n"
        text += f"{match_dict['match_date']} в {match_dict['match_time']}\n\n"
        analysis_text = match_dict.get('analysis_text', '')
        if analysis_text:
            text += f"📊 Анализ:\n\n{analysis_text}"
        else:
            text += "Анализ недоступен"
        await safe_edit_message(
            query,
            text,
            keyboards.analysis_view_keyboard()
        )


async def handle_my_analysis(update: Update, query, user_id):
    """Обработка кнопки 'Мои анализы'"""
    # Получаем все купленные матчи
    purchased_matches = database.get_purchased_matches_by_user(user_id)
    if not purchased_matches:
        text = "📭 *У вас пока нет купленных анализов*\n\n"
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
    text = "📊 *ВАШИ КУПЛЕННЫЕ АНАЛИЗЫ*\n\n"
    text += f"Всего анализов: {len(purchased_matches)}\n\n"
    text += "👇 *Выберите вид спорта для просмотра:*\n"
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
            [InlineKeyboardButton("◀️ Назад к выбору даты",
                                  callback_data=f'purchased_sport_{sport}')],
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
    text = f"{sport_display} *Матчи на {date_label}:*\n\n"
    for match in date_matches:
        text += f"• {match['team1']} vs {match['team2']} ({match['match_time']})\n"
    text += "\n👇 *Выберите матч для просмотра анализа:*"
    # Создаем клавиатуру с матчами
    keyboard = []
    for match in date_matches:
        button_text = f"{match['team1']} vs {match['team2']} ({match['match_time']})"
        callback_data = f"match_{match['id']}"
        keyboard.append([InlineKeyboardButton(button_text,
                                              callback_data=callback_data)])
    keyboard.append([InlineKeyboardButton(
        "◀️ Назад к выбору даты", callback_data=f'purchased_sport_{sport}')])
    keyboard.append([InlineKeyboardButton("🏠 В главное меню",
                                          callback_data='back_to_menu')])
    await safe_edit_message(
        query,
        text,
        InlineKeyboardMarkup(keyboard)
    )


def setup_user_handlers(application):
    """Настройка обработчиков пользователей"""
    application.add_handler(CommandHandler("start", start))
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
