import uuid, copy
from backend.app.templates import templates

HEAD = {"X-Flowforge-Client": "studio"}


def create(c):
    r = c.post("/api/workflows", json=templates()[0]["graph"], headers=HEAD)
    assert r.status_code == 201
    return r.json()


def start(c, f, key=None):
    return c.post(
        "/api/workflows/" + f["id"] + "/runs",
        json={"revision": f["revision"]},
        headers={**HEAD, "Idempotency-Key": key or uuid.uuid4().hex},
    )


def test_health(client):
    assert client.get("/api/health/live").json()["status"] == "ok"


def test_untrusted_host_rejected(client):
    assert client.get('/api/health/live',headers={'Host':'rebind.example'}).status_code==400


def test_registry(client):
    assert len(client.get("/api/node-types").json()) == 8


def test_all_templates_validate(client):
    for t in client.get("/api/templates").json():
        assert (
            client.post(
                "/api/workflows/validate", json=t["graph"], headers=HEAD
            ).status_code
            == 200
        )


def test_header_required(client):
    assert (
        client.post("/api/workflows", json=templates()[0]["graph"]).status_code == 403
    )


def test_cross_origin(client):
    assert (
        client.post(
            "/api/workflows",
            json=templates()[0]["graph"],
            headers={**HEAD, "Origin": "https://outside.example"},
        ).status_code
        == 403
    )


def test_flow_roundtrip(client):
    f = create(client)
    assert client.get("/api/workflows/" + f["id"]).json()["graph"] == f["graph"]


def test_optimistic_revision(client):
    f = create(client)
    body = {"revision": f["revision"], "graph": f["graph"]}
    url = "/api/workflows/" + f["id"]
    assert client.patch(url, json=body, headers=HEAD).status_code == 200
    assert client.patch(url, json=body, headers=HEAD).status_code == 409


def test_run_idempotency(client):
    f = create(client)
    key = uuid.uuid4().hex
    a = start(client, f, key)
    b = start(client, f, key)
    assert a.status_code == 202
    assert a.json()["id"] == b.json()["id"]


def test_idempotency_conflict(client):
    f = create(client)
    key = uuid.uuid4().hex
    start(client, f, key)
    r = client.post(
        "/api/workflows/" + f["id"] + "/runs",
        json={"revision": 2},
        headers={**HEAD, "Idempotency-Key": key},
    )
    assert r.status_code == 409


def test_stale_revision_cannot_run(client):
    f = create(client)
    r = client.post(
        "/api/workflows/" + f["id"] + "/runs",
        json={"revision": 99},
        headers={**HEAD, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert r.status_code == 409


def test_version_immutable(client):
    f = create(client)
    v = client.post("/api/workflows/" + f["id"] + "/versions", headers=HEAD).json()
    g = copy.deepcopy(f["graph"])
    g["name"] = "Changed"
    client.patch(
        "/api/workflows/" + f["id"], json={"revision": 1, "graph": g}, headers=HEAD
    )
    version = client.get("/api/workflows/" + f["id"] + "/versions").json()[0]
    assert version["id"] == v["id"]
    assert version["graph"]["name"] != g["name"]


def test_cancel_persists_request(client):
    f = create(client)
    r = start(client, f).json()
    assert (
        client.post("/api/runs/" + r["id"] + "/cancel", headers=HEAD).json()["status"]
        == "cancelling"
    )
    assert client.get("/api/runs/" + r["id"]).json()["status"] == "cancelling"


def test_event_sequence(client):
    f = create(client)
    r = start(client, f).json()
    client.post("/api/runs/" + r["id"] + "/cancel", headers=HEAD)
    e = client.get("/api/runs/" + r["id"] + "/events").json()
    assert [x["sequence"] for x in e] == [1, 2]
    assert (
        client.get("/api/runs/" + r["id"] + "/events?after_sequence=1").json() == e[1:]
    )


def test_invalid_graph_cannot_start(client):
    f = create(client)
    g = f["graph"]
    g["edges"] = []
    client.patch(
        "/api/workflows/" + f["id"], json={"revision": 1, "graph": g}, headers=HEAD
    )
    r = start(client, {**f, "revision": 2})
    assert r.status_code == 422


def test_missing_resources(client):
    for path in [
        "/api/workflows/missing",
        "/api/runs/missing",
        "/api/artifacts/missing/download",
    ]:
        assert client.get(path).status_code == 404


def test_missing_idempotency(client):
    f = create(client)
    assert (
        client.post(
            "/api/workflows/" + f["id"] + "/runs", json={"revision": 1}, headers=HEAD
        ).status_code
        == 422
    )


def test_websocket_replays_after_cursor(client):
    from backend.app.store import db, Run, emit

    f = create(client)
    r = start(client, f).json()
    with db() as s:
        row = s.get(Run, r["id"])
        row.status = "succeeded"
        emit(s, row.id, "run.completed", payload={"status": "succeeded"})
    with client.websocket_connect(
        "/api/runs/" + r["id"] + "/stream?after_sequence=1"
    ) as ws:
        event = ws.receive_json()
        assert event["sequence"] == 2
        assert event["kind"] == "run.completed"
        assert ws.receive_json()["kind"] == "stream.complete"


def test_websocket_rejects_cross_origin(client):
    from starlette.websockets import WebSocketDisconnect
    import pytest

    f = create(client)
    r = start(client, f).json()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/api/runs/" + r["id"] + "/stream",
            headers={"Origin": "https://evil.example"},
        ):
            pass
