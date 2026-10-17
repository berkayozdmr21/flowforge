"""Real Temporal checks; requires the running local stack."""

import time, uuid, json, sys
from pathlib import Path
import httpx

ROOT = Path(__file__).absolute().parents[1]
c = httpx.Client(
    base_url="http://127.0.0.1:9030",
    trust_env=False,
    timeout=10,
    headers={"X-Flowforge-Client": "studio"},
)


def delayed(seconds):
    defs = {d["type"]: d["defaults"] for d in c.get("/api/node-types").json()}

    def node(id, kind, x):
        return dict(
            id=id,
            type=kind,
            typeVersion=1,
            label=id,
            position={"x": x, "y": 100},
            config=defs[kind],
        )

    nodes = [
        node("input", "manual_input", 0),
        node("wait", "delay", 300),
        node("report", "report", 600),
    ]
    nodes[0]["config"]["records"] = [{"value": "persistent"}]
    nodes[1]["config"]["seconds"] = seconds
    graph = {
        "schemaVersion": 1,
        "name": "Dayanıklılık kontrolü",
        "nodes": nodes,
        "edges": [
            dict(id=a + b, source=a, target=b, sourceHandle="out", targetHandle="in")
            for a, b in [("input", "wait"), ("wait", "report")]
        ],
    }
    f = c.post("/api/workflows", json=graph)
    f.raise_for_status()
    f = f.json()
    r = c.post(
        "/api/workflows/" + f["id"] + "/runs",
        json={"revision": f["revision"]},
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    r.raise_for_status()
    rid = r.json()["id"]
    for _ in range(60):
        value = c.get("/api/runs/" + rid).json()
        if any(n["id"] == "wait" and n["status"] == "running" for n in value["nodes"]):
            return rid
        time.sleep(0.2)
    raise RuntimeError("Delay did not start")


def poll(rid):
    for _ in range(160):
        r = c.get("/api/runs/" + rid).json()
        if r["status"] in ["succeeded", "failed", "cancelled"]:
            return r
        time.sleep(0.25)
    raise RuntimeError("Run did not finish")


mode = sys.argv[1]
if mode == "start":
    rid = delayed(15)
    (ROOT / ".runtime/resilience.json").write_text(json.dumps({"id": rid}))
    print("Persistent timer running:", rid, flush=True)
elif mode == "verify":
    rid = json.loads((ROOT / ".runtime/resilience.json").read_text())["id"]
    r = poll(rid)
    assert r["status"] == "succeeded", r
    events = c.get("/api/runs/" + rid + "/events").json()
    assert (
        sum(e["kind"] == "node.started" and e["nodeId"] == "input" for e in events) == 1
    )
    print(
        "Worker restart passed: same run resumed; completed input was not rerun.",
        flush=True,
    )
elif mode == "cancel":
    rid = delayed(60)
    r = c.post("/api/runs/" + rid + "/cancel", json={})
    r.raise_for_status()
    result = poll(rid)
    assert result["status"] == "cancelled", result
    assert not result["artifacts"]
    print("Durable timer cancellation passed; no report produced.", flush=True)
