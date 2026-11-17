from pathlib import Path

import pytest

from naezlo.openapi import openapi_schema, render_openapi_schema

SAVED_SCHEMA = Path(__file__).resolve().parent.parent / "frontend" / "openapi.json"


def test_the_saved_schema_matches_the_api() -> None:
    """The frontend's types are generated from this file, so it must follow the backend."""
    assert SAVED_SCHEMA.read_text() == render_openapi_schema(), (
        "frontend/openapi.json is out of date: run `npm --prefix frontend run gen:api` "
        "and commit the result"
    )


def test_the_schema_does_not_depend_on_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    before = openapi_schema()
    monkeypatch.setenv("APP_NAME", "renamed")
    monkeypatch.setenv("DEV_LOGIN", "true")

    assert openapi_schema() == before
    assert "/api/auth/dev-login" in before["paths"]
