import sys, time, uuid
from pathlib import Path
import httpx

ROOT = Path(__file__).absolute().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.templates import node, edge

c = httpx.Client(
    base_url="http://127.0.0.1:9030",
    trust_env=False,
    timeout=10,
    headers={"X-Flowforge-Client": "studio"},
)
graph = {
    "schemaVersion": 1,
    "name": "Kalıcı hata kontrolü",
    "nodes": [
        node(
            "input",
            "manual_input",
            "Girdi",
            0,
            0,
            records=[
                {"category": "A", "amount": 1e308},
                {"category": "A", "amount": 1e308},
            ],
        ),
        node("sum", "aggregate", "Taşan toplam", 300, 0),
        node("report", "report", "Rapor", 600, 0),
    ],
    "edges": [edge("input", "sum"), edge("sum", "report")],
}
f = c.post("/api/workflows", json=graph)
f.raise_for_status()
f = f.json()
r = c.post(
    "/api/workflows/" + f["id"] + "/runs",
    json={"revision": 1},
    headers={"Idempotency-Key": uuid.uuid4().hex},
)
r.raise_for_status()
rid = r.json()["id"]
for _ in range(100):
    r = c.get("/api/runs/" + rid).json()
    if r["status"] in ["succeeded", "failed", "cancelled"]:
        break
    time.sleep(0.2)
assert r["status"] == "failed", r
assert next(n for n in r["nodes"] if n["id"] == "sum")["status"] == "failed"
assert next(n for n in r["nodes"] if n["id"] == "report")["status"] == "blocked"
attempts = c.get("/api/runs/" + rid + "/attempts").json()
assert len([a for a in attempts if a["nodeId"] == "sum"]) == 1
print("Permanent error passed: failed node, blocked report, no pointless retries.")
