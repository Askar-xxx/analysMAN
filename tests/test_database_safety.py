"""Safety tests for database.py purchase and generation lock flows."""
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

import database
from config import ANALYSIS_PRICE_RUB


def _mk_conn_factory(db_path):
    def _conn():
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    return _conn


def _create_temp_db():
    fd, path = tempfile.mkstemp(prefix="analysman_db_", suffix=".db")
    os.close(fd)
    return path


def test_purchase_analysis_prevents_double_paid_purchase():
    """A second purchase for the same match must not charge user twice."""
    db_path = _create_temp_db()
    try:
        conn_factory = _mk_conn_factory(db_path)
        with patch("database.get_db_connection", new=conn_factory):
            database.init_db()

            user_id = 10001
            database.get_or_create_user(user_id, "tester")
            match_id = database.add_match(
                sport="football",
                team1="A",
                team2="B",
                match_date="2026-02-27",
                match_time="20:00",
            )

            start_balance = int(ANALYSIS_PRICE_RUB) * 5
            conn = conn_factory()
            conn.execute(
                "UPDATE users SET balance = ?, total_analysis_bought = 0 WHERE user_id = ?",
                (start_balance, user_id),
            )
            conn.commit()
            conn.close()

            ok1, msg1 = database.purchase_analysis(user_id, match_id)
            ok2, msg2 = database.purchase_analysis(user_id, match_id)

            assert ok1 is True, msg1
            assert ok2 is False
            assert "приобрет" in str(msg2).lower()

            conn = conn_factory()
            paid_count = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM purchases
                WHERE user_id = ? AND match_id = ? AND status = 'paid'
                """,
                (user_id, match_id),
            ).fetchone()["c"]
            balance = conn.execute(
                "SELECT balance FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()["balance"]
            conn.close()

            assert paid_count == 1
            assert balance == start_balance - int(ANALYSIS_PRICE_RUB)
    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass


def test_generation_job_lock_lifecycle():
    """Generation lock should be acquired once and reusable after finish."""
    db_path = _create_temp_db()
    try:
        conn_factory = _mk_conn_factory(db_path)
        with patch("database.get_db_connection", new=conn_factory):
            database.init_db()

            match_id = database.add_match(
                sport="football",
                team1="C",
                team2="D",
                match_date="2026-02-27",
                match_time="21:00",
            )

            acquired1 = database.acquire_generation_job(match_id, owner="u1", stale_after_seconds=300)
            acquired2 = database.acquire_generation_job(match_id, owner="u2", stale_after_seconds=300)

            assert acquired1 is True
            assert acquired2 is False

            database.finish_generation_job(match_id, status="done")
            acquired3 = database.acquire_generation_job(match_id, owner="u3", stale_after_seconds=300)
            assert acquired3 is True
    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass


def test_init_db_deduplicates_legacy_paid_purchases_before_unique_index():
    """init_db should clean legacy duplicates and then create unique paid index."""
    db_path = _create_temp_db()
    try:
        conn_factory = _mk_conn_factory(db_path)
        with patch("database.get_db_connection", new=conn_factory):
            database.init_db()
            user_id = 10002
            database.get_or_create_user(user_id, "legacy")
            match_id = database.add_match(
                sport="football",
                team1="Legacy A",
                team2="Legacy B",
                match_date="2026-02-28",
                match_time="22:00",
            )

            conn = conn_factory()
            conn.execute("DROP INDEX IF EXISTS idx_purchases_paid_user_match")
            conn.execute(
                """
                INSERT INTO purchases (user_id, match_id, purchase_date, status, amount)
                VALUES (?, ?, '2026-02-25 12:00:00', 'paid', 100)
                """,
                (user_id, match_id),
            )
            conn.execute(
                """
                INSERT INTO purchases (user_id, match_id, purchase_date, status, amount)
                VALUES (?, ?, '2026-02-25 12:01:00', 'paid', 100)
                """,
                (user_id, match_id),
            )
            conn.commit()
            conn.close()

            database.init_db()

            conn = conn_factory()
            paid_count = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM purchases
                WHERE user_id = ? AND match_id = ? AND status = 'paid'
                """,
                (user_id, match_id),
            ).fetchone()["c"]
            unique_index = conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'index' AND name = 'idx_purchases_paid_user_match'
                """
            ).fetchone()
            conn.close()

            assert paid_count == 1
            assert unique_index is not None
    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass


def test_expire_old_pending_purchases_marks_only_stale_rows():
    """Old pending purchases must expire without affecting fresh or paid rows."""
    db_path = _create_temp_db()
    try:
        conn_factory = _mk_conn_factory(db_path)
        with patch("database.get_db_connection", new=conn_factory):
            database.init_db()

            user_id = 10003
            database.get_or_create_user(user_id, "cleanup")
            match_id = database.add_match(
                sport="football",
                team1="Old",
                team2="Fresh",
                match_date="2026-03-01",
                match_time="19:00",
            )

            stale_created_at = (datetime.now() - timedelta(minutes=121)).strftime("%Y-%m-%d %H:%M:%S")
            fresh_created_at = (datetime.now() - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")

            conn = conn_factory()
            conn.execute(
                """
                INSERT INTO purchases (user_id, match_id, purchase_date, created_at, status, amount, token)
                VALUES (?, ?, ?, ?, 'pending', 100, 'STALE123')
                """,
                (user_id, match_id, stale_created_at, stale_created_at),
            )
            conn.execute(
                """
                INSERT INTO purchases (user_id, match_id, purchase_date, created_at, status, amount, token)
                VALUES (?, ?, ?, ?, 'pending', 100, 'FRESH123')
                """,
                (user_id, match_id, fresh_created_at, fresh_created_at),
            )
            conn.execute(
                """
                INSERT INTO purchases (user_id, match_id, purchase_date, created_at, status, amount, token)
                VALUES (?, ?, ?, ?, 'paid', 100, 'PAID123')
                """,
                (user_id, match_id, stale_created_at, stale_created_at),
            )
            conn.commit()
            conn.close()

            expired_count = database.expire_old_pending_purchases(max_age_minutes=60)

            conn = conn_factory()
            statuses = {
                row["token"]: row["status"]
                for row in conn.execute("SELECT token, status FROM purchases").fetchall()
            }
            conn.close()

            assert expired_count == 1
            assert statuses["STALE123"] == "expired"
            assert statuses["FRESH123"] == "pending"
            assert statuses["PAID123"] == "paid"
    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass
