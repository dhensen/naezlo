"""Prints the OpenAPI schema of the API, the input of the frontend's generated types.

`npm --prefix frontend run gen:api` runs `python -m naezlo.openapi`, saves the output as
`frontend/openapi.json` and generates `frontend/src/api/schema.d.ts` from it. Both files are
committed; `tests/test_openapi.py` fails when the saved schema is behind the code.
"""

import json
import sys
from typing import Any

from naezlo.app import create_app
from naezlo.config import Settings


def openapi_schema() -> dict[str, Any]:
    """The schema, the same on every machine: no `.env`, no environment variables."""
    # `model_construct` takes the field defaults as they are; `Settings()` and
    # `Settings.model_validate()` would both read the environment.
    settings = Settings.model_construct(frontend_dist=None)
    return create_app(settings).openapi()


def render_openapi_schema() -> str:
    return json.dumps(openapi_schema(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    sys.stdout.write(render_openapi_schema())
