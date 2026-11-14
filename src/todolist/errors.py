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


async def _handle_app_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return JSONResponse(
        status_code=exc.status_code, content={"detail": exc.detail, "code": exc.code}
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
