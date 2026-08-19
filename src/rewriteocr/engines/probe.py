"""Startup environment probes and the diagnostic info block for bug reports."""

from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass, field

from rewriteocr import __version__
from rewriteocr.engines.tesseract_engine import find_tesseract, tesseract_version


@dataclass
class EnvironmentStatus:
    llama_server_path: str | None = None
    tesseract_path: str | None = None
    tesseract_version: str | None = None

    @property
    def has_llama(self) -> bool:
        return self.llama_server_path is not None

    @property
    def has_tesseract(self) -> bool:
        return self.tesseract_path is not None


def probe_environment(
    llama_override: str | None = None, tesseract_override: str | None = None
) -> EnvironmentStatus:
    status = EnvironmentStatus()
    status.llama_server_path = (
        llama_override if llama_override else shutil.which("llama-server")
    )
    status.tesseract_path = find_tesseract(tesseract_override)
    if status.tesseract_path:
        status.tesseract_version = tesseract_version(status.tesseract_path)
    return status


@dataclass
class DiagnosticInfo:
    """Everything a useful bug report needs; rendered by the copy button."""

    device: str = "unknown"
    model_id: str = "none"
    model_revision: str = "none"
    quant: str = "none"
    page_flags: list[str] = field(default_factory=list)

    def render(self, env: EnvironmentStatus) -> str:
        lines = [
            f"app_version: {__version__}",
            f"os: {platform.platform()}",
            f"python: {platform.python_version()}",
            f"backend_device: {self.device}",
            f"model_id: {self.model_id}",
            f"model_revision: {self.model_revision}",
            f"quant: {self.quant}",
            f"llama_server: {env.llama_server_path or 'not found'}",
            f"tesseract: {env.tesseract_version or 'not found'}",
        ]
        if self.page_flags:
            lines.append("page_flags: " + "; ".join(self.page_flags))
        return "\n".join(lines)
