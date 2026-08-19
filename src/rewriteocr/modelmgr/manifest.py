"""Model manifest: the single source of truth for model files, hashes,
sampling, and preprocessing. Nothing downstream may hardcode these values.

A user-updatable copy in the app data directory overrides the bundled one
when its manifest_version is equal or newer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources

from rewriteocr.config import app_data_dir
from rewriteocr.core.models import Capabilities


class ManifestError(Exception):
    pass


@dataclass(frozen=True)
class QuantSpec:
    name: str
    label: str
    file: str
    sha256: str
    size_mb: int
    ram_mb: int


@dataclass(frozen=True)
class MmprojSpec:
    file: str
    sha256: str
    size_mb: int


@dataclass(frozen=True)
class PreprocessSpec:
    dpi: int
    longest_edge_px: int
    pad_to_multiple: int


@dataclass(frozen=True)
class SamplingSpec:
    temperature: float
    repeat_penalty: float
    repeat_last_n: int
    max_tokens: int


@dataclass(frozen=True)
class PromptSpec:
    page: str
    region: str
    table: str


@dataclass(frozen=True)
class ModelSpec:
    id: str
    display_name: str
    description: str
    license: str
    license_url: str
    repo: str
    revision: str
    capabilities: Capabilities
    preprocess: PreprocessSpec
    sampling: SamplingSpec
    prompt: PromptSpec
    context_size: int
    quants: tuple[QuantSpec, ...]
    mmproj: MmprojSpec

    def quant(self, name: str) -> QuantSpec:
        for q in self.quants:
            if q.name == name:
                return q
        raise ManifestError(f"Model {self.id} has no quant named {name}.")

    def file_url(self, filename: str) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{filename}"


def _parse_model(raw: dict) -> ModelSpec:
    try:
        return ModelSpec(
            id=raw["id"],
            display_name=raw["display_name"],
            description=raw["description"],
            license=raw["license"],
            license_url=raw["license_url"],
            repo=raw["repo"],
            revision=raw["revision"],
            capabilities=Capabilities(**raw["capabilities"]),
            preprocess=PreprocessSpec(**raw["preprocess"]),
            sampling=SamplingSpec(**raw["sampling"]),
            prompt=PromptSpec(**raw["prompt"]),
            context_size=raw["context_size"],
            quants=tuple(QuantSpec(**q) for q in raw["quants"]),
            mmproj=MmprojSpec(
                file=raw["mmproj"]["file"],
                sha256=raw["mmproj"]["sha256"],
                size_mb=raw["mmproj"]["size_mb"],
            ),
        )
    except (KeyError, TypeError) as exc:
        raise ManifestError(f"Malformed model entry {raw.get('id', '?')}: {exc}") from exc


def _load_raw(text: str) -> dict:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ManifestError(f"Manifest is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or "models" not in data or "manifest_version" not in data:
        raise ManifestError("Manifest missing manifest_version or models.")
    return data


def load_manifest() -> list[ModelSpec]:
    """Bundled manifest, overridden by a valid newer copy in the app data dir."""
    bundled = _load_raw(
        resources.files("rewriteocr.resources").joinpath("manifest.json").read_text("utf-8")
    )
    chosen = bundled
    user_path = app_data_dir() / "manifest.json"
    if user_path.is_file():
        try:
            user = _load_raw(user_path.read_text(encoding="utf-8"))
            if user["manifest_version"] >= bundled["manifest_version"]:
                chosen = user
        except (OSError, ManifestError):
            pass
    return [_parse_model(m) for m in chosen["models"]]


def get_model(model_id: str, manifest: list[ModelSpec] | None = None) -> ModelSpec:
    for m in manifest or load_manifest():
        if m.id == model_id:
            return m
    raise ManifestError(f"Unknown model id: {model_id}")


def default_model(manifest: list[ModelSpec] | None = None) -> ModelSpec:
    models = manifest or load_manifest()
    if not models:
        raise ManifestError("Manifest contains no models.")
    return models[0]
