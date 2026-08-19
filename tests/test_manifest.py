import json

import pytest

from rewriteocr.config import app_data_dir
from rewriteocr.modelmgr.manifest import (
    ManifestError,
    default_model,
    get_model,
    load_manifest,
)


def test_bundled_manifest_loads_and_is_complete():
    models = load_manifest()
    assert len(models) >= 2
    glm = get_model("glm-ocr-0.9b", models)
    assert glm.revision == "65a42de1148dbed2297e922b5dbc7d9b70c36578"
    assert glm.sampling.repeat_penalty == 1.15
    assert glm.preprocess.dpi == 200
    for quant in glm.quants:
        assert len(quant.sha256) == 64
    assert len(glm.mmproj.sha256) == 64
    assert default_model(models).id == "glm-ocr-0.9b"


def test_file_urls_are_pinned_to_revision():
    glm = get_model("glm-ocr-0.9b")
    url = glm.file_url(glm.quants[0].file)
    assert "/resolve/65a42de1148dbed2297e922b5dbc7d9b70c36578/" in url


def test_unknown_model_raises():
    with pytest.raises(ManifestError):
        get_model("nope")


def test_user_manifest_override(tmp_path):
    user = {
        "manifest_version": 999,
        "models": [
            {
                "id": "test-model",
                "display_name": "Test",
                "description": "d",
                "license": "MIT",
                "license_url": "u",
                "repo": "r/r",
                "revision": "abc",
                "capabilities": {
                    "region_conditioned": True,
                    "layout_detection": False,
                    "bbox_output": False,
                    "min_region_lines": 2,
                    "output_format": "markdown",
                },
                "preprocess": {"dpi": 100, "longest_edge_px": 800, "pad_to_multiple": 0},
                "sampling": {
                    "temperature": 0.1, "repeat_penalty": 1.0,
                    "repeat_last_n": 64, "max_tokens": 500,
                },
                "prompt": {"page": "p", "region": "r", "table": "t"},
                "context_size": 4096,
                "quants": [
                    {"name": "Q4", "label": "l", "file": "f.gguf",
                     "sha256": "0" * 64, "size_mb": 1, "ram_mb": 2}
                ],
                "mmproj": {"file": "m.gguf", "sha256": "1" * 64, "size_mb": 1},
            }
        ],
    }
    (app_data_dir() / "manifest.json").write_text(json.dumps(user), encoding="utf-8")
    models = load_manifest()
    assert [m.id for m in models] == ["test-model"]


def test_corrupt_user_manifest_falls_back_to_bundled():
    (app_data_dir() / "manifest.json").write_text("{not json", encoding="utf-8")
    models = load_manifest()
    assert any(m.id == "glm-ocr-0.9b" for m in models)
