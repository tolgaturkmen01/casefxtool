# Notes

## Decisions

**Weekends and holidays.** When a non-publishing day is asked for, I return the
most recent published rate and report the upstream's own date in `rate_date`,
with `asked_date` echoing the request. I chose this over failing because
Friday's rate is the functionally correct answer for a Saturday question — as
long as the caller can see which day the number belongs to. When the two fields
differ, the model can tell the customer exactly that.

**Out-of-bound dates.** Future dates and dates before 1999-01-04 are rejected
before the upstream is contacted, with separate error codes. The upstream
happens to return 404 for both today, but relying on that is fragile: if its
behaviour changes to serving the latest rate instead, this service would start
answering silently and wrongly. The decision belongs on our side.

**Same currency.** `from == to` returns an error rather than short-circuiting to
a rate of 1.0. A caller asking to convert EUR to EUR has almost certainly built
the request wrong, and answering it cleanly would hide that.

**Decimal precision.** An `amount` with more than two decimal places is
rejected. Silently rounding would hide a caller's mistake; failing loudly is
more predictable for a tool an agent is calling on a customer's behalf.

**Caching.** Keyed on date, base, and target together, so a rate fetched for one
date can never be served for another. Failures are never cached.

## With another day

**A TTL for `latest`.** The `latest` payload is cached indefinitely. It is not a
lie — `rate_date` still names the real day — but a long-running process would
keep serving an increasingly old rate. A short TTL, on the order of an hour, is
the first thing I would add.

**Cache eviction.** `_cache` has no size limit. Fine at this scale, but a
production version needs an LRU or size cap.

## AI tools

I used Cursor. To keep the scope from drifting I wrote the constraints from the
brief into `.cursorrules` up front — no Docker, no CI, no extra endpoints, no
hardcoded upstream — and kept auto-apply off so I read and approved every diff
before it landed. I committed in small steps as each piece was verified. For
Part B I did not use the AI at all: I read `tool.py` myself, wrote the findings
in my own words, and then reproduced each one against a running instance before
writing it down.

## One thing the AI got wrong

The generated tests passed from the start, which is exactly the situation worth
being suspicious of when the same tool wrote both the code and the tests. Two
things came out of checking rather than trusting them.

The dependency list was the concrete one. `requirements.txt` ended up holding
200+ packages — `tensorflow`, `torch`, `spotdl` — because the freeze that
produced it ran against my global environment rather than the project venv, and
neither the generated `run.sh` nor the tests would have caught that: everything
passed on my machine using globally installed packages. I found it when I
rebuilt the venv from scratch and `pip install -r requirements.txt` failed on a
conflict between `spotdl` and the FastAPI version this service needs. The
repository was undeployable for anyone else while looking perfectly healthy
locally. I replaced the file with the four packages the service actually needs
and reran the suite against a closed-port upstream to confirm.

The smaller one: the first version used the deprecated `on_event` startup and
shutdown hooks. The tests passed regardless — deprecation warnings do not fail a
run — so this only surfaced from reading the warning output instead of the pass
count.