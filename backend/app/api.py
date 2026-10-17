from __future__ import annotations
import asyncio, time, os, json, hashlib, re
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from fastapi import (
    FastAPI,
    Request,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    Response,
)
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import Field
from sqlalchemy import select, func, text
from sqlalchemy.exc import IntegrityError
from alembic.config import Config
from alembic import command
from .domain import Graph, Strict, validate_graph, registry
from .templates import templates
from .store import (
    ROOT,
    DATA,
    db,
    engine,
    Flow,
    Version,
    Run,
    NodeRun,
    Attempt,
    Event,
    Artifact,
    Outbox,
    uid,
    pack,
    unpack,
    emit,
    run_dict,
    event_dict,
)
from .activities import output_of


def migrate():
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend/migrations"))
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app):
    await asyncio.to_thread(migrate)
    with db() as s:
        if s.scalar(select(func.count()).select_from(Flow)) == 0:
            graph = templates()[0]["graph"]
            s.add(Flow(id="welcome", name=graph["name"], graph=pack(graph)))
    yield


app = FastAPI(title="FlowForge API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["127.0.0.1", "localhost", "testserver", "[::1]"],
)


@app.middleware("http")
async def protect(request: Request, call_next):
    if request.method in [
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
    ] and request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        if request.headers.get("x-flowforge-client") != "studio" or (
            origin and urlparse(origin).netloc != request.headers.get("host")
        ):
            return JSONResponse(
                {"detail": "İstek kaynağı doğrulanamadı."}, status_code=403
            )
        try:
            if int(request.headers.get("content-length", "0")) > 2 * 1024 * 1024:
                return JSONResponse(
                    {"detail": "İstek en fazla 2 MB olabilir."}, status_code=413
                )
        except ValueError:
            return JSONResponse({"detail": "Geçersiz içerik boyutu."}, status_code=400)
        body = await request.body()
        if len(body) > 2 * 1024 * 1024:
            return JSONResponse(
                {"detail": "İstek en fazla 2 MB olabilir."}, status_code=413
            )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


def check(graph):
    try:
        return validate_graph(graph)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


def flow_dict(f):
    return dict(
        id=f.id,
        name=f.name,
        graph=unpack(f.graph),
        revision=f.revision,
        updated=f.updated,
    )


def flow_lock(s, key):
    f = s.execute(
        select(Flow).where(Flow.id == key).with_for_update()
    ).scalar_one_or_none()
    if not f:
        raise HTTPException(404, "Akış bulunamadı.")
    return f


def make_version(s, f, graph):
    digest = graph.digest()
    latest = s.execute(
        select(Version)
        .where(Version.flow_id == f.id)
        .order_by(Version.number.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest and latest.digest == digest:
        return latest
    v = Version(
        id=uid(),
        flow_id=f.id,
        number=latest.number + 1 if latest else 1,
        graph=pack(graph.model_dump()),
        digest=digest,
    )
    s.add(v)
    s.flush()
    return v


@app.get("/api/health/live")
def live():
    return {"status": "ok", "product": "FlowForge"}


@app.get("/api/health/ready")
async def ready(response: Response):
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        from .worker import connect

        client = await asyncio.wait_for(connect(), 3)
        await asyncio.wait_for(client.service_client.check_health(), 3)
        from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
        from temporalio.api.taskqueue.v1 import TaskQueue
        from .worker import TASK_QUEUE

        queue = await asyncio.wait_for(
            client.workflow_service.describe_task_queue(
                DescribeTaskQueueRequest(
                    namespace="default",
                    task_queue=TaskQueue(name=TASK_QUEUE),
                    task_queue_type=1,
                )
            ),
            3,
        )
        if not queue.pollers:
            raise RuntimeError("Worker not polling")
        return {
            "status": "ready",
            "database": (
                "PostgreSQL" if engine.dialect.name == "postgresql" else "test SQLite"
            ),
            "orchestrator": "Temporal",
        }
    except Exception:
        response.status_code = 503
        return {
            "status": "unavailable",
            "message": "PostgreSQL ve Temporal servislerini kontrol et.",
        }


@app.get("/api/node-types")
def nodes():
    return registry()


@app.get("/api/templates")
def get_templates():
    return templates()


@app.post("/api/workflows/validate")
def validate(graph: Graph):
    return {"valid": True, "order": check(graph)}


@app.get("/api/workflows")
def flows():
    with db() as s:
        return [
            flow_dict(f)
            for f in s.execute(select(Flow).order_by(Flow.updated.desc())).scalars()
        ]


@app.post("/api/workflows", status_code=201)
def create(graph: Graph):
    with db() as s:
        if s.scalar(select(func.count()).select_from(Flow)) >= 200:
            raise HTTPException(409, "En fazla 200 akış kaydedilebilir.")
        f = Flow(id=uid(), name=graph.name, graph=pack(graph.model_dump()))
        s.add(f)
        s.flush()
        return flow_dict(f)


@app.get("/api/workflows/{key}")
def read(key: str):
    with db() as s:
        return flow_dict(flow_lock(s, key))


class Update(Strict):
    revision: int = Field(ge=1)
    graph: Graph


@app.patch("/api/workflows/{key}")
def update(key: str, body: Update):
    with db() as s:
        f = flow_lock(s, key)
        if f.revision != body.revision:
            raise HTTPException(
                409,
                "Akış başka bir pencerede güncellendi. Kaydı yeniden aç veya yeni kopya oluştur.",
            )
        f.name = body.graph.name
        f.graph = pack(body.graph.model_dump())
        f.revision += 1
        f.updated = time.time()
        s.flush()
        return flow_dict(f)


@app.post("/api/workflows/{key}/versions", status_code=201)
def version(key: str):
    with db() as s:
        f = flow_lock(s, key)
        g = Graph(**unpack(f.graph))
        check(g)
        v = make_version(s, f, g)
        return dict(id=v.id, number=v.number, digest=v.digest, created=v.created)


@app.get("/api/workflows/{key}/versions")
def versions(key: str):
    with db() as s:
        flow_lock(s, key)
        return [
            dict(
                id=v.id,
                number=v.number,
                created=v.created,
                digest=v.digest,
                graph=unpack(v.graph),
            )
            for v in s.execute(
                select(Version)
                .where(Version.flow_id == key)
                .order_by(Version.number.desc())
            ).scalars()
        ]


class Start(Strict):
    revision: int = Field(ge=1)
    versionId: str | None = None


@app.post("/api/workflows/{key}/runs", status_code=202)
def start(key: str, body: Start, request: Request):
    request_key = request.headers.get("idempotency-key", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", request_key):
        raise HTTPException(422, "Geçerli Idempotency-Key gerekli.")
    digest = hashlib.sha256(pack(body.model_dump()).encode()).hexdigest()
    with db() as s:
        f = flow_lock(s, key)
        previous = s.execute(
            select(Run).where(Run.flow_id == key, Run.request_key == request_key)
        ).scalar_one_or_none()
        if previous:
            if previous.request_hash != digest:
                raise HTTPException(
                    409, "Bu idempotency anahtarı başka bir istek için kullanıldı."
                )
            return run_dict(s, previous)
        if (
            s.scalar(
                select(func.count())
                .select_from(Run)
                .where(Run.status.in_(["queued", "running", "cancelling"]))
            )
            >= 10
        ):
            raise HTTPException(429, "En fazla 10 çalıştırma aynı anda açık olabilir.")
        if body.versionId:
            v = s.get(Version, body.versionId)
            if not v or v.flow_id != key:
                raise HTTPException(404, "Sürüm bulunamadı.")
            graph = Graph(**unpack(v.graph))
        else:
            if f.revision != body.revision:
                raise HTTPException(409, "Çalıştırmadan önce güncel akışı kaydet.")
            graph = Graph(**unpack(f.graph))
            check(graph)
            v = make_version(s, f, graph)
        run = Run(
            id=uid(),
            flow_id=key,
            version_id=v.id,
            request_key=request_key,
            request_hash=digest,
        )
        s.add(run)
        s.flush()
        for n in graph.nodes:
            s.add(NodeRun(run_id=run.id, node_id=n.id))
        s.add(Outbox(run_id=run.id))
        emit(s, run.id, "run.queued")
        s.flush()
        return run_dict(s, run)


@app.get("/api/runs")
def runs(flow_id: str | None = None):
    with db() as s:
        query = select(Run).order_by(Run.created.desc()).limit(100)
        if flow_id:
            query = query.where(Run.flow_id == flow_id)
        return [
            dict(
                id=r.id,
                flowId=r.flow_id,
                status=r.status,
                created=r.created,
                finished=r.finished,
                error=r.error,
            )
            for r in s.execute(query).scalars()
        ]


@app.get("/api/runs/{key}")
def run(key: str):
    with db() as s:
        r = s.get(Run, key)
        if not r:
            raise HTTPException(404, "Çalıştırma bulunamadı.")
        return run_dict(s, r)


@app.get("/api/runs/{key}/nodes/{node_id}/output")
def node_output(key: str, node_id: str):
    with db() as s:
        n = s.execute(
            select(NodeRun).where(NodeRun.run_id == key, NodeRun.node_id == node_id)
        ).scalar_one_or_none()
        if not n:
            raise HTTPException(404, "Blok bulunamadı.")
        value = output_of(n)
        preview = value["records"][:20]
        # Bound UI responses even if a single record contains large strings.
        if len(pack(preview).encode()) > 32768:
            preview = [{k: str(v)[:200] for k, v in row.items()} for row in preview[:5]]
        return {**value, "records": preview, "preview": True}


@app.post("/api/runs/{key}/cancel")
def cancel(key: str):
    with db() as s:
        r = s.execute(
            select(Run).where(Run.id == key).with_for_update()
        ).scalar_one_or_none()
        if not r:
            raise HTTPException(404, "Çalıştırma bulunamadı.")
        if r.status not in ["succeeded", "failed", "cancelled"]:
            r.cancel_requested = 1
            r.status = "cancelling"
            emit(s, r.id, "run.cancelling")
        return {"status": r.status}


@app.get("/api/runs/{key}/attempts")
def attempts(key: str):
    with db() as s:
        return [
            dict(
                nodeId=a.node_id,
                attempt=a.number,
                status=a.status,
                error=a.error,
                started=a.started,
                finished=a.finished,
            )
            for a in s.execute(
                select(Attempt).where(Attempt.run_id == key).order_by(Attempt.started)
            ).scalars()
        ]


@app.get("/api/runs/{key}/events")
def events(key: str, after_sequence: int = 0):
    with db() as s:
        if not s.get(Run, key):
            raise HTTPException(404, "Çalıştırma bulunamadı.")
        return [
            event_dict(e)
            for e in s.execute(
                select(Event)
                .where(Event.run_id == key, Event.sequence > max(after_sequence, 0))
                .order_by(Event.sequence)
                .limit(500)
            ).scalars()
        ]


@app.websocket("/api/runs/{key}/stream")
async def stream(ws: WebSocket, key: str):
    origin = ws.headers.get("origin")
    host = ws.headers.get("host")
    if origin and urlparse(origin).netloc != host:
        await ws.close(code=1008)
        return
    if not re.fullmatch("[a-f0-9]{32}", key):
        await ws.close(code=1008)
        return
    try:
        last = max(0, int(ws.query_params.get("after_sequence", "0")))
    except ValueError:
        await ws.close(code=1008)
        return
    with db() as s:
        if not s.get(Run, key):
            await ws.close(code=1008)
            return
    await ws.accept()
    try:
        while True:
            batch = await asyncio.to_thread(events, key, last)
            for item in batch:
                await ws.send_json(item)
                last = item["sequence"]
            with db() as s:
                status = s.get(Run, key).status
                sequence = s.get(Run, key).seq
            if status in ["succeeded", "failed", "cancelled"] and last >= sequence:
                await ws.send_json({"kind": "stream.complete", "sequence": last})
                await ws.close()
                return
            await asyncio.sleep(0.3)
    except (WebSocketDisconnect, RuntimeError):
        return


@app.get("/api/artifacts/{key}/download")
def download(key: str):
    with db() as s:
        a = s.get(Artifact, key)
        if not a:
            raise HTTPException(404, "Rapor bulunamadı.")
        path = DATA / "artifacts" / a.path
        if not path.is_file():
            raise HTTPException(404, "Rapor dosyası bulunamadı.")
        return FileResponse(
            path,
            filename="flowforge-" + a.id[:8] + "." + a.format,
            media_type={
                "json": "application/json",
                "csv": "text/csv; charset=utf-8",
                "html": "text/html; charset=utf-8",
            }[a.format],
            headers={
                "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'"
            },
        )


DIST = ROOT / "frontend/dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="studio")
