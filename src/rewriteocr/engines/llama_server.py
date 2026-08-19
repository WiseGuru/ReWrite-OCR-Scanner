"""Lifecycle manager for the embedded llama-server subprocess.

Owns spawn, health polling, served-model identity verification, GPU to CPU
fallback, and idempotent teardown wired to every exit path. Nothing else in
the app talks to the process directly; the VLM engine only sees a base URL.
"""

from __future__ import annotations

import atexit
import json
import logging
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from enum import Enum
from pathlib import Path

from rewriteocr.config import logs_dir
from rewriteocr.constants import DEFAULT_PORT_BASE, PORT_PROBE_SPAN
from rewriteocr.engines.base import EngineUnavailableError

log = logging.getLogger("rewriteocr.llama_server")

HEALTH_TIMEOUT_S = 180.0
HEALTH_POLL_INTERVAL_S = 0.5


class ServerState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    FAILED = "failed"


def find_llama_server(settings_path: str | None = None) -> str:
    """Locate llama-server: explicit setting first, then PATH."""
    if settings_path and Path(settings_path).is_file():
        return settings_path
    found = shutil.which("llama-server")
    if found:
        return found
    raise EngineUnavailableError(
        "llama-server was not found. Install llama.cpp or set its path in settings."
    )


def probe_free_port(base: int = DEFAULT_PORT_BASE, span: int = PORT_PROBE_SPAN) -> int:
    for port in range(base, base + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise EngineUnavailableError(f"No free port in {base}-{base + span - 1}.")


class LlamaServerManager:
    """Manages exactly one llama-server process for the active model."""

    def __init__(
        self,
        model_path: Path,
        mmproj_path: Path,
        context_size: int,
        exe_path: str | None = None,
        port_base: int = DEFAULT_PORT_BASE,
    ) -> None:
        self.model_path = Path(model_path)
        self.mmproj_path = Path(mmproj_path)
        self.context_size = context_size
        self.exe_path = exe_path
        self.port_base = port_base
        self.state = ServerState.STOPPED
        self.device = "gpu"
        self.port: int | None = None
        self._proc: subprocess.Popen | None = None
        self._log_file = None
        atexit.register(self.stop)

    @property
    def base_url(self) -> str:
        if self.port is None:
            raise EngineUnavailableError("Server is not running.")
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        """Start on GPU; fall back to CPU automatically if the GPU path fails."""
        try:
            self._start_once(ngl=99)
            self.device = "gpu"
        except EngineUnavailableError as exc:
            log.warning("GPU start failed (%s); retrying on CPU", exc)
            self.stop()
            self._start_once(ngl=0)
            self.device = "cpu"

    def start_cpu(self) -> None:
        """Explicit CPU start, used after a mid-run GPU failure."""
        self.stop()
        self._start_once(ngl=0)
        self.device = "cpu"

    def _start_once(self, ngl: int) -> None:
        if not self.model_path.is_file():
            raise EngineUnavailableError(f"Model file missing: {self.model_path}")
        if not self.mmproj_path.is_file():
            raise EngineUnavailableError(f"mmproj file missing: {self.mmproj_path}")
        exe = find_llama_server(self.exe_path)
        self.state = ServerState.STARTING
        self.port = probe_free_port(self.port_base)
        cmd = [
            exe,
            "-m", str(self.model_path),
            "--mmproj", str(self.mmproj_path),
            "--host", "127.0.0.1",
            "--port", str(self.port),
            "-ngl", str(ngl),
            "--ctx-size", str(self.context_size),
            "--no-webui",
        ]
        log.info("Starting llama-server: %s", " ".join(cmd))
        self._log_file = open(logs_dir() / "llama-server.log", "ab")
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=self._log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except OSError as exc:
            self.state = ServerState.FAILED
            raise EngineUnavailableError(f"Failed to launch llama-server: {exc}") from exc
        try:
            self._wait_healthy()
            self._verify_identity()
        except EngineUnavailableError:
            self.state = ServerState.FAILED
            self.stop()
            raise
        self.state = ServerState.READY

    def _wait_healthy(self) -> None:
        deadline = time.monotonic() + HEALTH_TIMEOUT_S
        url = f"{self.base_url}/health"
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise EngineUnavailableError(
                    f"llama-server exited during startup (code {self._proc.returncode}). "
                    "See llama-server.log for details."
                )
            try:
                with urllib.request.urlopen(url, timeout=2) as resp:
                    if resp.status == 200:
                        return
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(HEALTH_POLL_INTERVAL_S)
        raise EngineUnavailableError("llama-server did not become healthy in time.")

    def _verify_identity(self) -> None:
        """Hard-fail if the listener is not serving our pinned model file."""
        try:
            with urllib.request.urlopen(f"{self.base_url}/props", timeout=5) as resp:
                props = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise EngineUnavailableError(f"Could not read /props for identity check: {exc}") from exc
        served = props.get("model_path") or props.get("default_generation_settings", {}).get(
            "model", ""
        )
        if Path(served).name != self.model_path.name:
            raise EngineUnavailableError(
                f"Port {self.port} is serving '{served}', not '{self.model_path.name}'. "
                "Refusing to use an unidentified server."
            )

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def stop(self) -> None:
        """Idempotent teardown. Safe from atexit, excepthook, and normal close."""
        proc, self._proc = self._proc, None
        self.state = ServerState.STOPPED
        self.port = None
        if proc is not None and proc.poll() is None:
            log.info("Stopping llama-server (pid %d)", proc.pid)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                        capture_output=True,
                        check=False,
                    )
                else:
                    proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    log.error("llama-server pid %d did not exit after kill", proc.pid)
        if self._log_file is not None:
            try:
                self._log_file.close()
            except OSError:
                pass
            self._log_file = None

    def __enter__(self) -> LlamaServerManager:
        return self

    def __exit__(self, *exc_info) -> None:
        self.stop()
