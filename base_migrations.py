# database.py (КОРОТКАЯ ВЕРСИЯ ДЛЯ МИГРАЦИИ)
import sqlite3
from datetime import datetime, timedelta

def get_db_connection():
    conn = sqlite3.connect('sports_bot.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def migrate_database():
    """Добавить недостающие поля в таблицу matches"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    print("🔄 Миграция базы данных sports_bot.db...")
    
    # 1. Проверяем текущую структуру
    cursor.execute("PRAGMA table_info(matches)")
    columns = cursor.fetchall()
    
    print("\n📊 Текущие поля в таблице 'matches':")
    existing_columns = []
    for col in columns:
        print(f"  - {col[1]}: {col[2]}")
        existing_columns.append(col[1])
    
    # 2. Определяем какие поля нужно добавить
    fields_to_add = [
        ('league', 'TEXT'),
        ('venue', 'TEXT'),
        ('api_event_id', 'TEXT'),
        ('status', 'TEXT DEFAULT "Scheduled"'),
        ('created_at', 'TEXT DEFAULT CURRENT_TIMESTAMP')
    ]
    
    # 3. Добавляем недостающие поля
    added_fields = []
    for field_name, field_type in fields_to_add:
        if field_name not in existing_columns:
            try:
                cursor.execute(f'ALTER TABLE matches ADD COLUMN {field_name} {field_type}')
                added_fields.append(field_name)
                print(f"✅ Добавлено поле: {field_name}")
            except Exception as e:
                print(f"⚠️ Ошибка при добавлении {field_name}: {e}")
        else:
            print(f"✓ Поле {field_name} уже существует")
    # 4. Создаем индекс только если поле api_event_id существует
    if 'api_event_id' in existing_columns or 'api_event_id' in added_fields:
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_api_event_id ON matches(api_event_id)')
            print("✅ Создан индекс для api_event_id")
        except:
            print("⚠️ Не удалось создать индекс для api_event_id")
    conn.commit()
    # 5. Показываем итоговую структуру
    cursor.execute("PRAGMA table_info(matches)")
    final_columns = cursor.fetchall()
    print("\n📊 Итоговая структура таблицы 'matches':")
    for col in final_columns:
        print(f"  - {col[1]}: {col[2]}")
    conn.close()
    if added_fields:
        print(f"\n🎉 Миграция успешна! Добавлено полей: {', '.join(added_fields)}")
    else:
        print("\n✅ Все поля уже добавлены, миграция не требуется")

    return True

if __name__ == "__main__":
    migrate_database()