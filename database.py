import sqlite3
from datetime import datetime, timedelta


def get_db_connection():
    conn = sqlite3.connect('sports_bot.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # ОБНОВЛЕННАЯ ТАБЛИЦА matches
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sport TEXT NOT NULL,
            team1 TEXT NOT NULL,
            team2 TEXT NOT NULL,
            match_date TEXT NOT NULL,
            match_time TEXT NOT NULL,
            league TEXT,
            venue TEXT,
            api_event_id TEXT UNIQUE,
            raw_json TEXT,
            source TEXT,
            home_team_id TEXT,
            away_team_id TEXT,
            home_score INTEGER,
            away_score INTEGER,
            match_datetime TEXT,
            status TEXT DEFAULT 'Scheduled',
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
    # Список новых полей для добавления
    new_columns = [
        ('league', 'TEXT'),
        ('venue', 'TEXT'),
        ('api_event_id', 'TEXT'),
        ('status', 'TEXT DEFAULT "Scheduled"'),
        ('created_at', 'TEXT DEFAULT CURRENT_TIMESTAMP'),
        ('raw_json', 'TEXT'),
        ('source', 'TEXT'),
        ('home_team_id', 'TEXT'),
        ('away_team_id', 'TEXT'),
        ('home_score', 'INTEGER'),
        ('away_score', 'INTEGER'),
        ('match_datetime', 'TEXT'),
    ]
    for column_name, column_type in new_columns:
        if column_name not in existing_columns:
            try:
                cursor.execute(f'ALTER TABLE matches ADD COLUMN {column_name} {column_type}')
                print(f"✅ Добавлено поле {column_name} в таблицу matches")
            except sqlite3.OperationalError as e:
                print(f"⚠️ Не удалось добавить поле {column_name}: {e}")
    # Индексы создаём ПОСЛЕ миграции, чтобы столбцы гарантированно существовали
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_match_date ON matches(match_date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_api_event_id ON matches(api_event_id)')
    conn.commit()
    conn.close()
    print("✅ База данных инициализирована")


# ОБНОВЛЕННАЯ ФУНКЦИЯ ДОБАВЛЕНИЯ МАТЧА
def add_match(sport, team1, team2, match_date, match_time,
              analysis_text=None, price=150, league=None, venue=None,
              api_event_id=None, status='Scheduled'):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO matches (sport, team1, team2, match_date, match_time,
                   analysis_text, price, league, venue, api_event_id, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (sport, team1, team2, match_date, match_time,
          analysis_text, price, league, venue, api_event_id, status))
    match_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return match_id


# ОБНОВЛЕННАЯ ФУНКЦИЯ СОЗДАНИЯ МАТЧА (для админов)
def create_match(sport, team1, team2, match_date, match_time,
                 price=150, league=None, venue=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO matches (sport, team1, team2, match_date, match_time,
                   price, league, venue, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Scheduled')
    ''', (sport, team1, team2, match_date, match_time,
          price, league, venue))
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
    - league, venue, api_event_id, status (опционально)
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
         league, venue, api_event_id, status, price)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        match_data.get('sport', 'football'),
        match_data['team1'],
        match_data['team2'],
        match_data['match_date'],
        match_data['match_time'],
        match_data.get('league'),
        match_data.get('venue'),
        match_data.get('api_event_id'),
        match_data.get('status', 'Scheduled'),
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
    print("🔍 Проверка структуры базы данных...")
    # Проверяем таблицу matches
    cursor.execute("PRAGMA table_info(matches)")
    columns = cursor.fetchall()
    print("📊 Таблица 'matches':")
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
        print("\n⚠️  Отсутствующие столбцы:")
        for col_name, col_type in missing_columns:
            print(f"  - {col_name}: {col_type}")
        # Добавляем недостающие столбцы
        print("\n🔄 Добавление недостающих столбцов...")
        for col_name, col_type in missing_columns:
            try:
                cursor.execute(f'ALTER TABLE matches ADD COLUMN {col_name} {col_type}')
                print(f"✅ Добавлен столбец: {col_name}")
            except Exception as e:
                print(f"❌ Ошибка при добавлении {col_name}: {e}")
    else:
        print("✅ Все необходимые столбцы присутствуют")
    conn.commit()
    conn.close()
    return len(missing_columns) == 0


def get_purchased_matches_by_user(user_id):
    """Получить все купленные матчи пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT m.*, p.purchase_date
        FROM matches m
        JOIN purchases p ON m.id = p.match_id
        WHERE p.user_id = ?
        ORDER BY m.match_date DESC, m.match_time DESC
    ''', (user_id,))
    matches = cursor.fetchall()
    conn.close()
    return matches


def get_purchased_matches_by_sport(user_id, sport):
    """Получить купленные матчи пользователя по виду спорта"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT m.*, p.purchase_date
        FROM matches m
        JOIN purchases p ON m.id = p.match_id
        WHERE p.user_id = ? AND m.sport = ?
        ORDER BY m.match_date DESC, m.match_time DESC
    ''', (user_id, sport))
    matches = cursor.fetchall()
    conn.close()
    return matches


def get_purchased_dates_by_sport(user_id, sport):
    """Получить даты купленных матчей по виду спорта"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DISTINCT m.match_date
        FROM matches m
        JOIN purchases p ON m.id = p.match_id
        WHERE p.user_id = ? AND m.sport = ?
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


# Функция для получения матчей на конкретную дату
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


def get_match_by_id(match_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM matches WHERE id = ?', (match_id,))
    match = cursor.fetchone()
    conn.close()
    return match


def update_match_analysis(match_id, analysis_text):
    conn = get_db_connection()
    cursor = conn.cursor()
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


def get_all_matches():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM matches ORDER BY match_date DESC, match_time DESC')
    matches = cursor.fetchall()
    conn.close()
    return matches


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


def add_balance(user_id, amount):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users
        SET balance = balance + ?
        WHERE user_id = ?
    ''', (amount, user_id))
    conn.commit()
    conn.close()


def purchase_analysis(user_id, match_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT price FROM matches WHERE id = ?', (match_id,))
    match = cursor.fetchone()
    if not match:
        conn.close()
        return False, "Матч не найден"
    price = match['price']
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        return False, "Пользователь не найден"
    if user['balance'] < price:
        conn.close()
        return False, f"Недостаточно средств. Нужно: {price} руб., у вас: {user['balance']} руб."
    cursor.execute('''
        UPDATE users
        SET balance = balance - ?,
            total_analysis_bought = total_analysis_bought + 1
        WHERE user_id = ?
    ''', (price, user_id))
    purchase_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''
        INSERT INTO purchases (user_id, match_id, purchase_date)
        VALUES (?, ?, ?)
    ''', (user_id, match_id, purchase_date))
    conn.commit()
    conn.close()
    return True, "Покупка успешна"


def has_purchased_analysis(user_id, match_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id FROM purchases
        WHERE user_id = ? AND match_id = ?
    ''', (user_id, match_id))
    purchase = cursor.fetchone()
    conn.close()
    return purchase is not None


def get_user_balance(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result['balance'] if result else 0


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
    except:
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
