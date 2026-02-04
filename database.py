import sqlite3
from datetime import datetime, timedelta


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
            analysis_text TEXT,
            price INTEGER DEFAULT 150,
            is_active BOOLEAN DEFAULT 1
        )
    ''')
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
    conn.commit()
    conn.close()


# Функции для матчей
def add_match(sport, team1, team2, match_date, match_time, analysis_text=None,
              price=150):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO matches (sport, team1, team2, match_date, match_time,
                   analysis_text, price)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (sport, team1, team2, match_date, match_time, analysis_text, price))
    match_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return match_id


def create_match(sport, team1, team2, match_date, match_time, price=150):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO matches (sport, team1, team2, match_date, match_time,
                   price)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (sport, team1, team2, match_date, match_time, price))
    match_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return match_id


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


# Инициализация при импорте
init_db()
