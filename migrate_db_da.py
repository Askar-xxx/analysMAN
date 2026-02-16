# -*- coding: utf-8 -*-
"""
Миграция БД для DonationAlerts интеграции: расширение таблицы purchases.

Добавляемые поля:
- token TEXT UNIQUE (уникальный код для оплаты через DA)
- status TEXT DEFAULT 'pending' (статус: pending/paid/expired)
- amount INTEGER (сумма в копейках, например 150 руб = 15000)
- expires_at TEXT (время истечения токена, ISO format)
- donation_event_id TEXT (ID события от DonationAlerts для идемпотентности)

Существующие поля (сохраняются):
- id, user_id, match_id, purchase_date
"""
import sqlite3
import shutil
from datetime import datetime


def migrate():
    """Выполнить миграцию с бэкапом"""
    db_path = 'sports_bot.db'
    backup_path = f'sports_bot.db.backup_da_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

    print("="*60)
    print("МИГРАЦИЯ БД: DonationAlerts Integration")
    print("="*60)

    # 1. Бэкап
    print(f"\n[1/5] Создание бэкапа: {backup_path}")
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
    print("\n[2/5] Подключение к БД...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 3. Проверка текущей схемы
    print("\n[3/5] Проверка текущей схемы таблицы purchases...")
    cursor.execute("PRAGMA table_info(purchases)")
    columns_before = cursor.fetchall()
    print(f"Текущие поля ({len(columns_before)}):")
    for col in columns_before:
        print(f"  - {col[1]} ({col[2]})")

    # 4. Проверка существующих записей
    cursor.execute('SELECT COUNT(*) FROM purchases')
    existing_count = cursor.fetchone()[0]
    print(f"\n[INFO] Найдено {existing_count} существующих покупок")

    # 5. Создание новой таблицы с расширенной схемой
    print("\n[4/5] Миграция таблицы purchases...")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS purchases_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            match_id INTEGER NOT NULL,
            purchase_date TEXT NOT NULL,
            token TEXT UNIQUE,
            status TEXT DEFAULT 'paid',
            amount INTEGER,
            expires_at TEXT,
            donation_event_id TEXT,
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            FOREIGN KEY (match_id) REFERENCES matches (id)
        )
    ''')
    print("[OK] Создана таблица purchases_new")

    # Копирование данных (существующие покупки получают status='paid')
    # Для старых записей: token=NULL (они уже оплачены через старую систему)
    cursor.execute('''
        INSERT INTO purchases_new
        (id, user_id, match_id, purchase_date, token, status, amount, expires_at, donation_event_id)
        SELECT
        id, user_id, match_id, purchase_date,
        NULL,  -- token (старые покупки без токена)
        'paid',  -- status (все старые покупки уже оплачены)
        15000,  -- amount (по умолчанию 150 руб = 15000 копеек)
        NULL,  -- expires_at (не применимо для оплаченных)
        NULL   -- donation_event_id (не применимо)
        FROM purchases
    ''')
    rows_copied = cursor.rowcount
    print(f"[OK] Скопировано {rows_copied} записей (статус: 'paid', amount: 15000)")

    # Замена таблиц
    cursor.execute('DROP TABLE purchases')
    cursor.execute('ALTER TABLE purchases_new RENAME TO purchases')
    print("[OK] Таблица purchases обновлена")

    # Создание индексов
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_purchases_token ON purchases(token)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_purchases_status ON purchases(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_purchases_user_id ON purchases(user_id)')
    print("[OK] Индексы созданы")

    conn.commit()

    # Проверка результата
    print("\n[5/5] ВЕРИФИКАЦИЯ - Проверка новой схемы...")
    cursor.execute("PRAGMA table_info(purchases)")
    columns_after = cursor.fetchall()
    print(f"Новые поля ({len(columns_after)}):")
    for col in columns_after:
        default_val = f", default={col[4]}" if col[4] else ""
        nullable = "" if col[3] else ", nullable"
        print(f"  - {col[1]} ({col[2]}{default_val}{nullable})")

    # Проверка данных
    cursor.execute('SELECT COUNT(*) FROM purchases WHERE status = "paid"')
    paid_count = cursor.fetchone()[0]
    print(f"\n[ВЕРИФИКАЦИЯ] Записей со статусом 'paid': {paid_count}")

    conn.close()

    print("\n" + "="*60)
    print("МИГРАЦИЯ ЗАВЕРШЕНА")
    print("="*60)
    print(f"Было полей: {len(columns_before)}")
    print(f"Стало полей: {len(columns_after)}")
    print(f"Добавлено полей: {len(columns_after) - len(columns_before)}")
    print(f"Скопировано записей: {rows_copied}")
    print(f"Бэкап: {backup_path}")
    print("\nДобавленные поля:")
    added_fields = set(col[1] for col in columns_after) - set(col[1] for col in columns_before)
    for field in sorted(added_fields):
        print(f"  + {field}")
    print("\n" + "="*60)
    print("NEXT STEPS:")
    print("1. Обновите database.py - функцию purchase_analysis()")
    print("2. Обновите user_handlers.py - handle_purchase()")
    print("3. Создайте webhook_server.py для DonationAlerts")
    print("="*60)


if __name__ == '__main__':
    migrate()
