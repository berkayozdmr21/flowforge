import time, json, uuid, sys
import httpx

client = httpx.Client(
    base_url="http://127.0.0.1:9030",
    trust_env=False,
    timeout=10,
    headers={"X-Flowforge-Client": "studio"},
)
ready = client.get("/api/health/ready")
print("Readiness:", ready.status_code, ready.text, flush=True)
templates = client.get("/api/templates").json()
for t in templates:
    f = client.post("/api/workflows", json=t["graph"])
    f.raise_for_status()
    f = f.json()
    r = client.post(
        "/api/workflows/" + f["id"] + "/runs",
        json={"revision": f["revision"]},
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    r.raise_for_status()
    r = r.json()
    start = time.monotonic()
    while time.monotonic() - start < 45:
        r = client.get("/api/runs/" + r["id"]).json()
        if r["status"] in ["succeeded", "failed", "cancelled"]:
            break
        time.sleep(0.25)
    print(
        t["id"],
        r["status"],
        [(n["id"], n["status"], n.get("error")) for n in r["nodes"]],
        flush=True,
    )
    if r["status"] != "succeeded":
        print(r, flush=True)
        sys.exit(1)
    assert len(r["artifacts"]) == 3
    for a in r["artifacts"]:
        result = client.get(a["url"])
        result.raise_for_status()
        assert len(result.content) == a["size"]
    events = client.get("/api/runs/" + r["id"] + "/events").json()
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    print("  Reports verified; events:", len(events), flush=True)
print("All three real PostgreSQL + Temporal flows passed.", flush=True)
