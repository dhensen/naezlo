import pytest

from naezlo.config import Settings


def test_settings_defaults() -> None:
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.app_name == "Naezlo"
    assert settings.environment == "development"


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_NAME", "renamed")

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.app_name == "renamed"
