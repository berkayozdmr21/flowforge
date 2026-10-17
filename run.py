"""Run the real local stack. No alternate in-process workflow engine."""

import os, sys, socket, time, subprocess, shutil, json, hashlib, urllib.request, zipfile, io, webbrowser, signal
from pathlib import Path

ROOT = Path(__file__).absolute().parent
RUNTIME = ROOT / ".runtime"
VERSION = "1.9.1"


def free(preferred):
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", preferred))
        except OSError:
            probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_http(url, seconds=60):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            with opener.open(url, timeout=2) as r:
                if r.status == 200:
                    return json.load(r)
        except Exception:
            time.sleep(0.35)
    raise RuntimeError("Servis hazir olmadi: " + url)


def temporal_binary():
    found = shutil.which("temporal")
    if found:
        return found
    tools = ROOT / ".tools"
    tools.mkdir(exist_ok=True)
    target = tools / "temporal.exe"
    if target.exists():
        return str(target)
    if os.name != "nt":
        raise RuntimeError("Temporal CLI kur veya Docker Compose kullan.")
    base = f"https://github.com/temporalio/cli/releases/download/v{VERSION}/"
    name = f"temporal_cli_{VERSION}_windows_amd64.zip"
    print("Resmi Temporal CLI indiriliyor (ilk kurulum)...", flush=True)
    checks = urllib.request.urlopen(base + "checksums.txt", timeout=60).read().decode()
    digest = next(
        line.split()[0]
        for line in checks.splitlines()
        if line.split()[-1].lstrip("*") == name
    )
    data = urllib.request.urlopen(base + name, timeout=120).read()
    if hashlib.sha256(data).hexdigest() != digest:
        raise RuntimeError("Temporal indirme hash kontrolu basarisiz.")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        member = next(x for x in archive.namelist() if x.endswith("temporal.exe"))
        target.write_bytes(archive.read(member))
    return str(target)


def main():
    os.chdir(ROOT)
    RUNTIME.mkdir(exist_ok=True)
    if not (ROOT / "frontend/dist/index.html").exists():
        raise RuntimeError(
            "Hazir arayuz yok. frontend klasorunde npm ci ve npm run build calistir."
        )
    if "--docker" in sys.argv:
        port = free(int(os.getenv("FLOWFORGE_PORT", "9030")))
        env = {**os.environ, "FLOWFORGE_PORT": str(port)}
        subprocess.run(
            ["docker", "compose", "up", "-d", "--build"], env=env, check=True
        )
        wait_http(f"http://127.0.0.1:{port}/api/health/ready", 120)
        if "--no-browser" not in sys.argv:
            webbrowser.open(f"http://127.0.0.1:{port}")
        print("Docker servisleri arka planda acik. Durdurmak icin: docker compose stop")
        return
    roots = (
        [Path(os.getenv("ProgramFiles", r"C:\Program Files")) / "PostgreSQL"]
        if os.name == "nt"
        else []
    )
    candidates = [
        p for base in roots if base.exists() for p in base.glob("*/bin/postgres.exe")
    ]
    pg = (
        Path(os.getenv("PG_BIN", ""))
        if os.getenv("PG_BIN")
        else sorted(candidates, reverse=True)[0].parent if candidates else None
    )
    if (
        not pg
        or not (pg / ("postgres.exe" if os.name == "nt" else "postgres")).exists()
    ):
        raise RuntimeError(
            "PostgreSQL bulunamadi. PostgreSQL 17+ kur veya Docker Desktop acikken python run.py --docker kullan. PG_BIN ile bin klasoru secilebilir."
        )
    temporal = temporal_binary()
    api_port = free(int(os.getenv("FLOWFORGE_PORT", "9030")))
    pg_port = free(55439)
    temporal_port = free(7239)
    ui_port = free(8239)
    cluster = RUNTIME / "postgres"
    children = []
    logs = []
    started_pg = False

    def start(name, args, env=None):
        log = open(RUNTIME / (name + ".log"), "a", encoding="utf-8")
        logs.append(log)
        process = subprocess.Popen(
            [str(a) for a in args],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        children.append((name, process))
        return process

    env = {
        **os.environ,
        "DATABASE_URL": f"postgresql+psycopg://flowforge@127.0.0.1:{pg_port}/flowforge",
        "TEMPORAL_ADDRESS": f"127.0.0.1:{temporal_port}",
        "FLOWFORGE_DATA": str(RUNTIME / "data"),
    }
    try:
        if not (cluster / "PG_VERSION").exists():
            subprocess.run(
                [
                    str(pg / "initdb"),
                    "-D",
                    str(cluster),
                    "-U",
                    "flowforge",
                    "-A",
                    "trust",
                    "--encoding=UTF8",
                    "--locale=C",
                ],
                check=True,
            )
        existing = (
            subprocess.run(
                [str(pg / "pg_ctl"), "-D", str(cluster), "status"], capture_output=True
            ).returncode
            == 0
        )
        if existing:
            # Reuse only this project's explicitly identified PostgreSQL cluster.
            pg_port = int((cluster / "postmaster.pid").read_text().splitlines()[3])
            env["DATABASE_URL"] = (
                f"postgresql+psycopg://flowforge@127.0.0.1:{pg_port}/flowforge"
            )
        else:
            start(
                "postgres",
                [pg / "postgres", "-D", cluster, "-p", str(pg_port), "-h", "127.0.0.1"],
            )
            started_pg = True
        import psycopg

        for _ in range(100):
            try:
                with psycopg.connect(
                    host="127.0.0.1",
                    port=pg_port,
                    user="flowforge",
                    dbname="postgres",
                    connect_timeout=2,
                    autocommit=True,
                ) as db:
                    if not db.execute(
                        "SELECT 1 FROM pg_database WHERE datname='flowforge'"
                    ).fetchone():
                        db.execute("CREATE DATABASE flowforge")
                break
            except psycopg.OperationalError:
                time.sleep(0.3)
        else:
            raise RuntimeError(
                "PostgreSQL baslatilamadi; .runtime/postgres.log dosyasina bak."
            )
        start(
            "temporal",
            [
                temporal,
                "server",
                "start-dev",
                "--ip",
                "127.0.0.1",
                "--port",
                str(temporal_port),
                "--ui-port",
                str(ui_port),
                "--db-filename",
                RUNTIME / "temporal.db",
                "--log-level",
                "warn",
            ],
        )
        start(
            "api",
            [
                sys.executable,
                "-m",
                "uvicorn",
                "backend.app.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(api_port),
            ],
            env,
        )
        url = f"http://127.0.0.1:{api_port}"
        wait_http(url + "/api/health/live")
        # Wait for Temporal before starting a polling worker.
        from temporalio.client import Client
        import asyncio

        async def temporal_ready():
            for _ in range(60):
                try:
                    await asyncio.wait_for(Client.connect(env["TEMPORAL_ADDRESS"]), 2)
                    return
                except Exception:
                    await asyncio.sleep(0.5)
            raise RuntimeError("Temporal baslatilamadi.")

        asyncio.run(temporal_ready())
        start("worker", [sys.executable, "-m", "backend.app.worker"], env)
        wait_http(url + "/api/health/ready")
        print(
            "\nFlowForge: "
            + url
            + "\nBu pencere acik kalsin. Durdurmak icin Ctrl+C.\n",
            flush=True,
        )
        (RUNTIME / "current-url.txt").write_text(url, encoding="utf-8")
        stop = RUNTIME / "stop-request"
        if stop.exists():
            stop.unlink()
        if "--no-browser" not in sys.argv:
            webbrowser.open(url)
        while True:
            if stop.exists():
                stop.unlink()
                break
            for name, p in children:
                if p.poll() is not None:
                    raise RuntimeError(
                        name
                        + " kapandi. .runtime/"
                        + name
                        + ".log dosyasini kontrol et."
                    )
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nServisler durduruluyor...", flush=True)
    finally:
        for name, p in reversed(children):
            if name == "postgres":
                continue
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    p.kill()
        if started_pg:
            subprocess.run(
                [str(pg / "pg_ctl"), "-D", str(cluster), "stop", "-m", "fast"],
                capture_output=True,
            )
        for log in logs:
            log.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("\nHATA: " + str(error), file=sys.stderr, flush=True)
        sys.exit(1)
