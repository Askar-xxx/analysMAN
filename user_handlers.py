import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler
import database
import keyboards
from utils import safe_edit_message, send_main_menu, format_match_info
from datetime import datetime, timedelta


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
        logger.info(f"Добавлено MENU_CATEGORY_SPORTS в history. Текущий history: {context.user_data['menu_history']}")
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
    elif query.data == 'deposit':
        context.user_data['menu_history'].append(MENU_MAIN)
        await handle_deposit_menu(query, user_id)
    elif query.data.startswith('check_topup_'):
        token = query.data.split('check_topup_')[1]
        await handle_check_topup(query, user_id, token)
    elif query.data.startswith('find_topup_by_amount_'):
        token = query.data.split('find_topup_by_amount_')[1]
        await handle_find_topup_by_amount(query, user_id, token)
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
        text += "\n\n✅ Вы уже приобрели этот анализ"
    elif user_balance >= price:
        text += (
            f"\n\n💳 Ваш баланс: <b>{user_balance} руб.</b> | "
            f"Стоимость: <b>{price} руб.</b>\n"
            "Нажмите «Купить анализ» для мгновенной покупки с баланса."
        )
    else:
        text += (
            f"\n\n💳 Ваш баланс: <b>{user_balance} руб.</b> | "
            f"Стоимость: <b>{price} руб.</b>\n"
            "Недостаточно средств. Пополните баланс для покупки анализа."
        )

    keyboard = keyboards.match_detail_keyboard(
        match_id, has_purchased, user_balance, price
    )
    await safe_edit_message(query, text, keyboard, parse_mode='HTML')


async def handle_purchase(query, user_id):
    """Покупка анализа с баланса (мгновенная оплата)."""
    from config import ANALYSIS_PRICE_RUB

    await query.answer()

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
            f"❌ <b>Недостаточно средств</b>\n\n"
            f"💳 Ваш баланс: <b>{user_balance} руб.</b>\n"
            f"💵 Стоимость анализа: <b>{price} руб.</b>\n\n"
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
        "🤖 Собираем данные и создаём анализ...\n"
        "⏱ Это займёт <b>30-60 секунд</b>.",
        None,
        parse_mode='HTML'
    )

    from webhook_server import generate_and_send_analysis
    await generate_and_send_analysis(
        user_id, match_id, match_dict,
        instruction_message_id=query.message.message_id
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

    # Проверяем есть ли сохранённый PNG
    import os
    cached_png_path = match_dict.get('analysis_png_path')
    if cached_png_path and os.path.exists(cached_png_path):
        # PNG уже есть — используем готовый, без API запросов
        logger.info(f"Используем сохранённый PNG: {cached_png_path}")
        png_path = cached_png_path
    else:
        # PNG нет — генерируем (первый раз или файл удалён)
        logger.info("PNG не найден, генерируем...")
        await safe_edit_message(
            query,
            "⏳ Подготовка анализа для матча\n"
            f"{match_dict['team1']} vs {match_dict['team2']}...",
            None
        )

        # Получаем обогащённые данные для PNG таблицы
        enriched_data = {}
        try:
            from match_data_fetcher import MatchDataFetcher
            fetcher = MatchDataFetcher()
            enriched_data = fetcher.fetch_match_data(match_dict)
            logger.info(f"Data fetched for PNG generation. Errors: {enriched_data.get('errors', [])}")
        except Exception as e:
            logger.error(f"Ошибка получения данных для PNG: {e}", exc_info=True)

        # Если анализ ещё не сгенерирован (listener отметил paid, но не сгенерировал)
        if not match_dict.get('analysis_text'):
            logger.info(f"analysis_text пуст для матча {match_id}, генерируем on-demand...")
            await safe_edit_message(
                query,
                "⏳ Генерация анализа для матча\n"
                f"{match_dict['team1']} vs {match_dict['team2']}...\n\n"
                "Это может занять 30-60 секунд.",
                None
            )

            # Формируем enriched_context для генерации
            enriched_context = "Обогащённые данные недоступны."
            try:
                from match_data_fetcher import build_enriched_context
                enriched_context = build_enriched_context(match_dict, enriched_data)
            except Exception as e:
                logger.error(f"Ошибка построения контекста: {e}", exc_info=True)

            try:
                from ai_generator import generate_match_analysis_with_context
                analysis_text = await generate_match_analysis_with_context(
                    match_dict, enriched_context
                )
                match_dict['analysis_text'] = analysis_text
                logger.info(f"Анализ сгенерирован on-demand для матча {match_id}")
            except Exception as e:
                logger.error(f"Ошибка on-demand генерации: {e}", exc_info=True)

        # Рендерим PNG и сохраняем в постоянную папку
        png_path = None
        cached_png_path = None
        try:
            from analysis_formatter import build_table_data
            from image_renderer import render_analysis_table

            table_data = build_table_data(match_dict, enriched_data)
            temp_png = render_analysis_table(match_dict, table_data)

            # Копируем в постоянную папку
            target_path = f"analysis_cache/analysis_{match_id}.png"
            os.makedirs("analysis_cache", exist_ok=True)
            import shutil
            shutil.copy(temp_png, target_path)

            # Проверяем, что файл действительно скопирован
            if os.path.exists(target_path):
                cached_png_path = target_path
                png_path = cached_png_path
                logger.info(f"PNG сохранён: {cached_png_path}")

                # Сохраняем путь в БД только если файл существует
                database.update_match_analysis(
                    match_id,
                    match_dict.get('analysis_text'),
                    cached_png_path
                )

                # Удаляем временный файл после успешного копирования
                try:
                    os.remove(temp_png)
                    logger.info(f"Временный файл удалён: {temp_png}")
                except Exception as e:
                    logger.warning(f"Не удалось удалить временный файл: {e}")
            else:
                logger.error(f"Файл не был скопирован: {target_path}")

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
            f"Матч пройдёт {date_formatted} в {match_dict['match_time']} МСК "
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
            pass

        # НЕ удаляем кэшированный PNG — он должен сохраняться для последующих просмотров

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


async def handle_check_topup(query, user_id, token):
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
            f"💳 Ваш баланс: <b>{balance} руб.</b>",
            keyboards.main_menu_keyboard(),
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
            f"Получено: <b>{received_rub:.2f} руб.</b>\n"
            f"Требуется: <b>{amount_rub} руб.</b> "
            f"(с учётом комиссии: от {min_acceptable / 100:.2f} руб.)\n\n"
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
        f"💰 Пополнено: <b>+{amount_rub} руб.</b> ({amount_rub} {analyses_word})\n"
        f"💳 Ваш баланс: <b>{new_balance} руб.</b>\n\n"
        "Выберите матч для покупки анализа!",
        keyboards.main_menu_keyboard(),
        parse_mode='HTML'
    )
    logger.info(
        f"✅ [check_topup] Баланс user={user_id} пополнен на {amount_rub} руб. "
        f"через ручную проверку. donation_id={donation_id}"
    )


async def handle_find_topup_by_amount(query, user_id, token):
    """
    Поиск доната по сумме для случая, когда пользователь нажал кнопку
    «Не вставил код». Token уже известен из callback_data — ищем
    подходящий незасчитанный донат в последних 30 записях DA.
    """
    import requests as http_requests
    from config import DA_ACCESS_TOKEN, DA_PROFILE_URL

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
            f"💳 Ваш баланс: <b>{balance} руб.</b>",
            keyboards.main_menu_keyboard(),
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

    # Временной порог: только донаты с момента создания токена для этого пользователя.
    # Это привязывает поиск к конкретной сессии оплаты, а не к случайному промежутку.
    try:
        cutoff_dt = datetime.strptime(topup['created_at'][:19], '%Y-%m-%d %H:%M:%S')
    except Exception:
        cutoff_dt = datetime.now() - timedelta(hours=2)

    # Ищем незасчитанный донат без кода в комментарии с любой суммой > 0
    candidates = []
    for donation in donations:
        received_kopeks = int(float(str(donation.get('amount', 0))) * 100)
        if received_kopeks <= 0:
            continue
        # Фильтрация по времени — игнорируем старые донаты
        created_at_str = donation.get('created_at', '')
        if created_at_str:
            try:
                # DA возвращает формат: "2024-01-15 12:34:56"
                donation_dt = datetime.strptime(created_at_str[:19], '%Y-%m-%d %H:%M:%S')
                if donation_dt < cutoff_dt:
                    continue
            except Exception:
                pass  # если парсинг не удался — пропускаем проверку времени
        msg = donation.get('message', '') or ''
        # Пропускаем донаты с 12-символьным кодом — они обработаются сами
        if re.search(r'\b([A-Z0-9]{12})\b', msg.upper()):
            continue
        if database.is_donation_event_used(str(donation['id'])):
            continue
        candidates.append(donation)

    if not candidates:
        keyboard = [
            [InlineKeyboardButton("🔄 Проверить ещё раз",
                                  callback_data=f'find_topup_by_amount_{token}')],
            [InlineKeyboardButton("✅ Перейти к оплате", url=DA_PROFILE_URL)],
            [InlineKeyboardButton("🏠 В главное меню",
                                  callback_data='back_to_menu')]
        ]
        await safe_edit_message(
            query,
            "⏳ <b>Незасчитанный донат не найден</b>\n\n"
            "Возможные причины:\n"
            "• Донат ещё не появился в системе — подождите 1-2 мин\n"
            "• Донат уже был засчитан ранее\n\n"
            "Если оплата точно была, обратитесь в поддержку.",
            InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
        return

    # Берём самый свежий подходящий донат, зачисляем фактическую сумму
    best = candidates[0]
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
        f"💰 Пополнено: <b>+{received_rub} руб.</b> ({received_rub} {analyses_word})\n"
        f"💳 Ваш баланс: <b>{new_balance} руб.</b>\n\n"
        "Донат найден и успешно засчитан!\n"
        "В следующий раз указывайте код в комментарии к донату.",
        keyboards.main_menu_keyboard(),
        parse_mode='HTML'
    )


async def handle_deposit_menu(query, user_id):
    """
    Пополнение баланса: показывает инструкцию с уникальным кодом.

    Если у пользователя есть действующий pending топап — показывает тот же
    код, чтобы он не потерял его при повторном входе в меню.
    Новый токен создаётся только если старый истёк или отсутствует.
    """
    from config import DA_PROFILE_URL

    existing = database.get_pending_topup_by_user(user_id)
    if existing:
        token = existing['token']
    else:
        token = database.create_balance_topup(user_id, amount_rub=0)
    balance = database.get_user_balance(user_id)

    text = (
        "💰 <b>ПОПОЛНЕНИЕ БАЛАНСА</b>\n\n"
        f"💳 Текущий баланс: <b>{balance} руб.</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "📋 <b>Инструкция:</b>\n"
        "1️⃣ Нажмите кнопку «Перейти к оплате»\n"
        "2️⃣ Отправьте донат на <b>любую сумму</b>\n"
        "3️⃣ Нажмите кнопку «Проверить баланс»\n\n"
        "✅ Баланс пополнится автоматически.\n"
        "1 руб. = 1 анализ  •  ⏱ Действует <b>10 минут</b>"
    )
    keyboard = [
        [InlineKeyboardButton("✅ Перейти к оплате", url=DA_PROFILE_URL)],
        [InlineKeyboardButton("🔄 Проверить баланс",
                              callback_data=f'find_topup_by_amount_{token}')],
        [InlineKeyboardButton("🏠 В главное меню",
                              callback_data='back_to_menu')]
    ]
    await safe_edit_message(
        query, text, InlineKeyboardMarkup(keyboard), parse_mode='HTML'
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
