# FlowForge

**Make work flow.** A visual automation studio built by **Berkay Özdemir**.

Design workflows on a canvas, execute them with a real durable worker, inspect every step, and download the results. A warm paper-and-olive interface keeps the workspace quiet while live node states make execution easy to follow.

**React 19 · TypeScript · React Flow · FastAPI · PostgreSQL · Temporal**

![FlowForge studio](docs/studio.jpg)

## What works

- Eight executable node types: **JSON input, transform, condition, merge, report, durable delay, aggregation and HTTP request**.
- A visual graph editor with typed ports, connection validation, mini map, zoom, node settings, duplication and deletion.
- A connection dialog as an alternative to dragging ports.
- Undo/redo, one history entry per completed drag, and browser draft persistence.
- Four executable templates: data quality, conditional routing, parallel sales analysis and a live HTTP API report.
- Server-side cycle detection, reachability checks, port validation and configuration schemas.
- Real Temporal workflows and Activities, up to four concurrent ready nodes per run, bounded retries and cancellation.
- Immutable workflow versions, optimistic draft updates and idempotent run creation.
- PostgreSQL transactions, an outbox dispatcher and ordered, persisted run events.
- WebSocket updates with cursor-based replay after reconnects.
- Run history, node output previews, attempt history and JSON workflow import/export.
- Server-generated **JSON, CSV and HTML** reports with safe escaping.
- Reduced motion, keyboard shortcuts and collapsible work panels.
- Persistent one-shot, hourly and daily schedules with pause/resume, cancellation, next-run display and occurrence history.

The original seven blocks and the public HTTP demo work without API keys. The HTTP demo needs internet access. AI provider integrations, file ingestion, webhooks and multi-user/team authorization remain future extensions. HTTP requests and scheduled executions are real, not simulated responses.

## Try it

1. Open **Hazır şablonlar** and choose **Müşteri verisi**.
2. Select the input node, edit its JSON and click **Girdiyi uygula**.
3. Adjust the transform options or leave the sample defaults.
4. Click **Çalıştır** and inspect the live event log.
5. Open **Raporlar** to download the JSON, CSV or HTML result.

The sample contains fictional records and `.test` email addresses. Cleaning the sample with a required email produces five unique, nonempty records. An empty result is valid data, not an execution error.

## Start on Windows

### Native local stack — verified

Prerequisites: **Python 3.10+ (3.12 recommended)** and an installed **PostgreSQL 17+**. PostgreSQL executables are discovered under `Program Files/PostgreSQL`; set `PG_BIN` to another installation's `bin` directory when necessary.

1. Extract the whole project.
2. Double-click **BASLAT.cmd**.
3. Keep the terminal open. The browser opens only after the API, PostgreSQL and Temporal worker are ready.
4. Stop with **Ctrl+C** in that terminal, or use **DURDUR.cmd**.

The first launch installs Python packages in `.venv` and, if missing, downloads Temporal CLI **1.9.1** from its official GitHub release. Its SHA-256 is checked against the official release checksums. Internet is required for that first setup. The production frontend is included; normal use does not require Node.js.

The launcher starts a project-owned PostgreSQL cluster, a persistent Temporal development server, the API and the worker. It chooses available ports; the editor prefers **9030**. The actual URL is printed and written to `.runtime/current-url.txt`. Runtime files and logs stay under `.runtime`; no existing system database is reconfigured. The native development cluster uses trust authentication on loopback only. Do not expose it on a network.

### Docker Compose

With Docker Desktop running:

```sh
docker compose up --build
```

Open [localhost:9030](http://127.0.0.1:9030). The Temporal UI is at [localhost:8239](http://127.0.0.1:8239). Use `FLOWFORGE_PORT` to change the editor's host port, for example `FLOWFORGE_PORT=9040 docker compose up --build` on a POSIX shell.

`DOCKER_BASLAT.cmd` provides the standard Windows Docker command. Stop containers with `docker compose stop`. PostgreSQL, Temporal state and output artifacts use named volumes. The included password is a development-only container default.

The Compose configuration was validated. Docker execution could not be verified in the development environment because its Docker engine was unavailable; the native stack was exercised end to end.

## Architecture

```mermaid
flowchart LR
  Editor[React + TypeScript editor] --> API[FastAPI]
  API --> PG[(Application PostgreSQL)]
  PG --> Outbox[Transactional outbox]
  Outbox --> Temporal[Temporal service]
  Temporal <--> Worker[Python worker]
  Worker --> PG
  Worker --> Files[Outputs and report artifacts]
  PG --> Events[Persisted ordered events]
  Events --> WS[WebSocket replay]
  WS --> Editor
  Temporal --> History[(Temporal persistence)]
```

The API never runs a workflow inside a request. Run creation stores the immutable version, run record and outbox intent atomically. A dispatcher starts a Temporal workflow using a stable run-based ID; repeated dispatch does not create a second workflow. The worker executes independent ready nodes in bounded parallel batches.

Workflow code handles deterministic orchestration. Database operations, transforms and artifact writes happen in Activities. Durable delays use Temporal timers. Large records and outputs are kept outside Temporal history: Activities return compact node/count/port metadata, with detailed data stored in application storage.

### Branches and joins

`condition` makes one decision over its input, e.g. `records.count > 0`. It activates `true` or `false`; the unused branch becomes `skipped`. Row filtering belongs in `transform`.

`merge` waits until every parent is terminal, ignores skipped branches and concatenates active results in edge order. All-skipped joins are skipped. A failed required operation fails the run and blocks remaining work. Empty record arrays are valid.

Activity execution is at least once. Stable output names, artifact IDs and completed-node checks make internal writes safe to repeat. This does not claim exactly-once effects for arbitrary external services.

### Persistence

Application tables: `workflows`, `workflow_versions`, `runs`, `node_runs`, `node_attempts`, `run_events`, `artifacts`, `outbox`, `workflow_schedules`, `schedule_runs`. Alembic manages the schema. Drafts use revisions; stale updates return 409. A running job or schedule uses its saved version even if the editor draft changes.

Clearing browser storage removes local unsaved drafts, not PostgreSQL saves. Named records, run history and reports remain under project-managed persistent storage. Keep backups of `.runtime` for the native stack or Docker volumes for Compose.

## Node settings

| Node | Configuration |
| --- | --- |
| JSON input | List of JSON objects, up to 10,000 records |
| Transform | Trim, remove empty rows, required field, deduplicate, comparisons, projection and rename |
| Condition | Record count or first-record field, operator and value |
| Merge | Stable concatenation, optional deduplication |
| Report | Title and JSON/CSV/HTML formats |
| Delay | Persistent timer, 0.1–300 seconds, cancellable |
| Aggregate | Group field, numeric field, count/sum/mean |
| HTTP request | GET/POST URL, timeout, nested JSON response path, input/custom JSON body, headers and optional bearer-token environment reference |

Transforms use a fixed declarative operation set. There is no `eval`, arbitrary Python block or user-supplied executable code.

### HTTP request block

Choose **HTTP ENTEGRASYONU / API kullanıcı raporu** in the template picker. It runs `JSON input → HTTP GET → Transform → Report` against JSONPlaceholder's public demo `/users` endpoint and exports selected fields as JSON, CSV and HTML. Empty input records are valid for a GET request.

- **GET** replaces incoming records with the API's JSON response. A JSON object becomes one record; an array must contain objects. For a wrapper such as `{"data":{"items":[...]}}`, set `responsePath` to `data.items`.
- **POST** sends the previous block's records as a JSON array, or the `body` object from advanced JSON settings when `bodySource` is `json`. Each node execution adds a stable `Idempotency-Key` derived from run/node IDs.
- The inspector exposes method, URL, timeout (1–30 seconds), response path, body source and token reference. Non-secret headers and a custom body can be edited under **Gelişmiş JSON ayarları** and applied explicitly.
- Requests and responses are limited to 1 MB; responses may contain at most 10,000 records. Responses must have a JSON content type. Redirects, local/private/reserved addresses, embedded URL credentials, custom ports and proxy environment settings are not supported. DNS results are checked and connections use the selected validated IP while HTTPS verifies the original hostname.
- GET transport errors, HTTP 408/429 and 5xx errors use the existing bounded Activity retry policy. Other HTTP status errors, invalid JSON and invalid configuration are permanent failures. POST request errors are permanent to avoid automatic resubmission after an ambiguous result.
- A completed node reuses its stored output. A worker crash or Activity timeout before persistence can still repeat an external request: the target API must honor `Idempotency-Key` for duplicate protection. Cancellation cannot roll back a remote operation. There is no exactly-once guarantee for third-party APIs.

For bearer authentication, set `tokenEnv` to a reference such as `CRM`, then define `FLOWFORGE_HTTP_TOKEN_CRM` in the **worker's environment** before starting the stack. Native `run.py` inherits shell variables; with Docker, explicitly pass the same variable to the `worker` service. Tokens are read at execution time and sent only over HTTPS. Token values are not stored in graph versions or HTTP metadata. Do not put credentials in URLs, `headers` or custom bodies: those settings are saved and exported with the graph. The generated reports contain API response data, so choose APIs and output fields accordingly.

To exercise real GET and POST calls against the public demo service while the stack is running:

```sh
python scripts/http_smoke.py
```

The demo POST endpoint simulates creation; its data does not persist at the provider. The acceptance script sends only fixed demo data.

## Scheduled executions

Open the **Zamanlanmış görevler** calendar-clock button in the editor header. Choose a name, first local date/time and **Bir kez**, **Her saat** or **Her 24 saat**. Saving first persists the current draft and creates an immutable version; subsequent draft edits do not change that schedule. Unapplied block JSON must be applied before scheduling.

- Times are sent as timezone-aware UTC instants and displayed in the browser's local timezone. Hourly/daily modes use fixed 3,600/86,400-second intervals, not calendar-day or DST-aware cron rules.
- PostgreSQL stores schedules and their occurrence history. The worker polls due schedules about once per second and transactionally creates the run, node states, schedule occurrence and existing Temporal outbox record. The browser may be closed; the computer, PostgreSQL, Temporal and worker must remain available. This is not a hosted always-on scheduler.
- PostgreSQL advisory and row locks serialize competing scheduler ticks. Unique occurrence/run keys and atomic advancement prevent duplicate database occurrences after dispatcher restarts. External HTTP side effects retain the idempotency limitations documented above.
- After downtime, a one-shot remains due and executes when the worker returns. Repeating schedules coalesce missed slots into the latest due slot; older slots are counted as skipped. If that schedule's previous run is still open or the worker observes 10 open runs, the repeating slot is skipped. One-shots wait for capacity.
- **Duraklat** prevents future dispatch. **Devam et** skips past repeating slots and resumes at the next future slot; an overdue paused one-shot remains due. **Zamanlamayı iptal et** permanently disables future dispatch. These actions do not cancel an already queued/running workflow: cancel that run separately in the execution panel.
- A one-shot is marked **Tetiklendi** when its run is queued; this is separate from its run's completion status. Each schedule shows its pinned version, next/held time, trigger count, skipped count, latest run status and up to 50 recent occurrences. Open an occurrence to inspect the immutable run and reports.
- At most 100 active/paused schedules are allowed in the local workspace. Schedule creation requires the same source checks and an idempotency key as manual execution.

With the stack running, verify real timed execution, controls, reports and competing PostgreSQL ticks:

```sh
python scripts/schedule_smoke.py
```

For restart acceptance, run `python scripts/schedule_smoke.py --prepare-restart`, stop/restart the local stack, then run `python scripts/schedule_smoke.py --verify-restart`. The script creates demo schedules and stores its restart reference only under ignored `.runtime/`.

## Controls

| Action | Control |
| --- | --- |
| Add node | Click a library item |
| Connect | Drag handles, or use the connection-dialog toolbar button |
| Configure | Select a node |
| Move | Drag the node |
| Pan / zoom | Canvas drag and mouse wheel / controls |
| Undo / redo | Ctrl+Z / Ctrl+Shift+Z |
| Duplicate | Ctrl+D |
| Delete selected node or edge | Delete / Backspace |
| Fit graph | Fit toolbar button |
| Export / import graph | Footer JSON controls |

Keyboard edit shortcuts are disabled in form fields and dialogs. Apply edited JSON explicitly before running. Historical runs open as read-only snapshots; return to the draft to edit, or restore a version as a new draft state.

## API

Open `/docs` for the interactive API. Key endpoints:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/health/live`, `/api/health/ready` | API liveness and stack readiness |
| GET | `/api/node-types`, `/api/templates` | Shared node schemas and examples |
| GET / POST | `/api/workflows` | List / create drafts |
| GET / PATCH | `/api/workflows/{id}` | Read / optimistic update |
| GET / POST | `/api/workflows/{id}/versions` | Immutable versions |
| POST | `/api/workflows/validate` | Validate a graph |
| POST | `/api/workflows/{id}/runs` | Start a saved version |
| GET / POST | `/api/workflows/{id}/schedules` | List / create version-pinned schedules |
| POST | `/api/schedules/{id}/{pause,resume,cancel}` | Control future dispatch |
| GET | `/api/schedules/{id}/runs` | Recent scheduled occurrences and run states |
| GET | `/api/runs`, `/api/runs/{id}` | History / snapshot |
| POST | `/api/runs/{id}/cancel` | Request cancellation |
| GET | `/api/runs/{id}/events`, `/attempts` | Event replay / attempts |
| WS | `/api/runs/{id}/stream` | Cursor-based live events |
| GET | `/api/runs/{id}/nodes/{node}/output` | Bounded output preview |
| GET | `/api/artifacts/{id}/download` | Download reports |

Writes require `X-Flowforge-Client: studio`. Run creation also requires `Idempotency-Key`. Same-key/same-request returns the same run; different payload reuse returns 409. Cross-origin writes and WebSocket connections are rejected.

## Development and checks

```sh
python -m venv .venv
python -m pip install -r requirements.txt
python -m pytest backend/tests -q
cd frontend
npm ci
npm test
npm run build
```

Run the native launcher with `python run.py` or use Compose. For hot reload, run `npm run dev` in `frontend`; its `/api` proxy expects an API on 9030. Set `DATABASE_URL`, `TEMPORAL_ADDRESS` and optionally `FLOWFORGE_DATA` for separate API/worker processes.

Automated checks cover backend/domain behavior, HTTP transport, schedule timing and lifecycle, activity persistence, and frontend graph/history/schedule behavior. Real-stack checks exercise four templates, real GET/POST calls, scheduled triggers, competing PostgreSQL ticks, full stack restart and artifact downloads. See [VERIFICATION.md](VERIFICATION.md) for recorded results.

`scripts/smoke.py`, `scripts/resilience.py` and `scripts/error_smoke.py` exercise a running local stack on 9030. They create clearly named test workflows and runs, so use a development data directory.

## Repository layout

```text
backend/app/domain.py       Node schemas and graph validation
backend/app/operations.py   Pure transforms and report rendering
backend/app/store.py        Application persistence and ordered events
backend/app/workflow.py     Deterministic Temporal orchestration
backend/app/activities.py   Database/file/data Activities
backend/app/worker.py       Worker and outbox dispatcher
backend/app/api.py          HTTP/WebSocket API and static frontend
backend/migrations/        Alembic schema history
backend/tests/             Domain, persistence, API and Activity tests
frontend/src/              Typed React editor and tests
frontend/dist/             Included production frontend
examples/                  Exportable example workflow documents
shared/schemas/            Exported graph and node contracts
run.py                     Native stack supervisor
```

## Limits and honest boundaries

- This is a **single-user local workspace**, not a public multi-tenant service. HTTP access implies access to that workspace. Bind to loopback; add authentication and workspace authorization before public hosting.
- Temporal's persistent **development server** is used locally and in the sample Compose stack. Production deployment needs a separately operated Temporal service and operational hardening.
- 100 nodes / 200 edges per graph, one input, ten open runs, four parallel ready nodes per run, a 1 MB graph limit and a 10 MB node-output limit.
- A run fails rather than pretending a permanent invalid-data error succeeded. Failed and skipped nodes have distinct states.
- Output previews are bounded; report downloads contain full results. HTML is escaped and CSV formula-like strings are neutralized.
- Cancellation is cooperative. Already committed output files or completed operations are not magically rolled back. Only completed report records are offered for download.
- Mobile layouts are available, but dense graph editing is primarily a desktop experience. Direct touch dragging has not been exhaustively device-tested.
- Schedules dispatch only after explicit creation. HTTP calls occur only in a graph's configured HTTP block. The application does not publish to GitHub or send external messages on its own.

## References

The implementation uses original interface/model code and third-party libraries under their own licenses. Google Fonts is optional; system fonts are the fallback. React Flow attribution is retained.

- [React Flow custom nodes](https://reactflow.dev/learn/customization/custom-nodes)
- [Temporal Python SDK](https://docs.temporal.io/develop/python)
- [Temporal CLI / persistent development server](https://docs.temporal.io/cli/setup-cli)
- [Temporal retry and idempotency guidance](https://github.com/temporalio/documentation/blob/main/docs/develop/python/best-practices/error-handling.mdx)
