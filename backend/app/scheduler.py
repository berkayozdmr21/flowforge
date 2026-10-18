"""Transactional clock ticks enqueue immutable graph versions through the existing outbox."""

from __future__ import annotations
import hashlib
import math
import time
from sqlalchemy import select, func, text
from .domain import Graph
from .store import (
    db,
    engine,
    Schedule,
    ScheduleRun,
    Version,
    Run,
    NodeRun,
    Outbox,
    uid,
    emit,
    unpack,
    TERMINAL,
)

PERIODS = {"once": 0, "hourly": 3600, "daily": 86400}


def schedule_dict(s, item):
    version = s.get(Version, item.version_id)
    last = s.get(Run, item.last_run_id) if item.last_run_id else None
    return dict(
        id=item.id,
        flowId=item.flow_id,
        versionId=item.version_id,
        version=version.number,
        name=item.name,
        mode=item.mode,
        status=item.status,
        nextRun=item.next_run if item.status in {"active", "paused"} else None,
        intervalSeconds=item.interval_seconds,
        created=item.created,
        fired=item.fired,
        skipped=item.skipped,
        lastRunId=item.last_run_id,
        lastRunStatus=last.status if last else None,
    )


def tick(now=None):
    now = time.time() if now is None else now
    with db() as s:
        # Serialize scheduler ticks across PostgreSQL workers. A transaction-scoped
        # lock is released automatically after a crash, rollback or commit.
        if engine.dialect.name == "postgresql":
            if not s.scalar(text("SELECT pg_try_advisory_xact_lock(741386299)")):
                return 0
        due = (
            s.execute(
                select(Schedule)
                .where(Schedule.status == "active", Schedule.next_run <= now)
                .order_by(Schedule.next_run, Schedule.id)
                .limit(50)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        created = 0
        open_count = s.scalar(
            select(func.count())
            .select_from(Run)
            .where(Run.status.notin_(list(TERMINAL)))
        )
        for item in due:
            period = item.interval_seconds
            missed = math.floor((now - item.next_run) / period) if period else 0
            slot = item.next_run + missed * period
            previous = s.get(Run, item.last_run_id) if item.last_run_id else None
            busy = open_count >= 10 or (
                previous is not None and previous.status not in TERMINAL
            )
            if busy and not period:
                continue  # Keep a one-shot pending until capacity becomes available.
            item.skipped += missed
            if period:
                item.next_run = slot + period
            if busy:
                item.skipped += 1
                continue
            graph = Graph(**unpack(s.get(Version, item.version_id).graph))
            key = f"schedule-{item.id}-{int(slot * 1000)}"
            run = Run(
                id=uid(),
                flow_id=item.flow_id,
                version_id=item.version_id,
                request_key=key,
                request_hash=hashlib.sha256(key.encode()).hexdigest(),
            )
            s.add(run)
            s.flush()
            for node in graph.nodes:
                s.add(NodeRun(run_id=run.id, node_id=node.id))
            s.add(Outbox(run_id=run.id))
            s.add(ScheduleRun(schedule_id=item.id, due=slot, run_id=run.id))
            emit(
                s,
                run.id,
                "run.queued",
                payload={"scheduleId": item.id, "scheduledFor": slot},
            )
            item.last_run_id = run.id
            item.fired += 1
            if not period:
                item.status = "completed"
            created += 1
            open_count += 1
        return created
