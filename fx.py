"""Upstream FX client, cache, and error types."""

from __future__ import annotations

import os
from typing import Any

import httpx
from starlette import status

FX_UPSTREAM_BASE = os.environ.get("FX_UPSTREAM_BASE", "https://api.frankfurter.dev").rstrip("/")
SOURCE_LABEL = "ECB via frankfurter.dev"

_cache: dict[str, dict[str, Any]] = {}


class ServiceError(Exception):
    def __init__(self, status_code: int, error: str, message: str) -> None:
        self.status_code = status_code
        self.error = error
        self.message = message


async def fetch_rate_payload(
    client: httpx.AsyncClient,
    *,
    base: str,
    target: str,
    date_path: str,
) -> dict[str, Any]:
    cache_key = f"{date_path}:{base}:{target}"
    if cache_key in _cache:
        return _cache[cache_key]

    try:
        response = await client.get(
            f"/v1/{date_path}",
            params={"base": base, "symbols": target},
        )
    except httpx.TimeoutException as exc:
        raise ServiceError(
            status.HTTP_504_GATEWAY_TIMEOUT,
            "upstream_timeout",
            "The exchange-rate service did not respond in time.",
        ) from exc
    except httpx.RequestError as exc:
        raise ServiceError(
            status.HTTP_502_BAD_GATEWAY,
            "upstream_unavailable",
            "The exchange-rate service could not be reached.",
        ) from exc

    if response.status_code == 404:
        raise ServiceError(
            status.HTTP_404_NOT_FOUND,
            "rate_not_found",
            "No exchange rate is available for the requested date or currency.",
        )
    if response.status_code >= 500:
        raise ServiceError(
            status.HTTP_502_BAD_GATEWAY,
            "upstream_error",
            "The exchange-rate service returned an error.",
        )
    if response.status_code != 200:
        raise ServiceError(
            status.HTTP_502_BAD_GATEWAY,
            "upstream_error",
            "The exchange-rate service returned an unexpected response.",
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise ServiceError(
            status.HTTP_502_BAD_GATEWAY,
            "upstream_invalid_response",
            "The exchange-rate service returned invalid JSON.",
        ) from exc

    rates = payload.get("rates")
    if not isinstance(rates, dict) or target not in rates or "date" not in payload:
        raise ServiceError(
            status.HTTP_502_BAD_GATEWAY,
            "upstream_invalid_response",
            "The exchange-rate service returned an incomplete response.",
        )

    _cache[cache_key] = payload
    return payload
