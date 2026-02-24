"""Тесты для analysis_formatter.py."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis_formatter import build_table_data  # noqa: E402


def _form_row(date, home, away, hs, as_, event_id):
    return {
        'date': date,
        'home_team': home,
        'away_team': away,
        'home_score': hs,
        'away_score': as_,
        'score': f"{hs}:{as_}",
        'event_id': str(event_id),
        'league': 'Premier League',
    }


def test_adaptive_rows_hide_empty_blocks():
    match = {
        'team1': 'Arsenal',
        'team2': 'Chelsea',
        'match_date': '2026-02-26',
        'league': 'Premier League. 28 тур'
    }
    enriched = {
        'standings': {},   # Турнирное положение будет пустым
        'h2h': [],         # История встреч будет пустой
        'team1_form': [
            _form_row('2026-02-20', 'Arsenal', 'Liverpool', 2, 1, 1001),
            _form_row('2026-02-16', 'Tottenham', 'Arsenal', 1, 0, 1002),
        ],
        'team2_form': [
            _form_row('2026-02-20', 'Man Utd', 'Chelsea', 1, 2, 2001),
            _form_row('2026-02-15', 'Chelsea', 'Everton', 0, 0, 2002),
        ],
    }

    table_data = build_table_data(match, enriched)
    labels = [row['label'] for row in table_data['rows']]

    assert "Текущая форма" in labels
    assert "Форма дома/на выезде" in labels
    assert "Статистические тренды" in labels

    # Пустые блоки скрыты
    assert "Турнирное положение" not in labels
    assert "Составы" not in labels
    assert "История встреч" not in labels
    assert table_data['coverage_rows_count'] == 3


def test_cup_profile_rows_are_used():
    match = {
        'team1': 'Celta Vigo',
        'team2': 'PAOK',
        'match_date': '2026-02-26',
        'league': 'UEFA Europa League. 32 тур'
    }
    enriched = {
        'is_cup': True,
        'standings': {},
        'h2h': [{'date': '2025-10-02', 'home_team': 'Celta Vigo', 'away_team': 'PAOK', 'score': '3:1'}],
        'team1_domestic_position': '#8 в La Liga, 36 очков после 24 матчей',
        'team2_domestic_position': '#3 в Greek Super League, 48 очков после 22 матчей',
        'team1_cup_path': ['2026-02-19: Celta Vigo 2:0 Rapid Wien'],
        'team2_cup_path': ['2026-02-19: PAOK 1:0 Braga'],
        'team1_form': [
            _form_row('2026-02-20', 'Celta Vigo', 'Osasuna', 2, 1, 3001),
            _form_row('2026-02-16', 'Real Sociedad', 'Celta Vigo', 1, 1, 3002),
        ],
        'team2_form': [
            _form_row('2026-02-20', 'Aris', 'PAOK', 0, 2, 4001),
            _form_row('2026-02-16', 'PAOK', 'AEK', 1, 0, 4002),
        ],
    }

    table_data = build_table_data(match, enriched)
    labels = [row['label'] for row in table_data['rows']]

    assert "Лиговая позиция" in labels
    assert "Кубковый путь" in labels
    assert "Турнирное положение" not in labels


def test_cup_rows_hidden_if_empty():
    match = {
        'team1': 'Team A',
        'team2': 'Team B',
        'match_date': '2026-02-26',
        'league': 'UEFA Europa Conference League. 32 тур'
    }
    enriched = {
        'is_cup': True,
        'team1_domestic_position': 'Нет данных',
        'team2_domestic_position': 'Нет данных',
        'team1_cup_path': [],
        'team2_cup_path': [],
        'team1_form': [],
        'team2_form': [],
        'h2h': [],
    }

    table_data = build_table_data(match, enriched)
    labels = [row['label'] for row in table_data['rows']]

    assert "Лиговая позиция" not in labels
    assert "Кубковый путь" not in labels


def test_lineups_are_formatted_as_header_and_bullets():
    match = {
        'team1': 'Team A',
        'team2': 'Team B',
        'match_date': '2026-02-26',
        'league': 'Premier League. 28 тур'
    }
    enriched = {
        'standings': {},
        'h2h': [],
        'team1_form': [
            _form_row('2026-02-20', 'Team A', 'Rival', 2, 1, 501),
            _form_row('2026-02-16', 'Rival', 'Team A', 1, 0, 502),
        ],
        'team2_form': [
            _form_row('2026-02-20', 'Team B', 'Rival', 1, 1, 601),
            _form_row('2026-02-16', 'Rival', 'Team B', 0, 1, 602),
        ],
        'lineup_501': [
            {'strPlayer': 'Alice', 'strTeam': 'Team A', 'strSubstitute': 'No'},
            {'strPlayer': 'Bea', 'strTeam': 'Team A', 'strSubstitute': 'No'},
        ],
        'lineup_502': [
            {'strPlayer': 'Alice', 'strTeam': 'Team A', 'strSubstitute': 'No'},
            {'strPlayer': 'Cara', 'strTeam': 'Team A', 'strSubstitute': 'No'},
        ],
        'lineup_601': [
            {'strPlayer': 'Tom', 'strTeam': 'Team B', 'strSubstitute': 'No'},
            {'strPlayer': 'Sam', 'strTeam': 'Team B', 'strSubstitute': 'No'},
        ],
        'lineup_602': [
            {'strPlayer': 'Tom', 'strTeam': 'Team B', 'strSubstitute': 'No'},
            {'strPlayer': 'Sam', 'strTeam': 'Team B', 'strSubstitute': 'No'},
        ],
    }

    table_data = build_table_data(match, enriched)
    lineups_row = next(row for row in table_data['rows'] if row['label'] == 'Составы')

    assert "Изменения в старте:" in lineups_row['left']
    assert "• " in lineups_row['left']
    assert "Замена:" not in lineups_row['left']
    assert lineups_row['right'] == "Состав без изменений"


def test_last_match_events_row_is_rendered():
    match = {
        'team1': 'Team A',
        'team2': 'Team B',
        'match_date': '2026-02-26',
        'league': 'Premier League. 28 тур'
    }
    enriched = {
        'standings': {},
        'h2h': [],
        'team1_form': [
            _form_row('2026-02-20', 'Team A', 'Rival', 2, 1, 701),
        ],
        'team2_form': [
            _form_row('2026-02-20', 'Rival', 'Team B', 0, 2, 801),
        ],
        'team1_last_match_events': {
            'subs': ['Player A → Player B'],
            'cards': ['Player C (ЖК)'],
        },
        'team2_last_match_events': {
            'subs': ['Player X → Player Y'],
            'cards': [],
        },
    }

    table_data = build_table_data(match, enriched)
    events_row = next(row for row in table_data['rows'] if row['label'] == 'События последнего матча')

    assert "Замены по ходу:" in events_row['left']
    assert "• Player A → Player B" in events_row['left']
    assert "Карточки:" in events_row['left']
    assert "• Player C (ЖК)" in events_row['left']
    assert "Замены по ходу:" in events_row['right']
    assert "• Player X → Player Y" in events_row['right']


def test_home_away_form_uses_wdl_notation():
    match = {
        'team1': 'Team A',
        'team2': 'Team B',
        'match_date': '2026-02-26',
        'league': 'Premier League. 28 тур'
    }
    enriched = {
        'standings': {},
        'h2h': [],
        'team1_form': [
            _form_row('2026-02-20', 'Team A', 'Rival 1', 2, 1, 1101),
            _form_row('2026-02-16', 'Team A', 'Rival 2', 1, 1, 1102),
        ],
        'team2_form': [
            _form_row('2026-02-20', 'Rival 3', 'Team B', 1, 0, 1201),
        ],
    }

    table_data = build_table_data(match, enriched)
    home_away_row = next(row for row in table_data['rows'] if row['label'] == 'Форма дома/на выезде')

    assert "(1W,1D,0L)" in home_away_row['left']
    assert "В," not in home_away_row['left']


def test_cup_round_is_normalized_in_title():
    match = {
        'team1': 'Team A',
        'team2': 'Team B',
        'match_date': '2026-02-26',
        'league': 'UEFA Champions League. 32 тур'
    }
    enriched = {
        'is_cup': True,
        'team1_form': [_form_row('2026-02-20', 'Team A', 'Rival', 1, 0, 901)],
        'team2_form': [_form_row('2026-02-20', 'Rival', 'Team B', 0, 1, 902)],
        'h2h': [],
        'standings': {},
    }

    table_data = build_table_data(match, enriched)
    assert "UEFA Champions League. 1/16 финала" in table_data['title']


def test_data_limited_badge_shown_only_for_poor_coverage():
    match = {
        'team1': 'Team A',
        'team2': 'Team B',
        'match_date': '2026-02-26',
        'league': 'Premier League. 28 тур'
    }
    enriched = {
        'team1_form': [_form_row('2026-02-20', 'Team A', 'Rival', 1, 0, 10001)],
        'team2_form': [_form_row('2026-02-20', 'Rival', 'Team B', 0, 1, 10002)],
        'h2h': [],
        'standings': {},
    }

    table_data = build_table_data(match, enriched)
    assert table_data['is_data_limited'] is True
    assert "[Данные ограничены]" in table_data['title']
