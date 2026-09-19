from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import get_settings


NATIVE_HOST_NAME = "com.sjtu.paperdownloader"
EXTENSION_ID = "hnmnojlkimfjgmeelnghlegofogpohoi"
DEFAULT_STARTUP_TIMEOUT_SECONDS = 20.0
DEFAULT_POLL_INTERVAL_SECONDS = 0.5


class NativeHostError(RuntimeError):
    """Raised when the native host cannot fulfill a request."""


@dataclass(frozen=True)
class ServiceStatus:
    backend_url: str
    health: dict[str, Any]


def debug_log(message: str) -> None:
    if os.environ.get("PAPERDOWNLOADER_NATIVE_HOST_LOG") != "1":
        return
    try:
        log_dir = repo_root() / ".debug"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "native-host.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    debug_log(f"main args={args!r} frozen={getattr(sys, 'frozen', False)}")
    if args and args[0] == "--run-service":
        return run_service_process()
    return run_native_host()


def run_native_host() -> int:
    debug_log("run_native_host waiting for request")
    request = read_native_message()
    debug_log(f"run_native_host received={request!r}")
    message_type = request.get("type")
    if message_type != "ensureService":
        write_native_message(
            {
                "ok": False,
                "error": f"Unknown native host request: {message_type!r}",
            }
        )
        return 1

    try:
        response = ensure_service()
    except Exception as exc:  # pragma: no cover - exercised via integration
        debug_log(f"run_native_host error={exc!r}")
        write_native_message({"ok": False, "error": str(exc)})
        return 1

    debug_log(f"run_native_host response={response!r}")
    write_native_message(response)
    return 0


def run_service_process() -> int:
    # Import lazily so the native host stays lightweight when just probing.
    from .cli import main as service_main

    os.chdir(repo_root())
    debug_log(f"run_service_process cwd={repo_root()}")
    service_main()
    return 0


def ensure_service(
    *,
    startup_timeout: float = DEFAULT_STARTUP_TIMEOUT_SECONDS,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
) -> dict[str, Any]:
    settings = get_settings()
    backend_url = normalize_backend_url(f"http://{settings.host}:{settings.port}")
    debug_log(f"ensure_service backend_url={backend_url}")
    existing = probe_service(backend_url)
    if existing is not None:
        debug_log("ensure_service found existing service")
        return {
            "ok": True,
            "backendUrl": backend_url,
            "serviceStarted": False,
            "health": existing.health,
        }

    debug_log("ensure_service launching subprocess")
    launch_service_subprocess()
    deadline = time.monotonic() + startup_timeout
    last_error = "Timed out waiting for local service health check."
    while time.monotonic() < deadline:
        status = probe_service(backend_url)
        if status is not None:
            debug_log("ensure_service health check succeeded after launch")
            return {
                "ok": True,
                "backendUrl": backend_url,
                "serviceStarted": True,
                "health": status.health,
            }
        time.sleep(poll_interval)

    debug_log("ensure_service timed out")
    raise NativeHostError(last_error)


def launch_service_subprocess() -> None:
    command = service_command()
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    env = os.environ.copy()
    env["PAPERDOWNLOADER_SERVICE_MODE"] = "1"
    if getattr(sys, "frozen", False):
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    debug_log(f"launch_service_subprocess command={command!r}")
    subprocess.Popen(
        command,
        cwd=str(repo_root()),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=os.name != "nt",
    )


def service_command() -> list[str]:
    if getattr(sys, "frozen", False):
        repo_python = repo_root() / ".venv" / "Scripts" / "python.exe"
        if repo_python.exists():
            return [str(repo_python), "-m", "paperdownloader.native_host", "--run-service"]
        return [str(Path(sys.executable).resolve()), "--run-service"]
    return [sys.executable, "-m", "paperdownloader.native_host", "--run-service"]


def probe_service(backend_url: str) -> ServiceStatus | None:
    request = Request(f"{backend_url}/health", method="GET")
    try:
        with urlopen(request, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, ConnectionError, OSError, HTTPError, json.JSONDecodeError):
        return None
    return ServiceStatus(backend_url=backend_url, health=payload)


def repo_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent
    return Path(__file__).resolve().parents[1]


def normalize_backend_url(value: str) -> str:
    return value.rstrip("/")


def read_native_message() -> dict[str, Any]:
    raw_length = sys.stdin.buffer.read(4)
    if len(raw_length) != 4:
        raise NativeHostError("No native host request payload was received.")
    message_length = struct.unpack("<I", raw_length)[0]
    debug_log(f"read_native_message length={message_length}")
    payload = sys.stdin.buffer.read(message_length)
    if len(payload) != message_length:
        raise NativeHostError("Incomplete native host request payload.")
    return json.loads(payload.decode("utf-8"))


def write_native_message(message: dict[str, Any]) -> None:
    payload = json.dumps(message).encode("utf-8")
    debug_log(f"write_native_message bytes={len(payload)}")
    sys.stdout.buffer.write(struct.pack("<I", len(payload)))
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
