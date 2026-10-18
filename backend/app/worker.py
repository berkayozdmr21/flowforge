from __future__ import annotations
import asyncio, os, logging
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from .store import db, Outbox, Run, emit, TERMINAL
from .workflow import GraphWorkflow
from .activities import load_spec, execute_node, node_state, finish_run
from .scheduler import tick

TASK_QUEUE = "flowforge-v1"


async def connect():
    return await Client.connect(os.getenv("TEMPORAL_ADDRESS", "127.0.0.1:7239"))


async def dispatch(client):
    while True:
        try:
            await asyncio.to_thread(tick)
            with db() as s:
                pending = [
                    r.run_id
                    for r in s.execute(select(Outbox).where(Outbox.sent == 0)).scalars()
                ]
            for run_id in pending:
                try:
                    try:
                        await client.start_workflow(
                            GraphWorkflow.run,
                            run_id,
                            id="flowforge-" + run_id,
                            task_queue=TASK_QUEUE,
                            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                        )
                    except WorkflowAlreadyStartedError:
                        pass
                    with db() as s:
                        s.get(Outbox, run_id).sent = 1
                        s.get(Outbox, run_id).error = None
                except Exception as e:
                    with db() as s:
                        o = s.get(Outbox, run_id)
                        o.attempts += 1
                        o.error = str(e)[:300]
            with db() as s:
                cancels = [
                    r.id
                    for r in s.execute(
                        select(Run).where(
                            Run.cancel_requested == 1, Run.status.notin_(list(TERMINAL))
                        )
                    ).scalars()
                ]
            for rid in cancels:
                try:
                    await client.get_workflow_handle("flowforge-" + rid).cancel()
                except Exception:
                    pass
        except Exception:
            logging.exception("Dispatcher failed; retrying.")
        await asyncio.sleep(1)


async def main():
    client = await connect()
    with ThreadPoolExecutor(max_workers=8) as pool:
        worker = Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[GraphWorkflow],
            activities=[load_spec, execute_node, node_state, finish_run],
            activity_executor=pool,
            max_concurrent_activities=8,
        )
        async with worker:
            await dispatch(client)


if __name__ == "__main__":
    asyncio.run(main())
