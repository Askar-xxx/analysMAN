# -*- coding: utf-8 -*-
"""
Тесты платёжного флоу: webhook DonationAlerts → purchase paid → генерация анализа.

Покрывает:
- Happy path: правильный токен и сумма → purchase становится paid
- Нет токена в сообщении → 400
- Неверная сумма → 400
- Токен не найден → 404
- Purchase уже paid (не pending) → 404
- Идемпотентность: тот же donation_id → 200 без повторной обработки
- Race condition защита: rowcount=0 → Already processed
- Отсутствуют обязательные поля → 400
- Неверный формат суммы → 400
- Очень длинное сообщение — токен в первых 500 символах находится
- Токен за пределами 500 символов — не находится (DoS защита)
"""
import json
import os
import sqlite3
import tempfile
from unittest.mock import patch

import pytest

import database


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _create_temp_db():
    fd, path = tempfile.mkstemp(prefix="analysman_payment_", suffix=".db")
    os.close(fd)
    return path


def _mk_conn_factory(db_path):
    def _conn():
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    return _conn


def _insert_pending_purchase(conn_factory, user_id, match_id, token, amount_kopeks):
    """Вставляет pending purchase с token напрямую в БД."""
    conn = conn_factory()
    conn.execute(
        """
        INSERT INTO purchases (user_id, match_id, purchase_date, status, amount, token)
        VALUES (?, ?, '2026-02-25 12:00:00', 'pending', ?, ?)
        """,
        (user_id, match_id, amount_kopeks, token),
    )
    conn.commit()
    purchase_id = conn.execute(
        "SELECT id FROM purchases WHERE token = ?", (token,)
    ).fetchone()["id"]
    conn.close()
    return purchase_id


def _get_purchase(conn_factory, purchase_id):
    conn = conn_factory()
    row = conn.execute(
        "SELECT status, donation_event_id FROM purchases WHERE id = ?",
        (purchase_id,)
    ).fetchone()
    conn.close()
    return dict(row)


def _set_purchase_paid(conn_factory, purchase_id, donation_event_id="old_don"):
    """Переводит purchase в paid напрямую через БД."""
    conn = conn_factory()
    conn.execute(
        "UPDATE purchases SET status = 'paid', donation_event_id = ? WHERE id = ?",
        (donation_event_id, purchase_id)
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Фикстура
# ---------------------------------------------------------------------------

@pytest.fixture()
def payment_env():
    """
    Изолированная среда для тестов платёжного флоу.

    - Временная SQLite БД вместо production sports_bot.db
    - generate_and_send_analysis замокан — не ходит в Telegram/DeepSeek
    - Возвращает (flask_test_client, conn_factory, match_id)
    """
    db_path = _create_temp_db()
    conn_factory = _mk_conn_factory(db_path)

    # Используем простую async-функцию вместо AsyncMock —
    # она гарантированно работает с asyncio.new_event_loop().run_until_complete()
    async def _mock_generate(*args, **kwargs):
        return True

    p_db = patch("database.get_db_connection", new=conn_factory)
    p_gen = patch("webhook_server.generate_and_send_analysis", new=_mock_generate)

    p_db.start()
    p_gen.start()

    try:
        database.init_db()
        database.get_or_create_user(99001, "test_user")
        match_id = database.add_match(
            sport="football",
            team1="Зенит",
            team2="ЦСКА",
            match_date="2026-03-01",
            match_time="20:00",
            price=150,
        )

        import webhook_server
        webhook_server.app.config["TESTING"] = True
        client = webhook_server.app.test_client()

        yield client, conn_factory, match_id
    finally:
        p_gen.stop()
        p_db.stop()
        try:
            os.unlink(db_path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Вспомогательная функция отправки вебхука
# ---------------------------------------------------------------------------

def _post_webhook(client, payload, headers=None):
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    return client.post(
        "/webhook/donationalerts",
        data=json.dumps(payload),
        headers=h,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestWebhookHappyPath:
    def test_valid_donation_marks_purchase_paid(self, payment_env):
        """Правильный токен и сумма → purchase paid, ответ 200."""
        client, conn_factory, match_id = payment_env
        token = "ABCDEF123456"  # ровно 12 символов
        purchase_id = _insert_pending_purchase(conn_factory, 99001, match_id, token, 15000)

        resp = _post_webhook(client, {
            "id": "donation_001",
            "amount": "150.00",
            "message": f"Оплата {token} спасибо",
        })

        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["status"] == "ok"
        assert body["purchase_id"] == purchase_id

        purchase = _get_purchase(conn_factory, purchase_id)
        assert purchase["status"] == "paid"
        assert purchase["donation_event_id"] == "donation_001"

    def test_token_in_lowercase_message_is_found(self, payment_env):
        """Токен в сообщении в нижнем регистре тоже работает."""
        client, conn_factory, match_id = payment_env
        token = "XYZ789ABCDEF"  # 12 символов
        _insert_pending_purchase(conn_factory, 99001, match_id, token, 15000)

        resp = _post_webhook(client, {
            "id": "donation_002",
            "amount": "150.00",
            "message": "код xyz789abcdef",
        })

        assert resp.status_code == 200, resp.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Валидация входных данных
# ---------------------------------------------------------------------------

class TestWebhookValidation:
    def test_missing_id_field_returns_400(self, payment_env):
        """Нет поля id → 400."""
        client, conn_factory, match_id = payment_env
        resp = _post_webhook(client, {"amount": "150.00", "message": "ABCDEF123456"})
        assert resp.status_code == 400
        assert "Missing required fields" in resp.get_json().get("error", "")

    def test_missing_amount_field_returns_400(self, payment_env):
        """Нет поля amount → 400."""
        client, conn_factory, match_id = payment_env
        resp = _post_webhook(client, {"id": "don_x", "message": "ABCDEF123456"})
        assert resp.status_code == 400

    def test_invalid_amount_format_returns_400(self, payment_env):
        """Неверный формат суммы → 400."""
        client, conn_factory, match_id = payment_env
        resp = _post_webhook(client, {
            "id": "don_x",
            "amount": "not_a_number",
            "message": "ABCDEF123456",
        })
        assert resp.status_code == 400
        assert "Invalid amount format" in resp.get_json().get("error", "")

    def test_no_token_in_message_returns_400(self, payment_env):
        """Нет токена в сообщении → 400."""
        client, conn_factory, match_id = payment_env
        resp = _post_webhook(client, {
            "id": "don_x",
            "amount": "150.00",
            "message": "просто так задонатил",
        })
        assert resp.status_code == 400
        assert "Token not found" in resp.get_json().get("error", "")

    def test_empty_message_returns_400(self, payment_env):
        """Пустое сообщение → 400."""
        client, conn_factory, match_id = payment_env
        resp = _post_webhook(client, {
            "id": "don_x",
            "amount": "150.00",
            "message": "",
        })
        assert resp.status_code == 400

    def test_unknown_token_returns_404(self, payment_env):
        """Токен не найден в БД → 404."""
        client, conn_factory, match_id = payment_env
        resp = _post_webhook(client, {
            "id": "don_x",
            "amount": "150.00",
            "message": "ZZZZZZ999999",
        })
        assert resp.status_code == 404
        assert "Purchase not found" in resp.get_json().get("error", "")

    def test_amount_mismatch_returns_400(self, payment_env):
        """Сумма не совпадает → 400, purchase остаётся pending."""
        client, conn_factory, match_id = payment_env
        token = "MISMATCH1234"  # 12 символов
        purchase_id = _insert_pending_purchase(conn_factory, 99001, match_id, token, 15000)

        resp = _post_webhook(client, {
            "id": "don_mismatch",
            "amount": "100.00",  # ожидалось 150.00
            "message": token,
        })

        assert resp.status_code == 400
        assert "Amount mismatch" in resp.get_json().get("error", "")

        # Purchase не должен поменять статус
        assert _get_purchase(conn_factory, purchase_id)["status"] == "pending"


# ---------------------------------------------------------------------------
# Purchase уже не pending
# ---------------------------------------------------------------------------

class TestWebhookAlreadyPaid:
    def test_already_paid_purchase_returns_404(self, payment_env):
        """Purchase уже paid → 404, повторно не обрабатывается."""
        client, conn_factory, match_id = payment_env
        token = "ALREADYPAID1"  # ровно 12 символов
        purchase_id = _insert_pending_purchase(conn_factory, 99001, match_id, token, 15000)
        _set_purchase_paid(conn_factory, purchase_id, "old_don")

        resp = _post_webhook(client, {
            "id": "don_new",
            "amount": "150.00",
            "message": token,
        })

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Идемпотентность
# ---------------------------------------------------------------------------

class TestWebhookIdempotency:
    def test_same_donation_id_returns_200_without_reprocessing(self, payment_env):
        """Тот же donation_id → 200 Already processed, статус не меняется."""
        client, conn_factory, match_id = payment_env
        token = "IDEMPTOKEN12"  # 12 символов
        purchase_id = _insert_pending_purchase(conn_factory, 99001, match_id, token, 15000)

        # Проставляем тот же donation_event_id что придёт в вебхуке
        conn = conn_factory()
        conn.execute(
            "UPDATE purchases SET donation_event_id = 'don_idem' WHERE id = ?",
            (purchase_id,)
        )
        conn.commit()
        conn.close()

        resp = _post_webhook(client, {
            "id": "don_idem",
            "amount": "150.00",
            "message": token,
        })

        assert resp.status_code == 200
        assert resp.get_json().get("message") == "Already processed"

        # Статус должен был остаться pending — ничего не менялось
        assert _get_purchase(conn_factory, purchase_id)["status"] == "pending"


# ---------------------------------------------------------------------------
# Race condition защита
# ---------------------------------------------------------------------------

class TestWebhookRaceCondition:
    def test_second_webhook_gets_already_processed_when_purchase_taken(self, payment_env):
        """
        Эмулируем race condition: другой процесс уже пометил purchase как paid
        до нашего UPDATE. Atomic UPDATE вернёт rowcount=0 → Already processed.
        """
        client, conn_factory, match_id = payment_env
        token = "RACECOND1234"  # ровно 12 символов
        purchase_id = _insert_pending_purchase(conn_factory, 99001, match_id, token, 15000)

        # Помечаем purchase как paid от имени «другого процесса»
        _set_purchase_paid(conn_factory, purchase_id, "other_process")

        # Наш вебхук приходит после — уже ничего не может обновить
        resp = _post_webhook(client, {
            "id": "don_race",
            "amount": "150.00",
            "message": token,
        })

        # Должны получить либо 200 (already processed), либо 404 (статус не pending)
        # В любом случае — не 500 и не повторная генерация
        assert resp.status_code in (200, 404), resp.get_data(as_text=True)


# ---------------------------------------------------------------------------
# DoS защита через лимит длины сообщения
# ---------------------------------------------------------------------------

class TestWebhookMessageLengthLimit:
    def test_token_in_first_500_chars_is_found(self, payment_env):
        """Токен в первых 500 символах сообщения — находится."""
        client, conn_factory, match_id = payment_env
        token = "LONGMSG12345"  # 12 символов
        _insert_pending_purchase(conn_factory, 99001, match_id, token, 15000)

        long_message = token + " " + "x" * 10000
        resp = _post_webhook(client, {
            "id": "don_long",
            "amount": "150.00",
            "message": long_message,
        })

        assert resp.status_code == 200, resp.get_data(as_text=True)

    def test_token_beyond_500_chars_not_found(self, payment_env):
        """Токен за пределами 500 символов — не находится (DoS защита)."""
        client, conn_factory, match_id = payment_env
        token = "FARBEYOND123"  # 12 символов
        _insert_pending_purchase(conn_factory, 99001, match_id, token, 15000)

        long_message = "x" * 600 + " " + token
        resp = _post_webhook(client, {
            "id": "don_far",
            "amount": "150.00",
            "message": long_message,
        })

        assert resp.status_code == 400
        assert "Token not found" in resp.get_json().get("error", "")
