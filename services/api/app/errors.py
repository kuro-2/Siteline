"""One error shape for every endpoint:
{"error": {"code": "...", "message": "...", "hint": "..."}}
Messages are shown to people, so they follow the copy voice in docs/06 §6.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.hint = hint


def body(code: str, message: str, hint: str | None = None) -> dict[str, dict[str, str | None]]:
    return {"error": {"code": code, "message": message, "hint": hint}}


def not_found(what: str, hint: str | None = None) -> ApiError:
    return ApiError(404, "not_found", f"We couldn't find that {what}.", hint)


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(body(exc.code, exc.message, exc.hint), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(x) for x in first.get("loc", []) if x not in ("body", "query"))
        msg = f"Check '{loc}': {first.get('msg', 'invalid value')}." if loc else "Check your input."
        return JSONResponse(body("invalid_input", msg), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        messages = {
            401: "Log in to do this.",
            403: "You don't have access to this.",
            404: "We couldn't find that page.",
            405: "That action isn't allowed here.",
        }
        code = {401: "unauthorised", 403: "forbidden", 404: "not_found"}.get(
            exc.status_code, "error"
        )
        msg = (
            exc.detail
            if isinstance(exc.detail, str) and exc.status_code not in messages
            else messages.get(exc.status_code, "Something went wrong.")
        )
        return JSONResponse(body(code, msg), status_code=exc.status_code)
