import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

from telegram.error import NetworkError

import main


def run_async(coro):
    return asyncio.run(coro)


def test_error_handler_logs_non_network_errors_as_error(monkeypatch):
    error_mock = Mock()
    warning_mock = Mock()

    monkeypatch.setattr(main.logger, "error", error_mock)
    monkeypatch.setattr(main.logger, "warning", warning_mock)
    main._ptb_net_error_state["count"] = 3
    main._ptb_net_error_state["last_at"] = 123.0

    run_async(main.error_handler(None, SimpleNamespace(error=RuntimeError("boom"))))

    warning_mock.assert_not_called()
    error_mock.assert_called_once()
    assert main._ptb_net_error_state == {"count": 0, "last_at": 0.0}


def test_error_handler_warns_on_single_network_error(monkeypatch):
    error_mock = Mock()
    warning_mock = Mock()

    monkeypatch.setattr(main.logger, "error", error_mock)
    monkeypatch.setattr(main.logger, "warning", warning_mock)
    monkeypatch.setattr(main, "_ptb_monotonic", lambda: 100.0)
    main._reset_ptb_network_error_state()

    run_async(main.error_handler(None, SimpleNamespace(error=NetworkError("connect failed"))))

    error_mock.assert_not_called()
    warning_mock.assert_called_once()
    assert "попытка %s" in warning_mock.call_args.args[0]
    assert warning_mock.call_args.args[2] == 1


def test_error_handler_escalates_after_network_error_series(monkeypatch):
    error_mock = Mock()
    warning_mock = Mock()
    monotonic_values = iter([100.0, 110.0, 120.0, 130.0, 140.0])

    monkeypatch.setattr(main.logger, "error", error_mock)
    monkeypatch.setattr(main.logger, "warning", warning_mock)
    monkeypatch.setattr(main, "_ptb_monotonic", lambda: next(monotonic_values))
    main._reset_ptb_network_error_state()

    for _ in range(main.PTB_NET_ERROR_ESCALATE_AFTER):
        run_async(main.error_handler(None, SimpleNamespace(error=NetworkError("connect failed"))))

    assert warning_mock.call_count == main.PTB_NET_ERROR_ESCALATE_AFTER - 1
    error_mock.assert_called_once()
    assert "Telegram API недоступен уже" in error_mock.call_args.args[0]
    assert error_mock.call_args.args[2] == main.PTB_NET_ERROR_ESCALATE_AFTER


def test_error_handler_resets_network_series_after_long_gap(monkeypatch):
    error_mock = Mock()
    warning_mock = Mock()
    monotonic_values = iter([100.0, 400.0])

    monkeypatch.setattr(main.logger, "error", error_mock)
    monkeypatch.setattr(main.logger, "warning", warning_mock)
    monkeypatch.setattr(main, "_ptb_monotonic", lambda: next(monotonic_values))
    main._reset_ptb_network_error_state()

    run_async(main.error_handler(None, SimpleNamespace(error=NetworkError("connect failed"))))
    run_async(main.error_handler(None, SimpleNamespace(error=NetworkError("connect failed"))))

    error_mock.assert_not_called()
    assert warning_mock.call_count == 2
    assert warning_mock.call_args_list[0].args[2] == 1
    assert warning_mock.call_args_list[1].args[2] == 1
