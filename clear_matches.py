import database

# Удаляем все матчи из БД
conn = database.get_db_connection()
cursor = conn.cursor()

cursor.execute("DELETE FROM matches")
affected_rows = cursor.rowcount

conn.commit()
conn.close()

print(f"Удалено матчей: {affected_rows}")
print("Все матчи удалены из базы данных!")
