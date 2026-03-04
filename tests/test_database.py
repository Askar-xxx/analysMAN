"""Тесты для ключевой финансовой логики database.py."""

import sqlite3
from datetime import datetime, timedelta

import config
import database
import pytest


@pytest.fixture
def db(monkeypatch, tmp_path):
    db_path = tmp_path / "test_database.sqlite3"

    def connect():
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    with connect() as conn:
        database._init_db_tables(conn)

    monkeypatch.setattr(database, "get_db_connection", connect)
    monkeypatch.setattr(database, "get_db", connect)
    monkeypatch.setattr(config, "ANALYSIS_PRICE_RUB", 150)
    return connect


def _create_match(**overrides):
    params = {
        "sport": "football",
        "team1": "Arsenal",
        "team2": "Chelsea",
        "match_date": datetime.now().strftime("%Y-%m-%d"),
        "match_time": "20:00",
        "analysis_text": None,
        "price": 150,
        "league": "Premier League",
        "api_event_id": None,
    }
    params.update(overrides)
    return database.add_match(**params)


def _set_user_state(connect, user_id, balance, total_analysis_bought=0):
    with connect() as conn:
        conn.execute(
            """
            UPDATE users
            SET balance = ?, total_analysis_bought = ?
            WHERE user_id = ?
            """,
            (balance, total_analysis_bought, user_id),
        )
        conn.commit()


def test_purchase_analysis_happy_path(db):
    user = database.get_or_create_user(101, "buyer")
    match_id = _create_match(price=150)
    _set_user_state(db, user["user_id"], balance=300, total_analysis_bought=0)

    ok, message = database.purchase_analysis(user["user_id"], match_id)

    assert ok is True
    assert message == "Покупка успешна"

    with db() as conn:
        user_row = conn.execute(
            "SELECT balance, total_analysis_bought FROM users WHERE user_id = ?",
            (user["user_id"],),
        ).fetchone()
        purchase = conn.execute(
            """
            SELECT user_id, match_id, status, amount
            FROM purchases
            WHERE user_id = ? AND match_id = ?
            """,
            (user["user_id"], match_id),
        ).fetchone()

    assert user_row["balance"] == 150
    assert user_row["total_analysis_bought"] == 1
    assert purchase["status"] == "paid"
    assert purchase["amount"] == 15000


def test_purchase_analysis_rejects_insufficient_balance(db):
    user = database.get_or_create_user(102, "poor")
    match_id = _create_match()
    _set_user_state(db, user["user_id"], balance=10)

    ok, message = database.purchase_analysis(user["user_id"], match_id)

    assert ok is False
    assert "Недостаточно средств" in message


def test_purchase_analysis_rejects_duplicate_paid_purchase(db):
    user = database.get_or_create_user(103, "dup")
    match_id = _create_match()
    _set_user_state(db, user["user_id"], balance=500)

    first = database.purchase_analysis(user["user_id"], match_id)
    second = database.purchase_analysis(user["user_id"], match_id)

    assert first == (True, "Покупка успешна")
    assert second == (False, "Анализ уже приобретен")


def test_purchase_analysis_rejects_missing_match_and_user(db):
    user = database.get_or_create_user(104, "exists")
    _set_user_state(db, user["user_id"], balance=300)
    match_id = _create_match()

    assert database.purchase_analysis(user["user_id"], 999999) == (False, "Матч не найден")
    assert database.purchase_analysis(999999, match_id) == (False, "Пользователь не найден")


def test_purchase_analysis_does_not_allow_balance_to_go_negative(db):
    user = database.get_or_create_user(105, "single-shot")
    match1 = _create_match(team1="A", team2="B")
    match2 = _create_match(team1="C", team2="D", api_event_id="evt-2")
    _set_user_state(db, user["user_id"], balance=150)

    first = database.purchase_analysis(user["user_id"], match1)
    second = database.purchase_analysis(user["user_id"], match2)

    assert first == (True, "Покупка успешна")
    assert second[0] is False
    assert "Недостаточно средств" in second[1]
    assert database.get_user_balance(user["user_id"]) == 0


def test_refund_purchase_happy_path(db):
    user = database.get_or_create_user(106, "refund")
    match_id = _create_match(price=180)
    _set_user_state(db, user["user_id"], balance=500)
    ok, _ = database.purchase_analysis(user["user_id"], match_id)
    assert ok is True

    with db() as conn:
        purchase_id = conn.execute(
            "SELECT id FROM purchases WHERE user_id = ? AND match_id = ?",
            (user["user_id"], match_id),
        ).fetchone()["id"]

    result = database.refund_purchase(purchase_id)

    assert result == (True, user["user_id"], 180)

    with db() as conn:
        purchase = conn.execute(
            "SELECT status FROM purchases WHERE id = ?",
            (purchase_id,),
        ).fetchone()
        balance = conn.execute(
            "SELECT balance FROM users WHERE user_id = ?",
            (user["user_id"],),
        ).fetchone()["balance"]

    assert purchase["status"] == "refunded"
    assert balance == 530


def test_refund_purchase_rejects_missing_already_refunded_and_pending(db):
    user = database.get_or_create_user(107, "refund-cases")
    match_id = _create_match(team1="Milan", team2="Inter", api_event_id="evt-3")
    _set_user_state(db, user["user_id"], balance=0)

    with db() as conn:
        conn.execute(
            """
            INSERT INTO purchases (user_id, match_id, purchase_date, created_at, status, amount)
            VALUES (?, ?, ?, ?, 'refunded', 15000)
            """,
            (user["user_id"], match_id, "2026-03-03 19:00:00", "2026-03-03 19:00:00"),
        )
        refunded_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.execute(
            """
            INSERT INTO purchases (user_id, match_id, purchase_date, created_at, status, amount)
            VALUES (?, ?, ?, ?, 'pending', 15000)
            """,
            (user["user_id"], match_id, "2026-03-03 19:05:00", "2026-03-03 19:05:00"),
        )
        pending_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.commit()

    assert database.refund_purchase(999999) == (False, "Покупка не найдена")
    assert database.refund_purchase(refunded_id) == (False, "Покупка уже возвращена")
    assert database.refund_purchase(pending_id) == (False, "Возврат невозможен: статус pending")


def test_complete_balance_topup_happy_path_and_real_received_amount(db):
    user1 = database.get_or_create_user(108, "fixed-topup")
    user2 = database.get_or_create_user(109, "flex-topup")
    _set_user_state(db, user1["user_id"], balance=0)
    _set_user_state(db, user2["user_id"], balance=0)

    token1 = database.create_balance_topup(user1["user_id"], amount_rub=100)
    token2 = database.create_balance_topup(user2["user_id"], amount_rub=0)

    with db() as conn:
        topup1_id = conn.execute(
            "SELECT id FROM balance_topups WHERE token = ?",
            (token1,),
        ).fetchone()["id"]
        topup2_id = conn.execute(
            "SELECT id FROM balance_topups WHERE token = ?",
            (token2,),
        ).fetchone()["id"]

    assert database.complete_balance_topup(topup1_id, "don-1", None) is True
    assert database.complete_balance_topup(topup2_id, "don-2", 250) is True

    with db() as conn:
        topup1 = conn.execute(
            "SELECT status, donation_event_id, amount_rub FROM balance_topups WHERE id = ?",
            (topup1_id,),
        ).fetchone()
        topup2 = conn.execute(
            "SELECT status, donation_event_id, amount_rub FROM balance_topups WHERE id = ?",
            (topup2_id,),
        ).fetchone()

    assert topup1["status"] == "paid"
    assert topup1["donation_event_id"] == "don-1"
    assert topup1["amount_rub"] == 100
    assert database.get_user_balance(user1["user_id"]) == 100

    assert topup2["status"] == "paid"
    assert topup2["donation_event_id"] == "don-2"
    assert topup2["amount_rub"] == 250
    assert database.get_user_balance(user2["user_id"]) == 250


def test_complete_balance_topup_is_idempotent_and_rejects_missing(db):
    user = database.get_or_create_user(110, "idempotent-topup")
    _set_user_state(db, user["user_id"], balance=0)
    token = database.create_balance_topup(user["user_id"], amount_rub=150)

    with db() as conn:
        topup_id = conn.execute(
            "SELECT id FROM balance_topups WHERE token = ?",
            (token,),
        ).fetchone()["id"]

    first = database.complete_balance_topup(topup_id, "don-3", 150)
    second = database.complete_balance_topup(topup_id, "don-3", 150)

    assert first is True
    assert second is False
    assert database.complete_balance_topup(999999, "don-missing", 100) is False
    assert database.get_user_balance(user["user_id"]) == 150


def test_get_or_create_user_creates_without_duplicates_and_updates_username(db):
    first = database.get_or_create_user(111, "first_name")
    second = database.get_or_create_user(111, "updated_name")

    with db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE user_id = ?",
            (111,),
        ).fetchone()["c"]
        username = conn.execute(
            "SELECT username FROM users WHERE user_id = ?",
            (111,),
        ).fetchone()["username"]

    assert first["user_id"] == 111
    assert second["user_id"] == 111
    assert count == 1
    assert username == "updated_name"


def test_add_balance_and_get_user_balance(db):
    user = database.get_or_create_user(112, "balance")
    _set_user_state(db, user["user_id"], balance=5)

    database.add_balance(user["user_id"], 7)

    assert database.get_user_balance(user["user_id"]) == 12
    assert database.get_user_balance(999999) == 0


def test_generation_job_lifecycle_and_stale_takeover(db):
    match_id = _create_match(api_event_id="evt-lock")

    assert database.acquire_generation_job(match_id, owner="u1", stale_after_seconds=300) is True
    assert database.acquire_generation_job(match_id, owner="u2", stale_after_seconds=300) is False

    database.finish_generation_job(match_id, status="done")
    assert database.acquire_generation_job(match_id, owner="u3", stale_after_seconds=300) is True

    with db() as conn:
        conn.execute(
            "UPDATE generation_jobs SET status = 'running', updated_at = '2000-01-01 00:00:00' WHERE match_id = ?",
            (match_id,),
        )
        conn.commit()

    assert database.acquire_generation_job(match_id, owner="u4", stale_after_seconds=1) is True


def test_expire_pending_topups_expires_only_past_rows(db):
    user = database.get_or_create_user(113, "expirer")
    _set_user_state(db, user["user_id"], balance=0)
    past = (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    future = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")

    with db() as conn:
        conn.execute(
            """
            INSERT INTO balance_topups (user_id, amount_rub, amount_kopeks, token, status, created_at, expires_at)
            VALUES (?, 100, 10000, 'TOPUPPAST001', 'pending', ?, ?)
            """,
            (user["user_id"], past, past),
        )
        conn.execute(
            """
            INSERT INTO balance_topups (user_id, amount_rub, amount_kopeks, token, status, created_at, expires_at)
            VALUES (?, 100, 10000, 'TOPUPFUTURE1', 'pending', ?, ?)
            """,
            (user["user_id"], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), future),
        )
        conn.commit()

    expired_count = database.expire_pending_topups()

    with db() as conn:
        statuses = {
            row["token"]: row["status"]
            for row in conn.execute("SELECT token, status FROM balance_topups").fetchall()
        }

    assert expired_count == 1
    assert statuses["TOPUPPAST001"] == "expired"
    assert statuses["TOPUPFUTURE1"] == "pending"


def test_is_donation_event_used_becomes_true_after_topup_completion(db):
    user = database.get_or_create_user(114, "used-donation")
    _set_user_state(db, user["user_id"], balance=0)
    token = database.create_balance_topup(user["user_id"], amount_rub=50)

    with db() as conn:
        topup_id = conn.execute(
            "SELECT id FROM balance_topups WHERE token = ?",
            (token,),
        ).fetchone()["id"]

    assert database.is_donation_event_used("don-4") is False
    assert database.complete_balance_topup(topup_id, "don-4", 50) is True
    assert database.is_donation_event_used("don-4") is True


def test_cleanup_old_purchases_deletes_only_old_purchase_and_png(db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    old_date = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    new_date = datetime.now().strftime("%Y-%m-%d")
    old_png = tmp_path / "old.webp"
    old_png.write_bytes(b"png")

    old_match_id = _create_match(team1="Old", team2="Match", match_date=old_date, api_event_id="evt-old")
    new_match_id = _create_match(team1="New", team2="Match", match_date=new_date, api_event_id="evt-new")
    user = database.get_or_create_user(115, "cleanup")
    _set_user_state(db, user["user_id"], balance=0)

    with db() as conn:
        conn.execute(
            "UPDATE matches SET analysis_png_path = ? WHERE id = ?",
            (str(old_png), old_match_id),
        )
        conn.execute(
            """
            INSERT INTO purchases (user_id, match_id, purchase_date, created_at, status, amount)
            VALUES (?, ?, '2026-03-01 10:00:00', '2026-03-01 10:00:00', 'paid', 15000)
            """,
            (user["user_id"], old_match_id),
        )
        conn.execute(
            """
            INSERT INTO purchases (user_id, match_id, purchase_date, created_at, status, amount)
            VALUES (?, ?, '2026-03-03 10:00:00', '2026-03-03 10:00:00', 'paid', 15000)
            """,
            (user["user_id"], new_match_id),
        )
        conn.commit()

    deleted_count = database.cleanup_old_purchases()

    with db() as conn:
        remaining_match_ids = {
            row["match_id"] for row in conn.execute("SELECT match_id FROM purchases").fetchall()
        }

    assert deleted_count == 1
    assert remaining_match_ids == {new_match_id}
    assert not old_png.exists()
