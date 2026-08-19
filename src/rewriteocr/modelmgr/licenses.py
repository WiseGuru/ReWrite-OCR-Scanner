"""Per-model license acknowledgment records. A model may not run until its
license has been shown and explicitly acknowledged once."""

from __future__ import annotations

import json
from pathlib import Path

from rewriteocr.config import app_data_dir
from rewriteocr.core.sidecar import now_iso


def _store_path() -> Path:
    return app_data_dir() / "license_acks.json"


def _load() -> dict:
    try:
        return json.loads(_store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def is_acknowledged(model_id: str) -> bool:
    return model_id in _load()


def record_acknowledgment(model_id: str, license_name: str) -> None:
    data = _load()
    data[model_id] = {"license": license_name, "acknowledged_at": now_iso()}
    path = _store_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)
