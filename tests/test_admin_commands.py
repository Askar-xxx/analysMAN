"""Smoke и регрессионные тесты для admin_commands.py."""

import asyncio
import os
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import admin_commands  # noqa: E402


class DummyMessage:
    """Записывает ответы команды без Telegram API."""

    def __init__(self):
        self.calls = []

    async def reply_text(self, text, parse_mode=None):
        self.calls.append({"text": text, "parse_mode": parse_mode})


def make_update(user_id=1):
    message = DummyMessage()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        message=message,
    )
    return update, message


def make_context(args=None, bot=None):
    return SimpleNamespace(args=list(args or []), bot=bot or SimpleNamespace(send_photo=AsyncMock()))


def run_async(coro):
    return asyncio.run(coro)


def build_sqlite_row(**values):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    columns = ", ".join(f"? AS {key}" for key in values)
    row = conn.execute(f"SELECT {columns}", tuple(values.values())).fetchone()
    conn.close()
    return row


@pytest.fixture
def sqlite_db(monkeypatch, tmp_path):
    db_path = tmp_path / "admin_commands_test.sqlite3"

    def connect():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance INTEGER DEFAULT 0,
                total_analysis_bought INTEGER DEFAULT 0,
                created_at TEXT
            );

            CREATE TABLE matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team1 TEXT,
                team2 TEXT,
                match_date TEXT,
                match_time TEXT,
                league TEXT,
                sport TEXT,
                api_event_id TEXT,
                is_active INTEGER DEFAULT 1,
                coverage_ok INTEGER,
                analysis_text TEXT,
                analysis_png_path TEXT,
                price INTEGER DEFAULT 150
            );

            CREATE TABLE purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                match_id INTEGER,
                purchase_date TEXT,
                created_at TEXT,
                status TEXT
            );

            CREATE TABLE balance_topups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount_rub INTEGER,
                status TEXT,
                token TEXT,
                created_at TEXT,
                expires_at TEXT
            );
            """
        )

    monkeypatch.setattr(admin_commands.database, "get_db_connection", connect)
    monkeypatch.setattr(admin_commands.database, "get_db", connect)
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    return db_path


@pytest.mark.parametrize(
    ("command", "args"),
    [
        (admin_commands.clean_matches_command, []),
        (admin_commands.clean_all_matches_command, []),
        (admin_commands.stats_command, []),
        (admin_commands.add_balance_command, ["1", "10"]),
        (admin_commands.clear_balance_command, ["1"]),
        (admin_commands.clear_purchases_command, ["all"]),
        (admin_commands.clear_user_analysis_command, ["1"]),
        (admin_commands.clear_topups_command, ["all"]),
        (admin_commands.userinfo_command, ["1"]),
        (admin_commands.finduser_command, ["tester"]),
        (admin_commands.topups_pending_command, []),
        (admin_commands.recent_donations_command, []),
        (admin_commands.refund_command, ["1"]),
        (admin_commands.refund_last_command, ["1"]),
        (admin_commands.force_sync_command, []),
        (admin_commands.regen_command, ["1"]),
        (admin_commands.regen_last_command, ["1"]),
        (admin_commands.matchinfo_command, ["1"]),
        (admin_commands.admin_help_command, []),
    ],
)
def test_all_admin_commands_reject_non_admin(monkeypatch, command, args):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: False)
    update, message = make_update()
    context = make_context(args)

    run_async(command(update, context))

    assert message.calls
    assert "нет прав" in message.calls[0]["text"].lower()


def test_format_match_brief_accepts_sqlite_row():
    row = build_sqlite_row(
        team1="Arsenal",
        team2="Chelsea",
        match_date="2026-03-03",
        match_time="20:00",
    )

    result = admin_commands._format_match_brief(row)

    assert result == "Arsenal vs Chelsea (2026-03-03 20:00)"


def test_stats_command_reports_counts(sqlite_db, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "analysis_cache").mkdir()
    (tmp_path / "analysis_cache" / "table.webp").write_bytes(b"png")

    with admin_commands.database.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO users (user_id, username, balance, total_analysis_bought, created_at) VALUES (1, 'tester', 10, 2, '2026-03-03 19:00:00')"
        )
        conn.execute(
            "INSERT INTO matches (team1, team2, match_date, match_time, league, sport, analysis_text, analysis_png_path) VALUES ('A', 'B', '2026-03-03', '21:00', 'League', 'football', 'text', 'analysis_cache/table.webp')"
        )
        conn.execute(
            "INSERT INTO purchases (user_id, match_id, purchase_date, created_at, status) VALUES (1, 1, '2026-03-03 19:05:00', '2026-03-03 19:05:00', 'paid')"
        )
        conn.execute(
            "INSERT INTO balance_topups (user_id, amount_rub, status, token, created_at, expires_at) VALUES (1, 100, 'pending', 'tok-1', '2026-03-03 19:10:00', '2026-03-03 20:10:00')"
        )
        conn.commit()

    update, message = make_update()
    run_async(admin_commands.stats_command(update, make_context()))

    assert "Матчи: 1" in message.calls[-1]["text"]
    assert "Покупки: 1" in message.calls[-1]["text"]
    assert "Пользователи: 1" in message.calls[-1]["text"]


def test_balance_commands_happy_path(sqlite_db, monkeypatch):
    with admin_commands.database.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO users (user_id, username, balance, total_analysis_bought, created_at) VALUES (5, 'anglesym', 3, 0, '2026-03-03 19:00:00')"
        )
        conn.commit()

    balances = {5: 3}

    def add_balance(user_id, amount):
        balances[user_id] += amount

    def get_user_balance(user_id):
        return balances[user_id]

    def reset_user_balance(user_id):
        balances[user_id] = 0
        return True

    monkeypatch.setattr(admin_commands.database, "add_balance", add_balance)
    monkeypatch.setattr(admin_commands.database, "get_user_balance", get_user_balance)
    monkeypatch.setattr(admin_commands.database, "reset_user_balance", reset_user_balance)

    update, message = make_update()
    run_async(admin_commands.add_balance_command(update, make_context(["5", "7"])))
    assert "Стало: 10 руб." in message.calls[-1]["text"]

    update, message = make_update()
    run_async(admin_commands.clear_balance_command(update, make_context(["5"])))
    assert "Стало: 0 руб." in message.calls[-1]["text"]


def test_clear_commands_happy_paths(sqlite_db, monkeypatch, tmp_path):
    png_path = tmp_path / "analysis_1.webp"
    png_path.write_bytes(b"img")

    with admin_commands.database.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO users (user_id, username, balance, total_analysis_bought, created_at) VALUES (7, 'buyer', 0, 2, '2026-03-03 19:00:00')"
        )
        conn.execute(
            "INSERT INTO matches (id, team1, team2, match_date, match_time, league, sport, analysis_text, analysis_png_path) VALUES (1, 'A', 'B', '2026-03-03', '20:00', 'League', 'football', 'text', ?)",
            (str(png_path),),
        )
        conn.execute(
            "INSERT INTO purchases (user_id, match_id, purchase_date, created_at, status) VALUES (7, 1, '2026-03-03 19:05:00', '2026-03-03 19:05:00', 'paid')"
        )
        conn.execute(
            "INSERT INTO balance_topups (user_id, amount_rub, status, token, created_at, expires_at) VALUES (7, 100, 'pending', 'tok', '2026-03-03 19:10:00', '2026-03-03 20:10:00')"
        )
        conn.commit()

    update, message = make_update()
    run_async(admin_commands.clear_purchases_command(update, make_context(["7"])))
    assert "Удалено покупок пользователя 7: 1" in message.calls[-1]["text"]

    with admin_commands.database.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO purchases (user_id, match_id, purchase_date, created_at, status) VALUES (7, 1, '2026-03-03 19:05:00', '2026-03-03 19:05:00', 'paid')"
        )
        conn.commit()

    update, message = make_update()
    run_async(admin_commands.clear_topups_command(update, make_context(["pending"])))
    assert "Удалено pending топапов: 1" in message.calls[-1]["text"]

    update, message = make_update()
    run_async(admin_commands.clear_user_analysis_command(update, make_context(["7"])))
    assert "Удалено покупок: 1" in message.calls[-1]["text"]
    assert "Очищено анализов матчей: 1" in message.calls[-1]["text"]
    assert not png_path.exists()


def test_user_lookup_and_topups_commands(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    monkeypatch.setattr(
        admin_commands.database,
        "get_user_full_info",
        lambda user_id: {
            "user": {
                "user_id": user_id,
                "username": "götterkiller",
                "balance": 3,
                "total_analysis_bought": 3,
                "created_at": "2026-03-03 19:16:00",
            },
            "purchases": [
                {
                    "id": 45,
                    "match_id": 83,
                    "status": "paid",
                    "created_at": "2026-03-03 19:23:00",
                    "purchase_date": "2026-03-03 19:23:00",
                }
            ],
            "topups": [],
        },
    )
    monkeypatch.setattr(
        admin_commands.database,
        "find_users",
        lambda query, limit=10: [
            {
                "user_id": 901255375,
                "username": "götterkiller",
                "balance": 3,
                "total_analysis_bought": 3,
                "created_at": "2026-03-03 19:16:00",
            }
        ],
    )
    monkeypatch.setattr(
        admin_commands.database,
        "get_all_pending_topups",
        lambda: [
            {
                "user_id": 901255375,
                "username": "götterkiller",
                "amount_rub": 100,
                "token": "ABCD12345678",
                "created_at": "2026-03-03 19:20:00",
                "expires_at": "2099-03-03 20:20:00",
            }
        ],
    )

    update, message = make_update()
    run_async(admin_commands.userinfo_command(update, make_context(["901255375"])))
    assert "#45 | match=83" in message.calls[-1]["text"]

    update, message = make_update()
    run_async(admin_commands.finduser_command(update, make_context(["götterkiller"])))
    assert "/refund_last 901255375" in message.calls[-1]["text"]

    update, message = make_update()
    run_async(admin_commands.topups_pending_command(update, make_context()))
    text = message.calls[-1]["text"]
    # Маска присутствует, полный токен — нет
    assert "ABCD…5678" in text
    assert "ABCD12345678" not in text


def test_recent_donations_command(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    monkeypatch.setitem(
        sys.modules,
        "da_polling",
        SimpleNamespace(
            get_recent_donations=lambda limit: [
                {
                    "id": "d-1",
                    "amount": 150,
                    "username": "supporter",
                    "message": "Спасибо за бота",
                    "created_at": "2026-03-03 19:30:00",
                }
            ]
        ),
    )

    update, message = make_update()
    run_async(admin_commands.recent_donations_command(update, make_context(["5"])))

    assert "Запрашиваю последние донаты" in message.calls[0]["text"]
    assert "supporter" in message.calls[-1]["text"]


def test_refund_commands_handle_sqlite_row_purchase(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    purchase_row = build_sqlite_row(
        id=45,
        user_id=901255375,
        match_id=83,
        team1="Arsenal",
        team2="Chelsea",
        match_date="2026-03-03",
        match_time="20:00",
    )

    monkeypatch.setattr(admin_commands.database, "refund_purchase", lambda purchase_id: (True, 901255375, 150))
    monkeypatch.setattr(
        admin_commands.database,
        "get_user_full_info",
        lambda user_id: {"user": {"username": "götterkiller", "balance": 153}},
    )
    monkeypatch.setattr(admin_commands.database, "get_user_balance", lambda user_id: 153)
    monkeypatch.setattr(admin_commands.database, "get_last_paid_purchase_by_user", lambda user_id: purchase_row)

    update, message = make_update()
    run_async(admin_commands.refund_command(update, make_context(["45"])))
    assert "purchase_id: 45" in message.calls[-1]["text"]

    update, message = make_update()
    run_async(admin_commands.refund_last_command(update, make_context(["901255375"])))
    assert "Arsenal vs Chelsea" in message.calls[-1]["text"]


def test_force_sync_command(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    sync_calls = {"sync": 0, "saved_matches": None}

    class FakeSyncer:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def sync(self):
            sync_calls["sync"] += 1
            return [{"id": 1}]

        def save_matches_to_db(self, matches):
            sync_calls["saved_matches"] = matches
            return {"total": 1, "inserted": 1, "skipped": 0, "errors": 0}

    monkeypatch.setitem(
        sys.modules,
        "sync_matches",
        SimpleNamespace(
            SportsDBSyncer=FakeSyncer,
            run_coverage_check=lambda: {"checked": 1, "ok": 1, "hidden": 0, "errors": 0},
        ),
    )

    update, message = make_update()
    run_async(admin_commands.force_sync_command(update, make_context()))

    assert sync_calls["sync"] == 1
    assert sync_calls["saved_matches"] == [{"id": 1}]
    assert "найдено: 1" in message.calls[-1]["text"]
    assert "проверено: 1" in message.calls[-1]["text"]


def test_regen_commands_route_correct_match_ids(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    purchase_row = build_sqlite_row(
        id=45,
        user_id=901255375,
        match_id=83,
        team1="Arsenal",
        team2="Chelsea",
        match_date="2026-03-03",
        match_time="20:00",
    )
    run_regen = AsyncMock()

    monkeypatch.setattr(admin_commands.database, "get_last_paid_purchase_by_user", lambda user_id: purchase_row)
    monkeypatch.setattr(admin_commands, "_run_regen_flow", run_regen)

    update, message = make_update()
    run_async(admin_commands.regen_command(update, make_context(["83", "901255375"])))
    run_regen.assert_awaited_with(update, ANY, 1, 83, target_user_id=901255375)

    update, message = make_update()
    context = make_context(["901255375"])
    run_async(admin_commands.regen_last_command(update, context))
    assert any("match_id: 83" in call["text"] for call in message.calls)
    run_regen.assert_awaited_with(update, context, 1, 83, target_user_id=None)


def test_matchinfo_command_renders_match_and_purchases(sqlite_db, monkeypatch):
    with admin_commands.database.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO users (user_id, username, balance, total_analysis_bought, created_at) VALUES (9, 'buyer', 0, 1, '2026-03-03 19:00:00')"
        )
        conn.execute(
            "INSERT INTO purchases (id, user_id, match_id, purchase_date, created_at, status) VALUES (45, 9, 83, '2026-03-03 19:23:00', '2026-03-03 19:23:00', 'paid')"
        )
        conn.commit()

    monkeypatch.setattr(
        admin_commands.database,
        "get_match_by_id",
        lambda match_id: {
            "id": match_id,
            "team1": "Arsenal",
            "team2": "Chelsea",
            "match_date": "2026-03-03",
            "match_time": "20:00",
            "league": "Premier League",
            "sport": "football",
            "api_event_id": "tsdb-123",
            "is_active": 1,
            "coverage_ok": 1,
            "analysis_text": "готов",
            "analysis_png_path": "analysis_cache/table.webp",
            "price": 150,
        },
    )

    update, message = make_update()
    run_async(admin_commands.matchinfo_command(update, make_context(["83"])))

    text = message.calls[-1]["text"]
    assert "Матч #83" in text
    assert "Покупки:</b> 1 paid" in text
    assert "#45" in text


def test_clean_matches_and_clean_all_matches_commands(sqlite_db, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    cache_dir = tmp_path / "analysis_cache"
    cache_dir.mkdir()
    orphan_png = cache_dir / "orphan.webp"
    orphan_png.write_bytes(b"png")
    linked_png = tmp_path / "linked.webp"
    linked_png.write_bytes(b"png")

    with admin_commands.database.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO matches (team1, team2, match_date, match_time, league, sport, analysis_text, analysis_png_path) VALUES ('A', 'B', '2026-03-03', '20:00', 'League', 'football', 'text', ?)",
            (str(linked_png),),
        )
        conn.execute(
            "INSERT INTO purchases (user_id, match_id, purchase_date, created_at, status) VALUES (1, 1, '2026-03-03 19:05:00', '2026-03-03 19:05:00', 'paid')"
        )
        conn.commit()

    monkeypatch.setattr(admin_commands.database, "cleanup_old_purchases", lambda: 1)
    monkeypatch.setattr(admin_commands.database, "delete_finished_matches_without_purchases", lambda: 2)

    update, message = make_update()
    run_async(admin_commands.clean_matches_command(update, make_context()))
    assert "Удалено покупок: 1" in message.calls[-1]["text"]
    assert not orphan_png.exists()

    update, message = make_update()
    run_async(admin_commands.clean_all_matches_command(update, make_context(["CONFIRM"])))
    assert "ПОЛНАЯ очистка завершена" in message.calls[-1]["text"]

    with admin_commands.database.get_db_connection() as conn:
        matches_count = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        purchases_count = conn.execute("SELECT COUNT(*) FROM purchases").fetchone()[0]

    assert matches_count == 0
    assert purchases_count == 0



# ═══════════════════════════════════════════════════════════════════════════
# /stats
# ═══════════════════════════════════════════════════════════════════════════

def test_stats_empty_db(sqlite_db, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    update, message = make_update()
    run_async(admin_commands.stats_command(update, make_context()))
    text = message.calls[-1]["text"]
    assert "Матчи: 0" in text
    assert "Покупки: 0" in text
    assert "Пользователи: 0" in text


def test_stats_no_analysis_cache_dir(sqlite_db, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    # analysis_cache не создаём — команда не должна упасть
    update, message = make_update()
    run_async(admin_commands.stats_command(update, make_context()))
    assert "0.00 MB" in message.calls[-1]["text"]


# ═══════════════════════════════════════════════════════════════════════════
# /addbalance
# ═══════════════════════════════════════════════════════════════════════════

def test_addbalance_missing_args(sqlite_db):
    update, message = make_update()
    run_async(admin_commands.add_balance_command(update, make_context([])))
    assert "Неверный формат" in message.calls[-1]["text"]


def test_addbalance_non_numeric(sqlite_db):
    update, message = make_update()
    run_async(admin_commands.add_balance_command(update, make_context(["abc", "50"])))
    assert "целыми числами" in message.calls[-1]["text"]


def test_addbalance_zero_amount(sqlite_db):
    update, message = make_update()
    run_async(admin_commands.add_balance_command(update, make_context(["1", "0"])))
    assert "положительной" in message.calls[-1]["text"]


def test_addbalance_negative_amount(sqlite_db):
    update, message = make_update()
    run_async(admin_commands.add_balance_command(update, make_context(["1", "-10"])))
    assert "положительной" in message.calls[-1]["text"]


def test_addbalance_nonexistent_user(sqlite_db):
    update, message = make_update()
    run_async(admin_commands.add_balance_command(update, make_context(["999999999", "50"])))
    assert "не найден" in message.calls[-1]["text"]


# ═══════════════════════════════════════════════════════════════════════════
# /clearbalance
# ═══════════════════════════════════════════════════════════════════════════

def test_clearbalance_missing_args(sqlite_db):
    update, message = make_update()
    run_async(admin_commands.clear_balance_command(update, make_context([])))
    assert "Неверный формат" in message.calls[-1]["text"]


def test_clearbalance_nonexistent_user(sqlite_db):
    update, message = make_update()
    run_async(admin_commands.clear_balance_command(update, make_context(["999999999"])))
    assert "не найден" in message.calls[-1]["text"]


# ═══════════════════════════════════════════════════════════════════════════
# /userinfo
# ═══════════════════════════════════════════════════════════════════════════

def test_userinfo_nonexistent_user(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    monkeypatch.setattr(admin_commands.database, "get_user_full_info", lambda user_id: None)
    update, message = make_update()
    run_async(admin_commands.userinfo_command(update, make_context(["999"])))
    assert "не найден" in message.calls[-1]["text"]


def test_userinfo_no_purchases_no_topups(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    monkeypatch.setattr(admin_commands.database, "get_user_full_info", lambda user_id: {
        "user": {
            "user_id": user_id, "username": None, "balance": 0,
            "total_analysis_bought": 0, "created_at": "2026-03-03 10:00:00",
        },
        "purchases": [],
        "topups": [],
    })
    update, message = make_update()
    run_async(admin_commands.userinfo_command(update, make_context(["1"])))
    text = message.calls[-1]["text"]
    assert "Нет покупок" in text
    assert "Нет пополнений" in text


def test_userinfo_html_special_chars_escaped(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    monkeypatch.setattr(admin_commands.database, "get_user_full_info", lambda user_id: {
        "user": {
            "user_id": user_id,
            "username": "<script>alert(1)</script>",
            "balance": 0, "total_analysis_bought": 0,
            "created_at": "2026-03-03 10:00:00",
        },
        "purchases": [],
        "topups": [],
    })
    update, message = make_update()
    run_async(admin_commands.userinfo_command(update, make_context(["1"])))
    text = message.calls[-1]["text"]
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


def test_userinfo_token_is_masked(monkeypatch):
    """Полный токен не должен всплывать в /userinfo."""
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    monkeypatch.setattr(admin_commands.database, "get_user_full_info", lambda user_id: {
        "user": {
            "user_id": user_id, "username": "testuser", "balance": 50,
            "total_analysis_bought": 1, "created_at": "2026-03-03 10:00:00",
        },
        "purchases": [],
        "topups": [
            {
                "id": 7,
                "amount_rub": 100,
                "status": "pending",
                "token": "ABCD12345678",
                "created_at": "2026-03-03 10:05:00",
            }
        ],
    })
    update, message = make_update()
    run_async(admin_commands.userinfo_command(update, make_context(["1"])))
    text = message.calls[-1]["text"]
    assert "ABCD12345678" not in text
    assert "ABCD…5678" in text


def test_mask_token_helper():
    """_mask_token: длинный токен маскируется, короткий — без изменений."""
    assert admin_commands._mask_token("ABCD12345678") == "ABCD…5678"
    assert admin_commands._mask_token("short") == "short"
    assert admin_commands._mask_token(None) == "—"


# ═══════════════════════════════════════════════════════════════════════════
# /finduser
# ═══════════════════════════════════════════════════════════════════════════

def test_finduser_no_args(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    update, message = make_update()
    run_async(admin_commands.finduser_command(update, make_context([])))
    assert "Использование" in message.calls[-1]["text"]


def test_finduser_not_found(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    monkeypatch.setattr(admin_commands.database, "find_users", lambda query, limit=10: [])
    update, message = make_update()
    run_async(admin_commands.finduser_command(update, make_context(["nobody"])))
    assert "никого не нашёл" in message.calls[-1]["text"].lower()


def test_finduser_multi_word_query_joined(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    received = []

    def find_users(query, limit=10):
        received.append(query)
        return []

    monkeypatch.setattr(admin_commands.database, "find_users", find_users)
    update, message = make_update()
    run_async(admin_commands.finduser_command(update, make_context(["john", "doe"])))
    assert received[0] == "john doe"


# ═══════════════════════════════════════════════════════════════════════════
# /refund
# ═══════════════════════════════════════════════════════════════════════════

def test_refund_missing_args(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    update, message = make_update()
    run_async(admin_commands.refund_command(update, make_context([])))
    assert "Использование" in message.calls[-1]["text"]


def test_refund_non_numeric(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    update, message = make_update()
    run_async(admin_commands.refund_command(update, make_context(["abc"])))
    assert "целым числом" in message.calls[-1]["text"]


def test_refund_already_refunded(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    monkeypatch.setattr(
        admin_commands.database,
        "refund_purchase",
        lambda purchase_id: (False, "уже возвращён"),
    )
    update, message = make_update()
    run_async(admin_commands.refund_command(update, make_context(["45"])))
    assert "Возврат не выполнен" in message.calls[-1]["text"]


# ═══════════════════════════════════════════════════════════════════════════
# /refund_last
# ═══════════════════════════════════════════════════════════════════════════

def test_refund_last_missing_args(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    update, message = make_update()
    run_async(admin_commands.refund_last_command(update, make_context([])))
    assert "Использование" in message.calls[-1]["text"]


def test_refund_last_non_numeric_user(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    update, message = make_update()
    run_async(admin_commands.refund_last_command(update, make_context(["abc"])))
    assert "целым числом" in message.calls[-1]["text"]


def test_refund_last_no_purchases(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    monkeypatch.setattr(
        admin_commands.database,
        "get_last_paid_purchase_by_user",
        lambda user_id: None,
    )
    update, message = make_update()
    run_async(admin_commands.refund_last_command(update, make_context(["1"])))
    assert "нет оплаченных покупок" in message.calls[-1]["text"]


# ═══════════════════════════════════════════════════════════════════════════
# /regen и _run_regen_flow
# ═══════════════════════════════════════════════════════════════════════════

def test_regen_missing_args(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    update, message = make_update()
    run_async(admin_commands.regen_command(update, make_context([])))
    assert "Использование" in message.calls[-1]["text"]


def test_regen_non_numeric(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    update, message = make_update()
    run_async(admin_commands.regen_command(update, make_context(["abc"])))
    assert "целыми числами" in message.calls[-1]["text"]


def test_regen_flow_match_not_found(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    monkeypatch.setattr(admin_commands.database, "get_match_by_id", lambda match_id: None)
    update, message = make_update()
    run_async(admin_commands._run_regen_flow(update, make_context(), 1, 999))
    assert "не найден" in message.calls[-1]["text"]


def test_regen_flow_rejects_concurrent_generation(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    monkeypatch.setattr(admin_commands.database, "get_match_by_id", lambda match_id: {
        "id": match_id, "team1": "Arsenal", "team2": "Chelsea",
        "match_date": "2026-03-03", "match_time": "20:00",
    })
    monkeypatch.setattr(
        admin_commands.database,
        "acquire_generation_job",
        lambda match_id, owner, stale_after_seconds: False,
        raising=False,
    )
    update, message = make_update()
    run_async(admin_commands._run_regen_flow(update, make_context(), 1, 83))
    assert "уже идёт генерация" in message.calls[-1]["text"]


# ═══════════════════════════════════════════════════════════════════════════
# /regen_last
# ═══════════════════════════════════════════════════════════════════════════

def test_regen_last_missing_args(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    update, message = make_update()
    run_async(admin_commands.regen_last_command(update, make_context([])))
    assert "Использование" in message.calls[-1]["text"]


def test_regen_last_no_purchases(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    monkeypatch.setattr(
        admin_commands.database,
        "get_last_paid_purchase_by_user",
        lambda user_id: None,
    )
    update, message = make_update()
    run_async(admin_commands.regen_last_command(update, make_context(["1"])))
    assert "нет оплаченных покупок" in message.calls[-1]["text"]


# ═══════════════════════════════════════════════════════════════════════════
# /matchinfo
# ═══════════════════════════════════════════════════════════════════════════

def test_matchinfo_missing_args(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    update, message = make_update()
    run_async(admin_commands.matchinfo_command(update, make_context([])))
    assert "Использование" in message.calls[-1]["text"]


def test_matchinfo_not_found(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    monkeypatch.setattr(admin_commands.database, "get_match_by_id", lambda match_id: None)
    update, message = make_update()
    run_async(admin_commands.matchinfo_command(update, make_context(["999"])))
    assert "не найден" in message.calls[-1]["text"]


def test_matchinfo_multiple_buyers(sqlite_db, monkeypatch):
    with admin_commands.database.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO users (user_id, username, balance, total_analysis_bought, created_at) "
            "VALUES (10, 'alice', 0, 1, '2026-03-03 10:00:00')"
        )
        conn.execute(
            "INSERT INTO users (user_id, username, balance, total_analysis_bought, created_at) "
            "VALUES (11, 'bob', 0, 1, '2026-03-03 10:00:00')"
        )
        conn.execute(
            "INSERT INTO purchases (id, user_id, match_id, purchase_date, created_at, status) "
            "VALUES (1, 10, 83, '2026-03-03 10:00:00', '2026-03-03 10:00:00', 'paid')"
        )
        conn.execute(
            "INSERT INTO purchases (id, user_id, match_id, purchase_date, created_at, status) "
            "VALUES (2, 11, 83, '2026-03-03 10:01:00', '2026-03-03 10:01:00', 'paid')"
        )
        conn.commit()

    monkeypatch.setattr(admin_commands.database, "get_match_by_id", lambda match_id: {
        "id": match_id, "team1": "Arsenal", "team2": "Chelsea",
        "match_date": "2026-03-03", "match_time": "20:00",
        "league": "Premier League", "sport": "football",
        "api_event_id": "tsdb-123", "is_active": 1, "coverage_ok": 1,
        "analysis_text": "готов", "analysis_png_path": None, "price": 150,
    })
    update, message = make_update()
    run_async(admin_commands.matchinfo_command(update, make_context(["83"])))
    text = message.calls[-1]["text"]
    assert "2 paid" in text
    assert "alice" in text
    assert "bob" in text


# ═══════════════════════════════════════════════════════════════════════════
# /clearpurchases
# ═══════════════════════════════════════════════════════════════════════════

def test_clearpurchases_no_args(sqlite_db):
    update, message = make_update()
    run_async(admin_commands.clear_purchases_command(update, make_context([])))
    assert "Укажите аргумент" in message.calls[-1]["text"]


def test_clearpurchases_invalid_arg(sqlite_db):
    update, message = make_update()
    run_async(admin_commands.clear_purchases_command(update, make_context(["notanumber"])))
    assert "all" in message.calls[-1]["text"].lower()


# ═══════════════════════════════════════════════════════════════════════════
# /cleartopups
# ═══════════════════════════════════════════════════════════════════════════

def test_cleartopups_no_args(sqlite_db):
    update, message = make_update()
    run_async(admin_commands.clear_topups_command(update, make_context([])))
    assert "Укажите аргумент" in message.calls[-1]["text"]


def test_cleartopups_invalid_arg(sqlite_db):
    update, message = make_update()
    run_async(admin_commands.clear_topups_command(update, make_context(["notanumber"])))
    assert "all" in message.calls[-1]["text"].lower()


def test_cleartopups_pending_when_empty(sqlite_db):
    update, message = make_update()
    run_async(admin_commands.clear_topups_command(update, make_context(["pending"])))
    assert "Удалено pending топапов: 0" in message.calls[-1]["text"]


# ═══════════════════════════════════════════════════════════════════════════
# /clearuseranalysis
# ═══════════════════════════════════════════════════════════════════════════

def test_clearuseranalysis_no_purchases(sqlite_db):
    with admin_commands.database.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO users (user_id, username, balance, total_analysis_bought, created_at) "
            "VALUES (20, 'lonely', 0, 0, '2026-03-03 10:00:00')"
        )
        conn.commit()
    update, message = make_update()
    run_async(admin_commands.clear_user_analysis_command(update, make_context(["20"])))
    assert "удалять нечего" in message.calls[-1]["text"].lower()


def test_clearuseranalysis_shared_match_preserves_png(sqlite_db, monkeypatch, tmp_path):
    """Если у матча есть другой покупатель — PNG не трогаем."""
    png_path = tmp_path / "analysis_83.webp"
    png_path.write_bytes(b"img")

    with admin_commands.database.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO users (user_id, username, balance, total_analysis_bought, created_at) "
            "VALUES (21, 'userA', 0, 1, '2026-03-03 10:00:00')"
        )
        conn.execute(
            "INSERT INTO users (user_id, username, balance, total_analysis_bought, created_at) "
            "VALUES (22, 'userB', 0, 1, '2026-03-03 10:00:00')"
        )
        conn.execute(
            "INSERT INTO matches (id, team1, team2, match_date, match_time, league, sport, analysis_text, analysis_png_path) "
            "VALUES (83, 'A', 'B', '2026-03-03', '20:00', 'L', 'football', 'текст', ?)",
            (str(png_path),),
        )
        conn.execute(
            "INSERT INTO purchases (user_id, match_id, purchase_date, created_at, status) "
            "VALUES (21, 83, '2026-03-03 10:00:00', '2026-03-03 10:00:00', 'paid')"
        )
        conn.execute(
            "INSERT INTO purchases (user_id, match_id, purchase_date, created_at, status) "
            "VALUES (22, 83, '2026-03-03 10:01:00', '2026-03-03 10:01:00', 'paid')"
        )
        conn.commit()

    update, message = make_update()
    run_async(admin_commands.clear_user_analysis_command(update, make_context(["21"])))

    assert png_path.exists(), "PNG не должен быть удалён — у матча есть второй покупатель"
    assert "Очищено анализов матчей: 0" in message.calls[-1]["text"]


# ═══════════════════════════════════════════════════════════════════════════
# /clean_matches
# ═══════════════════════════════════════════════════════════════════════════

def test_clean_matches_empty_db_and_cache(sqlite_db, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "analysis_cache").mkdir()
    monkeypatch.setattr(admin_commands.database, "cleanup_old_purchases", lambda: 0)
    monkeypatch.setattr(admin_commands.database, "delete_finished_matches_without_purchases", lambda: 0)
    update, message = make_update()
    run_async(admin_commands.clean_matches_command(update, make_context()))
    text = message.calls[-1]["text"]
    assert "Удалено покупок: 0" in text
    assert "Удалено матчей: 0" in text
    assert "Удалено осиротевших PNG: 0" in text


# ═══════════════════════════════════════════════════════════════════════════
# /clean_all_matches
# ═══════════════════════════════════════════════════════════════════════════

def test_clean_all_matches_without_confirm(sqlite_db):
    update, message = make_update()
    run_async(admin_commands.clean_all_matches_command(update, make_context([])))
    assert "CONFIRM" in message.calls[-1]["text"]


def test_clean_all_matches_lowercase_confirm_rejected(sqlite_db):
    """Только точное CONFIRM в капслоке — любой другой регистр отклоняется."""
    update, message = make_update()
    run_async(admin_commands.clean_all_matches_command(update, make_context(["confirm"])))
    assert "CONFIRM" in message.calls[-1]["text"]
    assert "ПОЛНАЯ очистка завершена" not in message.calls[-1]["text"]


def test_clean_all_matches_resets_sqlite_sequence(sqlite_db):
    with admin_commands.database.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO matches (team1, team2, match_date, match_time, league, sport) "
            "VALUES ('A', 'B', '2026-03-03', '20:00', 'L', 'football')"
        )
        conn.execute(
            "INSERT INTO purchases (user_id, match_id, purchase_date, created_at, status) "
            "VALUES (1, 1, '2026-03-03 10:00:00', '2026-03-03 10:00:00', 'paid')"
        )
        conn.commit()

    update, message = make_update()
    run_async(admin_commands.clean_all_matches_command(update, make_context(["CONFIRM"])))

    with admin_commands.database.get_db_connection() as conn:
        remaining = conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name IN ('matches', 'purchases')"
        ).fetchall()
    assert remaining == [], "sqlite_sequence должен быть сброшен после clean_all_matches"


# ═══════════════════════════════════════════════════════════════════════════
# /force_sync
# ═══════════════════════════════════════════════════════════════════════════

def test_force_sync_exception_path(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)

    class BoomSyncer:
        def __init__(self, **kwargs):
            pass

        def sync(self):
            raise RuntimeError("сеть недоступна")

    monkeypatch.setitem(
        sys.modules,
        "sync_matches",
        SimpleNamespace(SportsDBSyncer=BoomSyncer, run_coverage_check=lambda: {}),
    )
    update, message = make_update()
    run_async(admin_commands.force_sync_command(update, make_context()))
    assert "Ошибка синхронизации" in message.calls[-1]["text"]


# ═══════════════════════════════════════════════════════════════════════════
# /recent_donations
# ═══════════════════════════════════════════════════════════════════════════

def test_recent_donations_default_limit(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    received_limit = []
    monkeypatch.setitem(
        sys.modules,
        "da_polling",
        SimpleNamespace(get_recent_donations=lambda limit: received_limit.append(limit) or []),
    )
    update, message = make_update()
    run_async(admin_commands.recent_donations_command(update, make_context([])))
    assert received_limit[0] == 10


def test_recent_donations_non_numeric_arg(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    update, message = make_update()
    run_async(admin_commands.recent_donations_command(update, make_context(["abc"])))
    assert "целым числом" in message.calls[-1]["text"]


def test_recent_donations_no_results(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    monkeypatch.setitem(
        sys.modules,
        "da_polling",
        SimpleNamespace(get_recent_donations=lambda limit: []),
    )
    update, message = make_update()
    run_async(admin_commands.recent_donations_command(update, make_context(["5"])))
    assert "не вернул донаты" in message.calls[-1]["text"]


# ═══════════════════════════════════════════════════════════════════════════
# _reply_text_chunks
# ═══════════════════════════════════════════════════════════════════════════

def test_reply_text_chunks_splits_long_message():
    message = DummyMessage()
    long_text = "строка\n" * 600  # ~4200 символов > MAX_ADMIN_MESSAGE_LEN
    run_async(admin_commands._reply_text_chunks(message, long_text))
    assert len(message.calls) > 1
    for call in message.calls:
        assert len(call["text"]) <= admin_commands.MAX_ADMIN_MESSAGE_LEN


def test_reply_text_chunks_empty_string():
    message = DummyMessage()
    run_async(admin_commands._reply_text_chunks(message, ""))
    assert message.calls == []


def test_reply_text_chunks_short_message():
    message = DummyMessage()
    run_async(admin_commands._reply_text_chunks(message, "коротко"))
    assert len(message.calls) == 1
    assert message.calls[0]["text"] == "коротко"


# ═══════════════════════════════════════════════════════════════════════════

def test_admin_help_and_handler_registration(monkeypatch):
    monkeypatch.setattr(admin_commands.database, "is_admin", lambda user_id: True)
    update, message = make_update()
    run_async(admin_commands.admin_help_command(update, make_context()))
    assert "/refund_last user_id" in message.calls[-1]["text"]

    application = SimpleNamespace(add_handler=AsyncMock())
    recorded = []

    def add_handler(handler):
        recorded.extend(handler.commands)

    application.add_handler = add_handler
    admin_commands.setup_admin_handlers(application)

    expected = {
        "finduser",
        "userinfo",
        "topups_pending",
        "recent_donations",
        "refund_last",
        "refund",
        "force_sync",
        "regen_last",
        "regen",
        "clean_matches",
        "clean_all_matches",
        "stats",
        "addbalance",
        "clearbalance",
        "clearpurchases",
        "clearuseranalysis",
        "cleartopups",
        "matchinfo",
        "adminhelp",
    }
    assert set(recorded) == expected
