import sqlite3
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


STATIC_ADMIN_IDS = set()


def _get_system_admin_ids():
    """
    Возвращает список админов, заданных на уровне конфигурации/кода.
    Они считаются администраторами даже без записи в таблице admins.
    """
    ids = set(STATIC_ADMIN_IDS)
    try:
        from config import ADMIN_IDS
        ids.update(ADMIN_IDS)
    except ImportError:
        pass
    return ids


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
            token TEXT UNIQUE,
            status TEXT DEFAULT 'pending',
            amount REAL,
            expires_at TEXT,
            donation_event_id TEXT,
            instruction_message_id INTEGER,
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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS balance_topups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount_rub INTEGER NOT NULL,
            amount_kopeks INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            donation_event_id TEXT,
            return_match_id INTEGER,
            return_match_source TEXT,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS generation_jobs (
            match_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'running',
            owner TEXT,
            updated_at TEXT NOT NULL,
            error TEXT
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_topups_token ON balance_topups(token)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_topups_user_id ON balance_topups(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_topups_status ON balance_topups(status)')

    # Авто-миграция balance_topups
    cursor.execute("PRAGMA table_info(balance_topups)")
    topups_columns = [col[1] for col in cursor.fetchall()]
    if 'instruction_message_id' not in topups_columns:
        try:
            cursor.execute('ALTER TABLE balance_topups ADD COLUMN instruction_message_id INTEGER')
        except Exception as e:
            print(f"Не удалось добавить instruction_message_id в balance_topups: {e}")
    if 'return_match_id' not in topups_columns:
        try:
            cursor.execute('ALTER TABLE balance_topups ADD COLUMN return_match_id INTEGER')
        except Exception as e:
            print(f"Не удалось добавить return_match_id в balance_topups: {e}")
    if 'return_match_source' not in topups_columns:
        try:
            cursor.execute('ALTER TABLE balance_topups ADD COLUMN return_match_source TEXT')
        except Exception as e:
            print(f"Не удалось добавить return_match_source в balance_topups: {e}")
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
        ('analysis_png_path', 'TEXT'),
    ]
    for column_name, column_type in new_columns:
        if column_name not in existing_columns:
            try:
                cursor.execute(f'ALTER TABLE matches ADD COLUMN {column_name} {column_type}')
                print(f"Добавлено поле {column_name} в таблицу matches")
            except sqlite3.OperationalError as e:
                print(f"Не удалось добавить поле {column_name}: {e}")
    try:
        cursor.execute("ALTER TABLE matches ADD COLUMN coverage_ok INTEGER DEFAULT NULL")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE matches ADD COLUMN coverage_checked_at TEXT DEFAULT NULL")
    except Exception:
        pass

    # Индексы для matches
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_match_date ON matches(match_date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_api_event_id ON matches(api_event_id)')

    # Авто-миграция таблицы purchases (добавляем DA-поля если отсутствуют)
    cursor.execute("PRAGMA table_info(purchases)")
    purchases_columns = [col[1] for col in cursor.fetchall()]
    new_purchases_columns = [
        ('token', 'TEXT'),
        ('status', "TEXT DEFAULT 'paid'"),
        ('amount', 'INTEGER'),
        ('expires_at', 'TEXT'),
        ('donation_event_id', 'TEXT'),
    ]
    for column_name, column_type in new_purchases_columns:
        if column_name not in purchases_columns:
            try:
                cursor.execute(f'ALTER TABLE purchases ADD COLUMN {column_name} {column_type}')
                print(f"Добавлено поле {column_name} в таблицу purchases")
            except sqlite3.OperationalError as e:
                print(f"Не удалось добавить поле {column_name}: {e}")

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_purchases_token ON purchases(token)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_purchases_status ON purchases(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_purchases_user_id ON purchases(user_id)')
    # Миграция для старых БД: удаляем дубли paid-покупок, иначе unique-индекс не создастся.
    cursor.execute(
        '''
        DELETE FROM purchases
        WHERE status = 'paid'
          AND id NOT IN (
              SELECT MIN(id)
              FROM purchases
              WHERE status = 'paid'
              GROUP BY user_id, match_id
          )
        '''
    )
    # Один пользователь может иметь только одну paid-покупку на матч.
    cursor.execute(
        '''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_purchases_paid_user_match
        ON purchases(user_id, match_id)
        WHERE status = 'paid'
        '''
    )

    # Системные админы всегда присутствуют в таблице для корректной выдачи меню команд.
    for admin_id in _get_system_admin_ids():
        cursor.execute(
            '''
            INSERT OR IGNORE INTO admins (user_id, username, added_by)
            VALUES (?, ?, ?)
            ''',
            (admin_id, None, None)
        )

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
          AND coverage_ok = 1
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
    needs_commit = False

    if not user:
        from config import ANALYSIS_PRICE_RUB
        welcome_bonus = int(ANALYSIS_PRICE_RUB)
        cursor.execute('''
            INSERT INTO users (user_id, username, balance, total_analysis_bought)
            VALUES (?, ?, ?, 0)
        ''', (user_id, username, welcome_bonus))
        needs_commit = True
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
    elif username and user['username'] != username:
        cursor.execute(
            'UPDATE users SET username = ? WHERE user_id = ?',
            (username, user_id)
        )
        needs_commit = True

    # Если пользователь админ, синхронизируем username в таблице admins
    # (актуально для системных админов из .env и уже добавленных админов).
    if is_admin(user_id):
        cursor.execute('SELECT user_id, username FROM admins WHERE user_id = ?', (user_id,))
        admin_row = cursor.fetchone()
        if admin_row:
            if username and admin_row['username'] != username:
                cursor.execute(
                    'UPDATE admins SET username = ? WHERE user_id = ?',
                    (username, user_id)
                )
                needs_commit = True
        else:
            cursor.execute(
                '''
                INSERT OR IGNORE INTO admins (user_id, username, added_by)
                VALUES (?, ?, NULL)
                ''',
                (user_id, username)
            )
            needs_commit = True

    if needs_commit:
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
    """Пополняет баланс пользователя на указанную сумму (в рублях)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users
        SET balance = balance + ?
        WHERE user_id = ?
    ''', (amount, user_id))
    conn.commit()
    conn.close()


def get_user_balance(user_id):
    """Возвращает текущий баланс пользователя (в рублях)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return 0
    balance = row['balance']
    return balance if balance is not None else 0


def purchase_analysis(user_id, match_id):
    """
    Покупает анализ с баланса пользователя (мгновенная оплата).

    Проверяет баланс, списывает ANALYSIS_PRICE_RUB рублей,
    создаёт запись со status='paid'.

    Returns:
        tuple: (success: bool, message: str)
    """
    from config import ANALYSIS_PRICE_RUB

    conn = get_db_connection()
    cursor = conn.cursor()
    price = ANALYSIS_PRICE_RUB

    try:
        # Лочим БД на запись, чтобы два параллельных клика не создали двойную покупку.
        cursor.execute('BEGIN IMMEDIATE')

        cursor.execute('SELECT 1 FROM matches WHERE id = ?', (match_id,))
        match = cursor.fetchone()
        if not match:
            conn.rollback()
            return False, "Матч не найден"

        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        if not user:
            conn.rollback()
            return False, "Пользователь не найден"

        cursor.execute(
            '''
            SELECT id FROM purchases
            WHERE user_id = ? AND match_id = ? AND status = 'paid'
            LIMIT 1
            ''',
            (user_id, match_id)
        )
        if cursor.fetchone():
            conn.rollback()
            return False, "Анализ уже приобретен"

        if user['balance'] < price:
            conn.rollback()
            return False, (
                f"Недостаточно средств. Нужно: {price} руб., "
                f"у вас: {user['balance']} руб."
            )

        cursor.execute(
            '''
            UPDATE users
            SET balance = balance - ?,
                total_analysis_bought = total_analysis_bought + 1
            WHERE user_id = ? AND balance >= ?
            ''',
            (price, user_id, price)
        )
        if cursor.rowcount == 0:
            conn.rollback()
            return False, "Недостаточно средств."

        purchase_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute(
            '''
            INSERT INTO purchases (user_id, match_id, purchase_date, status, amount)
            VALUES (?, ?, ?, 'paid', ?)
            ''',
            (user_id, match_id, purchase_date, price * 100)
        )

        conn.commit()
        return True, "Покупка успешна"
    except sqlite3.IntegrityError:
        conn.rollback()
        return False, "Анализ уже приобретен"
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _parse_dt_safe(raw: str):
    """Парсер datetime с fallback для кривых/пустых значений."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw, '%Y-%m-%d %H:%M:%S')
    except Exception:
        return None


def acquire_generation_job(match_id, owner=None, stale_after_seconds=300):
    """
    Пытается захватить lock генерации для match_id.

    Returns:
        bool: True если lock захвачен текущим процессом.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now()
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')

    try:
        cursor.execute('BEGIN IMMEDIATE')
        cursor.execute(
            '''
            SELECT status, updated_at
            FROM generation_jobs
            WHERE match_id = ?
            ''',
            (match_id,)
        )
        row = cursor.fetchone()

        if not row:
            cursor.execute(
                '''
                INSERT INTO generation_jobs (match_id, status, owner, updated_at, error)
                VALUES (?, 'running', ?, ?, NULL)
                ''',
                (match_id, owner, now_str)
            )
            conn.commit()
            return True

        status = (row['status'] or '').lower()
        updated_at = _parse_dt_safe(row['updated_at'])
        is_stale = (
            updated_at is None
            or (now - updated_at).total_seconds() > int(stale_after_seconds)
        )

        if status == 'running' and not is_stale:
            conn.rollback()
            return False

        cursor.execute(
            '''
            UPDATE generation_jobs
            SET status = 'running',
                owner = ?,
                updated_at = ?,
                error = NULL
            WHERE match_id = ?
            ''',
            (owner, now_str, match_id)
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()


def finish_generation_job(match_id, status='done', error=None):
    """Завершает lock генерации для match_id."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        cursor.execute(
            '''
            INSERT INTO generation_jobs (match_id, status, owner, updated_at, error)
            VALUES (?, ?, NULL, ?, ?)
            ON CONFLICT(match_id) DO UPDATE SET
                status = excluded.status,
                owner = NULL,
                updated_at = excluded.updated_at,
                error = excluded.error
            ''',
            (match_id, status, now_str, error)
        )
        conn.commit()
    finally:
        conn.close()


def wait_for_match_analysis(match_id, timeout_seconds=90, poll_interval=0.5):
    """
    Ждёт появления analysis_text в matches для данного матча.
    Возвращает True, если текст появился в пределах timeout.
    """
    import time
    deadline = time.monotonic() + float(timeout_seconds)
    while time.monotonic() < deadline:
        match = get_match_by_id(match_id)
        if match:
            if isinstance(match, dict):
                analysis_text = str(match.get('analysis_text') or '').strip()
            else:
                analysis_text = str(match['analysis_text'] or '').strip()
            if analysis_text:
                return True
        time.sleep(float(poll_interval))
    return False


def create_balance_topup(user_id, amount_rub=0):
    """
    Создаёт pending запись пополнения баланса.

    amount_rub=0 означает «любая сумма» (гибкий топап):
    баланс пополнится на фактически полученную сумму из DA.

    Returns:
        str: уникальный token для DA комментария
    """
    import uuid
    token = uuid.uuid4().hex[:12].upper()
    amount_kopeks = amount_rub * 100
    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    expires_at = (datetime.now() + timedelta(minutes=30)).strftime('%Y-%m-%d %H:%M:%S')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO balance_topups
        (user_id, amount_rub, amount_kopeks, token, status, created_at, expires_at)
        VALUES (?, ?, ?, ?, 'pending', ?, ?)
    ''', (user_id, amount_rub, amount_kopeks, token, created_at, expires_at))
    conn.commit()
    conn.close()
    return token


def update_topup_instruction_message(token, message_id):
    """Сохраняет message_id инструкции пополнения для последующего редактирования."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE balance_topups SET instruction_message_id = ? WHERE token = ?',
        (message_id, token)
    )
    conn.commit()
    conn.close()


def update_topup_return_target(token, match_id=None, match_source='browse'):
    """Сохраняет цель возврата к матчу после пополнения (для автозачёта listener'ом)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        '''
        UPDATE balance_topups
        SET return_match_id = ?, return_match_source = ?
        WHERE token = ?
        ''',
        (match_id, match_source if match_id else None, token)
    )
    conn.commit()
    conn.close()


def get_topup_by_token(token):
    """Возвращает pending запись пополнения по token."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''
        SELECT * FROM balance_topups
        WHERE token = ? AND status = 'pending' AND expires_at > ?
    ''', (token, now))
    row = cursor.fetchone()
    conn.close()
    return row


def expire_pending_topups():
    """Переводит истёкшие pending пополнения в expired и удаляет expired старше 12ч."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''
        UPDATE balance_topups
        SET status = 'expired'
        WHERE status = 'pending' AND expires_at <= ?
    ''', (now,))
    expired_count = cursor.rowcount

    # Удаляем expired записи старше 12 часов
    cutoff = (datetime.now() - timedelta(hours=12)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''
        DELETE FROM balance_topups
        WHERE status = 'expired' AND expires_at <= ?
    ''', (cutoff,))
    deleted_count = cursor.rowcount

    conn.commit()
    conn.close()
    if deleted_count > 0:
        logger.info(f"Удалено старых expired topups: {deleted_count}")
    return expired_count


def get_pending_topup_by_user(user_id):
    """
    Возвращает актуальный pending топап пользователя (не истёкший).

    Используется чтобы повторно показать тот же код при повторном
    входе в меню пополнения — пользователь не теряет свой токен.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''
        SELECT * FROM balance_topups
        WHERE user_id = ? AND status = 'pending' AND expires_at > ?
        ORDER BY created_at DESC
        LIMIT 1
    ''', (user_id, now))
    row = cursor.fetchone()
    conn.close()
    return row


def reset_user_balance(user_id):
    """Обнуляет баланс пользователя (админская операция)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = 0 WHERE user_id = ?', (user_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def get_any_topup_by_token(token):
    """Возвращает любую запись пополнения по token (pending или paid)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM balance_topups WHERE token = ?', (token,))
    row = cursor.fetchone()
    conn.close()
    return row


def is_donation_event_used(donation_event_id):
    """Проверяет, был ли уже засчитан донат с данным donation_event_id."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id FROM balance_topups WHERE donation_event_id = ?',
        (str(donation_event_id),)
    )
    row = cursor.fetchone()
    conn.close()
    return row is not None


def complete_balance_topup(topup_id, donation_event_id, received_amount_rub=None):
    """
    Помечает пополнение как выполненное и пополняет баланс пользователя.

    received_amount_rub: фактически полученная сумма (для гибких топапов
    с amount_rub=0). Если None — используется amount_rub из записи топапа.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        'SELECT user_id, amount_rub FROM balance_topups WHERE id = ?',
        (topup_id,)
    )
    topup = cursor.fetchone()
    if not topup:
        conn.close()
        return False

    # Определяем сколько реально зачислить
    amount_to_credit = (
        received_amount_rub
        if received_amount_rub is not None
        else topup['amount_rub']
    )

    # Обновляем статус и фактическую сумму в записи топапа
    cursor.execute('''
        UPDATE balance_topups
        SET status = 'paid', donation_event_id = ?, amount_rub = ?
        WHERE id = ?
    ''', (donation_event_id, amount_to_credit, topup_id))

    # Пополняем баланс (COALESCE защищает от NULL у старых пользователей)
    cursor.execute('''
        UPDATE users SET balance = COALESCE(balance, 0) + ?
        WHERE user_id = ?
    ''', (amount_to_credit, topup['user_id']))

    conn.commit()
    conn.close()
    return True


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
    # Системные админы из конфигурации/кода всегда имеют права
    if user_id in _get_system_admin_ids():
        return True
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

    # Добавляем системных админов в выдачу (на случай, если init_db еще не запускался).
    existing_ids = {admin['user_id'] for admin in admins}
    for admin_id in _get_system_admin_ids():
        if admin_id not in existing_ids:
            admins.append({
                'user_id': admin_id,
                'username': None,
                'added_at': None,
                'added_by_username': None,
            })
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
        WHERE sport = ? AND match_date = ? AND is_active = 1 AND coverage_ok = 1
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
