from __future__ import annotations
import asyncio
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from .activities import load_spec, execute_node, node_state, finish_run

POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3
)


@workflow.defn
class GraphWorkflow:
    @workflow.run
    async def run(self, run_id: str):
        async def call(fn, arg):
            return await workflow.execute_activity(
                fn,
                arg,
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=POLICY,
            )

        async def state(node, status, error=None):
            await call(
                node_state,
                {"runId": run_id, "nodeId": node, "status": status, "error": error},
            )

        try:
            spec = await call(load_spec, run_id)
            nodes = {n["id"]: n for n in spec["nodes"]}
            pending = set(nodes)
            results = {}
            edges = spec["edges"]

            async def perform(n, parents):
                if n["type"] == "delay":
                    await state(n["id"], "running")
                    await workflow.sleep(n["seconds"])
                return await call(
                    execute_node,
                    {"runId": run_id, "nodeId": n["id"], "parents": parents},
                )

            while pending:
                ready = []
                for node_id, n in nodes.items():
                    if node_id not in pending:
                        continue
                    incoming = [e for e in edges if e["target"] == node_id]
                    if not all(e["source"] in results for e in incoming):
                        continue
                    active = [
                        e
                        for e in incoming
                        if results[e["source"]]["status"] == "succeeded"
                        and (
                            nodes[e["source"]]["type"] != "condition"
                            or results[e["source"]]["port"] == e["sourceHandle"]
                        )
                    ]
                    if incoming and not active:
                        await state(node_id, "skipped")
                        results[node_id] = {"status": "skipped"}
                        pending.remove(node_id)
                        continue
                    ready.append((n, [e["source"] for e in active]))
                    if len(ready) == 4:
                        break
                if not ready:
                    if not pending:
                        break
                    # A skipped dependency can unlock nodes later in the ordered graph.
                    continue
                outputs = await asyncio.gather(
                    *(perform(n, parents) for n, parents in ready),
                    return_exceptions=True,
                )
                failure = None
                for (n, _), out in zip(ready, outputs):
                    pending.remove(n["id"])
                    if isinstance(out, BaseException):
                        if isinstance(out, asyncio.CancelledError):
                            raise out
                        message = str(out.__cause__ or out)[:500]
                        await state(n["id"], "failed", message)
                        results[n["id"]] = {"status": "failed"}
                        failure = message
                    else:
                        results[n["id"]] = {**out, "status": "succeeded"}
                if failure:
                    await call(
                        finish_run,
                        {"runId": run_id, "status": "failed", "error": failure},
                    )
                    return "failed"
            await call(finish_run, {"runId": run_id, "status": "succeeded"})
            return "succeeded"
        except asyncio.CancelledError:
            await call(finish_run, {"runId": run_id, "status": "cancelled"})
            return "cancelled"
        except Exception as exc:
            await call(
                finish_run,
                {
                    "runId": run_id,
                    "status": "failed",
                    "error": str(exc.__cause__ or exc)[:500],
                },
            )
            return "failed"
