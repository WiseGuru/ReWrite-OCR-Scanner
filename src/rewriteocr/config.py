"""App data directory resolution and persisted user settings."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from rewriteocr.constants import APP_NAME


def app_data_dir() -> Path:
    """Per-user writable directory for models, profiles, settings, and logs."""
    override = os.environ.get("REWRITEOCR_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = (Path(xdg) if xdg else Path.home() / ".local" / "share") / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def models_dir() -> Path:
    d = app_data_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def profiles_dir() -> Path:
    d = app_data_dir() / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def projects_dir() -> Path:
    """All project sidecars and their figure folders. Nothing is ever
    written next to the source PDF."""
    d = app_data_dir() / "projects"
    d.mkdir(parents=True, exist_ok=True)
    return d


def temp_dir() -> Path:
    """Scratch space for transient working files (engine inputs)."""
    d = app_data_dir() / "temp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def clean_stale_temp(max_age_s: float = 24 * 3600) -> None:
    """Best-effort removal of scratch left behind by a hard kill. Entries
    younger than max_age_s are skipped in case another instance owns them."""
    import shutil
    import time

    cutoff = time.time() - max_age_s
    try:
        entries = list(temp_dir().iterdir())
    except OSError:
        return
    for entry in entries:
        try:
            if entry.stat().st_mtime < cutoff:
                if entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink(missing_ok=True)
        except OSError:
            continue


def logs_dir() -> Path:
    d = app_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


class Settings:
    """Small JSON-backed settings store. Not for document state; that is the sidecar's job."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_data_dir() / "settings.json"
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        try:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._data = {}

    def save(self) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()
