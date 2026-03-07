import asyncio

import main


def test_refresh_dynamic_description_logs_warning_on_failure(monkeypatch):
    bot = object()
    warnings = []

    async def fail_update(_bot):
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "update_dynamic_description", fail_update)
    monkeypatch.setattr(main.logger, "warning", lambda message, reason, error: warnings.append((message, reason, str(error))))

    asyncio.run(main._refresh_dynamic_description(bot, "test"))

    assert warnings
    assert warnings[0][1] == "test"
