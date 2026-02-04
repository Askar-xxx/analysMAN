import database
from datetime import datetime

# Удаляем старый матч (опционально)
conn = database.get_db_connection()
cursor = conn.cursor()
cursor.execute("DELETE FROM matches WHERE match_date = '2024-01-20'")
conn.commit()
conn.close()

# Добавляем матч на СЕГОДНЯ
today = datetime.now().strftime('%Y-%m-%d')
print(f"Добавляю матч на СЕГОДНЯШНЮЮ дату: {today}")

database.add_match(
    sport='football',
    team1='МЮ',
    team2='Реал',
    match_date=today,  # СЕГОДНЯ!
    match_time='20:00',
    analysis_text='Прогноз: обе забьют. Основная ставка: тотал больше 2.5'
)

print("Тестовый матч добавлен на сегодня!")
