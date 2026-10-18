"""Real PostgreSQL + Temporal schedule acceptance. Requires the local stack.

Optional restart check: run --prepare-restart, stop/restart the stack, then
run --verify-restart. The prepared schedule uses an immutable demo graph.
"""

import json
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import httpx

ROOT = Path(__file__).absolute().parents[1]
sys.path.insert(0, str(ROOT))
STATE = ROOT / ".runtime/schedule-smoke.json"


def check(response):
    response.raise_for_status()
    return response.json()


def create(client, flow, mode="once", delay=3):
    return check(
        client.post(
            f'/api/workflows/{flow["id"]}/schedules',
            json={
                "revision": flow["revision"],
                "name": "Schedule acceptance " + mode,
                "mode": mode,
                "startAt": (
                    datetime.now(timezone.utc) + timedelta(seconds=delay)
                ).isoformat(),
            },
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
    )


def verify(client, item):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        rows = check(client.get(f'/api/schedules/{item["id"]}/runs'))
        if rows and rows[0]["status"] in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.25)
    assert len(rows) == 1 and rows[0]["status"] == "succeeded", rows
    run = check(client.get(f'/api/runs/{rows[0]["id"]}'))
    assert run["versionId"] == item["versionId"] and len(run["artifacts"]) == 3
    for artifact in run["artifacts"]:
        response = client.get(artifact["url"])
        response.raise_for_status()
        assert len(response.content) == artifact["size"]
    print(
        json.dumps(
            {
                "scheduleId": item["id"],
                "runId": run["id"],
                "status": run["status"],
                "reports": 3,
            }
        ),
        flush=True,
    )


def main():
    with httpx.Client(
        base_url="http://127.0.0.1:9030",
        trust_env=False,
        timeout=10,
        headers={"X-Flowforge-Client": "studio"},
    ) as client:
        check(client.get("/api/health/ready"))
        if "--verify-restart" in sys.argv:
            verify(client, json.loads(STATE.read_text()))
            print("Persistent schedule survived stack restart.", flush=True)
            return
        graph = check(client.get("/api/templates"))[0]["graph"]
        graph["name"] = "Schedule acceptance"
        flow = check(client.post("/api/workflows", json=graph))
        if "--prepare-restart" in sys.argv:
            item = create(client, flow, delay=15)
            STATE.write_text(json.dumps(item), encoding="utf-8")
            print("Restart acceptance schedule prepared: " + item["id"], flush=True)
            return
        once = create(client, flow)
        paused = create(client, flow, "hourly")
        cancelled = create(client, flow, "daily")
        check(client.post(f'/api/schedules/{paused["id"]}/pause'))
        check(client.post(f'/api/schedules/{cancelled["id"]}/cancel'))
        verify(client, once)
        assert check(client.get(f'/api/schedules/{paused["id"]}/runs')) == []
        assert check(client.get(f'/api/schedules/{cancelled["id"]}/runs')) == []
        resumed = check(client.post(f'/api/schedules/{paused["id"]}/resume'))
        assert resumed["nextRun"] > time.time() and resumed["skipped"] >= 1
        check(client.post(f'/api/schedules/{paused["id"]}/cancel'))
        print(
            "One-shot trigger, pause/resume, cancellation and report downloads passed.",
            flush=True,
        )
        # A controlled clock probes competing scheduler ticks against real PostgreSQL.
        concurrent = create(client, flow, delay=120)
        from backend.app.scheduler import tick

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: tick(concurrent["nextRun"]), range(4)))
        assert sum(results) == 1, results
        verify(client, concurrent)
        print(
            "Concurrent PostgreSQL scheduler ticks created exactly one occurrence.",
            flush=True,
        )


if __name__ == "__main__":
    main()
