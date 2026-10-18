from __future__ import annotations
import os, json, time, uuid
from pathlib import Path
from contextlib import contextmanager
from sqlalchemy import (
    create_engine,
    Column,
    String,
    Text,
    Integer,
    Float,
    ForeignKey,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import declarative_base, sessionmaker

ROOT = Path(os.path.abspath(__file__)).parents[2]
DATA = Path(os.getenv("FLOWFORGE_DATA", str(ROOT / ".runtime/data")))
DATA.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://flowforge@127.0.0.1:55439/flowforge"
)
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    **(
        {"connect_args": {"check_same_thread": False}}
        if DATABASE_URL.startswith("sqlite")
        else {}
    ),
)
Session = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()


def uid():
    return uuid.uuid4().hex


def pack(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def unpack(value):
    return json.loads(value)


class Flow(Base):
    __tablename__ = "workflows"
    id = Column(String, primary_key=True, default=uid)
    name = Column(String(100), nullable=False)
    graph = Column(Text, nullable=False)
    revision = Column(Integer, default=1, nullable=False)
    updated = Column(Float, default=time.time, nullable=False)


class Version(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (UniqueConstraint("flow_id", "number"),)
    id = Column(String, primary_key=True, default=uid)
    flow_id = Column(String, ForeignKey("workflows.id"), nullable=False)
    number = Column(Integer, nullable=False)
    graph = Column(Text, nullable=False)
    digest = Column(String, nullable=False)
    created = Column(Float, default=time.time, nullable=False)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("flow_id", "request_key"),)
    id = Column(String, primary_key=True, default=uid)
    flow_id = Column(String, ForeignKey("workflows.id"), nullable=False)
    version_id = Column(String, ForeignKey("workflow_versions.id"), nullable=False)
    request_key = Column(String, nullable=False)
    request_hash = Column(String, nullable=False)
    status = Column(String, default="queued", nullable=False)
    seq = Column(Integer, default=0, nullable=False)
    created = Column(Float, default=time.time, nullable=False)
    finished = Column(Float)
    error = Column(Text)
    cancel_requested = Column(Integer, default=0, nullable=False)


class NodeRun(Base):
    __tablename__ = "node_runs"
    __table_args__ = (UniqueConstraint("run_id", "node_id"),)
    id = Column(String, primary_key=True, default=uid)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False)
    node_id = Column(String, nullable=False)
    status = Column(String, default="pending", nullable=False)
    output = Column(Text)
    error = Column(Text)
    started = Column(Float)
    finished = Column(Float)
    attempt = Column(Integer, default=0, nullable=False)


class Attempt(Base):
    __tablename__ = "node_attempts"
    __table_args__ = (UniqueConstraint("run_id", "node_id", "number"),)
    id = Column(String, primary_key=True, default=uid)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False)
    node_id = Column(String, nullable=False)
    number = Column(Integer, nullable=False)
    status = Column(String, nullable=False)
    error = Column(Text)
    started = Column(Float, default=time.time, nullable=False)
    finished = Column(Float)


class Event(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "sequence"),)
    id = Column(String, primary_key=True, default=uid)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False)
    sequence = Column(Integer, nullable=False)
    kind = Column(String, nullable=False)
    node_id = Column(String)
    payload = Column(Text, default="{}", nullable=False)
    created = Column(Float, default=time.time, nullable=False)


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("run_id", "node_id", "format"),)
    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False)
    node_id = Column(String, nullable=False)
    format = Column(String, nullable=False)
    title = Column(String, nullable=False)
    size = Column(Integer, nullable=False)
    digest = Column(String, nullable=False)
    path = Column(String, nullable=False)


class Outbox(Base):
    __tablename__ = "outbox"
    run_id = Column(String, ForeignKey("runs.id"), primary_key=True)
    sent = Column(Integer, default=0, nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    error = Column(Text)


class Schedule(Base):
    __tablename__ = "workflow_schedules"
    __table_args__ = (UniqueConstraint("flow_id", "request_key"),)
    id = Column(String, primary_key=True, default=uid)
    flow_id = Column(String, ForeignKey("workflows.id"), nullable=False)
    version_id = Column(String, ForeignKey("workflow_versions.id"), nullable=False)
    name = Column(String(100), nullable=False)
    mode = Column(String, nullable=False)
    status = Column(String, default="active", nullable=False)
    next_run = Column(Float, nullable=False, index=True)
    interval_seconds = Column(Integer, nullable=False, default=0)
    created = Column(Float, default=time.time, nullable=False)
    fired = Column(Integer, default=0, nullable=False)
    skipped = Column(Integer, default=0, nullable=False)
    last_run_id = Column(String, ForeignKey("runs.id"))
    request_key = Column(String, nullable=False)
    request_hash = Column(String, nullable=False)


class ScheduleRun(Base):
    __tablename__ = "schedule_runs"
    schedule_id = Column(String, ForeignKey("workflow_schedules.id"), primary_key=True)
    due = Column(Float, primary_key=True)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, unique=True)


@contextmanager
def db():
    s = Session()
    try:
        yield s
        s.commit()
    except BaseException:
        s.rollback()
        raise
    finally:
        s.close()


def emit(s, run_id, kind, node_id=None, payload=None):
    run = s.execute(select(Run).where(Run.id == run_id).with_for_update()).scalar_one()
    run.seq += 1
    e = Event(
        run_id=run_id,
        sequence=run.seq,
        kind=kind,
        node_id=node_id,
        payload=pack(payload or {}),
    )
    s.add(e)
    return e


TERMINAL = {"succeeded", "failed", "cancelled"}


def run_dict(s, r):
    nodes = s.execute(select(NodeRun).where(NodeRun.run_id == r.id)).scalars().all()
    artifacts = (
        s.execute(select(Artifact).where(Artifact.run_id == r.id)).scalars().all()
    )
    v = s.get(Version, r.version_id)
    return dict(
        id=r.id,
        flowId=r.flow_id,
        versionId=r.version_id,
        version=v.number,
        status=r.status,
        sequence=r.seq,
        created=r.created,
        finished=r.finished,
        error=r.error,
        graph=unpack(v.graph),
        nodes=[
            dict(
                id=n.node_id,
                status=n.status,
                attempt=n.attempt,
                output=unpack(n.output) if n.output else None,
                error=n.error,
                started=n.started,
                finished=n.finished,
            )
            for n in nodes
        ],
        artifacts=[
            dict(
                id=a.id,
                nodeId=a.node_id,
                format=a.format,
                title=a.title,
                size=a.size,
                url="/api/artifacts/" + a.id + "/download",
            )
            for a in artifacts
        ],
    )


def event_dict(e):
    return dict(
        id=e.id,
        runId=e.run_id,
        sequence=e.sequence,
        kind=e.kind,
        nodeId=e.node_id,
        payload=unpack(e.payload),
        created=e.created,
    )
