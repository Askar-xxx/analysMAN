# -*- coding: utf-8 -*-
"""
Тестовый скрипт для проверки рендеринга PNG таблиц локально.
Использует моковые данные для проверки работы image_renderer.py
"""
import sys
import os

# Моковые данные для тестирования
mock_match = {
    'id': 999,
    'team1': 'Liverpool',
    'team2': 'Manchester City',
    'match_date': '2026-02-20',
    'match_time': '20:00',
    'league': 'English Premier League',
    'sport': 'football'
}

mock_enriched_data = {
    'h2h': [
        {'date': '2025-11-10', 'home_team': 'Liverpool', 'away_team': 'Manchester City',
         'home_score': 2, 'away_score': 0, 'score': '2:0'},
        {'date': '2025-08-15', 'home_team': 'Manchester City', 'away_team': 'Liverpool',
         'home_score': 1, 'away_score': 1, 'score': '1:1'},
        {'date': '2025-03-10', 'home_team': 'Liverpool', 'away_team': 'Manchester City',
         'home_score': 3, 'away_score': 1, 'score': '3:1'},
    ],
    'standings': {
        'table': [
            {'name': 'Liverpool', 'rank': 1, 'played': 25, 'win': 18, 'draw': 4, 'loss': 3,
             'goalsfor': 52, 'goalsagainst': 21, 'goaldifference': 31, 'points': 58, 'form': 'WWDWL'},
            {'name': 'Manchester City', 'rank': 2, 'played': 25, 'win': 17, 'draw': 5, 'loss': 3,
             'goalsfor': 49, 'goalsagainst': 20, 'goaldifference': 29, 'points': 56, 'form': 'WWWDL'},
        ],
        'league_id': 4328,
        'season': '2025-2026'
    },
    'team1_form': [
        {'date': '2026-02-10', 'home_team': 'Liverpool', 'away_team': 'Arsenal',
         'home_score': 2, 'away_score': 1, 'score': '2:1', 'league': 'Premier League'},
        {'date': '2026-02-03', 'home_team': 'Chelsea', 'away_team': 'Liverpool',
         'home_score': 0, 'away_score': 2, 'score': '0:2', 'league': 'Premier League'},
        {'date': '2026-01-27', 'home_team': 'Liverpool', 'away_team': 'Brighton',
         'home_score': 3, 'away_score': 0, 'score': '3:0', 'league': 'Premier League'},
        {'date': '2026-01-20', 'home_team': 'Tottenham', 'away_team': 'Liverpool',
         'home_score': 1, 'away_score': 1, 'score': '1:1', 'league': 'Premier League'},
        {'date': '2026-01-13', 'home_team': 'Liverpool', 'away_team': 'Everton',
         'home_score': 2, 'away_score': 0, 'score': '2:0', 'league': 'Premier League'},
    ],
    'team2_form': [
        {'date': '2026-02-10', 'home_team': 'Arsenal', 'away_team': 'Manchester City',
         'home_score': 1, 'away_score': 2, 'score': '1:2', 'league': 'Premier League'},
        {'date': '2026-02-03', 'home_team': 'Manchester City', 'away_team': 'Newcastle',
         'home_score': 3, 'away_score': 1, 'score': '3:1', 'league': 'Premier League'},
        {'date': '2026-01-27', 'home_team': 'Aston Villa', 'away_team': 'Manchester City',
         'home_score': 0, 'away_score': 2, 'score': '0:2', 'league': 'Premier League'},
        {'date': '2026-01-20', 'home_team': 'Manchester City', 'away_team': 'West Ham',
         'home_score': 4, 'away_score': 0, 'score': '4:0', 'league': 'Premier League'},
        {'date': '2026-01-13', 'home_team': 'Manchester United', 'away_team': 'Manchester City',
         'home_score': 1, 'away_score': 1, 'score': '1:1', 'league': 'Premier League'},
    ],
    'errors': []
}


def main():
    """Основная функция для тестирования"""
    print("=" * 60)
    print("TEST: PNG Table Rendering")
    print("=" * 60)
    print()

    try:
        # Импортируем модули
        print("1. Importing modules...")
        from analysis_formatter import build_table_data
        from image_renderer import render_analysis_table
        print("[OK] Modules imported successfully")
        print()

        # Формируем структурированные данные
        print("2. Building structured data...")
        table_data = build_table_data(mock_match, mock_enriched_data)
        print("[OK] Data built successfully")
        print()
        print("Table data structure:")
        for key, value in table_data.items():
            if isinstance(value, dict):
                print(f"  {key}: {{{', '.join(value.keys())}}}")
            elif isinstance(value, list):
                print(f"  {key}: [{len(value)} items]")
            else:
                val_str = str(value)
                print(f"  {key}: {val_str[:50]}..." if len(val_str) > 50 else f"  {key}: {val_str}")
        print()

        # Рендерим PNG
        print("3. Rendering PNG table...")
        png_path = render_analysis_table(mock_match, table_data)
        print(f"[OK] PNG created: {png_path}")
        print()

        # Проверяем файл
        if os.path.exists(png_path):
            file_size = os.path.getsize(png_path)
            print("File information:")
            print(f"  Path: {png_path}")
            print(f"  Size: {file_size:,} bytes ({file_size / 1024:.2f} KB)")
            print()
            print("[SUCCESS] TEST PASSED!")
            print()
            print(f"Open the file to view: {png_path}")
        else:
            print("[ERROR] File was not created")
            sys.exit(1)

    except ImportError as e:
        print(f"[ERROR] Import failed: {e}")
        print()
        print("Install dependencies:")
        print("  pip install Pillow>=10.0.0")
        sys.exit(1)

    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
