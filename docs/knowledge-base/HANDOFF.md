# Coding-agent handoff

Snapshot: 26 October 2026. Start with [README.md](README.md), then the runbook.
The current requested work is this knowledge base; no new runtime feature is
being implemented as part of the handoff.

## User intent and accepted decisions

The product is called the **gateway**. It must travel to a Linux server with MT5
inside the image, Python collection, persistent SQLite storage, and a web dashboard.
The user accepted 20 FX instruments plus all 14 metals available from this broker,
all 21 native MT5 intervals, and 1Y/3Y/5Y/10Y/Max history views. Those views have
already been implemented; they do not create yearly MT5 candle intervals.
Resource limits matter because unconstrained MT5 previously overwhelmed the laptop.
Credentials come from the local `.env`; never copy them into documentation.

## First checks

Work in the actual project root, not the Codex conversation directory. Read the
existing diff before changing files: many working files are uncommitted or
untracked and are intentional. Do not reset or clean the repository.

```powershell
git status --short
docker compose --project-directory . -p mt5scraper-portable -f docker/compose.server.yaml ps
Invoke-RestMethod http://127.0.0.1:8080/health
python -m unittest discover -s tests -v
```

Inspect `/api/tables` for coverage and `/api/live?symbol=EURUSD` for collector
health. A healthy HTTP server does not prove MT5 is connected. At handoff, these
checks showed 714 populated tables, an online collector, and 39 passing tests.
Do not assume every populated table has complete historical coverage.

## Preserve these boundaries

- Ordinary upgrades retain both named volumes. Never use `down -v` or reset the
  database unless the user explicitly requests data removal.
- Keep loopback web bindings and the current caps: core 4 CPU/4 GiB, dashboard
  0.25 CPU/256 MiB, with no additional swap.
- The unrelated `mt5-gateway`, Postgres, Redis, and `slate-*` containers are not
  owned by this Compose project. Do not prune Docker globally.
- The stack is a market-data collector. Do not add order placement implicitly.
- A rebuilt image is not running until its service is recreated.

## Remaining engineering risks

These are follow-up candidates, not claims that the stack is production-certified:

1. Validate a fresh deployment on the actual Linux/amd64 server, including first-run
   package downloads, broker connectivity, volume persistence, and resource caps.
   Local Docker builds and the broker-connected local stack do not verify that host.
2. Add a controlled historical backfill workflow. Live catch-up remains bounded
   and does not launch a historical job automatically.
3. Verify the broker's timestamp convention and exact offset, including session
   boundaries. `MT5_TIME_OFFSET_SECONDS` defaults to zero and affects new live
   data only; existing rows are not rewritten.
4. Reconcile legacy `setup.py` dependencies with Docker: legacy NumPy 1.24.0 versus
   tested Wine runtime NumPy 1.26.4. Editable installation is not the deployment path.
5. Pin build dependencies more tightly. Dashboard Basic auth is optional through
   `DASHBOARD_USER` and `DASHBOARD_PASSWORD`; keep remote access behind HTTPS/SSH.

Worker supervision, bounded signal shutdown, and live coverage/gap reporting are
implemented. Their behavior has local unit and container checks, but shutdown
under every failure mode is not production-certified.

## Validation expectations

The 43 tests cover startup helpers, historical paging, collection logic, and
dashboard queries. Much of MT5 behavior is mocked; passing tests do not replace
a broker-connected smoke check. Preserve regression coverage for earliest-candle
paging, indexed SQLite queries, calendar ranges, and monthly forming-bar handling.
Documentation-only changes do not require recreating containers.

The sanitized handoff ZIP contains source and documentation, not a runnable image
archive. It excludes credentials, databases, persisted MT5 state, and the terminal
binary. Supply those separately through the existing deployment process when needed.
