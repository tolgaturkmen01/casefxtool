# fx-tool

A single-endpoint HTTP service that converts an amount between two currencies
using ECB rates published via [frankfurter.dev](https://frankfurter.dev).

## Run

```bash
./run.sh
```

Listens on `PORT` (default `8080`). Upstream comes from `FX_UPSTREAM_BASE`
(default `https://api.frankfurter.dev`); the real host is not hardcoded anywhere.

## Test

```bash
./test.sh
```

Tests never touch the network — the upstream is faked with `httpx.MockTransport`.
They pass with `FX_UPSTREAM_BASE` pointing at a closed port.

## Endpoint

```
GET /tools/convert?amount=250&from=EUR&to=TRY&date=2026-08-28
```

`date` is optional; omitting it uses the latest published rates.

```json
{
  "amount": 250.0,
  "from": "EUR",
  "to": "TRY",
  "rate": 47.1234,
  "result": 11780.85,
  "rate_date": "2026-08-28",
  "asked_date": "2026-08-28",
  "source": "ECB via frankfurter.dev"
}
```

`rate_date` is read from the upstream payload — it is the date the rate actually
belongs to, never the date that was asked for. `asked_date` echoes the request
(`null` when no date was given). When the two differ, the caller can see it and
tell the customer which day the number is from.

## Behaviour

| Case | Response |
|---|---|
| Weekend or holiday | 200. The upstream returns the previous published day; `rate_date` shows that day and differs from `asked_date`. |
| Date in the future | 422 `date_in_future`. Rejected before contacting the upstream. |
| Date before 1999-01-04 | 422 `date_before_series_start`. Rejected before contacting the upstream. |
| Currency code not 3 letters | 422 `validation_error` |
| Currency code unknown to the upstream | 404 `rate_not_found` |
| `from` equals `to` | 422 `same_currency`. No upstream call. |
| `amount` missing | 422 `validation_error` |
| `amount` zero or negative | 422 `validation_error` |
| `amount` with more than 2 decimals | 422 `validation_error` |
| Upstream times out | 504 `upstream_timeout` |
| Upstream unreachable | 502 `upstream_unavailable` |
| Upstream returns 5xx | 502 `upstream_error` |
| Upstream returns non-JSON or an incomplete payload | 502 `upstream_invalid_response` |

Every failure returns a non-2xx status and `{"error": "...", "message": "..."}`.
The service never invents a rate and never returns a rate labelled with a date it
does not belong to.

## Error codes

| Code | Status |
|---|---|
| `validation_error` | 422 |
| `same_currency` | 422 |
| `date_in_future` | 422 |
| `date_before_series_start` | 422 |
| `rate_not_found` | 404 |
| `upstream_timeout` | 504 |
| `upstream_unavailable` | 502 |
| `upstream_error` | 502 |
| `upstream_invalid_response` | 502 |

## Caching

Successful upstream payloads are cached in-process, keyed by date, base, and
target. A repeated question does not re-ask the upstream. Failures are not
cached.