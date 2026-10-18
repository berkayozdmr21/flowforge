# Verification — 18 October 2026

## HTTP request extension

- 122 backend/domain tests and 17 frontend graph/history tests passed (139 total); production TypeScript/Vite build passed.
- HTTP tests exercise URL/header validation, private/mixed DNS rejection, pinned IP connections, TLS hostname selection, nested response mapping, body/response/record bounds, JSON parsing, token lookup, sanitized errors, timeout handling, GET retry classification, permanent POST failures and saved Activity output reuse.
- Real PostgreSQL + Temporal execution completed all four templates. Report downloads matched recorded sizes and run events remained contiguous.
- `scripts/http_smoke.py` performed real GET (HTTP 200, 10 records) and POST (HTTP 201, 1 record) requests to JSONPlaceholder, then verified all three downloadable report formats for each. The provider's POST endpoint is a demo and does not persist changes.
- Browser acceptance selected the HTTP template, inspected the HTTP controls, ran it successfully, showed 10 records and all three report links, and checked POST body-source controls. No browser errors or warnings were reported.
- Runtime HTTP requests use Python's standard-library HTTP client with validated/pinned DNS and TLS verification; they do not use proxy environment variables. Tests mock transport boundaries, while the opt-in acceptance script covers the real external API.
- External POST effects cannot be rolled back by cancellation. A crash or Activity timeout before output persistence can repeat a request; target APIs must honor the stable idempotency key. This extension does not claim exactly-once remote delivery.

## Original core acceptance — 17 October 2026

## Automated checks

- 65 backend/domain tests passed: graph validation, schema checks, operations, report safety, immutable versions, optimistic updates, idempotent starts, cancellation requests, event replay, WebSocket origin checks and recorded Activity retries.
- 17 frontend tests passed: graph connection rules, import validation and undo/redo isolation/history bounds.
- TypeScript and Vite 8 production build passed.
- `npm audit` reported zero known vulnerabilities at verification time.
- `docker compose config --quiet` passed. The Docker daemon was unavailable, so container execution was not verified.
- One third-party deprecation warning remains in the backend test adapter: Starlette recommends httpx2 for its test client. It did not fail the tests.

## Real PostgreSQL + Temporal

The native stack used PostgreSQL 17 and official Temporal CLI 1.9.1 with persistent storage. All three templates completed and their three report formats downloaded with matching byte sizes. Event sequences were contiguous.

A 15-second timer run survived a worker stop/restart under the same run ID. Its completed input node was not executed again. Cancellation of a 60-second timer completed as `cancelled` without a report. A numeric-overflow failure produced a failed aggregate, a blocked report and only one attempt for the permanent error.

The native `run.py` supervisor started the real PostgreSQL, Temporal, API and worker stack, waited for readiness and printed the working URL. No replacement in-memory workflow executor was used. Preview processes were kept separate from other projects' services.

## Browser checks

The browser confirmed template selection, adding a delay block and undoing it, run creation, a live WebSocket connection, all node-completion events, a five-record cleaned result and three report links. No browser warning/error logs were observed in the final acceptance pass. See `docs/studio.jpg`. The warm neutral palette was requested during development and replaced the initial violet interface. Native file-picker saving and arbitrary touch devices are not exhaustively covered.

## Scope

The core local-workspace delivery now has eight real node types, including GET/POST HTTP requests. File/AI connections, webhooks/schedules and multi-user permissions remain future extensions.

The final browser acceptance also imported a delay workflow from JSON, refreshed while it was running, reattached to the same run ID in read-only mode and cancelled it from the UI. The mini map displayed all three nodes and all three report links were visible.
