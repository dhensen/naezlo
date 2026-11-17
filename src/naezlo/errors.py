"""API errors with a machine-readable code.

Every error response has the shape `{"detail": "<message for humans>", "code": "<snake_case>"}`.
`detail` is the key FastAPI itself uses (validation errors, unknown routes), so clients can
always read it; `code` is what they branch on.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


class NotAuthenticatedError(AppError):
    def __init__(self) -> None:
        super().__init__(401, "not_authenticated", "Not signed in")


class NotFoundError(AppError):
    def __init__(self, detail: str = "Not found") -> None:
        super().__init__(404, "not_found", detail)


class ForbiddenError(AppError):
    """The caller can see the resource, but the action needs a higher role."""

    def __init__(self, detail: str = "Not allowed") -> None:
        super().__init__(403, "forbidden", detail)


class ConflictError(AppError):
    """The request is valid but the current state does not allow it. Give a specific code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(409, code, detail)


class OAuthError(Exception):
    """An error of an OAuth endpoint (/register, /token, /revoke), in the shape OAuth clients
    expect: `{"error": "<code from the RFC>", "error_description": "<message>"}` (RFC 6749 5.2).
    """

    def __init__(self, error: str, description: str, status_code: int = 400) -> None:
        super().__init__(description)
        self.status_code = status_code
        self.error = error
        self.description = description


async def _handle_app_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return JSONResponse(
        status_code=exc.status_code, content={"detail": exc.detail, "code": exc.code}
    )


def oauth_error_response(error: OAuthError) -> JSONResponse:
    """The response for an `OAuthError`. Raising the error gives the same; a route returns
    this instead when the changes of the request must be kept (raising rolls them back)."""
    return JSONResponse(
        status_code=error.status_code,
        content={"error": error.error, "error_description": error.description},
        headers={"Cache-Control": "no-store"},
    )


async def _handle_oauth_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, OAuthError)
    return oauth_error_response(exc)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(OAuthError, _handle_oauth_error)
