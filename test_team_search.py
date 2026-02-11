"""
Тест функции поиска API-Football team_id по названию команды.
"""

from sync_api_football import APIFootballClient, find_or_search_team_id

def test_search_team():
    """Тест поиска команды через API"""
    print("=" * 70)
    print("Тест: Поиск API-Football team_id по названию")
    print("=" * 70)
    print()

    client = APIFootballClient()

    # Тест 1: Поиск Chelsea
    print("1. Поиск: Chelsea (EPL)")
    print("-" * 70)
    team_id = client.search_team_by_name("Chelsea", league_id="39")
    if team_id:
        print(f"[OK] Найдено: team_id = {team_id}")
    else:
        print("[FAIL] Не найдено")
    print()

    # Тест 2: Поиск Liverpool
    print("2. Поиск: Liverpool (EPL)")
    print("-" * 70)
    team_id = client.search_team_by_name("Liverpool", league_id="39")
    if team_id:
        print(f"[OK] Найдено: team_id = {team_id}")
    else:
        print("[FAIL] Не найдено")
    print()

    # Тест 3: Поиск Arsenal без указания лиги
    print("3. Поиск: Arsenal (без лиги)")
    print("-" * 70)
    team_id = client.search_team_by_name("Arsenal")
    if team_id:
        print(f"[OK] Найдено: team_id = {team_id}")
    else:
        print("[FAIL] Не найдено")
    print()

    # Тест 4: Гибридный поиск (с БД)
    print("4. Гибридный поиск: Arsenal (TheSportsDB ID: 133604)")
    print("-" * 70)
    team_id = find_or_search_team_id("133604", "Arsenal", "39", client)
    if team_id:
        print(f"[OK] Найдено: team_id = {team_id}")
        print("   (При повторном вызове должен взять из БД)")
    else:
        print("[FAIL] Не найдено")
    print()

    # Тест 5: Повторный гибридный поиск (должен взять из БД)
    print("5. Повторный поиск Arsenal (должен быть из БД)")
    print("-" * 70)
    team_id = find_or_search_team_id("133604", "Arsenal", "39", client)
    if team_id:
        print(f"[OK] Найдено: team_id = {team_id}")
    else:
        print("[FAIL] Не найдено")
    print()

    print("=" * 70)
    print(f"Использовано запросов: {client.requests_made}/{client.daily_limit}")
    print("=" * 70)


if __name__ == "__main__":
    try:
        test_search_team()
    except KeyboardInterrupt:
        print("\n\nПрервано пользователем")
    except Exception as e:
        print(f"\nОшибка: {e}")
        import traceback
        traceback.print_exc()
