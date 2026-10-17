"""Prepare an isolated Python environment, then launch FlowForge."""

import sys, os, subprocess, venv, shutil
from pathlib import Path

root = Path(__file__).absolute().parents[1]
if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10 veya ustu gerekli. Python 3.12 onerilir.")
target = root / ".venv"
python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if not python.exists():
    try:
        venv.EnvBuilder(with_pip=True).create(target)
    except subprocess.CalledProcessError:
        venv.EnvBuilder(with_pip=False).create(target)
probe = subprocess.run(
    [str(python), "-c", "import fastapi,temporalio,psycopg,alembic,uvicorn,websockets"],
    capture_output=True,
)
if probe.returncode:
    temp = root / ".tmp"
    temp.mkdir(exist_ok=True)
    env = {**os.environ, "TEMP": str(temp), "TMP": str(temp)}
    pip_probe = subprocess.run(
        [str(python), "-m", "pip", "--version"], capture_output=True
    )
    if pip_probe.returncode:
        # Some bundled Python distributions intentionally omit ensurepip.
        host = shutil.which("python")
        if not host:
            raise SystemExit("pip bulunamadi. Standart Python 3.12 kurulumunu kullan.")
        command = [host, "-m", "pip", "--python", str(python)]
    else:
        command = [str(python), "-m", "pip"]
    requirements = root / "requirements.lock.txt"
    subprocess.run(
        [
            *command,
            "install",
            "--no-compile",
            "-r",
            str(requirements if requirements.exists() else root / "requirements.txt"),
        ],
        env=env,
        check=True,
    )
raise SystemExit(
    subprocess.call([str(python), str(root / "run.py"), *sys.argv[1:]], cwd=root)
)
