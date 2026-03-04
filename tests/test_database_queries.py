"""Тесты для query/helper-веток database.py."""

import sqlite3
from datetime import datetime, timedelta

import config
import database
import pytest


@pytest.fixture
def db(monkeypatch, tmp_path):
    db_path = tmp_path / "test_database_queries.sqlite3"

    def connect():
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    with connect() as conn:
        database._init_db_tables(conn)

    @database.contextmanager
    def get_db():
        conn = connect()
        try:
            yield conn
        finally:
            conn.close()

    monkeypatch.setattr(database, "get_db_connection", connect)
    monkeypatch.setattr(database, "get_db", get_db)
    monkeypatch.setattr(config, "ANALYSIS_PRICE_RUB", 150)
    database.STATIC_ADMIN_IDS.clear()
    return connect


@pytest.fixture
def helpers(db):
    def create_user(user_id, username, balance=0, total_analysis_bought=0):
        user = database.get_or_create_user(user_id, username)
        with db() as conn:
            conn.execute(
                """
                UPDATE users
                SET balance = ?, total_analysis_bought = ?, created_at = ?
                WHERE user_id = ?
                """,
                (balance, total_analysis_bought, f"2026-03-{user_id % 28 + 1:02d} 10:00:00", user_id),
            )
            conn.commit()
        return user

    def create_match(**overrides):
        params = {
            "sport": "football",
            "team1": "Arsenal",
            "team2": "Chelsea",
            "match_date": "2026-03-03",
            "match_time": "20:00",
            "analysis_text": None,
            "price": 150,
            "league": "Premier League",
            "api_event_id": None,
        }
        params.update(overrides)
        return database.add_match(**params)

    def update_match(match_id, **fields):
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with db() as conn:
            conn.execute(
                f"UPDATE matches SET {assignments} WHERE id = ?",
                (*fields.values(), match_id),
            )
            conn.commit()

    def create_purchase(
        user_id,
        match_id,
        *,
        status="paid",
        amount=15000,
        purchase_date="2026-03-03 10:00:00",
        created_at="2026-03-03 10:00:00",
        token=None,
    ):
        with db() as conn:
            conn.execute(
                """
                INSERT INTO purchases
                (user_id, match_id, purchase_date, created_at, status, amount, token)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, match_id, purchase_date, created_at, status, amount, token),
            )
            row_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            conn.commit()
        return row_id

    def create_topup(
        user_id,
        token,
        *,
        amount_rub=100,
        status="pending",
        created_at="2026-03-03 10:00:00",
        expires_at="2099-03-03 10:30:00",
        donation_event_id=None,
    ):
        with db() as conn:
            conn.execute(
                """
                INSERT INTO balance_topups
                (user_id, amount_rub, amount_kopeks, token, status, created_at, expires_at, donation_event_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, amount_rub, amount_rub * 100, token, status, created_at, expires_at, donation_event_id),
            )
            row_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            conn.commit()
        return row_id

    return {
        "create_user": create_user,
        "create_match": create_match,
        "update_match": update_match,
        "create_purchase": create_purchase,
        "create_topup": create_topup,
        "db": db,
    }


def test_match_queries_and_dates(helpers):
    match_today = helpers["create_match"](team1="A", team2="B", match_date=datetime.now().strftime("%Y-%m-%d"), match_time="10:00")
    helpers["update_match"](match_today, coverage_ok=1)
    match_tomorrow = helpers["create_match"](team1="C", team2="D", match_date=(datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"), match_time="11:00", api_event_id="evt-1")
    helpers["update_match"](match_tomorrow, coverage_ok=1)
    match_later = helpers["create_match"](team1="E", team2="F", match_date=(datetime.now() + timedelta(days=8)).strftime("%Y-%m-%d"), match_time="12:00", api_event_id="evt-2")
    helpers["update_match"](match_later, coverage_ok=1)
    inactive = helpers["create_match"](team1="X", team2="Y", match_date=datetime.now().strftime("%Y-%m-%d"), match_time="13:00", api_event_id="evt-3")
    helpers["update_match"](inactive, is_active=0, coverage_ok=1)

    assert database.get_match_by_id(match_today)["team1"] == "A"
    assert database.get_match_by_id(999999) is None

    all_matches = database.get_all_matches()
    assert len(all_matches) == 4

    today_matches = database.get_today_matches("football")
    assert [row["id"] for row in today_matches] == [match_today]

    today_group, tomorrow_group = database.get_today_tomorrow_matches("football")
    assert [row["team1"] for row in today_group] == ["A"]
    assert [row["team1"] for row in tomorrow_group] == ["C"]

    by_date = database.get_matches_by_date("football", datetime.now().strftime("%Y-%m-%d"))
    assert [row["id"] for row in by_date] == [match_today]

    available_dates = database.get_available_dates_with_matches("football")
    assert available_dates == sorted(available_dates)
    assert datetime.now().strftime("%Y-%m-%d") in available_dates
    assert (datetime.now() + timedelta(days=8)).strftime("%Y-%m-%d") not in available_dates


def test_get_matches_by_date_filtered_hides_old_or_uncovered_matches(helpers, monkeypatch):
    frozen_now = datetime(2026, 3, 4, 12, 0, 0)

    class FrozenDateTime:
        @staticmethod
        def now():
            return frozen_now

        @staticmethod
        def strptime(value, fmt):
            return datetime.strptime(value, fmt)

    monkeypatch.setattr(database, "datetime", FrozenDateTime)

    today = frozen_now.strftime("%Y-%m-%d")
    future = (frozen_now + timedelta(minutes=30)).strftime("%H:%M")
    stale = (frozen_now - timedelta(hours=4)).strftime("%H:%M")
    invalid_time = helpers["create_match"](team1="Broken", team2="Clock", match_date=today, match_time="xx:yy", api_event_id="bad-time")
    keep_future = helpers["create_match"](team1="Soon", team2="Start", match_date=today, match_time=future, api_event_id="future")
    too_old = helpers["create_match"](team1="Old", team2="News", match_date=today, match_time=stale, api_event_id="old")
    uncovered = helpers["create_match"](team1="No", team2="Coverage", match_date=today, match_time=future, api_event_id="nocov")
    helpers["update_match"](invalid_time, coverage_ok=1)
    helpers["update_match"](keep_future, coverage_ok=1)
    helpers["update_match"](too_old, coverage_ok=1)
    helpers["update_match"](uncovered, coverage_ok=0)

    result_ids = [row["id"] for row in database.get_matches_by_date_filtered("football", today)]

    assert invalid_time in result_ids
    assert keep_future in result_ids
    assert too_old not in result_ids
    assert uncovered not in result_ids


def test_purchase_query_helpers(helpers):
    user = helpers["create_user"](201, "buyer", balance=0)
    match_paid = helpers["create_match"](team1="Paid", team2="Match", api_event_id="paid-1")
    match_pending = helpers["create_match"](team1="Pending", team2="Match", api_event_id="pending-1")
    match_refunded = helpers["create_match"](team1="Refunded", team2="Match", sport="basketball", api_event_id="refund-1")
    helpers["create_purchase"](user["user_id"], match_paid, status="paid", purchase_date="2026-03-03 11:00:00", created_at="2026-03-03 11:00:00")
    helpers["create_purchase"](user["user_id"], match_pending, status="pending", purchase_date="2026-03-03 12:00:00", created_at="2026-03-03 12:00:00")
    helpers["create_purchase"](user["user_id"], match_refunded, status="refunded", purchase_date="2026-03-03 13:00:00", created_at="2026-03-03 13:00:00")

    purchased = database.get_purchased_matches_by_user(user["user_id"])
    assert [row["id"] for row in purchased] == [match_paid]
    assert purchased[0]["purchase_date"] == "2026-03-03 11:00:00"

    purchased_football = database.get_purchased_matches_by_sport(user["user_id"], "football")
    assert [row["id"] for row in purchased_football] == [match_paid]

    assert database.get_purchased_dates_by_sport(user["user_id"], "football") == ["2026-03-03"]
    assert database.has_purchased_analysis(user["user_id"], match_paid) is True
    assert database.has_purchased_analysis(user["user_id"], match_pending) is False
    assert database.has_purchased_analysis(user["user_id"], 999999) is False

    last_paid = database.get_last_paid_purchase_by_user(user["user_id"])
    assert last_paid["match_id"] == match_paid


def test_user_queries_and_stats(helpers):
    rich = helpers["create_user"](301, "alpha_user", balance=7, total_analysis_bought=3)
    helpers["create_user"](302, "beta", balance=2, total_analysis_bought=1)
    match_id = helpers["create_match"](api_event_id="usr-match")
    helpers["create_purchase"](rich["user_id"], match_id, status="paid", purchase_date="2026-03-03 12:00:00", created_at="2026-03-03 12:00:00")
    helpers["create_topup"](rich["user_id"], "TOPUPUSER001", status="paid", donation_event_id="don-301")

    full = database.get_user_full_info(rich["user_id"])
    assert full is not None
    assert full["user"]["user_id"] == rich["user_id"]
    assert len(full["purchases"]) == 1
    assert len(full["topups"]) == 1
    assert database.get_user_full_info(999999) is None

    assert [row["username"] for row in database.find_users("alpha")] == ["alpha_user"]
    assert [row["user_id"] for row in database.find_users(str(rich["user_id"]))] == [rich["user_id"]]
    assert database.find_users("missing-user") == []

    stats = database.get_user_stats(rich["user_id"])
    assert stats == {"balance": 7, "total_analysis_bought": 3, "purchased_count": 1}
    assert database.get_user_stats(999999) is None

    all_users = database.get_all_users()
    assert {row["user_id"] for row in all_users} == {301, 302}


def test_topup_helpers(helpers):
    user = helpers["create_user"](401, "topup-user", balance=0)
    expired_at = (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    future_1 = (datetime.now() + timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M:%S")
    future_2 = (datetime.now() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    helpers["create_topup"](user["user_id"], "TOPUPPENDING1", created_at="2026-03-03 10:00:00", expires_at=future_1)
    helpers["create_topup"](user["user_id"], "TOPUPPENDING2", created_at="2026-03-03 11:00:00", expires_at=future_2)
    helpers["create_topup"](user["user_id"], "TOPUPEXPIRED1", expires_at=expired_at)
    helpers["create_topup"](user["user_id"], "TOPUPPAID0001", status="paid", donation_event_id="don-paid")

    database.update_topup_instruction_message("TOPUPPENDING1", 777)
    database.update_topup_return_target("TOPUPPENDING1", 55, "purchased")

    topup = database.get_topup_by_token("TOPUPPENDING1")
    any_topup = database.get_any_topup_by_token("TOPUPPAID0001")
    pending_by_user = database.get_pending_topup_by_user(user["user_id"])
    all_pending = database.get_all_pending_topups()

    assert topup["instruction_message_id"] == 777
    assert topup["return_match_id"] == 55
    assert topup["return_match_source"] == "purchased"
    assert database.get_topup_by_token("TOPUPEXPIRED1") is None
    assert database.get_topup_by_token("TOPUPPAID0001") is None
    assert any_topup["status"] == "paid"
    assert pending_by_user["token"] == "TOPUPPENDING2"
    assert [row["token"] for row in all_pending] == ["TOPUPPENDING2", "TOPUPPENDING1"]


def test_match_crud_helpers_and_cleanup(helpers, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    new_id, is_new = database.sync_match_from_api(
        {
            "sport": "football",
            "team1": "Sync",
            "team2": "Created",
            "match_date": "2026-03-04",
            "match_time": "21:00",
            "league": "Cup",
            "api_event_id": "api-100",
            "price": 175,
        }
    )
    dup_id, dup_flag = database.sync_match_from_api(
        {
            "sport": "football",
            "team1": "Sync",
            "team2": "Created",
            "match_date": "2026-03-04",
            "match_time": "21:00",
            "league": "Cup",
            "api_event_id": "api-100",
        }
    )
    fallback_id, fallback_flag = database.sync_match_from_api(
        {
            "sport": "football",
            "team1": "Fallback",
            "team2": "Teams",
            "match_date": "2026-03-05",
            "match_time": "19:00",
        }
    )
    fallback_dup_id, fallback_dup_flag = database.sync_match_from_api(
        {
            "sport": "football",
            "team1": "Fallback",
            "team2": "Teams",
            "match_date": "2026-03-05",
            "match_time": "22:00",
        }
    )

    png_file = tmp_path / "analysis.png"
    png_file.write_bytes(b"png")
    database.update_match_analysis(new_id, "analysis body", str(png_file))
    old_path = database.clear_match_analysis(new_id)
    database.delete_match(999999)
    database.delete_match(fallback_id)

    old_date = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    old_png = tmp_path / "old.png"
    keep_png = tmp_path / "keep.png"
    old_png.write_bytes(b"old")
    keep_png.write_bytes(b"keep")
    deletable = helpers["create_match"](team1="Delete", team2="Me", match_date=old_date, match_time="09:00", api_event_id="cleanup-1")
    keep_match = helpers["create_match"](team1="Keep", team2="Me", match_date=old_date, match_time="10:00", api_event_id="cleanup-2")
    inactive = helpers["create_match"](team1="Inactive", team2="Gone", match_date=datetime.now().strftime("%Y-%m-%d"), match_time="11:00", api_event_id="cleanup-3")
    helpers["update_match"](deletable, analysis_png_path=str(old_png))
    helpers["update_match"](keep_match, analysis_png_path=str(keep_png))
    helpers["update_match"](inactive, analysis_png_path=str(tmp_path / "inactive.png"), is_active=0)
    user = helpers["create_user"](501, "cleanup")
    helpers["create_purchase"](user["user_id"], keep_match, status="paid")

    deleted_count = database.delete_finished_matches_without_purchases()

    assert is_new is True
    assert dup_id == new_id
    assert dup_flag is False
    assert fallback_flag is True
    assert fallback_dup_id == fallback_id
    assert fallback_dup_flag is False
    assert old_path == str(png_file)
    assert database.get_match_by_id(new_id)["analysis_text"] is None
    assert database.get_match_by_id(fallback_id) is None
    assert deleted_count == 2
    assert database.get_match_by_id(deletable) is None
    assert database.get_match_by_id(keep_match) is not None
    assert database.get_match_by_id(inactive) is None
    assert not old_png.exists()
    assert keep_png.exists()


def test_admin_helpers_and_reset_balance(helpers):
    helpers["create_user"](601, "root", balance=15)
    helpers["create_user"](602, "adder", balance=0)

    assert database.add_admin(601, "root", 602) is True
    assert database.is_admin(601) is True

    admins = database.get_all_admins()
    assert any(row["user_id"] == 601 for row in admins)

    database.remove_admin(601)
    assert database.is_admin(601) is False

    assert database.reset_user_balance(601) is True
    assert database.get_user_balance(601) == 0
    assert database.reset_user_balance(999999) is False
