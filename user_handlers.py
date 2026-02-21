import logging
from pathlib import Path
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
    # Скриншоты шага пополнения показываем только в рамках второго UX.
    # Не удаляем их при повторном входе во 2-й шаг и при проверке баланса.
    if (
        not query.data.startswith('confirm_code_copy_')
        and not query.data.startswith('check_balance_')
    ):
        await _cleanup_topup_step_images(query, context)
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
    elif query.data == 'support':
        context.user_data['menu_history'].append(MENU_MAIN)
        await handle_support_menu(query)
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
        if match_source == 'purchased':
            context.user_data['menu_history'].append(MENU_PURCHASED_DATE)
            context.user_data['current_match_id'] = match_id
            await handle_show_analysis(query, user_id, match_id)
            return
        else:
            context.user_data['menu_history'].append(MENU_MATCHES_LIST)
        context.user_data['current_match_id'] = match_id
        await handle_match_detail(query, user_id, match_id, match_source=match_source)
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
        context.user_data['current_date'] = date_str
        context.user_data['match_source'] = 'purchased'
        await handle_purchased_date(query, user_id, sport, date_str)
    elif query.data == 'deposit':
        context.user_data['menu_history'].append(MENU_MAIN)
        await handle_deposit_menu(query, user_id)
    elif query.data.startswith('confirm_code_copy_'):
        token = query.data.split('confirm_code_copy_')[1]
        await handle_confirm_code_copy(query, context, user_id, token)
    elif query.data.startswith('check_balance_'):
        token = query.data.split('check_balance_')[1]
        await handle_check_balance_status(query, user_id, token)
    elif query.data.startswith('check_topup_'):
        token = query.data.split('check_topup_')[1]
        await handle_check_topup(query, user_id, token)
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
        if sport in ('basketball', 'hockey'):
            text = (
                "🚧 Этот раздел сейчас в разработке.\n\n"
                "Аналитика по этому виду спорта скоро появится."
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data='back')]
            ])
        else:
            text = f"На ближайшую неделю матчей по {sport} нет."
            keyboard = keyboards.main_menu_keyboard()
        await safe_edit_message(
            query,
            text,
            keyboard
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
        if sport in ('basketball', 'hockey'):
            text = (
                "🚧 Этот раздел сейчас в разработке.\n\n"
                "Аналитика по этому виду спорта скоро появится."
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data='back')]
            ])
        else:
            text = f"На ближайшую неделю матчей по {sport} нет."
            keyboard = keyboards.main_menu_keyboard()
        await safe_edit_message(
            query,
            text,
            keyboard
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


async def handle_analysis_back_to_matches(query, context, sport, date_str):
    """
    Возврат из экрана готового анализа к списку матчей.

    Удаляем хвост истории (детали матча/список), чтобы дальнейший «Назад»
    шёл симметрично: матчи -> даты -> спорт.
    """
    history = context.user_data.get('menu_history', [])
    while history and history[-1] in (MENU_MATCH_DETAIL, MENU_MATCHES_LIST):
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
    """Обработка детальной страницы матча с проверкой количества алмазов."""
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

    if has_purchased and match_source != 'purchased':
        text += "\n\n✅ Вы уже приобрели этот анализ"
    elif user_balance >= price:
        text += (
            f"\n\n💎 У вас: <b>{user_balance} алмазов</b> | "
            f"Цена анализа: <b>{price} 💎</b>\n"
            "Нажмите «Приобрести анализ» для мгновенной покупки."
        )
    else:
        text += (
            f"\n\n💎 У вас: <b>{user_balance} алмазов</b> | "
            f"Цена анализа: <b>{price} 💎</b>\n"
            "Недостаточно алмазов. Нажмите «Приобрести алмазы», затем вернитесь к покупке."
        )

    keyboard = keyboards.match_detail_keyboard(
        match_id, has_purchased, user_balance, price
    )
    await safe_edit_message(query, text, keyboard, parse_mode='HTML')


async def handle_purchase(query, user_id):
    """Покупка анализа за алмазы (мгновенная оплата)."""
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

    # Проверка количества алмазов
    price = ANALYSIS_PRICE_RUB
    user_balance = database.get_user_balance(user_id)
    if user_balance < price:
        text = (
            f"❌ <b>Недостаточно алмазов</b>\n\n"
            f"💎 У вас: <b>{user_balance} алмазов</b>\n"
            f"💠 Цена анализа: <b>{price} 💎</b>\n\n"
            "Приобретите алмазы и вернитесь к покупке."
        )
        keyboard = [
            [InlineKeyboardButton("💎 Приобрести алмазы",
                                  callback_data='deposit')],
            [InlineKeyboardButton("◀️ Назад", callback_data='back')],
            [InlineKeyboardButton("🏠 В главное меню",
                                  callback_data='back_to_menu')]
        ]
        await safe_edit_message(
            query, text, InlineKeyboardMarkup(keyboard), parse_mode='HTML'
        )
        return

    # Списываем алмазы и создаём paid purchase
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
            "❌ Код зачисления не найден. Возможно, срок действия истёк.\n\n"
            "Вернитесь в меню и создайте новый запрос.",
            keyboards.main_menu_keyboard()
        )
        return

    if topup['status'] == 'paid':
        balance = database.get_user_balance(user_id)
        await safe_edit_message(
            query,
            f"✅ <b>Оплата уже зачтена!</b>\n\n"
            f"💎 У вас: <b>{balance} алмазов</b>",
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
                                  callback_data=f'check_topup_{token}')],
            [InlineKeyboardButton("✅ Перейти к оплате", url=DA_PROFILE_URL)],
            [InlineKeyboardButton("🏠 В главное меню",
                                  callback_data='back_to_menu')]
        ]
        from config import SUPPORT_USERNAME
        support_text = f"@{SUPPORT_USERNAME}" if SUPPORT_USERNAME else "поддержку"
        await safe_edit_message(
            query,
            "⏳ <b>Оплата пока не найдена</b>\n\n"
            "Если вы уже отправили донат — подождите 1-2 минуты "
            "и нажмите «Проверить ещё раз».\n\n"
            "⚠️ Автозачёт работает только при наличии кода в комментарии доната.\n"
            f"Если отправили без кода — обратитесь в {support_text}.",
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
            "❌ Ошибка зачисления алмазов. Обратитесь в поддержку.",
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
        f"✅ <b>Алмазы зачислены!</b>\n\n"
        f"💎 Зачислено: <b>+{amount_rub} 💎</b> ({amount_rub} {analyses_word})\n"
        f"💠 У вас: <b>{new_balance} алмазов</b>\n\n"
        "Выберите матч для покупки анализа!",
        keyboards.main_menu_keyboard(),
        parse_mode='HTML'
    )
    logger.info(
        f"✅ [check_topup] Баланс user={user_id} пополнен на {amount_rub} руб. "
        f"через ручную проверку. donation_id={donation_id}"
    )


async def _show_deposit_payment_screen(query, context, user_id, token):
    """Шаг 2: текущий UX оплаты (после подтверждения копирования кода)."""
    from config import DA_PROFILE_URL, ANALYSIS_PRICE_RUB

    topup = database.get_topup_by_token(token)
    if not topup or topup['user_id'] != user_id:
        await safe_edit_message(
            query,
            "❌ Код зачисления не найден или истёк.\n\n"
            "Вернитесь в меню и создайте новый запрос.",
            keyboards.main_menu_keyboard()
        )
        return

    balance = database.get_user_balance(user_id)
    text = (
        "💎 <b>ПРИОБРЕТЕНИЕ АЛМАЗОВ</b>\n\n"
        f"💠 У вас: <b>{balance} алмазов</b>\n\n"
        "📋 <b>Инструкция:</b>\n"
        f"1️⃣ Скопируйте код: <code>{token}</code>\n"
        "2️⃣ Нажмите «Перейти к оплате»\n"
        "3️⃣ Оплатите в DonationAlerts любую сумму в рублях\n"
        "4️⃣ ‼️ Вставьте код в поле <b>«Комментарий»</b>\n"
        "5️⃣ Нажмите «Проверить зачисление»\n\n"
        f"✅ 1 анализ = {int(ANALYSIS_PRICE_RUB)} алмазов"
    )
    keyboard = [
        [InlineKeyboardButton("✅ Перейти к оплате", url=DA_PROFILE_URL)],
        [InlineKeyboardButton("🔄 Проверить зачисление",
                              callback_data=f'check_balance_{token}')],
        [InlineKeyboardButton("🏠 В главное меню",
                              callback_data='back_to_menu')]
    ]
    bot = query.message.get_bot()
    chat_id = query.message.chat_id

    # Сначала отправляем 2 скриншота STEP_1 и STEP_2 (если файлы есть).
    base_dir = Path(__file__).resolve().parent
    step_images = [
        ("STEP 1", base_dir / 'assets' / 'STEP_1.png'),
        ("STEP 2", base_dir / 'assets' / 'STEP_2.png'),
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


async def handle_deposit_menu(query, user_id):
    """
    Приобретение алмазов: показывает уникальный код, который нужно вставить
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
    balance = database.get_user_balance(user_id)
    top_pointer_line = "👇👇👇👇👇"
    bottom_pointer_line = "☝️☝️☝️☝️☝️"
    code_lines = (
        f"<code>{token}</code>\n"
        f"<code>{token}</code>\n"
        f"<code>{token}</code>"
    )

    text = (
        "💎 <b>ПРИОБРЕТЕНИЕ АЛМАЗОВ</b>\n\n"
        f"💠 У вас: <b>{balance} алмазов</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "⚠️ <b>ШАГ 1: СКОПИРУЙТЕ ВАШ КОД</b>\n"
        "⚠️ <b>ШАГ 2: ВСТАВЬТЕ В КОММЕНТАРИИ К ДОНАТУ</b>\n\n"
        f"{top_pointer_line}\n{code_lines}\n{bottom_pointer_line}\n\n"
        "<b>⚠️НЕ СКОПИРОВАЛ КОД - АЛМАЗЫ НЕ ЗАЧИСЛЯТСЯ⚠️</b>\n"
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


async def handle_check_balance_status(query, user_id, token):
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
            f"✅ <b>Алмазы зачислены!</b>\n\n"
            f"💎 Зачислено: <b>+{credited} 💎</b> ({credited} {analyses_word})\n"
            f"💠 У вас: <b>{balance} алмазов</b>\n\n"
            "Выберите матч для покупки анализа!",
            keyboards.main_menu_keyboard(),
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


async def handle_support_menu(query):
    """Экран техподдержки из главного меню."""
    from config import SUPPORT_USERNAME

    support_text = (
        f"@{SUPPORT_USERNAME}" if SUPPORT_USERNAME else "аккаунт поддержки"
    )
    text = (
        "🎧 <b>ТЕХПОДДЕРЖКА</b>\n\n"
        "Если возникли вопросы по оплате, анализам или работе бота,\n"
        f"напишите в {support_text}."
    )
    keyboard = [
        [InlineKeyboardButton("🏠 В главное меню", callback_data='back_to_menu')]
    ]
    await safe_edit_message(
        query,
        text,
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
        if sport in ('basketball', 'hockey'):
            text = (
                "🚧 Этот раздел сейчас в разработке.\n\n"
                "Аналитика по этому виду спорта скоро появится."
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data='back')]
            ])
        else:
            text = f"На ближайшую неделю матчей по {sport} нет."
            keyboard = keyboards.main_menu_keyboard()
        await safe_edit_message(
            query,
            text,
            keyboard
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
