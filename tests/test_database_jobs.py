# -*- coding: utf-8 -*-
"""
Тесты database.py: acquire_generation_job и wait_for_match_analysis.

acquire_generation_job:
- Первый вызов возвращает True (lock захвачен)
- Второй вызов на тот же match_id возвращает False (уже занят)
- После finish_generation_job lock освобождается → можно захватить снова
- Протухший lock (stale) перехватывается новым владельцем

wait_for_match_analysis:
- Анализ уже есть → возвращает True сразу
- Анализ появляется во время ожидания → возвращает True
- Анализ так и не появился → возвращает False по таймауту
- Матч не существует → возвращает False по таймауту
"""
import os
import sqlite3
import tempfile
import threading
import time
from unittest.mock import patch

import database


# ---------------------------------------------------------------------------
# Вспомогательные функции (те же что в test_database_safety.py)
# ---------------------------------------------------------------------------

def _create_temp_db():
    fd, path = tempfile.mkstemp(prefix="analysman_jobs_", suffix=".db")
    os.close(fd)
    return path


def _mk_conn_factory(db_path):
    def _conn():
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    return _conn


def _setup_db():
    """Создаёт временную БД, инициализирует схему. Возвращает (db_path, conn_factory, match_id)."""
    db_path = _create_temp_db()
    conn_factory = _mk_conn_factory(db_path)
    with patch("database.get_db_connection", new=conn_factory):
        database.init_db()
        match_id = database.add_match(
            sport="football",
            team1="Спартак",
            team2="Локомотив",
            match_date="2026-03-10",
            match_time="19:00",
        )
    return db_path, conn_factory, match_id


def _cleanup(db_path):
    try:
        os.unlink(db_path)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# acquire_generation_job
# ---------------------------------------------------------------------------

class TestAcquireGenerationJob:
    def test_first_acquire_returns_true(self):
        """Первый вызов захватывает lock."""
        db_path, conn_factory, match_id = _setup_db()
        try:
            with patch("database.get_db_connection", new=conn_factory):
                result = database.acquire_generation_job(match_id, owner="u1")
            assert result is True
        finally:
            _cleanup(db_path)

    def test_second_acquire_same_match_returns_false(self):
        """Второй вызов на тот же match_id возвращает False — lock уже занят."""
        db_path, conn_factory, match_id = _setup_db()
        try:
            with patch("database.get_db_connection", new=conn_factory):
                first = database.acquire_generation_job(match_id, owner="u1")
                second = database.acquire_generation_job(match_id, owner="u2")
            assert first is True
            assert second is False
        finally:
            _cleanup(db_path)

    def test_different_matches_can_be_acquired_independently(self):
        """Разные матчи не мешают друг другу."""
        db_path, conn_factory, match_id = _setup_db()
        try:
            with patch("database.get_db_connection", new=conn_factory):
                match_id2 = database.add_match(
                    sport="football",
                    team1="Зенит",
                    team2="ЦСКА",
                    match_date="2026-03-11",
                    match_time="20:00",
                )
                r1 = database.acquire_generation_job(match_id, owner="u1")
                r2 = database.acquire_generation_job(match_id2, owner="u2")
            assert r1 is True
            assert r2 is True
        finally:
            _cleanup(db_path)

    def test_lock_released_after_finish(self):
        """После finish_generation_job lock освобождается — следующий acquire проходит."""
        db_path, conn_factory, match_id = _setup_db()
        try:
            with patch("database.get_db_connection", new=conn_factory):
                database.acquire_generation_job(match_id, owner="u1")
                database.finish_generation_job(match_id, status="done")
                reacquired = database.acquire_generation_job(match_id, owner="u2")
            assert reacquired is True
        finally:
            _cleanup(db_path)

    def test_error_finish_also_releases_lock(self):
        """finish_generation_job со статусом error тоже освобождает lock."""
        db_path, conn_factory, match_id = _setup_db()
        try:
            with patch("database.get_db_connection", new=conn_factory):
                database.acquire_generation_job(match_id, owner="u1")
                database.finish_generation_job(match_id, status="error", error="oops")
                reacquired = database.acquire_generation_job(match_id, owner="u3")
            assert reacquired is True
        finally:
            _cleanup(db_path)

    def test_stale_lock_is_overridden(self):
        """Протухший lock (updated_at давно в прошлом) перехватывается новым владельцем."""
        db_path, conn_factory, match_id = _setup_db()
        try:
            with patch("database.get_db_connection", new=conn_factory):
                # Захватываем lock
                database.acquire_generation_job(match_id, owner="u_old")

                # Руками переводим updated_at в далёкое прошлое (10 минут назад)
                conn = conn_factory()
                conn.execute(
                    "UPDATE generation_jobs SET updated_at = '2000-01-01 00:00:00' WHERE match_id = ?",
                    (match_id,)
                )
                conn.commit()
                conn.close()

                # stale_after_seconds=1 — lock точно протух
                overridden = database.acquire_generation_job(
                    match_id, owner="u_new", stale_after_seconds=1
                )
            assert overridden is True
        finally:
            _cleanup(db_path)


# ---------------------------------------------------------------------------
# wait_for_match_analysis
# ---------------------------------------------------------------------------

class TestWaitForMatchAnalysis:
    def test_returns_true_immediately_if_analysis_exists(self):
        """Анализ уже есть в БД → True без ожидания."""
        db_path, conn_factory, match_id = _setup_db()
        try:
            with patch("database.get_db_connection", new=conn_factory):
                # Записываем analysis_text сразу
                database.update_match_analysis(match_id, "Готовый анализ матча")
                result = database.wait_for_match_analysis(match_id, timeout_seconds=5)
            assert result is True
        finally:
            _cleanup(db_path)

    def test_returns_false_on_timeout_if_no_analysis(self):
        """Анализ так и не появился → False по таймауту."""
        db_path, conn_factory, match_id = _setup_db()
        try:
            with patch("database.get_db_connection", new=conn_factory):
                started = time.monotonic()
                result = database.wait_for_match_analysis(
                    match_id, timeout_seconds=0.3, poll_interval=0.1
                )
                elapsed = time.monotonic() - started
            assert result is False
            # Убеждаемся что реально ждал, а не вернул сразу
            assert elapsed >= 0.2
        finally:
            _cleanup(db_path)

    def test_returns_false_for_nonexistent_match(self):
        """Несуществующий match_id → False по таймауту."""
        db_path, conn_factory, match_id = _setup_db()
        try:
            with patch("database.get_db_connection", new=conn_factory):
                result = database.wait_for_match_analysis(
                    99999, timeout_seconds=0.2, poll_interval=0.1
                )
            assert result is False
        finally:
            _cleanup(db_path)

    def test_returns_true_when_analysis_appears_during_wait(self):
        """
        Анализ появляется во время ожидания → True.
        Отдельный поток записывает анализ через 0.2 сек, wait ждёт до 2 сек.
        """
        db_path, conn_factory, match_id = _setup_db()
        try:
            def _write_analysis_after_delay():
                time.sleep(0.2)
                with patch("database.get_db_connection", new=conn_factory):
                    database.update_match_analysis(match_id, "Анализ появился!")

            writer = threading.Thread(target=_write_analysis_after_delay, daemon=True)
            writer.start()

            with patch("database.get_db_connection", new=conn_factory):
                result = database.wait_for_match_analysis(
                    match_id, timeout_seconds=2.0, poll_interval=0.1
                )

            writer.join(timeout=1)
            assert result is True
        finally:
            _cleanup(db_path)

    def test_empty_analysis_text_not_counted(self):
        """Пустая строка analysis_text не считается готовым анализом."""
        db_path, conn_factory, match_id = _setup_db()
        try:
            with patch("database.get_db_connection", new=conn_factory):
                # Записываем пустой анализ
                database.update_match_analysis(match_id, "")
                result = database.wait_for_match_analysis(
                    match_id, timeout_seconds=0.2, poll_interval=0.1
                )
            assert result is False
        finally:
            _cleanup(db_path)
