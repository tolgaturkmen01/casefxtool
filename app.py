"""Currency conversion service for the mangolab case study."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette import status

from fx import (
    FX_UPSTREAM_BASE,
    SOURCE_LABEL,
    ServiceError,
    fetch_rate_payload,
)

TWOPLACES = Decimal("0.01")
CURRENCY_RE = re.compile(r"^[A-Za-z]{3}$")

app = FastAPI(title="fx-tool", version="0.1.0")


def error_response(status_code: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": error, "message": message})


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return error_response(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "validation_error",
        validation_message(exc),
    )


@app.exception_handler(ServiceError)
async def handle_service_error(request: Request, exc: ServiceError) -> JSONResponse:
    return error_response(exc.status_code, exc.error, exc.message)


def validation_message(exc: RequestValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "The request could not be validated."
    first = errors[0]
    field_parts = [str(part) for part in first.get("loc", ()) if part not in {"body", "query"}]
    field = field_parts[-1] if field_parts else "request"
    detail = first.get("msg", "Invalid value.")
    return f"{field}: {detail}"


@app.on_event("startup")
async def startup() -> None:
    app.state.http_client = httpx.AsyncClient(base_url=FX_UPSTREAM_BASE, timeout=10.0)


@app.on_event("shutdown")
async def shutdown() -> None:
    await app.state.http_client.aclose()


def normalize_currency(code: str, field_name: str) -> str:
    normalized = code.upper()
    if not CURRENCY_RE.match(code):
        raise ServiceError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "validation_error",
            f"{field_name}: must be a 3-letter currency code.",
        )
    return normalized


def validate_amount(value: Decimal) -> Decimal:
    if value <= 0:
        raise ServiceError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "validation_error",
            "amount: must be greater than zero.",
        )
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        raise ServiceError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "validation_error",
            "amount: must have at most 2 decimal places.",
        )
    return value


@app.get("/tools/convert")
async def convert(
    amount: Decimal = Query(...),
    from_currency: str = Query(alias="from"),
    to: str = Query(...),
    asked_date: date | None = Query(default=None, alias="date"),
) -> dict[str, Any]:
    amount = validate_amount(amount)
    base = normalize_currency(from_currency, "from")
    target = normalize_currency(to, "to")

    if base == target:
        raise ServiceError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "same_currency",
            "Source and target currency must be different.",
        )

    if asked_date is not None:
        if asked_date > date.today():
            raise ServiceError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "date_in_future",
                "The requested date is in the future; no rate has been published for it yet.",
            )
        if asked_date < date(1999, 1, 4):
            raise ServiceError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "date_before_series_start",
                "The ECB series starts on 1999-01-04; no rate exists for earlier dates.",
            )

    date_path = str(asked_date) if asked_date is not None else "latest"
    client: httpx.AsyncClient = app.state.http_client
    payload = await fetch_rate_payload(
        client, base=base, target=target, date_path=date_path
    )

    rate = Decimal(str(payload["rates"][target]))
    result = (amount * rate).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

    response: dict[str, Any] = {
        "amount": float(amount),
        "from": base,
        "to": target,
        "rate": float(rate),
        "result": float(result),
        "rate_date": payload["date"],
        "source": SOURCE_LABEL,
    }
    if asked_date is not None:
        response["asked_date"] = asked_date.isoformat()
    else:
        response["asked_date"] = None
    return response
