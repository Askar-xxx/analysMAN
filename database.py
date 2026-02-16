import sqlite3
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def get_db_connection():
    conn = sqlite3.connect('sports_bot.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sport TEXT NOT NULL,
            team1 TEXT NOT NULL,
            team2 TEXT NOT NULL,
            match_date TEXT NOT NULL,
            match_time TEXT NOT NULL,
            league TEXT,
            api_event_id TEXT UNIQUE,
            source TEXT,
            home_team_id TEXT,
            away_team_id TEXT,
            match_datetime TEXT,
            analysis_text TEXT,
            price INTEGER DEFAULT 150,
            is_active BOOLEAN DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Таблица teams (кэш lookupteam)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS teams (
            team_id TEXT PRIMARY KEY,
            name TEXT,
            short_name TEXT,
            badge_url TEXT,
            sport TEXT DEFAULT 'football',
            raw_json TEXT,
            source TEXT,
            cached_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Таблица sync_meta (метаданные синхронизации)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sync_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    # Остальные таблицы без изменений
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 0,
            total_analysis_bought INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            match_id INTEGER NOT NULL,
            purchase_date TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            FOREIGN KEY (match_id) REFERENCES matches (id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            added_by INTEGER,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # ПРОВЕРЯЕМ И ОБНОВЛЯЕМ СУЩЕСТВУЮЩУЮ ТАБЛИЦУ
    # Если таблица уже существует, добавляем недостающие поля
    cursor.execute("PRAGMA table_info(matches)")
    existing_columns = [col[1] for col in cursor.fetchall()]
    # Список полей для обратной совместимости
    new_columns = [
        ('league', 'TEXT'),
        ('api_event_id', 'TEXT'),
        ('created_at', 'TEXT DEFAULT CURRENT_TIMESTAMP'),
        ('source', 'TEXT'),
        ('home_team_id', 'TEXT'),
        ('away_team_id', 'TEXT'),
        ('match_datetime', 'TEXT'),
    ]
    for column_name, column_type in new_columns:
        if column_name not in existing_columns:
            try:
                cursor.execute(f'ALTER TABLE matches ADD COLUMN {column_name} {column_type}')
                print(f"Добавлено поле {column_name} в таблицу matches")
            except sqlite3.OperationalError as e:
                print(f"Не удалось добавить поле {column_name}: {e}")

    # Индексы
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_match_date ON matches(match_date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_api_event_id ON matches(api_event_id)')
    conn.commit()
    conn.close()
    print("База данных инициализирована")


# ОБНОВЛЕННАЯ ФУНКЦИЯ ДОБАВЛЕНИЯ МАТЧА
def add_match(sport, team1, team2, match_date, match_time,
              analysis_text=None, price=150, league=None,
              api_event_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO matches (sport, team1, team2, match_date, match_time,
                   analysis_text, price, league, api_event_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (sport, team1, team2, match_date, match_time,
          analysis_text, price, league, api_event_id))
    match_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return match_id


# ОБНОВЛЕННАЯ ФУНКЦИЯ СОЗДАНИЯ МАТЧА (для админов)
def create_match(sport, team1, team2, match_date, match_time,
                 price=150, league=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO matches (sport, team1, team2, match_date, match_time,
                   price, league)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (sport, team1, team2, match_date, match_time,
          price, league))
    match_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return match_id


# ФУНКЦИЯ ДЛЯ СИНХРОНИЗАЦИИ (новая)
def sync_match_from_api(match_data):
    """
    Синхронизировать матч из API с базой данных
    match_data должен содержать:
    - sport, team1, team2, match_date, match_time
    - league, api_event_id (опционально)
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    # Проверяем, существует ли уже матч с таким api_event_id
    api_event_id = match_data.get('api_event_id')
    if api_event_id:
        cursor.execute('SELECT id FROM matches WHERE api_event_id = ?', (api_event_id,))
        existing = cursor.fetchone()
        if existing:
            conn.close()
            return existing['id'], False  # ID, is_new=False
    # Проверяем по командам и дате (резервный вариант)
    cursor.execute('''
        SELECT id FROM matches
        WHERE team1 = ? AND team2 = ? AND match_date = ?
    ''', (match_data['team1'], match_data['team2'], match_data['match_date']))
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return existing['id'], False
    # Добавляем новый матч
    cursor.execute('''
        INSERT INTO matches
        (sport, team1, team2, match_date, match_time,
         league, api_event_id, price)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        match_data.get('sport', 'football'),
        match_data['team1'],
        match_data['team2'],
        match_data['match_date'],
        match_data['match_time'],
        match_data.get('league'),
        match_data.get('api_event_id'),
        match_data.get('price', 150)
    ))
    match_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return match_id, True  # ID, is_new=True


# ОБНОВЛЕННАЯ ФУНКЦИЯ ПОЛУЧЕНИЯ МАТЧА
def get_match_by_id(match_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM matches WHERE id = ?', (match_id,))
    match = cursor.fetchone()
    conn.close()
    return match


# ОБНОВЛЕННАЯ ФУНКЦИЯ ПОЛУЧЕНИЯ ВСЕХ МАТЧЕЙ
def get_all_matches():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM matches
        ORDER BY match_date DESC, match_time DESC
    ''')
    matches = cursor.fetchall()
    conn.close()
    return matches


# ОБНОВЛЕННАЯ ФУНКЦИЯ ПОЛУЧЕНИЯ МАТЧЕЙ ПО ДАТЕ
def get_matches_by_date(sport, match_date):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM matches
        WHERE sport = ? AND match_date = ? AND is_active = 1
        ORDER BY match_time
    ''', (sport, match_date))
    matches = cursor.fetchall()
    conn.close()
    return matches


# НОВАЯ ФУНКЦИЯ: Проверка структуры БД
def check_database_structure():
    """Проверить и исправить структуру базы данных"""
    conn = get_db_connection()
    cursor = conn.cursor()
    print("Проверка структуры базы данных...")
    # Проверяем таблицу matches
    cursor.execute("PRAGMA table_info(matches)")
    columns = cursor.fetchall()
    print("Таблица 'matches':")
    required_columns = {
        'id': 'INTEGER PRIMARY KEY',
        'sport': 'TEXT',
        'team1': 'TEXT',
        'team2': 'TEXT',
        'match_date': 'TEXT',
        'match_time': 'TEXT',
        'league': 'TEXT',
        'venue': 'TEXT',
        'api_event_id': 'TEXT',
        'status': 'TEXT',
        'analysis_text': 'TEXT',
        'price': 'INTEGER',
        'is_active': 'BOOLEAN',
        'created_at': 'TEXT'
    }
    existing_columns = {}
    for col in columns:
        existing_columns[col[1]] = col[2]
        print(f"  - {col[1]}: {col[2]}")
    # Проверяем отсутствующие столбцы
    missing_columns = []
    for col_name, col_type in required_columns.items():
        if col_name not in existing_columns:
            missing_columns.append((col_name, col_type))
    if missing_columns:
        print("\nОтсутствующие столбцы:")
        for col_name, col_type in missing_columns:
            print(f"  - {col_name}: {col_type}")
        # Добавляем недостающие столбцы
        print("\nДобавление недостающих столбцов...")
        for col_name, col_type in missing_columns:
            try:
                cursor.execute(f'ALTER TABLE matches ADD COLUMN {col_name} {col_type}')
                print(f"Добавлен столбец: {col_name}")
            except Exception as e:
                print(f"Ошибка при добавлении {col_name}: {e}")
    else:
        print("Все необходимые столбцы присутствуют")
    conn.commit()
    conn.close()
    return len(missing_columns) == 0


def get_purchased_matches_by_user(user_id):
    """Получить все купленные матчи пользователя (только оплаченные)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT m.*, p.purchase_date
        FROM matches m
        JOIN purchases p ON m.id = p.match_id
        WHERE p.user_id = ? AND p.status = 'paid'
        ORDER BY m.match_date DESC, m.match_time DESC
    ''', (user_id,))
    matches = cursor.fetchall()
    conn.close()
    return matches


def get_purchased_matches_by_sport(user_id, sport):
    """Получить купленные матчи пользователя по виду спорта (только оплаченные)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT m.*, p.purchase_date
        FROM matches m
        JOIN purchases p ON m.id = p.match_id
        WHERE p.user_id = ? AND m.sport = ? AND p.status = 'paid'
        ORDER BY m.match_date DESC, m.match_time DESC
    ''', (user_id, sport))
    matches = cursor.fetchall()
    conn.close()
    return matches


def get_purchased_dates_by_sport(user_id, sport):
    """Получить даты купленных матчей по виду спорта (только оплаченные)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DISTINCT m.match_date
        FROM matches m
        JOIN purchases p ON m.id = p.match_id
        WHERE p.user_id = ? AND m.sport = ? AND p.status = 'paid'
        ORDER BY m.match_date DESC
    ''', (user_id, sport))
    dates = cursor.fetchall()
    conn.close()
    return [date['match_date'] for date in dates]


def get_today_matches(sport):
    conn = get_db_connection()
    cursor = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute('''
        SELECT * FROM matches
        WHERE sport = ? AND match_date = ? AND is_active = 1
        ORDER BY match_time
    ''', (sport, today))
    matches = cursor.fetchall()
    conn.close()
    return matches


def get_today_tomorrow_matches(sport):
    conn = get_db_connection()
    cursor = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    tomorrow_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    cursor.execute('''
        SELECT * FROM matches
        WHERE sport = ? AND match_date IN (?, ?) AND is_active = 1
        ORDER BY match_date, match_time
    ''', (sport, today, tomorrow_date))
    matches = cursor.fetchall()
    conn.close()
    # Разделяем матчи по дням
    today_matches = []
    tomorrow_matches = []
    for match in matches:
        if match['match_date'] == today:
            today_matches.append(match)
        else:
            tomorrow_matches.append(match)
    return today_matches, tomorrow_matches


# Функция для получения доступных дат с матчами (сегодня + 7 дней вперед)
def get_available_dates_with_matches(sport):
    conn = get_db_connection()
    cursor = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    week_later = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
    cursor.execute('''
        SELECT DISTINCT match_date
        FROM matches
        WHERE sport = ? AND match_date >= ? AND match_date <= ? AND is_active = 1
        ORDER BY match_date
    ''', (sport, today, week_later))
    dates = cursor.fetchall()
    conn.close()
    return [date['match_date'] for date in dates]


def update_match_analysis(match_id, analysis_text, png_path=None):
    """Обновляет текст анализа и опционально путь к PNG."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if png_path:
        cursor.execute('''
            UPDATE matches
            SET analysis_text = ?, analysis_png_path = ?
            WHERE id = ?
        ''', (analysis_text, png_path, match_id))
    else:
        cursor.execute('''
            UPDATE matches
            SET analysis_text = ?
            WHERE id = ?
        ''', (analysis_text, match_id))
    conn.commit()
    conn.close()


def delete_match(match_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM matches WHERE id = ?', (match_id,))
    conn.commit()
    conn.close()


# Функции для пользователей
def get_or_create_user(user_id, username=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    if not user:
        cursor.execute('''
            INSERT INTO users (user_id, username, balance, total_analysis_bought)
            VALUES (?, ?, 0, 0)
        ''', (user_id, username))
        conn.commit()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
    conn.close()
    return user


# START TEMPORARY DISABLE BALANCE LOGIC — MVP PURCHASE FLOW (2026-02-16)
# def add_balance(user_id, amount):
#     conn = get_db_connection()
#     cursor = conn.cursor()
#     cursor.execute('''
#         UPDATE users
#         SET balance = balance + ?
#         WHERE user_id = ?
#     ''', (amount, user_id))
#     conn.commit()
#     conn.close()
# END TEMPORARY DISABLE BALANCE LOGIC
# TODO: Restore after MVP — see mvp_scan_report.md

def add_balance(user_id, amount):
    """Заглушка для MVP - баланс обновляется через DonationAlerts webhook"""
    pass


def purchase_analysis(user_id, match_id):
    """
    Создаёт pending purchase для DonationAlerts оплаты (MVP версия).

    TEMPORARY (2026-02-16): Убрана проверка баланса и списание средств.
    Теперь создаёт запись со status='pending' и уникальным token.

    Returns:
        tuple: (success: bool, message_or_token: str)
            - Если success=True: message_or_token содержит token для оплаты
            - Если success=False: message_or_token содержит сообщение об ошибке
    """
    import uuid
    from datetime import timedelta
    from config import ANALYSIS_PRICE_RUB

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT price FROM matches WHERE id = ?', (match_id,))
    match = cursor.fetchone()
    if not match:
        conn.close()
        return False, "Матч не найден"

    # START TEMPORARY DISABLE BALANCE LOGIC — MVP PURCHASE FLOW (2026-02-16)
    # Старая логика (закомментирована):
    # - Проверка баланса пользователя
    # - Списание средств
    # - Обновление total_analysis_bought
    #
    # price = match['price']
    # cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    # user = cursor.fetchone()
    # if not user:
    #     conn.close()
    #     return False, "Пользователь не найден"
    # if user['balance'] < price:
    #     conn.close()
    #     return False, f"Недостаточно средств. Нужно: {price} руб., у вас: {user['balance']} руб."
    # cursor.execute('''
    #     UPDATE users
    #     SET balance = balance - ?,
    #         total_analysis_bought = total_analysis_bought + 1
    #     WHERE user_id = ?
    # ''', (price, user_id))
    # END TEMPORARY DISABLE BALANCE LOGIC

    # Новая логика: создание pending purchase с token
    token = uuid.uuid4().hex[:12].upper()  # Уникальный 12-символьный код
    amount = ANALYSIS_PRICE_RUB * 100  # Цена в копейках (например, 2 руб = 200 коп)
    purchase_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    expires_at = (datetime.now() + timedelta(minutes=30)).strftime('%Y-%m-%d %H:%M:%S')

    cursor.execute('''
        INSERT INTO purchases (user_id, match_id, purchase_date, token, status, amount, expires_at)
        VALUES (?, ?, ?, ?, 'pending', ?, ?)
    ''', (user_id, match_id, purchase_date, token, amount, expires_at))
    conn.commit()
    conn.close()

    return True, token  # Возвращаем token вместо сообщения "Покупка успешна"


def has_purchased_analysis(user_id, match_id):
    """Проверяет, есть ли оплаченная покупка (status='paid') для данного матча."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id FROM purchases
        WHERE user_id = ? AND match_id = ? AND status = 'paid'
    ''', (user_id, match_id))
    purchase = cursor.fetchone()
    conn.close()
    return purchase is not None


def has_pending_purchase(user_id, match_id):
    """Проверяет, есть ли pending покупка для данного матча."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, token, expires_at FROM purchases
        WHERE user_id = ? AND match_id = ? AND status = 'pending'
    ''', (user_id, match_id))
    purchase = cursor.fetchone()
    conn.close()
    return purchase


def update_instruction_message_id(purchase_id, message_id):
    """Сохраняет message_id инструкции для последующего удаления."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE purchases
        SET instruction_message_id = ?
        WHERE id = ?
    ''', (message_id, purchase_id))
    conn.commit()
    conn.close()


def get_purchase_by_token(token):
    """Получает purchase по token (для listener)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, user_id, match_id, amount, status, donation_event_id, instruction_message_id
        FROM purchases
        WHERE token = ? AND status = 'pending'
    ''', (token,))
    purchase = cursor.fetchone()
    conn.close()
    return purchase


# START TEMPORARY DISABLE BALANCE LOGIC — MVP PURCHASE FLOW (2026-02-16)
# def get_user_balance(user_id):
#     conn = get_db_connection()
#     cursor = conn.cursor()
#     cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
#     result = cursor.fetchone()
#     conn.close()
#     return result['balance'] if result else 0
# END TEMPORARY DISABLE BALANCE LOGIC
# TODO: Restore after MVP — see mvp_scan_report.md

def get_user_balance(user_id):
    """Заглушка для MVP - баланс не используется"""
    return 0


def get_user_stats(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT balance, total_analysis_bought
        FROM users
        WHERE user_id = ?
    ''', (user_id,))
    stats = cursor.fetchone()
    # Отдельный запрос для количества покупок
    if stats:
        cursor.execute('SELECT COUNT(*) as purchased_count FROM purchases WHERE user_id = ?', (user_id,))
        purchase_count = cursor.fetchone()
        result = {
            'balance': stats['balance'],
            'total_analysis_bought': stats['total_analysis_bought'],
            'purchased_count': purchase_count['purchased_count'] if purchase_count else 0
        }
    else:
        result = None
    conn.close()
    return result


def get_all_users():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users ORDER BY created_at DESC')
    users = cursor.fetchall()
    conn.close()
    return users


# Функции для администраторов
def add_admin(user_id, username, added_by):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO admins (user_id, username, added_by)
            VALUES (?, ?, ?)
        ''', (user_id, username, added_by))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def remove_admin(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM admins WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()


def is_admin(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM admins WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None


def get_all_admins():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT a.user_id, a.username, a.added_at,
               u.username as added_by_username
        FROM admins a
        LEFT JOIN users u ON a.added_by = u.user_id
        ORDER BY a.added_at DESC
    ''')
    admins = cursor.fetchall()
    conn.close()
    return admins


def cleanup_old_purchases():
    """Удалить старые покупки (анализы хранятся 1 день после матча)"""
    import os
    conn = get_db_connection()
    cursor = conn.cursor()

    # Дата отсечки: вчера
    cutoff_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

    # Получаем пути к PNG файлам для старых матчей перед удалением
    cursor.execute('''
        SELECT analysis_png_path FROM matches
        WHERE match_date < ? AND analysis_png_path IS NOT NULL
    ''', (cutoff_date,))
    png_paths = [row['analysis_png_path'] for row in cursor.fetchall()]

    # Находим и удаляем покупки для матчей старше cutoff_date
    cursor.execute('''
        DELETE FROM purchases
        WHERE match_id IN (
            SELECT id FROM matches
            WHERE match_date < ?
        )
    ''', (cutoff_date,))

    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()

    # Удаляем PNG файлы
    deleted_png = 0
    for png_path in png_paths:
        if png_path and os.path.exists(png_path):
            try:
                os.remove(png_path)
                deleted_png += 1
            except Exception as e:
                logger.warning(f"Не удалось удалить PNG {png_path}: {e}")

    if deleted_png > 0:
        logger.info(f"Удалено PNG файлов: {deleted_png}")

    return deleted_count


def delete_finished_matches_without_purchases():
    """
    Удалить завершенные матчи (is_active=0) если на них нет покупок.
    Также удалить старые активные матчи (старше 1 дня).
    Удаляет также соответствующие PNG файлы анализов.
    """
    import os
    conn = get_db_connection()
    cursor = conn.cursor()

    # Получаем пути к PNG файлов перед удалением матчей
    cursor.execute('''
        SELECT analysis_png_path FROM matches
        WHERE (is_active = 0 OR match_date < date('now', '-1 day'))
        AND id NOT IN (SELECT DISTINCT match_id FROM purchases)
        AND analysis_png_path IS NOT NULL
    ''')
    png_paths = [row['analysis_png_path'] for row in cursor.fetchall()]

    # 1. Удаляем деактивированные матчи без покупок
    cursor.execute('''
        DELETE FROM matches
        WHERE is_active = 0
        AND id NOT IN (SELECT DISTINCT match_id FROM purchases)
    ''')
    deleted_inactive = cursor.rowcount

    # 2. Удаляем старые матчи (старше 1 дня) без покупок
    cutoff_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    cursor.execute('''
        DELETE FROM matches
        WHERE match_date < ?
        AND id NOT IN (SELECT DISTINCT match_id FROM purchases)
    ''', (cutoff_date,))
    deleted_old = cursor.rowcount

    conn.commit()
    conn.close()

    # Удаляем PNG файлы
    deleted_png = 0
    for png_path in png_paths:
        if png_path and os.path.exists(png_path):
            try:
                os.remove(png_path)
                deleted_png += 1
            except Exception as e:
                logger.warning(f"Не удалось удалить PNG {png_path}: {e}")

    if deleted_png > 0:
        logger.info(f"Удалено PNG файлов (без покупок): {deleted_png}")

    return deleted_inactive + deleted_old


def get_matches_by_date_filtered(sport, match_date):
    """
    Получить матчи по дате с фильтрацией прошедших.
    Не показывать матчи которые прошли более 3 часов назад.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Получаем все активные матчи на дату
    cursor.execute('''
        SELECT * FROM matches
        WHERE sport = ? AND match_date = ? AND is_active = 1
        ORDER BY match_time
    ''', (sport, match_date))
    matches = cursor.fetchall()
    conn.close()

    # Фильтруем по времени - не показываем матчи старше 3 часов
    now = datetime.now()
    filtered_matches = []

    for match in matches:
        try:
            # Парсим дату и время матча
            match_datetime_str = f"{match['match_date']} {match['match_time']}"
            match_datetime = datetime.strptime(match_datetime_str, '%Y-%m-%d %H:%M')

            # Вычисляем разницу (матч в МСК, мы тоже в МСК)
            time_diff = now - match_datetime

            # Показываем только если:
            # 1. Матч в будущем (time_diff < 0)
            # 2. Матч начался менее 3 часов назад (LIVE или недавно завершен)
            if time_diff.total_seconds() < 3 * 3600:  # 3 часа
                filtered_matches.append(match)

        except Exception:
            # Если не можем распарсить время - показываем матч
            filtered_matches.append(match)

    return filtered_matches
