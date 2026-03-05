"""Тесты для analysis_formatter.py."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis_formatter import (  # noqa: E402
    build_table_data,
    extract_tournament_position,
    extract_current_form,
    extract_stats_trends,
    extract_h2h_history,
    extract_lineup_changes,
    _has_meaningful_value,
    _normalize_league_display,
    _normalize_team_id,
    _ru_plural,
)


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
    assert any(label.startswith("Статистические тренды") for label in labels)

    # Core rows остаются даже при пустых данных (с placeholder)
    assert "Турнирное положение" in labels
    assert "История встреч" in labels
    # Optional rows скрыты
    assert "Изменения состава" not in labels
    assert "События последнего матча" not in labels


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

    # Core cup rows остаются с placeholder
    assert "Лиговая позиция" in labels
    assert "Кубковый путь" in labels


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
    lineups_row = next(row for row in table_data['rows'] if row['label'] == 'Изменения состава')

    assert "Изменения состава (" not in lineups_row['left']
    assert "Источник: старт" in lineups_row['left']
    assert "• " in lineups_row['left']
    assert "Замена:" not in lineups_row['left']
    assert lineups_row['right'].startswith("Состав без изменений")


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


# ---------------------------------------------------------------------------
# Unit-тесты отдельных функций
# ---------------------------------------------------------------------------

class TestExtractTournamentPosition:

    def _standings(self, entries):
        return {'standings': {'table': entries}}

    def test_top4_zone(self):
        data = self._standings([{'name': 'Arsenal', 'rank': 3, 'points': 48, 'played': 23}])
        result = extract_tournament_position(data, 'Arsenal')
        assert '#3 место' in result
        assert 'зона ЛЧ' in result
        assert '48 очков' in result

    def test_relegation_zone(self):
        data = self._standings([{'name': 'Luton', 'rank': 19, 'points': 14, 'played': 23}])
        result = extract_tournament_position(data, 'Luton')
        assert 'зона вылета' in result

    def test_midtable_no_zone(self):
        data = self._standings([{'name': 'Wolves', 'rank': 11, 'points': 30, 'played': 23}])
        result = extract_tournament_position(data, 'Wolves')
        assert 'зона' not in result

    def test_team_not_found_empty_string(self):
        data = self._standings([{'name': 'Arsenal', 'rank': 1, 'points': 60, 'played': 24}])
        assert extract_tournament_position(data, 'Chelsea') == ''

    def test_empty_data_empty_string(self):
        assert extract_tournament_position({}, 'Arsenal') == ''


class TestExtractCurrentFormUnit:

    def _data(self, matches, is_home=True):
        key = 'team1_form' if is_home else 'team2_form'
        return {key: matches}

    def test_all_wins_home(self):
        matches = [
            _form_row('2026-01-01', 'Arsenal', f'Opp{i}', 2, 0, 100 + i)
            for i in range(3)
        ]
        result = extract_current_form(self._data(matches), 'Arsenal', is_home=True)
        assert result.startswith('WWW')

    def test_away_wins(self):
        matches = [
            _form_row('2026-01-01', f'Opp{i}', 'Chelsea', 0, 1, 200 + i)
            for i in range(2)
        ]
        result = extract_current_form(self._data(matches, is_home=False), 'Chelsea', is_home=False)
        assert result.startswith('WW')

    def test_dirty_data_both_sides_skipped(self):
        """Матч где home_team == away_team == команда — пропускается."""
        matches = [
            _form_row('2026-01-01', 'Arsenal', 'Arsenal', 2, 0, 300),  # грязные данные
            _form_row('2026-01-02', 'Arsenal', 'Chelsea', 1, 0, 301),   # валидный
        ]
        result = extract_current_form(self._data(matches), 'Arsenal', is_home=True)
        form_part = result.split(' ')[0]
        assert len(form_part) == 1  # только один валидный матч
        assert form_part == 'W'

    def test_max_six_matches_counted(self):
        matches = [
            _form_row('2026-01-01', 'Arsenal', f'Opp{i}', 1, 0, 400 + i)
            for i in range(10)
        ]
        result = extract_current_form(self._data(matches), 'Arsenal', is_home=True)
        form_part = result.split(' ')[0]
        assert len(form_part) <= 6

    def test_empty_returns_empty(self):
        assert extract_current_form({}, 'Arsenal', is_home=True) == ''


class TestExtractStatsTrendsUnit:

    def _data(self, matches, is_home=True):
        key = 'team1_form' if is_home else 'team2_form'
        return {key: matches}

    def test_no_misleading_home_label(self):
        """После фикса слово 'домашних' не должно появляться в выводе."""
        matches = [_form_row('2026-01-01', 'Arsenal', 'Chelsea', 1, 0, 500)]
        result = extract_stats_trends(self._data(matches), 'Arsenal', is_home=True)
        assert 'домашних' not in result

    def test_basic_percentages_present(self):
        matches = [
            _form_row('2026-01-01', 'Arsenal', 'Chelsea', 2, 1, 600),
            _form_row('2026-01-02', 'Arsenal', 'Liverpool', 0, 0, 601),
        ]
        result = extract_stats_trends(self._data(matches), 'Arsenal', is_home=True)
        assert '%' in result
        assert 'среднем' in result

    def test_empty_returns_empty(self):
        assert extract_stats_trends({}, 'Arsenal', is_home=True) == ''


class TestHasMeaningfulValue:

    def test_real_value_true(self):
        assert _has_meaningful_value('#3 место, 40 очков') is True

    def test_empty_string_false(self):
        assert _has_meaningful_value('') is False

    def test_stub_nет_данных_false(self):
        assert _has_meaningful_value('нет данных') is False

    def test_stub_mixed_case_false(self):
        assert _has_meaningful_value('Нет данных') is False

    def test_недостаточно_данных_false(self):
        assert _has_meaningful_value('недостаточно данных') is False


class TestNormalizeLeagueDisplay:

    def test_cup_32_to_116(self):
        result = _normalize_league_display('Champions League. 32 тур', is_cup=True)
        assert '1/16 финала' in result

    def test_cup_4_to_12(self):
        result = _normalize_league_display('Europa League. 4 тур', is_cup=True)
        assert '1/2 финала' in result

    def test_cup_2_to_final(self):
        result = _normalize_league_display('Some Cup. 2 тур', is_cup=True)
        assert 'Финал' in result

    def test_league_not_converted(self):
        result = _normalize_league_display('Premier League. 25 тур', is_cup=False)
        assert result == 'Premier League. 25 тур'

    def test_no_round_pattern_unchanged(self):
        result = _normalize_league_display('Cup Final', is_cup=True)
        assert result == 'Cup Final'


def test_current_form_limited_to_5():
    """Форма не должна превышать 5 символов даже при 7 матчах."""
    enriched = {
        'team1_form': [
            _form_row(f'2026-02-{20-i}', 'Team A', 'Rival', 2, 1, 100+i)
            for i in range(7)
        ]
    }
    result = extract_current_form(enriched, 'Team A', is_home=True)
    form_letters = result.split(' ')[0]
    assert len(form_letters) <= 5


def test_core_rows_not_hidden_when_empty():
    """Core rows показываются с placeholder даже при пустых данных."""
    match = {
        'team1': 'Team A', 'team2': 'Team B',
        'match_date': '2026-02-26', 'league': 'Premier League'
    }
    enriched = {
        'standings': {}, 'h2h': [],
        'team1_form': [], 'team2_form': [],
    }
    table_data = build_table_data(match, enriched)
    labels = [row['label'] for row in table_data['rows']]
    assert 'Турнирное положение' in labels
    assert 'Текущая форма' in labels
    assert 'История встреч' in labels
    assert any(label.startswith('Статистические тренды') for label in labels)
    # Optional скрыты
    assert 'Изменения состава' not in labels
    assert 'События последнего матча' not in labels
    # Core rows с placeholder
    tp_row = next(r for r in table_data['rows'] if r['label'] == 'Турнирное положение')
    assert tp_row['left'] == 'Недостаточно данных'


def test_stats_trends_uses_team_ids():
    """Тренды корректно определяют сторону по team_id при alias-именах."""
    enriched = {
        'team1_trends_form': [
            {
                'date': '2026-02-20', 'home_team': 'Paris SG',
                'away_team': 'Lyon', 'home_score': 3, 'away_score': 1,
                'home_team_id': '100', 'away_team_id': '200',
            }
        ]
    }
    result = extract_stats_trends(enriched, 'PSG', is_home=True, team_id='100')
    assert '100%' in result
    assert '1/1' not in result


def test_h2h_single_match_wording():
    """H2H с 1 матчем текущего сезона имеет корректную формулировку."""
    enriched = {
        'h2h': [{'date': '2025-10-01', 'home_team': 'A', 'away_team': 'B', 'score': '1:0'}],
        'h2h_is_current_season': True,
    }
    result = extract_h2h_history(enriched)
    assert 'В этом сезоне лиги сыграна 1 очная встреча:' in result


def test_h2h_multiple_matches_wording():
    """H2H с 2+ матчами текущего сезона."""
    enriched = {
        'h2h': [
            {'date': '2026-01-15', 'home_team': 'A', 'away_team': 'B', 'score': '2:1'},
            {'date': '2025-10-01', 'home_team': 'B', 'away_team': 'A', 'score': '0:0'},
        ],
        'h2h_is_current_season': True,
    }
    result = extract_h2h_history(enriched)
    assert 'Очные встречи в сезоне лиги: 2' in result


def test_build_table_data_h2h_uses_match_team_ids_for_aliases():
    """H2H in table uses canonical names when API gives aliases (Wolves -> Wolverhampton Wanderers)."""
    match = {
        'team1': 'Wolverhampton Wanderers',
        'team2': 'Liverpool',
        'home_team_id': '4063',
        'away_team_id': '133602',
        'match_date': '2026-02-26',
        'league': 'Premier League'
    }
    enriched = {
        'standings': {},
        'team1_form': [],
        'team2_form': [],
        'h2h_is_current_season': True,
        'h2h': [
            {
                'date': '2025-09-28',
                'home_team': 'Wolves',
                'away_team': 'Liverpool',
                'home_team_id': '4063',
                'away_team_id': '133602',
                'score': '1:2'
            }
        ]
    }

    table_data = build_table_data(match, enriched)
    history_row = next(row for row in table_data['rows'] if row['label'] == 'История встреч')
    assert '2025-09-28: Wolverhampton Wanderers 1:2 Liverpool' in history_row['left']


def test_build_table_data_h2h_uses_team_meta_aliases_without_ids():
    """Alias from team meta normalizes H2H rows when match team_id is missing."""
    match = {
        'team1': 'Wolverhampton Wanderers',
        'team2': 'Liverpool',
        'home_team_id': '4063',
        'away_team_id': '133602',
        'match_date': '2026-03-06',
        'league': 'FA Cup',
    }
    enriched = {
        'standings': {},
        'team1_form': [],
        'team2_form': [],
        'h2h_is_current_season': False,
        'h2h_season_source': 'schedule_confirmed',
        'team1_meta': {
            'team_name': 'Wolverhampton Wanderers',
            'team_short': 'Wolves',
            'team_alternate': 'Wolves',
            'aliases': ['Wolves'],
        },
        'h2h': [
            {'date': '2026-03-03', 'home_team': 'Wolverhampton Wanderers', 'away_team': 'Liverpool',
             'score': '2:1', 'home_team_id': '4063', 'away_team_id': '133602'},
            {'date': '2024-09-28', 'home_team': 'Wolves', 'away_team': 'Liverpool', 'score': '1:2'},
        ],
    }

    table_data = build_table_data(match, enriched)
    history_row = next(row for row in table_data['rows'] if row['label'] == 'История встреч')
    assert '2026-03-03: Wolverhampton Wanderers 2:1 Liverpool' in history_row['left']
    assert '2024-09-28: Wolverhampton Wanderers 1:2 Liverpool' in history_row['left']


def test_ru_plural():
    """Русские склонения работают корректно."""
    assert _ru_plural(1, 'очко', 'очка', 'очков') == 'очко'
    assert _ru_plural(2, 'очко', 'очка', 'очков') == 'очка'
    assert _ru_plural(5, 'очко', 'очка', 'очков') == 'очков'
    assert _ru_plural(11, 'очко', 'очка', 'очков') == 'очков'
    assert _ru_plural(21, 'очко', 'очка', 'очков') == 'очко'
    assert _ru_plural(43, 'очко', 'очка', 'очков') == 'очка'


# ---------------------------------------------------------------------------
# Confidence filter для составов
# ---------------------------------------------------------------------------

def test_lineup_changes_ignores_other_team_in_event():
    """Игроки соперника (strTeam != team_name) в том же event — нормальное поведение, не contamination."""
    enriched = {
        'team1_form': [
            _form_row('2026-02-20', 'Crystal Palace', 'Tottenham', 1, 0, 801),
            _form_row('2026-02-16', 'Crystal Palace', 'Arsenal', 2, 1, 802),
        ],
        'lineup_801': [
            {'strPlayer': 'Eze', 'strTeam': 'Crystal Palace', 'strSubstitute': 'No', 'idTeam': '200'},
            {'strPlayer': 'Olise', 'strTeam': 'Crystal Palace', 'strSubstitute': 'No', 'idTeam': '200'},
            {'strPlayer': 'Son', 'strTeam': 'Tottenham', 'strSubstitute': 'No', 'idTeam': '300'},
        ],
        'lineup_802': [
            {'strPlayer': 'Eze', 'strTeam': 'Crystal Palace', 'strSubstitute': 'No', 'idTeam': '200'},
            {'strPlayer': 'Zaha', 'strTeam': 'Crystal Palace', 'strSubstitute': 'No', 'idTeam': '200'},
            {'strPlayer': 'Kane', 'strTeam': 'Tottenham', 'strSubstitute': 'No', 'idTeam': '300'},
        ],
    }
    result = extract_lineup_changes(
        enriched, 'Crystal Palace', is_home=True,
        team_id='200', opponent_team_id='300'
    )
    # Не должно быть placeholder — это нормальные данные
    assert 'надёжных данных' not in result
    assert 'Son' not in result  # Игрок Tottenham не попал в результат
    assert 'Kane' not in result


def test_lineup_changes_detects_contamination():
    """Contamination: strTeam совпадает с нашей командой, но idTeam — соперника."""
    enriched = {
        'team1_form': [
            _form_row('2026-02-20', 'Crystal Palace', 'Tottenham', 1, 0, 801),
            _form_row('2026-02-16', 'Crystal Palace', 'Arsenal', 2, 1, 802),
        ],
        'lineup_801': [
            {'strPlayer': 'Eze', 'strTeam': 'Crystal Palace', 'strSubstitute': 'No', 'idTeam': '200'},
            # Ошибка API: strTeam = Crystal Palace, но idTeam = Tottenham
            {'strPlayer': 'Son', 'strTeam': 'Crystal Palace', 'strSubstitute': 'No', 'idTeam': '300'},
        ],
        'lineup_802': [
            {'strPlayer': 'Eze', 'strTeam': 'Crystal Palace', 'strSubstitute': 'No', 'idTeam': '200'},
            {'strPlayer': 'Olise', 'strTeam': 'Crystal Palace', 'strSubstitute': 'No', 'idTeam': '200'},
        ],
    }
    result = extract_lineup_changes(
        enriched, 'Crystal Palace', is_home=True,
        team_id='200', opponent_team_id='300'
    )
    assert 'надёжных данных' in result


def test_lineup_changes_detects_non_own_team_id_even_if_opponent_unknown():
    """Contamination: strTeam совпадает, но idTeam не равен team_id (и не равен opponent_team_id)."""
    enriched = {
        'team1_form': [
            _form_row('2026-02-20', 'Team A', 'Team X', 1, 0, 901),
            _form_row('2026-02-16', 'Team A', 'Team Y', 2, 1, 902),
        ],
        'lineup_901': [
            {'strPlayer': 'Own 1', 'strTeam': 'Team A', 'strSubstitute': 'No', 'idTeam': '100'},
            # Ошибка API: игрок помечен как Team A, но idTeam вообще третьей команды
            {'strPlayer': 'Noise', 'strTeam': 'Team A', 'strSubstitute': 'No', 'idTeam': '999'},
        ],
        'lineup_902': [
            {'strPlayer': 'Own 1', 'strTeam': 'Team A', 'strSubstitute': 'No', 'idTeam': '100'},
            {'strPlayer': 'Own 2', 'strTeam': 'Team A', 'strSubstitute': 'No', 'idTeam': '100'},
        ],
    }
    result = extract_lineup_changes(
        enriched, 'Team A', is_home=True,
        team_id='100', opponent_team_id='200'
    )
    assert 'надёжных данных' in result


def test_lineup_changes_degrades_on_low_confidence():
    """Больше 40% игроков без idTeam и strTeam — low confidence."""
    enriched = {
        'team1_form': [
            _form_row('2026-02-20', 'Team A', 'Rival', 1, 0, 901),
            _form_row('2026-02-16', 'Team A', 'Rival2', 2, 1, 902),
        ],
        'lineup_901': [
            {'strPlayer': 'P1', 'strTeam': 'Team A', 'strSubstitute': 'No', 'idTeam': '100'},
            {'strPlayer': 'P2', 'strSubstitute': 'No'},  # no strTeam, no idTeam
            {'strPlayer': 'P3', 'strSubstitute': 'No'},  # no strTeam, no idTeam
        ],
        'lineup_902': [
            {'strPlayer': 'P1', 'strTeam': 'Team A', 'strSubstitute': 'No', 'idTeam': '100'},
            {'strPlayer': 'P4', 'strSubstitute': 'No'},
            {'strPlayer': 'P5', 'strSubstitute': 'No'},
        ],
    }
    result = extract_lineup_changes(
        enriched, 'Team A', is_home=True,
        team_id='100', opponent_team_id='200'
    )
    assert 'надёжных данных' in result


def test_lineup_changes_marks_partial_source_instead_of_hiding():
    """При неполном старте показываем изменения с пометкой, а не скрываем блок."""
    enriched = {
        'team1_form': [
            _form_row('2026-02-20', 'Team A', 'Rival', 1, 0, 1001),
            _form_row('2026-02-16', 'Team A', 'Rival2', 2, 1, 1002),
        ],
        # Новый матч: доступно только 10 игроков старта
        'lineup_1001': [
            {'strPlayer': f'N{i}', 'strTeam': 'Team A', 'strSubstitute': 'No', 'idTeam': '100'}
            for i in range(1, 11)
        ],
        # Предыдущий матч: 11 игроков старта
        'lineup_1002': [
            {'strPlayer': f'O{i}', 'strTeam': 'Team A', 'strSubstitute': 'No', 'idTeam': '100'}
            for i in range(1, 12)
        ],
    }
    result = extract_lineup_changes(
        enriched, 'Team A', is_home=True, team_id='100', opponent_team_id='200'
    )
    assert "Изменения состава" not in result
    assert "Источник: старт" in result
    assert "надёжных данных" not in result


def test_team_id_normalization_for_lineups():
    """team_id как int, у игроков как str — корректное сравнение."""
    assert _normalize_team_id(None) == ''
    assert _normalize_team_id(123) == '123'
    assert _normalize_team_id(' 456 ') == '456'

    enriched = {
        'team1_form': [
            _form_row('2026-02-20', 'Team A', 'Rival', 1, 0, 1001),
            _form_row('2026-02-16', 'Team A', 'Rival2', 2, 1, 1002),
        ],
        'lineup_1001': [
            {'strPlayer': 'Alice', 'strTeam': 'Team A', 'strSubstitute': 'No', 'idTeam': '100'},
            {'strPlayer': 'Bob', 'strTeam': 'Team A', 'strSubstitute': 'No', 'idTeam': '100'},
        ],
        'lineup_1002': [
            {'strPlayer': 'Alice', 'strTeam': 'Team A', 'strSubstitute': 'No', 'idTeam': '100'},
            {'strPlayer': 'Carol', 'strTeam': 'Team A', 'strSubstitute': 'No', 'idTeam': '100'},
        ],
    }
    # team_id как int
    result = extract_lineup_changes(
        enriched, 'Team A', is_home=True,
        team_id=100, opponent_team_id=200
    )
    # Должен нормально обработать — не placeholder
    assert 'надёжных данных' not in result
    assert 'Bob' in result or 'Carol' in result
