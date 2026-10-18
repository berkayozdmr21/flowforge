import uuid
from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy import select, update, func
from backend.app.store import db, Schedule, ScheduleRun, Run, Outbox, Version, unpack
from backend.app.scheduler import tick
from backend.app.templates import templates

HEAD = {"X-Flowforge-Client": "studio"}


@pytest.fixture
def scheduled(client):
    with db() as s:
        s.execute(update(Schedule).values(status="cancelled"))
        s.execute(update(Run).values(status="succeeded"))
    flow = client.post(
        "/api/workflows", json=templates()[0]["graph"], headers=HEAD
    ).json()
    return flow


def make(client, flow, mode="once", start=None, key=None, **kwargs):
    return client.post(
        f'/api/workflows/{flow["id"]}/schedules',
        json={
            "revision": flow["revision"],
            "name": "Scheduled test",
            "mode": mode,
            "startAt": start
            or (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(),
            **kwargs,
        },
        headers={**HEAD, "Idempotency-Key": key or uuid.uuid4().hex},
    )


def due(item):
    return item["nextRun"]


def test_once_enqueues_atomically_and_only_once(client, scheduled):
    response = make(client, scheduled)
    assert response.status_code == 201
    item = response.json()
    assert tick(due(item) - 1) == 0
    assert tick(due(item)) == 1
    assert tick(due(item) + 1) == 0
    saved = client.get(f'/api/workflows/{scheduled["id"]}/schedules').json()[0]
    assert (
        saved["status"] == "completed"
        and saved["nextRun"] is None
        and saved["fired"] == 1
    )
    runs = client.get(f'/api/schedules/{item["id"]}/runs').json()
    assert len(runs) == 1 and runs[0]["scheduledFor"] == due(item)
    with db() as s:
        run = s.get(Run, runs[0]["id"])
        assert s.get(Outbox, run.id).sent == 0
        assert run.version_id == item["versionId"]


@pytest.mark.parametrize("mode,period", [("hourly", 3600), ("daily", 86400)])
def test_recurring_coalesces_missed_and_skips_overlap(client, scheduled, mode, period):
    item = make(client, scheduled, mode).json()
    assert tick(due(item) + 2 * period + 1) == 1
    with db() as s:
        stored = s.get(Schedule, item["id"])
        assert stored.skipped == 2 and stored.next_run == due(item) + 3 * period
        assert stored.fired == 1
    assert tick(due(item) + 3 * period) == 0  # Previous run is still queued.
    with db() as s:
        stored = s.get(Schedule, item["id"])
        assert stored.skipped == 3
        s.get(Run, stored.last_run_id).status = "succeeded"
    assert tick(due(item) + 4 * period) == 1
    assert len(client.get(f'/api/schedules/{item["id"]}/runs').json()) == 2


def test_paused_and_cancelled_schedules_never_fire(client, scheduled):
    item = make(client, scheduled).json()
    assert (
        client.post(f'/api/schedules/{item["id"]}/pause', headers=HEAD).json()["status"]
        == "paused"
    )
    assert tick(due(item) + 1) == 0
    assert (
        client.post(f'/api/schedules/{item["id"]}/resume', headers=HEAD).json()[
            "status"
        ]
        == "active"
    )
    assert (
        client.post(f'/api/schedules/{item["id"]}/cancel', headers=HEAD).json()[
            "status"
        ]
        == "cancelled"
    )
    assert tick(due(item) + 1) == 0
    assert (
        client.post(f'/api/schedules/{item["id"]}/resume', headers=HEAD).status_code
        == 409
    )
    assert (
        client.post(f'/api/schedules/{item["id"]}/cancel', headers=HEAD).status_code
        == 200
    )


def test_pause_does_not_cancel_existing_run(client, scheduled):
    item = make(client, scheduled, "hourly").json()
    tick(due(item))
    client.post(f'/api/schedules/{item["id"]}/pause', headers=HEAD)
    with db() as s:
        run = s.get(Run, s.get(Schedule, item["id"]).last_run_id)
        assert run.status == "queued" and not run.cancel_requested


def test_resume_skips_paused_repeats(client, scheduled, monkeypatch):
    item = make(client, scheduled, "hourly").json()
    client.post(f'/api/schedules/{item["id"]}/pause', headers=HEAD)
    from backend.app import api

    monkeypatch.setattr(api.time, "time", lambda: due(item) + 7201)
    resumed = client.post(f'/api/schedules/{item["id"]}/resume', headers=HEAD).json()
    assert resumed["nextRun"] == due(item) + 10800 and resumed["skipped"] == 3


def test_pins_immutable_version_despite_draft_changes(client, scheduled):
    item = make(client, scheduled).json()
    graph = scheduled["graph"]
    graph["name"] = "Changed draft"
    graph["nodes"][0]["config"]["records"] = [{"changed": True}]
    assert (
        client.patch(
            f'/api/workflows/{scheduled["id"]}',
            json={"revision": 1, "graph": graph},
            headers=HEAD,
        ).status_code
        == 200
    )
    tick(due(item))
    with db() as s:
        stored = s.get(Schedule, item["id"])
        frozen = unpack(s.get(Version, stored.version_id).graph)
        assert frozen["name"] != "Changed draft"
        assert s.get(Run, stored.last_run_id).version_id == stored.version_id


def test_idempotency_survives_expired_start_time(client, scheduled, monkeypatch):
    key = uuid.uuid4().hex
    start = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
    item = make(client, scheduled, start=start, key=key).json()
    from backend.app import api

    monkeypatch.setattr(api.time, "time", lambda: due(item) + 5)
    assert make(client, scheduled, start=start, key=key).json()["id"] == item["id"]
    assert (
        make(client, scheduled, start=start, key=key, name="Other").status_code == 409
    )


@pytest.mark.parametrize(
    "start",
    [
        "2020-01-01T10:00:00Z",
        "2028-01-01T10:00:00",
        "not-a-date",
        "2100-01-01T10:00:00Z",
    ],
)
def test_invalid_start_rejected(client, scheduled, start):
    assert make(client, scheduled, start=start).status_code == 422


def test_timezone_offset_normalized(client, scheduled):
    date = datetime.now(timezone(timedelta(hours=3))) + timedelta(hours=1)
    item = make(client, scheduled, start=date.isoformat()).json()
    assert abs(item["nextRun"] - date.timestamp()) < 0.001


def test_stale_revision_and_invalid_graph_rejected(client, scheduled):
    assert make(client, scheduled, revision=2).status_code == 409
    graph = scheduled["graph"]
    graph["edges"] = []
    client.patch(
        f'/api/workflows/{scheduled["id"]}',
        json={"revision": 1, "graph": graph},
        headers=HEAD,
    )
    assert make(client, {**scheduled, "revision": 2}).status_code == 422


def test_creation_and_actions_require_write_header(client, scheduled):
    assert (
        client.post(f'/api/workflows/{scheduled["id"]}/schedules', json={}).status_code
        == 403
    )
    item = make(client, scheduled).json()
    assert client.post(f'/api/schedules/{item["id"]}/pause').status_code == 403
    assert (
        client.post(f'/api/schedules/{item["id"]}/delete', headers=HEAD).status_code
        == 422
    )


def test_one_shot_waits_for_capacity(client, scheduled):
    item = make(client, scheduled).json()
    # Existing API runs participate in the same dispatch capacity check.
    for _ in range(10):
        response = client.post(
            f'/api/workflows/{scheduled["id"]}/runs',
            json={"revision": 1},
            headers={**HEAD, "Idempotency-Key": uuid.uuid4().hex},
        )
        assert response.status_code == 202
    assert tick(due(item)) == 0
    with db() as s:
        s.execute(update(Run).values(status="succeeded"))
    assert tick(due(item) + 5) == 1


def test_schedule_tick_rolls_back_on_failure(client, scheduled, monkeypatch):
    item = make(client, scheduled).json()
    import backend.app.scheduler as scheduler

    original = scheduler.emit
    monkeypatch.setattr(
        scheduler, "emit", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("disk"))
    )
    with pytest.raises(RuntimeError):
        tick(due(item))
    with db() as s:
        stored = s.get(Schedule, item["id"])
        assert stored.fired == 0 and stored.status == "active"
        assert (
            s.scalar(
                select(func.count())
                .select_from(ScheduleRun)
                .where(ScheduleRun.schedule_id == item["id"])
            )
            == 0
        )
    monkeypatch.setattr(scheduler, "emit", original)
    assert tick(due(item)) == 1


def test_missing_schedule_and_workflow(client):
    assert client.get("/api/workflows/missing/schedules").status_code == 404
    assert client.get("/api/schedules/missing/runs").status_code == 404
    assert client.post("/api/schedules/missing/pause", headers=HEAD).status_code == 404
