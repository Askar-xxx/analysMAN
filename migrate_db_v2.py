"""
Миграция БД v2: удаление h2h/standings/apif/raw_json полей из matches,
удаление apif_team_id из teams. Создаёт бэкап перед миграцией.
"""
import sqlite3
import shutil
import os
from datetime import datetime

DB_PATH = 'sports_bot.db'


def migrate():
    if not os.path.exists(DB_PATH):
        print(f"БД {DB_PATH} не найдена, миграция не требуется")
        return

    # Бэкап
    backup_path = f'{DB_PATH}.backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    shutil.copy2(DB_PATH, backup_path)
    print(f"Бэкап создан: {backup_path}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Проверяем нужна ли миграция matches
    cursor.execute("PRAGMA table_info(matches)")
    columns = [col[1] for col in cursor.fetchall()]

    removed_cols = [
        'h2h_json', 'h2h_fetched_at', 'standings_json', 'standings_fetched_at',
        'apif_stats_json', 'apif_stats_fetched_at',
        'apif_injuries_json', 'apif_injuries_fetched_at',
        'apif_full_standings_json', 'apif_standings_fetched_at',
        'apif_top_scorers_json', 'apif_scorers_fetched_at',
        'raw_json',
    ]

    needs_migration = any(col in columns for col in removed_cols)

    if needs_migration:
        print("Миграция таблицы matches...")
        # Список полей которые оставляем
        keep_cols = [c for c in columns if c not in removed_cols]
        cols_str = ', '.join(keep_cols)

        cursor.execute(f'''
            CREATE TABLE matches_new AS
            SELECT {cols_str} FROM matches
        ''')
        cursor.execute('DROP TABLE matches')
        cursor.execute('ALTER TABLE matches_new RENAME TO matches')

        # Пересоздаём индексы
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_match_date ON matches(match_date)')
        if 'api_event_id' in keep_cols:
            cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_api_event_id ON matches(api_event_id)')

        print(f"matches: удалены столбцы {[c for c in removed_cols if c in columns]}")
    else:
        print("Таблица matches уже в актуальном формате")

    # Проверяем нужна ли миграция teams
    cursor.execute("PRAGMA table_info(teams)")
    teams_columns = [col[1] for col in cursor.fetchall()]

    if 'apif_team_id' in teams_columns:
        print("Миграция таблицы teams...")
        keep_cols = [c for c in teams_columns if c != 'apif_team_id']
        cols_str = ', '.join(keep_cols)

        cursor.execute(f'''
            CREATE TABLE teams_new AS
            SELECT {cols_str} FROM teams
        ''')
        cursor.execute('DROP TABLE teams')
        cursor.execute('ALTER TABLE teams_new RENAME TO teams')

        print("teams: удалён столбец apif_team_id")
    else:
        print("Таблица teams уже в актуальном формате")

    conn.commit()
    conn.close()
    print("Миграция завершена успешно!")


if __name__ == '__main__':
    migrate()
