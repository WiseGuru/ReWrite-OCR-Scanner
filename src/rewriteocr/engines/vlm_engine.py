"""VLM OCR engine speaking the OpenAI-compatible chat completions API of the
embedded llama-server. All sampling values come from the model manifest."""

from __future__ import annotations

import base64
import io
import json
import logging
import time
import urllib.error
import urllib.request

from PIL import Image

from rewriteocr.core.models import (
    Capabilities,
    PageHints,
    PageResult,
    RegionHints,
    RegionResult,
)
from rewriteocr.engines.base import EngineCrashedError, EngineError
from rewriteocr.engines.llama_server import LlamaServerManager, ServerState
from rewriteocr.modelmgr.manifest import ModelSpec

log = logging.getLogger("rewriteocr.vlm")

REQUEST_TIMEOUT_S = 600


def _image_to_data_url(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


class VLMEngine:
    """OCREngine implementation backed by a LlamaServerManager."""

    def __init__(self, spec: ModelSpec, server: LlamaServerManager) -> None:
        self.spec = spec
        self.server = server

    @property
    def engine_id(self) -> str:
        return f"vlm:{self.spec.id}"

    def capabilities(self) -> Capabilities:
        return self.spec.capabilities

    def extract_page(self, image: Image.Image, hints: PageHints) -> PageResult:
        text, dt = self._complete(image, self.spec.prompt.page, hints.repeat_penalty_override)
        return PageResult(markdown=text, engine_id=self.engine_id, duration_s=dt)

    def extract_region(self, image: Image.Image, hints: RegionHints) -> RegionResult:
        prompt = self.spec.prompt.table if hints.kind == "table" else self.spec.prompt.region
        text, dt = self._complete(image, prompt, None)
        return RegionResult(markdown=text, engine_id=self.engine_id, duration_s=dt)

    def _complete(
        self, image: Image.Image, prompt: str, repeat_penalty_override: float | None
    ) -> tuple[str, float]:
        if self.server.state is not ServerState.READY:
            raise EngineError("VLM server is not ready.")
        sampling = self.spec.sampling
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": _image_to_data_url(image)}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            "temperature": sampling.temperature,
            "repeat_penalty": repeat_penalty_override or sampling.repeat_penalty,
            "repeat_last_n": sampling.repeat_last_n,
            "max_tokens": sampling.max_tokens,
        }
        req = urllib.request.Request(
            f"{self.server.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            if not self.server.is_alive():
                raise EngineCrashedError(f"llama-server died during request: {detail}") from exc
            raise EngineError(f"VLM request failed ({exc.code}): {detail}") from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            if not self.server.is_alive():
                raise EngineCrashedError(f"llama-server died during request: {exc}") from exc
            raise EngineError(f"VLM request failed: {exc}") from exc
        duration = time.monotonic() - started
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise EngineError(f"Unexpected completion response shape: {body}") from exc
        return text.strip(), duration
