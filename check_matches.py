import database
from datetime import datetime

# Проверяем все матчи в базе
conn = database.get_db_connection()
cursor = conn.cursor()
# Смотрим структуру таблицы
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print("Таблицы в базе:", tables)
# Смотрим все матчи
cursor.execute("SELECT * FROM matches")
matches = cursor.fetchall()
print(f"\nВсего матчей в базе: {len(matches)}")
for match in matches:
    print(f"ID: {match['id']}")
    print(f"Спорт: {match['sport']}")
    print(f"Команды: {match['team1']} vs {match['team2']}")
    print(f"Дата: {match['match_date']}")
    print(f"Время: {match['match_time']}")
    print(f"Аналитика: {match['analysis_text'][:50] if match['analysis_text'] else 'Нет'}")
    print("-" * 30)
conn.close()
# Проверяем матчи на сегодня
today = datetime.now().strftime('%Y-%m-%d')
print(f"\nСегодняшняя дата: {today}")
today_matches = database.get_today_matches('football')
print(f"Матчей на сегодня: {len(today_matches)}")
