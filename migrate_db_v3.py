# -*- coding: utf-8 -*-
"""
Миграция БД v3: удаление ненужных полей из таблицы matches.

Удаляемые поля:
- venue (не отображается в UI, не нужно для fetching)
- home_score (не применимо для будущих матчей)
- away_score (не применимо для будущих матчей)
- round (дублируется в тексте league)
- status (не используется в UI и генерации)

Оставляемые поля:
- id, sport, team1, team2, match_date, match_time, league
- price, is_active, created_at, analysis_text
- home_team_id, away_team_id, api_event_id (нужны для on-demand fetching)
- source, match_datetime (трассировка)
"""
import sqlite3
import shutil
from datetime import datetime


def migrate():
    """Выполнить миграцию с бэкапом"""
    db_path = 'sports_bot.db'
    backup_path = f'sports_bot.db.backup_v3_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

    print("="*60)
    print("МИГРАЦИЯ БД v3: Удаление ненужных полей")
    print("="*60)

    # 1. Бэкап
    print(f"\n[1/4] Создание бэкапа: {backup_path}")
    try:
        shutil.copy(db_path, backup_path)
        print(f"[OK] Бэкап создан: {backup_path}")
    except FileNotFoundError:
        print("[ERROR] БД не найдена! Запустите database.init_db() сначала.")
        return
    except Exception as e:
        print(f"[ERROR] Ошибка создания бэкапа: {e}")
        return

    # 2. Подключение к БД
    print("\n[2/4] Подключение к БД...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 3. Проверка текущей схемы
    print("\n[3/4] Проверка текущей схемы...")
    cursor.execute("PRAGMA table_info(matches)")
    columns_before = cursor.fetchall()
    print(f"Текущие поля ({len(columns_before)}):")
    for col in columns_before:
        print(f"  - {col[1]} ({col[2]})")

    # 4. Создание новой таблицы с упрощённой схемой
    print("\n[4/4] Миграция таблицы matches...")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS matches_new (
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
    print("[OK] Создана таблица matches_new")

    # Копирование данных (только оставшиеся поля)
    cursor.execute('''
        INSERT INTO matches_new
        (id, sport, team1, team2, match_date, match_time, league,
         api_event_id, source, home_team_id, away_team_id, match_datetime,
         analysis_text, price, is_active, created_at)
        SELECT
        id, sport, team1, team2, match_date, match_time, league,
        api_event_id, source, home_team_id, away_team_id, match_datetime,
        analysis_text, price, is_active, created_at
        FROM matches
    ''')
    rows_copied = cursor.rowcount
    print(f"[OK] Скопировано {rows_copied} записей")

    # Замена таблиц
    cursor.execute('DROP TABLE matches')
    cursor.execute('ALTER TABLE matches_new RENAME TO matches')
    print("[OK] Таблица matches обновлена")

    # Восстановление индексов
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_match_date ON matches(match_date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_api_event_id ON matches(api_event_id)')
    print("[OK] Индексы восстановлены")

    conn.commit()

    # Проверка результата
    print("\n[ВЕРИФИКАЦИЯ] Проверка новой схемы...")
    cursor.execute("PRAGMA table_info(matches)")
    columns_after = cursor.fetchall()
    print(f"Новые поля ({len(columns_after)}):")
    for col in columns_after:
        print(f"  - {col[1]} ({col[2]})")

    conn.close()

    print("\n" + "="*60)
    print("МИГРАЦИЯ ЗАВЕРШЕНА")
    print("="*60)
    print(f"Было полей: {len(columns_before)}")
    print(f"Стало полей: {len(columns_after)}")
    print(f"Удалено полей: {len(columns_before) - len(columns_after)}")
    print(f"Скопировано записей: {rows_copied}")
    print(f"Бэкап: {backup_path}")
    print("\nУдалённые поля:")
    removed_fields = set(col[1] for col in columns_before) - set(col[1] for col in columns_after)
    for field in sorted(removed_fields):
        print(f"  - {field}")
    print("="*60)


if __name__ == '__main__':
    migrate()
