from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple


def _clamp(value: int, min_value: int = 0, max_value: int = 100) -> int:
    return max(min_value, min(max_value, int(value)))


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip().replace('%', '').replace(',', '.')
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_date(value: str) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value[:19], fmt)
        except ValueError:
            continue
    return None


def _find_standings_entry(table: List[dict], team_name: str) -> Optional[dict]:
    team_lc = str(team_name or '').strip().lower()
    if not team_lc:
        return None
    for entry in table or []:
        name = str(entry.get('name') or '').strip().lower()
        if not name:
            continue
        if name == team_lc or name in team_lc or team_lc in name:
            return entry
    return None


def _team_recent_points(form_matches: List[dict], team_name: str, limit: int = 5) -> Tuple[int, int]:
    points = 0
    winless_streak = 0
    checked = 0
    for match in (form_matches or [])[:limit]:
        try:
            hs = int(match.get('home_score', 0) or 0)
            aw = int(match.get('away_score', 0) or 0)
        except Exception:
            continue
        is_home = str(match.get('home_team', '')) == team_name
        if is_home:
            if hs > aw:
                points += 3
                winless_streak = 0
            elif hs == aw:
                points += 1
                winless_streak += 1
            else:
                winless_streak += 1
        else:
            if aw > hs:
                points += 3
                winless_streak = 0
            elif hs == aw:
                points += 1
                winless_streak += 1
            else:
                winless_streak += 1
        checked += 1
    return points, winless_streak if checked else 0


def _extract_h2h_stats_averages(h2h_recent_stats: List[dict]) -> Dict[str, float]:
    cards_values: List[float] = []
    fouls_values: List[float] = []
    for row in h2h_recent_stats or []:
        stats = row.get('stats') if isinstance(row, dict) else None
        if not isinstance(stats, dict):
            continue

        yc = stats.get('Жёлтые карточки', {})
        rc = stats.get('Красные карточки', {})
        fouls = stats.get('Фолы', {})

        total_cards = 0.0
        for item in (yc, rc):
            if not isinstance(item, dict):
                continue
            for side in ('home', 'away'):
                v = _to_float(item.get(side))
                if v is not None:
                    total_cards += v
        if total_cards > 0:
            cards_values.append(total_cards)

        total_fouls = 0.0
        if isinstance(fouls, dict):
            for side in ('home', 'away'):
                v = _to_float(fouls.get(side))
                if v is not None:
                    total_fouls += v
        if total_fouls > 0:
            fouls_values.append(total_fouls)

    result: Dict[str, float] = {}
    if cards_values:
        result['avg_cards'] = sum(cards_values) / len(cards_values)
    if fouls_values:
        result['avg_fouls'] = sum(fouls_values) / len(fouls_values)
    return result


def _build_derby_signal(match: dict, data: dict) -> dict:
    team1_meta = data.get('team1_meta') or {}
    team2_meta = data.get('team2_meta') or {}
    h2h = data.get('h2h') or []
    h2h_stats = data.get('h2h_recent_stats') or []

    score = 5
    reasons: List[str] = []

    country1 = str(team1_meta.get('country') or '').strip().lower()
    country2 = str(team2_meta.get('country') or '').strip().lower()
    if country1 and country2 and country1 == country2:
        score += 20
        reasons.append("команды из одной страны")

    city1 = str(team1_meta.get('stadium_location') or '').split(',', 1)[0].strip().lower()
    city2 = str(team2_meta.get('stadium_location') or '').split(',', 1)[0].strip().lower()
    if city1 and city2 and city1 == city2:
        score += 35
        reasons.append("клубы из одного города/агломерации")

    if len(h2h) >= 5:
        score += 10
        reasons.append("богатая история очных встреч")

    agg = _extract_h2h_stats_averages(h2h_stats)
    avg_cards = agg.get('avg_cards')
    avg_fouls = agg.get('avg_fouls')
    if avg_cards is not None and avg_cards >= 5:
        score += 20
        reasons.append(f"повышенная жёсткость очных (в среднем {avg_cards:.1f} карточек)")
    if avg_fouls is not None and avg_fouls >= 24:
        score += 15
        reasons.append(f"высокий уровень борьбы (около {avg_fouls:.1f} фолов)")

    if not reasons:
        reasons.append("ярких признаков принципиального дерби по данным немного")

    return {
        'label': 'Фактор дерби',
        'score': _clamp(score),
        'reasons': reasons[:3],
    }


def _build_motivation_signal(match: dict, data: dict) -> dict:
    team1 = str(match.get('team1') or '')
    team2 = str(match.get('team2') or '')
    standings = data.get('standings') or {}
    table = standings.get('table') or []
    entry1 = _find_standings_entry(table, team1)
    entry2 = _find_standings_entry(table, team2)
    is_cup = bool(data.get('is_cup'))
    round_text = str(data.get('round') or '').lower()

    score = 30
    reasons: List[str] = []

    if entry1 and entry2:
        rank1 = int(entry1.get('rank', 0) or 0)
        rank2 = int(entry2.get('rank', 0) or 0)
        points1 = int(entry1.get('points', 0) or 0)
        points2 = int(entry2.get('points', 0) or 0)
        points_gap = abs(points1 - points2)
        rank_gap = abs(rank1 - rank2)

        if points_gap <= 3:
            score += 15
            reasons.append(f"минимальный разрыв по очкам ({points_gap})")
        if rank_gap <= 2:
            score += 10
            reasons.append("команды рядом в таблице")
        if rank1 <= 4 or rank2 <= 4:
            score += 10
            reasons.append("борьба за верх таблицы")
        if rank1 >= 16 or rank2 >= 16:
            score += 15
            reasons.append("давление зоны вылета")

    if is_cup:
        score += 10
        reasons.append("кубковый формат повышает цену ошибки")
        if any(marker in round_text for marker in ('финал', 'semi', '1/2', '1/4', '1/8')):
            score += 12
            reasons.append("поздняя стадия турнира")

    team1_points, team1_winless = _team_recent_points(data.get('team1_form') or [], team1)
    team2_points, team2_winless = _team_recent_points(data.get('team2_form') or [], team2)
    if team1_points or team2_points:
        if abs(team1_points - team2_points) <= 3:
            score += 8
            reasons.append("форма сопоставима, матч ожидается плотным")
        if team1_winless >= 3 or team2_winless >= 3:
            score += 7
            reasons.append("одна из команд идёт на серии без побед и нуждается в реакции")

    if not reasons:
        reasons.append("базовая турнирная мотивация без экстремального фона")

    return {
        'label': 'Настрой и мотивация',
        'score': _clamp(score),
        'reasons': reasons[:3],
    }


def _detect_match_loser(h2h_match: dict, team1: str, team2: str) -> Tuple[Optional[str], int]:
    home = str(h2h_match.get('home_team') or '')
    away = str(h2h_match.get('away_team') or '')
    try:
        hs = int(h2h_match.get('home_score', 0) or 0)
        aw = int(h2h_match.get('away_score', 0) or 0)
    except Exception:
        return None, 0

    if hs == aw:
        return None, 0

    loser = home if hs < aw else away
    diff = abs(hs - aw)
    if loser not in (team1, team2):
        return None, diff
    return loser, diff


def _build_revenge_signal(match: dict, data: dict) -> dict:
    team1 = str(match.get('team1') or '')
    team2 = str(match.get('team2') or '')
    h2h = data.get('h2h') or []

    score = 8
    reasons: List[str] = []
    if not h2h:
        return {
            'label': 'Фактор реванша',
            'score': score,
            'reasons': ['очных встреч в доступной выборке недостаточно'],
        }

    sorted_h2h = sorted(
        [m for m in h2h if isinstance(m, dict)],
        key=lambda m: str(m.get('date') or ''),
        reverse=True
    )

    recent = sorted_h2h[0]
    loser, diff = _detect_match_loser(recent, team1, team2)
    if loser:
        score += 25
        winner = team2 if loser == team1 else team1
        reasons.append(f"в последней очной {loser} уступил {winner}")
        if diff >= 2:
            score += 15
            reasons.append(f"поражение было крупным (разница {diff} мяча)")

        recent_date = _parse_date(str(recent.get('date') or ''))
        if recent_date:
            days_ago = (datetime.now() - recent_date).days
            if 0 <= days_ago <= 180:
                score += 10
                reasons.append("свежая очная история усиливает тему реванша")

    if len(sorted_h2h) >= 2:
        loser1, _ = _detect_match_loser(sorted_h2h[0], team1, team2)
        loser2, _ = _detect_match_loser(sorted_h2h[1], team1, team2)
        if loser1 and loser1 == loser2:
            score += 20
            reasons.append("одна команда проиграла два последних очных матча подряд")

    if not reasons:
        reasons.append("очные не дают сильного сигнала на реванш")

    return {
        'label': 'Реванш',
        'score': _clamp(score),
        'reasons': reasons[:3],
    }


def _build_confidence(data: dict) -> dict:
    score = 10
    if (data.get('standings') or {}).get('table'):
        score += 20
    if data.get('h2h'):
        score += 20
    if data.get('team1_form') and data.get('team2_form'):
        score += 20
    if data.get('team1_last_match_stats') or data.get('team2_last_match_stats') or data.get('h2h_recent_stats'):
        score += 20
    if data.get('team1_meta') and data.get('team2_meta'):
        score += 10
    if data.get('round') or data.get('league_id'):
        score += 10

    score = _clamp(score)
    if score >= 75:
        label = "высокая"
    elif score >= 45:
        label = "средняя"
    else:
        label = "низкая"
    return {'score': score, 'label': label}


def build_match_signals(match: dict, data: dict) -> dict:
    """Собирает ключевые сигналы матча: дерби, мотивация, реванш."""
    derby = _build_derby_signal(match, data)
    motivation = _build_motivation_signal(match, data)
    revenge = _build_revenge_signal(match, data)
    confidence = _build_confidence(data)

    return {
        'derby': derby,
        'motivation': motivation,
        'revenge': revenge,
        'confidence': confidence,
    }
