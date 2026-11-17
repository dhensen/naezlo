import asyncio

import pytest

from naezlo.e2e import _ensure_database, accepting_mailer, e2e_settings
from naezlo.mailer import Mail


def test_e2e_settings_use_the_e2e_database_and_dev_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_LOGIN", "false")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.com")

    settings = e2e_settings(8765)

    assert settings.database_url == settings.e2e_database_url
    assert settings.database_url.endswith("/todolist_e2e")
    assert settings.dev_login is True
    assert settings.public_base_url == "http://localhost:8765"
    assert settings.google_login_enabled is False
    assert settings.email_enabled is False


def test_only_a_database_named_e2e_is_emptied() -> None:
    # Sync on purpose: `asyncio.run` cannot be called inside the tests' event loop.
    with pytest.raises(SystemExit, match="Refusing to empty the database 'todolist'"):
        asyncio.run(_ensure_database("postgresql+asyncpg://u:p@localhost:5435/todolist"))


async def test_the_e2e_mailer_accepts_a_mail_without_a_network() -> None:
    await accepting_mailer().send(Mail(to="a@example.com", subject="s", text="t", html="<p>t</p>"))
