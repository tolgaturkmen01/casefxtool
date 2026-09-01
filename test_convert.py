"""Tests for the /tools/convert endpoint using httpx.MockTransport."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

import fx
from app import app


@pytest.fixture
def upstream_calls() -> list[str]:
    return []


@pytest.fixture
def client(upstream_calls: list[str]) -> TestClient:
    fx._cache.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        upstream_calls.append(f"{request.method} {request.url}")
        url_str = str(request.url)
        path = request.url.path

        if "symbols=XXX" in url_str:
            return httpx.Response(404, json={"message": "not found"})
        if path == "/v1/2000-01-01":
            return httpx.Response(500, text="internal error")
        if path == "/v1/2000-01-02":
            return httpx.Response(200, text="not-json")
        if path == "/v1/latest":
            return httpx.Response(
                200,
                json={
                    "amount": 1.0,
                    "base": "EUR",
                    "date": "2026-09-01",
                    "rates": {"TRY": 55.9498},
                },
            )
        if path == "/v1/2026-08-28":
            return httpx.Response(
                200,
                json={
                    "amount": 1.0,
                    "base": "EUR",
                    "date": "2026-08-28",
                    "rates": {"TRY": 47.1234},
                },
            )
        if path == "/v1/2026-08-30":
            return httpx.Response(
                200,
                json={
                    "amount": 1.0,
                    "base": "EUR",
                    "date": "2026-08-28",
                    "rates": {"TRY": 47.1234},
                },
            )
        if path == "/v1/2099-01-01":
            return httpx.Response(404, json={"message": "not found"})
        return httpx.Response(404, json={"message": "not found"})

    transport = httpx.MockTransport(handler)
    mock_client = httpx.AsyncClient(transport=transport, base_url="http://fake-upstream")

    with TestClient(app) as test_client:
        test_client.app.state.http_client = mock_client
        yield test_client

    fx._cache.clear()


def test_success_with_asked_date(client: TestClient) -> None:
    response = client.get(
        "/tools/convert",
        params={"amount": "250", "from": "EUR", "to": "TRY", "date": "2026-08-28"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "amount": 250.0,
        "from": "EUR",
        "to": "TRY",
        "rate": 47.1234,
        "result": 11780.85,
        "rate_date": "2026-08-28",
        "asked_date": "2026-08-28",
        "source": "ECB via frankfurter.dev",
    }


def test_weekend_asked_date_differs_from_rate_date(client: TestClient) -> None:
    response = client.get(
        "/tools/convert",
        params={"amount": "100", "from": "EUR", "to": "TRY", "date": "2026-08-30"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["asked_date"] == "2026-08-30"
    assert body["rate_date"] == "2026-08-28"


def test_latest_without_date(client: TestClient) -> None:
    response = client.get(
        "/tools/convert",
        params={"amount": "10", "from": "EUR", "to": "TRY"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["rate_date"] == "2026-09-01"
    assert body["asked_date"] is None


def test_future_date_returns_error(client: TestClient) -> None:
    response = client.get(
        "/tools/convert",
        params={"amount": "10", "from": "EUR", "to": "TRY", "date": "2099-01-01"},
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": "date_in_future",
        "message": "The requested date is in the future; no rate has been published for it yet.",
    }


def test_same_currency_returns_error(client: TestClient) -> None:
    response = client.get(
        "/tools/convert",
        params={"amount": "10", "from": "EUR", "to": "EUR"},
    )

    assert response.status_code == 422
    assert response.json()["error"] == "same_currency"


def test_invalid_currency_returns_error(client: TestClient) -> None:
    response = client.get(
        "/tools/convert",
        params={"amount": "10", "from": "EUR", "to": "XXX"},
    )

    assert response.status_code == 404
    assert response.json()["error"] == "rate_not_found"


def test_upstream_500_returns_error(client: TestClient) -> None:
    response = client.get(
        "/tools/convert",
        params={"amount": "10", "from": "EUR", "to": "TRY", "date": "2000-01-01"},
    )

    assert response.status_code == 502
    assert response.json()["error"] == "upstream_error"


def test_upstream_non_json_returns_error(client: TestClient) -> None:
    response = client.get(
        "/tools/convert",
        params={"amount": "10", "from": "EUR", "to": "TRY", "date": "2000-01-02"},
    )

    assert response.status_code == 502
    assert response.json()["error"] == "upstream_invalid_response"


@pytest.mark.parametrize(
    ("amount", "message_part"),
    [
        ("0", "greater than zero"),
        ("-5", "greater than zero"),
        ("1.234", "2 decimal places"),
    ],
)
def test_amount_validation(client: TestClient, amount: str, message_part: str) -> None:
    response = client.get(
        "/tools/convert",
        params={"amount": amount, "from": "EUR", "to": "TRY"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "validation_error"
    assert message_part in body["message"]


def test_missing_amount_uses_custom_validation_error(client: TestClient) -> None:
    response = client.get("/tools/convert", params={"from": "EUR", "to": "TRY"})

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "validation_error"
    assert "amount" in body["message"]


def test_decimal_precision_only_on_result(client: TestClient) -> None:
    response = client.get(
        "/tools/convert",
        params={"amount": "1", "from": "EUR", "to": "TRY", "date": "2026-08-28"},
    )

    body = response.json()
    assert body["rate"] == 47.1234
    assert body["result"] == 47.12


def test_repeat_request_uses_cache(client: TestClient, upstream_calls: list[str]) -> None:
    params = {"amount": "1", "from": "EUR", "to": "TRY", "date": "2026-08-28"}

    first = client.get("/tools/convert", params=params)
    second = client.get("/tools/convert", params=params)

    assert first.status_code == 200
    assert second.status_code == 200
    assert len([call for call in upstream_calls if "/v1/2026-08-28" in call]) == 1


def test_timeout_returns_upstream_timeout(client: TestClient) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    transport = httpx.MockTransport(handler)
    client.app.state.http_client = httpx.AsyncClient(
        transport=transport, base_url="http://fake-upstream"
    )

    response = client.get(
        "/tools/convert",
        params={"amount": "1", "from": "EUR", "to": "TRY"},
    )

    assert response.status_code == 504
    assert response.json()["error"] == "upstream_timeout"
