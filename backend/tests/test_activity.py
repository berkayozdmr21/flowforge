import uuid
from types import SimpleNamespace
import pytest
from backend.app import activities
from backend.app.store import db, NodeRun, Attempt, Event
from backend.app.templates import templates
from sqlalchemy import select

HEAD = {"X-Flowforge-Client": "studio"}


def test_transient_activity_retry_preserves_attempts(client, monkeypatch):
    f = client.post("/api/workflows", json=templates()[0]["graph"], headers=HEAD).json()
    r = client.post(
        "/api/workflows/" + f["id"] + "/runs",
        json={"revision": 1},
        headers={**HEAD, "Idempotency-Key": uuid.uuid4().hex},
    ).json()
    rid = r["id"]
    original = activities.process
    monkeypatch.setattr(activities.activity, "info", lambda: SimpleNamespace(attempt=1))

    def fail_once(*args, **kwargs):
        raise OSError("temporary disk interruption")

    monkeypatch.setattr(activities, "process", fail_once)
    with pytest.raises(OSError):
        activities.execute_node({"runId": rid, "nodeId": "source", "parents": []})
    with db() as s:
        n = s.execute(
            select(NodeRun).where(NodeRun.run_id == rid, NodeRun.node_id == "source")
        ).scalar_one()
        assert n.status == "retry_wait"
    monkeypatch.setattr(activities.activity, "info", lambda: SimpleNamespace(attempt=2))
    monkeypatch.setattr(activities, "process", original)
    out = activities.execute_node({"runId": rid, "nodeId": "source", "parents": []})
    assert out["count"] == 7
    with db() as s:
        a = (
            s.execute(
                select(Attempt).where(Attempt.run_id == rid).order_by(Attempt.number)
            )
            .scalars()
            .all()
        )
        assert [(x.number, x.status) for x in a] == [(1, "failed"), (2, "succeeded")]
        assert s.execute(
            select(Event).where(Event.run_id == rid, Event.kind == "node.retrying")
        ).scalar_one()
