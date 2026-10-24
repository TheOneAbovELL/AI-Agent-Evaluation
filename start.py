"""TraceGrade launcher: one command sets everything up and starts the application.

    python start.py                 # install/update dependencies, then open the web app
    python start.py --port 8600     # use another port
    python start.py --no-browser    # do not open a browser tab
    python start.py --setup-only    # prepare everything, do not start the server

What it does, in order:
1. Creates `.env` from `.env.example` if you do not have one yet (add API keys there).
2. Installs the exact locked dependencies:
   - with uv (recommended):        `uv sync`
   - without uv (Python 3.12/3.13): a `.venv` with pip and requirements.txt
   Re-runs are fast: nothing is reinstalled when the lock file has not changed.
   If the project folder was moved, the old `.venv` is rebuilt automatically.
3. Prints a configuration and provider check (no network calls).
4. Starts the Streamlit interface and opens it in your browser. Stop with Ctrl+C.

Only the Python standard library is used here, so it runs before anything is installed.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import time
import venv
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
APP = ROOT / "src" / "tracegrade" / "ui" / "app.py"
MARKER = VENV / ".tracegrade-install"
LOCATION = VENV / ".tracegrade-location"


def say(message: str) -> None:
    print(f"[tracegrade] {message}", flush=True)


def fail(message: str) -> None:
    print(f"[tracegrade] ERROR: {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def run(command: list[str]) -> None:
    result = subprocess.run(command, cwd=ROOT, check=False)  # noqa: S603 - fixed argv
    if result.returncode != 0:
        fail(f"command failed ({result.returncode}): {' '.join(command)}")


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_venv_location() -> None:
    """Rebuild `.venv` when the project was moved: its launchers embed the old path."""
    if VENV.exists() and LOCATION.exists() and LOCATION.read_text(encoding="utf-8") != str(ROOT):
        say("The project folder has moved since .venv was created; rebuilding .venv ...")
        try:
            shutil.rmtree(VENV)
        except OSError as exc:
            fail(f"could not remove the old .venv ({exc}). Close programs using it and retry.")


def remember_venv_location() -> None:
    if VENV.exists():
        LOCATION.write_text(str(ROOT), encoding="utf-8")


def ensure_env_file() -> None:
    env, example = ROOT / ".env", ROOT / ".env.example"
    if not env.exists() and example.exists():
        shutil.copyfile(example, env)
        say("Created .env from .env.example (runs offline until you add an API key there).")


def fingerprint(*paths: Path) -> str:
    digest = hashlib.sha256()
    for path in paths:
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def install_with_uv(uv: str) -> list[str]:
    say("Installing dependencies with uv (exact versions from uv.lock)...")
    say("The first run can take a few minutes; please wait and do not press Ctrl+C.")
    run([uv, "sync", "--locked"])
    return [uv, "run", "--locked", "python"]


def install_with_pip() -> list[str]:
    if sys.version_info < (3, 12) or sys.version_info >= (3, 14):
        fail(
            "TraceGrade needs Python 3.12 or 3.13 (you are running "
            f"{sys.version.split()[0]}). Install one of them, or install uv "
            "(https://docs.astral.sh/uv/) which downloads the right Python automatically."
        )
    if not venv_python().exists():
        say(f"Creating virtual environment in {VENV.name}/ ...")
        venv.EnvBuilder(with_pip=True).create(VENV)
    wanted = fingerprint(ROOT / "requirements.txt", ROOT / "pyproject.toml")
    if not MARKER.exists() or MARKER.read_text(encoding="utf-8") != wanted:
        python = str(venv_python())
        say("Installing dependencies with pip (pinned versions from requirements.txt)...")
        say("The first run can take several minutes; please wait and do not press Ctrl+C.")
        run(
            [
                python,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-q",
                "-r",
                "requirements.txt",
            ]
        )
        run(
            [
                python,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-q",
                "-e",
                ".",
                "--no-deps",
            ]
        )
        MARKER.write_text(wanted, encoding="utf-8")
    else:
        say("Dependencies are up to date.")
    return [str(venv_python())]


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def free_port(preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        if not port_in_use(port):
            return port
    fail(f"No free port between {preferred} and {preferred + 19}.")
    return preferred


def main() -> int:
    try:
        return start()
    except KeyboardInterrupt:
        say("Interrupted. Nothing is broken: run `python start.py` again to continue.")
        return 130


def start() -> int:
    parser = argparse.ArgumentParser(description="Set up and start TraceGrade.")
    parser.add_argument("--port", type=int, default=8501, help="web interface port (default 8501)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    parser.add_argument("--setup-only", action="store_true", help="install and check, then exit")
    args = parser.parse_args()

    os.chdir(ROOT)
    say(f"Project folder: {ROOT}")
    ensure_env_file()
    ensure_venv_location()
    uv = shutil.which("uv")
    python_cmd = install_with_uv(uv) if uv else install_with_pip()
    remember_venv_location()

    say("Configuration check:")
    run([*python_cmd, "-m", "tracegrade", "doctor"])
    if args.setup_only:
        say("Setup complete. Start the app with: python start.py")
        return 0

    port = free_port(args.port)
    if port != args.port:
        say(f"Port {args.port} is busy; using {port}.")
    url = f"http://localhost:{port}"
    command = [
        *python_cmd,
        "-m",
        "streamlit",
        "run",
        str(APP),
        "--server.port",
        str(port),
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]
    say(f"Starting the web interface at {url} (stop with Ctrl+C) ...")
    server = subprocess.Popen(command, cwd=ROOT)  # noqa: S603 - fixed argv
    try:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and server.poll() is None and not port_in_use(port):
            time.sleep(0.5)
        if server.poll() is not None:
            fail("the web interface exited during startup; see the messages above.")
        say(f"TraceGrade is running: {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return server.wait()
    except KeyboardInterrupt:
        say("Stopping...")
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        return 0


if __name__ == "__main__":
    sys.exit(main())
