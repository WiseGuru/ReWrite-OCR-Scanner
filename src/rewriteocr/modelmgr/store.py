"""On-disk model store: <app data>/models/<model-id>/<file>."""

from __future__ import annotations

import hashlib
from pathlib import Path

from rewriteocr.config import models_dir
from rewriteocr.modelmgr.manifest import ModelSpec, QuantSpec


def model_dir(spec: ModelSpec) -> Path:
    d = models_dir() / spec.id
    d.mkdir(parents=True, exist_ok=True)
    return d


def quant_path(spec: ModelSpec, quant: QuantSpec) -> Path:
    return model_dir(spec) / quant.file


def mmproj_path(spec: ModelSpec) -> Path:
    return model_dir(spec) / spec.mmproj.file


def is_quant_installed(spec: ModelSpec, quant: QuantSpec) -> bool:
    return quant_path(spec, quant).is_file() and mmproj_path(spec).is_file()


def installed_quants(spec: ModelSpec) -> list[QuantSpec]:
    return [q for q in spec.quants if is_quant_installed(spec, q)]


def any_model_installed(manifest: list[ModelSpec]) -> bool:
    return any(installed_quants(spec) for spec in manifest)


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def verify_file(path: Path, expected_sha256: str) -> bool:
    return path.is_file() and sha256_file(path) == expected_sha256.lower()
