# -*- coding: utf-8 -*-
"""
Тестовый скрипт для проверки полного цикла генерации анализа v2.0:
1. Инициализация БД
2. Синхронизация матчей из Premium TheSportsDB
3. On-demand fetching данных (H2H, standings, form)
4. Генерация анализа через DeepSeek API
5. Постобработка и вывод результата
"""
import asyncio
import os
import sys
from datetime import datetime

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Проверка наличия БД
db_exists = os.path.exists('sports_bot.db')
print("=" * 60)
print("ТЕСТИРОВАНИЕ ГЕНЕРАЦИИ АНАЛИЗА v2.0")
print("=" * 60 + "\n")
print(f"БД существует: {'Да' if db_exists else 'Нет (будет создана)'}\n")

# 1. Инициализация БД
print("[Шаг 1] Инициализация БД")
import database  # noqa: E402
database.init_db()
print("[OK] БД инициализирована\n")

# 2. Синхронизация матчей
print("[Шаг 2] Синхронизация матчей из TheSportsDB Premium API")
print("         Режим: top3 (3 матча на ближайшие 3 дня)")

from sync_matches import SportsDBSyncer  # noqa: E402

syncer = SportsDBSyncer(mode='top3', limit=3)
matches = syncer.sync()

if not matches:
    print("[ERROR] Не удалось получить матчи из API")
    sys.exit(1)

results = syncer.save_matches_to_db(matches)
print("[OK] Синхронизация завершена:")
print(f"     - Найдено матчей: {results['total']}")
print(f"     - Добавлено новых: {results['inserted']}")
print(f"     - Пропущено (дубли): {results['skipped']}")
print(f"     - Ошибок: {results['errors']}\n")

# 3. Выбор матча для тестирования
print("[Шаг 3] Выбор матча для тестирования")

conn = database.get_db_connection()
cursor = conn.cursor()
cursor.execute('''
    SELECT * FROM matches
    WHERE sport = 'football'
    AND home_team_id IS NOT NULL
    AND away_team_id IS NOT NULL
    AND api_event_id IS NOT NULL
    ORDER BY match_datetime ASC
    LIMIT 1
''')
match_row = cursor.fetchone()
conn.close()

if not match_row:
    print("[ERROR] Нет подходящих матчей в БД")
    sys.exit(1)

match = dict(match_row)
print("[OK] Выбран матч:")
print(f"     - {match['team1']} vs {match['team2']}")
print(f"     - Лига: {match.get('league', 'N/A')}")
print(f"     - Дата: {match.get('match_date', 'N/A')} {match.get('match_time', 'N/A')}")
print(f"     - API Event ID: {match.get('api_event_id', 'N/A')}")
print(f"     - Home Team ID: {match.get('home_team_id', 'N/A')}")
print(f"     - Away Team ID: {match.get('away_team_id', 'N/A')}\n")

# 4. On-demand fetching
print("[Шаг 4] On-demand fetching данных")
print("         Запрос H2H, standings, form из Premium API...")

from match_data_fetcher import (  # noqa: E402
    MatchDataFetcher,
    build_enriched_context
)

start_time = datetime.now()
fetcher = MatchDataFetcher()
enriched_data = fetcher.fetch_match_data(match)
fetch_duration = (datetime.now() - start_time).total_seconds()

print(f"[OK] Данные получены за {fetch_duration:.2f} сек:")
print(f"     - H2H матчей: {len(enriched_data.get('h2h', []))}")
standings_ok = (enriched_data.get('standings') and
                enriched_data['standings'].get('table'))
print(f"     - Standings: {'Да' if standings_ok else 'Нет'}")
print(f"     - Team1 form: {len(enriched_data.get('team1_form', []))}")
print(f"     - Team2 form: {len(enriched_data.get('team2_form', []))}")
print(f"     - Ошибок: {len(enriched_data.get('errors', []))}")

if enriched_data.get('errors'):
    print("\n[WARNING] Ошибки при fetching:")
    for error in enriched_data['errors']:
        print(f"          - {error}")

# Форматирование контекста
enriched_context = build_enriched_context(match, enriched_data)
context_length = len(enriched_context)
print(f"\n     Enriched context: {context_length} символов")

if context_length < 100:
    print("\n[WARNING] Контекст очень короткий, возможно данные не получены")
    print(f"          Контекст:\n{enriched_context}\n")

# 5. Генерация анализа
print("[Шаг 5] Генерация анализа через DeepSeek API")
print("         Вызов generate_match_analysis_with_context()...")
print("         (это может занять 10-20 секунд)\n")


async def generate_analysis():
    from ai_generator import generate_match_analysis_with_context  # noqa: E402
    start_time = datetime.now()
    analysis = await generate_match_analysis_with_context(match, enriched_context)
    duration = (datetime.now() - start_time).total_seconds()
    return analysis, duration


analysis_text, gen_duration = asyncio.run(generate_analysis())

print(f"[OK] Анализ сгенерирован за {gen_duration:.2f} сек")
print(f"     Длина: {len(analysis_text)} символов")

# 6. Результат
print("\n" + "=" * 60)
print("РЕЗУЛЬТАТ ГЕНЕРАЦИИ")
print("=" * 60 + "\n")
print(f"Матч: {match['team1']} vs {match['team2']}")
print(f"Лига: {match.get('league', 'N/A')}")
print(f"Дата: {match.get('match_date', 'N/A')} {match.get('match_time', 'N/A')}\n")
print("Обогащённые данные:")
print(f"  - H2H: {len(enriched_data.get('h2h', []))} матчей")
standings_ok = (enriched_data.get('standings') and
                enriched_data['standings'].get('table'))
print(f"  - Standings: {'Да' if standings_ok else 'Нет'}")
print(f"  - Form: {len(enriched_data.get('team1_form', []))} + "
      f"{len(enriched_data.get('team2_form', []))} матчей\n")
print(f"Время генерации: {gen_duration:.2f} сек")
print(f"Длина анализа: {len(analysis_text)} символов")
print("\n" + "-" * 60)
print("АНАЛИЗ:")
print("-" * 60 + "\n")
print(analysis_text)
print("\n" + "-" * 60 + "\n")

# 7. Проверка качества
print("[Проверка качества анализа]")

# Проверка запрещённых слов
banned_words = ['коэффициент', 'ставк', 'прогноз']
found_banned = []
for word in banned_words:
    if word in analysis_text.lower():
        found_banned.append(word)

if found_banned:
    print(f"[FAIL] Найдены запрещённые слова: {', '.join(found_banned)}")
else:
    print("[OK] Запрещённые слова отсутствуют")

# Проверка длины
if 2200 <= len(analysis_text) <= 2800:
    print("[OK] Длина в целевом диапазоне (2200-2800)")
elif len(analysis_text) <= 3000:
    print("[WARNING] Длина в допустимом диапазоне (до 3000)")
elif len(analysis_text) <= 3800:
    print("[WARNING] Длина близка к hard cap (до 3800)")
else:
    print("[FAIL] Длина превышает hard cap (>3800)")

# Проверка эмодзи
emoji_count = sum(1 for char in analysis_text if ord(char) > 127000)
if emoji_count <= 4:
    print(f"[OK] Эмодзи в пределах лимита ({emoji_count}/4)")
else:
    print(f"[FAIL] Превышен лимит эмодзи ({emoji_count}/4)")

# Проверка упоминания команд
if match['team1'] in analysis_text and match['team2'] in analysis_text:
    print("[OK] Обе команды упомянуты в анализе")
else:
    print("[FAIL] Не все команды упомянуты")

print("\n" + "=" * 60)
print("ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
print("=" * 60 + "\n")
