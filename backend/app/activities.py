from __future__ import annotations
import time, hashlib, json
from sqlalchemy import select
from temporalio import activity
from temporalio.exceptions import ApplicationError
from .store import (
    db,
    Run,
    NodeRun,
    Version,
    Artifact,
    Attempt,
    DATA,
    emit,
    pack,
    unpack,
    TERMINAL,
)
from .operations import process, report_bytes, atomic_write


def lock_run(s, run_id):
    return s.execute(select(Run).where(Run.id == run_id).with_for_update()).scalar_one()


def output_of(n):
    if not n or not n.output:
        return {"schemaVersion": 1, "records": [], "meta": {"count": 0}}
    value = unpack(n.output)
    return (
        unpack((DATA / "outputs" / value["ref"]).read_text(encoding="utf-8"))
        if "ref" in value
        else value
    )


@activity.defn
def load_spec(run_id: str):
    with db() as s:
        r = lock_run(s, run_id)
        if r.status == "queued":
            r.status = "running"
            emit(s, r.id, "run.started")
        graph = unpack(s.get(Version, r.version_id).graph)
        # Keep record payloads out of Temporal history.
        return {
            "nodes": [
                dict(id=n["id"], type=n["type"], seconds=n["config"].get("seconds", 0))
                for n in graph["nodes"]
            ],
            "edges": graph["edges"],
        }


@activity.defn
def node_state(args: dict):
    with db() as s:
        run = lock_run(s, args["runId"])
        n = s.execute(
            select(NodeRun).where(
                NodeRun.run_id == run.id, NodeRun.node_id == args["nodeId"]
            )
        ).scalar_one()
        if n.status in ["succeeded", "failed", "skipped", "cancelled", "blocked"]:
            return
        n.status = args["status"]
        now = time.time()
        if n.status == "running":
            n.started = n.started or now
        else:
            n.finished = now
        n.error = args.get("error")
        emit(
            s,
            run.id,
            "node." + n.status,
            n.node_id,
            {"error": n.error} if n.error else {},
        )


@activity.defn
def execute_node(args: dict):
    run_id, node_id = args["runId"], args["nodeId"]
    attempt = activity.info().attempt
    try:
        with db() as s:
            run = lock_run(s, run_id)
            if run.cancel_requested or run.status in TERMINAL:
                raise ApplicationError(
                    "Çalıştırma iptal edildi.", non_retryable=True, type="CancelledRun"
                )
            n = s.execute(
                select(NodeRun).where(
                    NodeRun.run_id == run_id, NodeRun.node_id == node_id
                )
            ).scalar_one()
            if n.status == "succeeded":
                value = output_of(n)
                return {
                    "nodeId": node_id,
                    "port": value["meta"].get("decision", "out"),
                    "count": value["meta"]["count"],
                }
            if n.status != "running":
                n.status = "running"
                n.started = n.started or time.time()
                emit(s, run_id, "node.started", node_id, {"attempt": attempt})
            n.attempt = attempt
            record = s.execute(
                select(Attempt).where(
                    Attempt.run_id == run_id,
                    Attempt.node_id == node_id,
                    Attempt.number == attempt,
                )
            ).scalar_one_or_none()
            if not record:
                s.add(
                    Attempt(
                        run_id=run_id, node_id=node_id, number=attempt, status="running"
                    )
                )
            graph = unpack(s.get(Version, run.version_id).graph)
            node = next(x for x in graph["nodes"] if x["id"] == node_id)
            parents = {
                x.node_id: x
                for x in s.execute(
                    select(NodeRun).where(
                        NodeRun.run_id == run_id, NodeRun.node_id.in_(args["parents"])
                    )
                ).scalars()
            }
            inputs = [output_of(parents[key]) for key in args["parents"]]
        envelope, port = process(node["type"], node["config"], inputs)
        raw = pack(envelope).encode("utf-8")
        if len(raw) > 10 * 1024 * 1024:
            raise ValueError("Blok çıktısı 10 MB sınırını aşıyor.")
        output_name = (
            hashlib.sha256((run_id + ":" + node_id).encode()).hexdigest() + ".json"
        )
        atomic_write(DATA / "outputs" / output_name, raw)
        artifacts = []
        if node["type"] == "report":
            for fmt in dict.fromkeys(node["config"]["formats"]):
                aid = hashlib.sha256(
                    (run_id + ":" + node_id + ":" + fmt).encode()
                ).hexdigest()[:32]
                content = report_bytes(envelope, node["config"]["title"], fmt)
                path = aid + "." + fmt
                atomic_write(DATA / "artifacts" / path, content)
                artifacts.append(
                    dict(
                        id=aid,
                        run_id=run_id,
                        node_id=node_id,
                        format=fmt,
                        title=node["config"]["title"],
                        size=len(content),
                        digest=hashlib.sha256(content).hexdigest(),
                        path=path,
                    )
                )
        with db() as s:
            run = lock_run(s, run_id)
            n = s.execute(
                select(NodeRun).where(
                    NodeRun.run_id == run_id, NodeRun.node_id == node_id
                )
            ).scalar_one()
            if run.cancel_requested:
                raise ApplicationError(
                    "Çalıştırma iptal edildi.", non_retryable=True, type="CancelledRun"
                )
            n.status = "succeeded"
            n.output = pack({"ref": output_name, "count": len(envelope["records"])})
            n.finished = time.time()
            n.error = None
            for artifact in artifacts:
                s.merge(Artifact(**artifact))
            a = s.execute(
                select(Attempt).where(
                    Attempt.run_id == run_id,
                    Attempt.node_id == node_id,
                    Attempt.number == attempt,
                )
            ).scalar_one()
            a.status = "succeeded"
            a.finished = time.time()
            emit(
                s,
                run_id,
                "node.succeeded",
                node_id,
                {"count": len(envelope["records"]), "attempt": attempt, "port": port},
            )
        return {"nodeId": node_id, "port": port, "count": len(envelope["records"])}
    except Exception as exc:
        message = str(exc)[:500]
        with db() as s:
            run = lock_run(s, run_id)
            a = s.execute(
                select(Attempt).where(
                    Attempt.run_id == run_id,
                    Attempt.node_id == node_id,
                    Attempt.number == attempt,
                )
            ).scalar_one_or_none()
            if a:
                a.status = "failed"
                a.error = message
                a.finished = time.time()
            if run.status not in TERMINAL:
                transient = not isinstance(exc, (ValueError, ApplicationError))
                if transient:
                    n = s.execute(
                        select(NodeRun).where(
                            NodeRun.run_id == run_id, NodeRun.node_id == node_id
                        )
                    ).scalar_one()
                    n.status = "retry_wait"
                emit(
                    s,
                    run_id,
                    "node.retrying" if transient else "node.error",
                    node_id,
                    {"attempt": attempt, "error": message},
                )
        if isinstance(exc, ApplicationError):
            raise
        if isinstance(exc, ValueError):
            raise ApplicationError(
                message, non_retryable=True, type="InvalidNodeData"
            ) from exc
        raise


@activity.defn
def finish_run(args: dict):
    with db() as s:
        run = lock_run(s, args["runId"])
        if run.status in TERMINAL:
            return
        run.status = "cancelled" if run.cancel_requested else args["status"]
        run.error = args.get("error")
        run.finished = time.time()
        nodes = (
            s.execute(select(NodeRun).where(NodeRun.run_id == run.id)).scalars().all()
        )
        for n in nodes:
            if n.status in ["pending", "ready", "running", "retry_wait"]:
                n.status = "cancelled" if run.status == "cancelled" else "blocked"
                n.finished = time.time()
                emit(s, run.id, "node." + n.status, n.node_id)
        emit(
            s,
            run.id,
            "run.completed",
            payload={"status": run.status, "error": run.error},
        )
