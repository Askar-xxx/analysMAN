import asyncio
import os
import sys
import time
import types
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import healthcheck  # noqa: E402
import healthcheck_utils  # noqa: E402
import main  # noqa: E402


def test_healthcheck_success_when_both_heartbeats_are_fresh(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(healthcheck_utils, "HEARTBEAT_DIR", tmp_path)
    healthcheck_utils.touch_heartbeat("main")
    healthcheck_utils.touch_heartbeat("da_polling")

    healthy, problems = healthcheck.check_health()

    assert healthy is True
    assert problems == []


def test_healthcheck_fails_when_main_heartbeat_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(healthcheck_utils, "HEARTBEAT_DIR", tmp_path)
    healthcheck_utils.touch_heartbeat("da_polling")

    healthy, problems = healthcheck.check_health()

    assert healthy is False
    assert any("main: missing heartbeat" in problem for problem in problems)


def test_healthcheck_fails_when_listener_heartbeat_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(healthcheck_utils, "HEARTBEAT_DIR", tmp_path)
    healthcheck_utils.touch_heartbeat("main")

    healthy, problems = healthcheck.check_health()

    assert healthy is False
    assert any("da_polling: missing heartbeat" in problem for problem in problems)


def test_healthcheck_fails_when_heartbeat_is_stale(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(healthcheck_utils, "HEARTBEAT_DIR", tmp_path)
    healthcheck_utils.touch_heartbeat("main")
    healthcheck_utils.touch_heartbeat("da_polling")
    stale_time = time.time() - (healthcheck_utils.HEARTBEAT_MAX_AGE_SECONDS + 5)
    stale_path = healthcheck_utils.get_heartbeat_path("main")
    os.utime(stale_path, (stale_time, stale_time))

    healthy, problems = healthcheck.check_health()

    assert healthy is False
    assert any("main: stale heartbeat" in problem for problem in problems)


def test_heartbeat_threshold_boundary(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(healthcheck_utils, "HEARTBEAT_DIR", tmp_path)
    healthcheck_utils.touch_heartbeat("main")
    path = healthcheck_utils.get_heartbeat_path("main")

    fresh_time = time.time() - (healthcheck_utils.HEARTBEAT_MAX_AGE_SECONDS - 1)
    os.utime(path, (fresh_time, fresh_time))
    assert healthcheck_utils.heartbeat_is_fresh("main") is True

    stale_time = time.time() - (healthcheck_utils.HEARTBEAT_MAX_AGE_SECONDS + 1)
    os.utime(path, (stale_time, stale_time))
    assert healthcheck_utils.heartbeat_is_fresh("main") is False


def test_main_heartbeat_loop_survives_touch_errors(monkeypatch):
    async def _run():
        calls = []
        monkeypatch.setattr(main, "HEARTBEAT_INTERVAL_SECONDS", 0.01)

        def fake_touch(name):
            calls.append(name)
            if len(calls) == 1:
                raise RuntimeError("boom")

        monkeypatch.setattr(main, "touch_heartbeat", fake_touch)

        task = asyncio.create_task(main.main_heartbeat_loop())
        await asyncio.sleep(0.03)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert len(calls) >= 2

    asyncio.run(_run())


def test_post_init_creates_and_post_shutdown_cancels_heartbeat_task(monkeypatch):
    async def _run():
        recorded_create_task = []
        touch_calls = []
        remove_calls = []
        original_create_task = asyncio.create_task

        class FakeScheduler:
            def __init__(self):
                self.started = False
                self.jobs = []
                self.shutdown_called = False

            def add_job(self, func, **kwargs):
                self.jobs.append((func, kwargs))

            def start(self):
                self.started = True

            def shutdown(self, wait=False):
                self.shutdown_called = True

        async def fake_setup_admin_commands_menu(bot):
            return None

        def fake_touch(name):
            touch_calls.append(name)

        def fake_remove(name):
            remove_calls.append(name)

        def fake_create_task(coro):
            task = original_create_task(coro)
            recorded_create_task.append(task)
            return task

        fake_admin_module = types.SimpleNamespace(
            setup_admin_commands_menu=fake_setup_admin_commands_menu
        )
        monkeypatch.setitem(sys.modules, "admin_commands", fake_admin_module)
        monkeypatch.setattr(main, "AsyncIOScheduler", FakeScheduler)
        monkeypatch.setattr(main, "touch_heartbeat", fake_touch)
        monkeypatch.setattr(main, "remove_heartbeat", fake_remove)
        monkeypatch.setattr(main.asyncio, "create_task", fake_create_task)
        monkeypatch.setattr(main, "HEARTBEAT_INTERVAL_SECONDS", 3600)

        application = types.SimpleNamespace(bot_data={}, bot=object())

        await main.post_init(application)

        assert len(recorded_create_task) == 1
        assert application.bot_data["main_heartbeat_task"] is recorded_create_task[0]
        assert isinstance(application.bot_data["scheduler"], FakeScheduler)
        assert touch_calls[0] == "main"

        await main.post_shutdown(application)

        assert recorded_create_task[0].cancelled() is True
        assert "main_heartbeat_task" not in application.bot_data
        assert remove_calls == ["main"]

    asyncio.run(_run())


def test_main_registers_global_error_handler(monkeypatch):
    added_handlers = []

    class FakeApplication:
        def __init__(self):
            self.post_init = None
            self.post_shutdown = None

        def add_error_handler(self, handler):
            added_handlers.append(handler)

        def run_polling(self):
            return None

    class FakeBuilder:
        def token(self, _token):
            return self

        def build(self):
            return FakeApplication()

    fake_application_factory = types.SimpleNamespace(builder=lambda: FakeBuilder())

    monkeypatch.setattr(main, "Application", fake_application_factory)
    monkeypatch.setattr(main.database, "init_db", lambda: None)
    monkeypatch.setitem(
        sys.modules,
        "user_handlers",
        types.SimpleNamespace(setup_user_handlers=lambda app: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "admin_commands",
        types.SimpleNamespace(setup_admin_handlers=lambda app: None),
    )

    main.main()

    assert added_handlers == [main.error_handler]
