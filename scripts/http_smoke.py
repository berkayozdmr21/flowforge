"""Opt-in real network acceptance against JSONPlaceholder's public demo API.

The demo POST endpoint simulates a create operation; no private data is sent.
Run with a local FlowForge stack running: python scripts/http_smoke.py
"""

import json
import time
import uuid
import httpx


def main():
    with httpx.Client(
        base_url="http://127.0.0.1:9030",
        trust_env=False,
        timeout=10,
        headers={"X-Flowforge-Client": "studio"},
    ) as client:
        client.get("/api/health/ready").raise_for_status()
        template = next(
            t for t in client.get("/api/templates").json() if t["id"] == "http-users"
        )
        for method, status in [("GET", 200), ("POST", 201)]:
            graph = json.loads(json.dumps(template["graph"]))
            graph["name"] = f"HTTP {method} acceptance"
            target = next(n for n in graph["nodes"] if n["type"] == "http_request")
            if method == "POST":
                target["config"].update(
                    method="POST",
                    url="https://jsonplaceholder.typicode.com/posts",
                    bodySource="json",
                    body={"title": "FlowForge acceptance", "userId": 1},
                )
                next(n for n in graph["nodes"] if n["type"] == "transform")["config"][
                    "selectFields"
                ] = ["id", "title"]
            response = client.post("/api/workflows", json=graph)
            response.raise_for_status()
            flow = response.json()
            response = client.post(
                f'/api/workflows/{flow["id"]}/runs',
                json={"revision": flow["revision"]},
                headers={"Idempotency-Key": uuid.uuid4().hex},
            )
            response.raise_for_status()
            run = response.json()
            deadline = time.monotonic() + 110
            while time.monotonic() < deadline:
                run = client.get(f'/api/runs/{run["id"]}').json()
                if run["status"] in {"succeeded", "failed", "cancelled"}:
                    break
                time.sleep(0.2)
            assert run["status"] == "succeeded", run.get("error")
            output = client.get(f'/api/runs/{run["id"]}/nodes/http/output')
            output.raise_for_status()
            # The API returns the envelope under output, with bounded record previews.
            payload = output.json()
            envelope = payload.get("output", payload)
            assert envelope["meta"]["http"]["status"] == status, payload
            assert envelope["records"], payload
            assert len(run["artifacts"]) == 3
            for artifact in run["artifacts"]:
                data = client.get(artifact["url"])
                data.raise_for_status()
                assert len(data.content) == artifact["size"]
            print(
                json.dumps(
                    {
                        "method": method,
                        "status": status,
                        "records": envelope["meta"]["count"],
                        "artifacts": len(run["artifacts"]),
                        "runId": run["id"],
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
