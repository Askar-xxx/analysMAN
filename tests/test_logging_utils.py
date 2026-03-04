import logging
import sys
from unittest.mock import Mock

import logging_utils


def _cleanup_managed_handlers():
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        if getattr(handler, logging_utils.MANAGED_HANDLER_ATTR, False):
            root_logger.removeHandler(handler)
            handler.close()


def test_telegram_log_handler_debounces_and_truncates(monkeypatch):
    sent_messages = []
    response = Mock()
    response.raise_for_status.return_value = None

    def fake_post(url, json, timeout):
        sent_messages.append((url, json, timeout))
        return response

    monotonic_values = iter([100.0, 130.0, 161.0])
    monkeypatch.setattr(logging_utils.requests, 'post', fake_post)
    monkeypatch.setattr(logging_utils.time, 'monotonic', lambda: next(monotonic_values))

    handler = logging_utils.TelegramLogHandler(
        token='test-token',
        chat_id=123456,
        min_interval_seconds=60,
    )

    first_record = logging.LogRecord(
        name='alerts.test',
        level=logging.ERROR,
        pathname=__file__,
        lineno=10,
        msg='x' * 700,
        args=(),
        exc_info=None,
    )
    second_record = logging.LogRecord(
        name='alerts.test',
        level=logging.ERROR,
        pathname=__file__,
        lineno=11,
        msg='second should be debounced',
        args=(),
        exc_info=None,
    )
    third_record = logging.LogRecord(
        name='alerts.test',
        level=logging.CRITICAL,
        pathname=__file__,
        lineno=12,
        msg='third passes debounce window',
        args=(),
        exc_info=None,
    )

    handler.emit(first_record)
    handler.emit(second_record)
    handler.emit(third_record)

    assert len(sent_messages) == 2
    assert sent_messages[0][0].endswith('/bottest-token/sendMessage')
    assert sent_messages[0][1]['chat_id'] == 123456
    assert sent_messages[0][1]['text'].startswith('⚠️ [ERROR] test_logging_utils: ')
    assert sent_messages[0][1]['text'].split(': ', 1)[1] == 'x' * 500
    assert '[CRITICAL]' in sent_messages[1][1]['text']


def test_telegram_log_handler_includes_exception_details(monkeypatch):
    sent_messages = []
    response = Mock()
    response.raise_for_status.return_value = None

    def fake_post(url, json, timeout):
        sent_messages.append((url, json, timeout))
        return response

    monkeypatch.setattr(logging_utils.requests, 'post', fake_post)
    monkeypatch.setattr(logging_utils.time, 'monotonic', lambda: 100.0)

    handler = logging_utils.TelegramLogHandler(
        token='test-token',
        chat_id=123456,
        min_interval_seconds=0,
    )

    try:
        raise RuntimeError('boom')
    except RuntimeError:
        record = logging.LogRecord(
            name='alerts.test',
            level=logging.ERROR,
            pathname=__file__,
            lineno=10,
            msg='handler failed',
            args=(),
            exc_info=sys.exc_info(),
        )

    handler.emit(record)

    text = sent_messages[0][1]['text']
    assert 'RuntimeError: boom' in text
    assert 'handler failed' in text


def test_should_attach_telegram_handler_disabled_under_pytest(monkeypatch):
    monkeypatch.setenv('PYTEST_CURRENT_TEST', 'tests/test_logging_utils.py::test_case')

    assert logging_utils._should_attach_telegram_handler() is False


def test_should_attach_telegram_handler_disabled_by_env_flag(monkeypatch):
    monkeypatch.delenv('PYTEST_CURRENT_TEST', raising=False)
    monkeypatch.setenv('DISABLE_TELEGRAM_ALERTS', '1')

    assert logging_utils._should_attach_telegram_handler() is False


def test_setup_logging_creates_rotating_file(tmp_path):
    _cleanup_managed_handlers()

    try:
        logger = logging_utils.setup_logging(
            'unit_logging',
            log_dir=tmp_path,
            token='',
            alert_chat_id=0,
        )
        logger.info('file logging smoke test')

        for handler in logger.handlers:
            if hasattr(handler, 'flush'):
                handler.flush()

        log_file = tmp_path / 'unit_logging.log'
        assert log_file.exists()
        assert 'file logging smoke test' in log_file.read_text(encoding='utf-8')
    finally:
        _cleanup_managed_handlers()


def test_setup_logging_skips_telegram_handler_under_pytest(tmp_path, monkeypatch):
    _cleanup_managed_handlers()
    monkeypatch.setenv('PYTEST_CURRENT_TEST', 'tests/test_logging_utils.py::test_case')

    try:
        logger = logging_utils.setup_logging(
            'unit_logging_pytest',
            log_dir=tmp_path,
            token='real-token-would-be-here',
            alert_chat_id=123456,
        )

        assert not any(
            isinstance(handler, logging_utils.TelegramLogHandler)
            for handler in logger.handlers
        )
    finally:
        _cleanup_managed_handlers()


def test_setup_logging_skips_telegram_handler_when_disabled_by_env(tmp_path, monkeypatch):
    _cleanup_managed_handlers()
    monkeypatch.delenv('PYTEST_CURRENT_TEST', raising=False)
    monkeypatch.setenv('DISABLE_TELEGRAM_ALERTS', 'true')

    try:
        logger = logging_utils.setup_logging(
            'unit_logging_env_opt_out',
            log_dir=tmp_path,
            token='real-token-would-be-here',
            alert_chat_id=123456,
        )

        assert not any(
            isinstance(handler, logging_utils.TelegramLogHandler)
            for handler in logger.handlers
        )
    finally:
        _cleanup_managed_handlers()
