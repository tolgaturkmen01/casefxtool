# REVIEW.md — tool.py

Findings are ranked by what they cost a paying customer. The first three all
produce a wrong number that looks like a right one; the rest matter but are
visible sooner.

### 1. The cache key ignores the date

**What happens:** `_cache` is keyed on `f"{base}-{target}"` only. Once any date
has been fetched for a pair, every later request for that pair returns the
cached rate, whatever date was asked for.

**Cost to the customer:** After a single call the service silently serves wrong
numbers to everyone. I asked for 2020-01-02 first, then 2026-08-28: the second
request returned the 2020 rate of 6.67, giving 1,667.50 TRY for 250 EUR. The
correct answer is 14,042.95 TRY — an eight-fold error with no warning, and the
response labels the stale rate with the date that was asked for.

**How I verified it:**
```
curl -s "localhost:8090/tools/convert?amount=1&to=TRY&on=2020-01-02"
curl -s "localhost:8090/tools/convert?amount=1&to=TRY&on=2026-08-28"
```
Both return `"rate":6.67`, with `rate_date` echoing the requested date.

**This is the one I would fix before shipping tonight.** Every other finding
affects some requests; this one poisons all of them after the first call.

### 2. Errors return 200 with a zero rate

**What happens:** A bare `except Exception` catches everything and returns HTTP
200 with `rate` and `result` set to 0.0.

**Cost to the customer:** The agent has no way to tell the call failed. It reads
a successful response and tells the customer their 250 EUR is worth 0 TRY.
Nothing surfaces the failure to us either — there is no non-2xx status and no
alert, so the customer sees the wrong answer before we know anything broke.

**How I verified it:**
```
curl -s -w "\n%{http_code}\n" "localhost:8090/tools/convert?amount=250&to=XYZ"
```
Returns `{"rate":0.0,"result":0.0}` with status 200, while the server logs
`conversion failed: 'rates'`.

### 3. rate_date is invented

**What happens:** `rate_date` is filled with `str(on or date.today())`. The
upstream tells us which day its rates belong to in `payload["date"]`, and that
field is never read. On a weekend the code falls back to `/latest` but still
labels the result with the date that was asked for.

**Cost to the customer:** The customer is told a number belongs to a day it does
not belong to. A Saturday query returns Friday's rate stamped Saturday, and the
agent cannot tell the customer which day the number is really from — which is
the one thing this tool exists to get right.

**How I verified it:**
```
curl -s "localhost:8090/tools/convert?amount=1&to=TRY&on=2026-08-29"
```
2026-08-29 is a Saturday. The rate returned is 56.17 — Friday's rate, which the
same date returns from a correct implementation — but `rate_date` reports 2026-08-29.

### 4. Parameter names don't match the contract

**What happens:** The endpoint expects `from_` and `on`; the documented
interface uses `from` and `date`. Because `from_` has a default of `"EUR"`, a
request sending `from=USD` does not fail — the parameter is ignored.

**Cost to the customer:** A USD conversion is quietly answered with EUR rates.
No error, no warning, just a wrong currency and a wrong number.

**How I verified it:**
```
curl -s "localhost:8090/tools/convert?amount=250&from=USD&to=TRY"
```
The response echoes `"from":"EUR"` and the amount is converted at the EUR rate.

### 5. Upstream is hardcoded

**What happens:** `UPSTREAM = "https://api.frankfurter.dev/v1"` is a literal.
Neither `FX_UPSTREAM_BASE` nor `PORT` is read.

**Cost to the customer:** Nothing is testable against a fake upstream, so
failure behaviour can only be discovered in production. If frankfurter.dev
changes host or we need to point at a backup, the only fix is a code change and
a deploy — during an outage, that is the slowest possible lever.

**How I verified it:** No `os.environ` or `os.getenv` call appears anywhere in
the file; the constant is used directly in `fetch_rate`.

### 6. The rate is rounded before multiplication

**What happens:** `round(rate, 2)` is applied to the rate, and the rounded value
is what gets multiplied by the amount.

**Cost to the customer:** Every conversion is off, and the error scales with the
amount. At a rate of 56.1718, 250 EUR should be 14,042.95 TRY; rounding the rate
to 56.17 first gives 14,042.50. For a currency whose rate is below 0.01 the
rounded rate becomes 0.00 and the answer is zero. Rounding belongs on the
result, not the rate.

**How I verified it:** Compared the same request against a correct
implementation at the same date and rate — 14,042.50 versus 14,042.95.

### Looks suspicious but is fine

`httpx.AsyncClient()` is created with no timeout argument, which reads like a
request that could hang forever. It is not: httpx applies a 5-second default. The
real criticism is narrower — the timeout was inherited rather than chosen, and
for a call sitting in front of a paying customer that budget should be explicit.

### Lower priority

The client is created at module level and never closed on shutdown, leaving
sockets open. And `_cache` has no eviction policy — harmless today because the
key collapses everything onto one entry per pair, but the moment finding 1 is
fixed the cache grows unbounded and needs a TTL or size limit.