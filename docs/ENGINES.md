# Engines and model management

Update this doc in the same change as any behavior it describes.

## Engine interface (`engines/base.py`)

`OCREngine` protocol: `capabilities()`, `extract_page()`,
`extract_region()`. UI features gate on `Capabilities`; a missing
capability disables the control with a tooltip naming the reason, never a
silent degrade. Adding a model later is a manifest change, not a refactor.

## Model manifest (`modelmgr/manifest.py`, `resources/manifest.json`)

The single source of truth for model files, pinned HF revisions, SHA-256
hashes, sampling, preprocessing, prompts, and capabilities. **Nothing
downstream may hardcode a sampling or preprocess value**; wrong sampling is
the direct cause of the looping failure. A user copy at
`<app data>/manifest.json` overrides the bundled one when its
`manifest_version` is equal or newer; a corrupt user copy falls back to
bundled.

Pinned models: ggml-org/GLM-OCR-GGUF (default, MIT) and
ggml-org/LightOnOCR-1B-1025-GGUF (Apache-2.0; the spec named
LightOnOCR-2-1B, which has no official GGUF, so v1 of that model is
pinned instead). mmproj files ship Q8_0 from upstream and are never
quantized by us or offered as a user option.

## llama-server lifecycle (`engines/llama_server.py`)

`LlamaServerManager` owns the subprocess; nothing else talks to it, and the
VLM engine only sees a base URL.

- Port: probe-bind upward from `constants.DEFAULT_PORT_BASE` (**18131**).
  18099 and 18110 belong to other local pipelines on dev machines; never
  use them here.
- Start: `-m <quant> --mmproj <mmproj> -ngl 99 --ctx-size <manifest>
  --no-webui`, `CREATE_NO_WINDOW` on Windows, output to
  `logs/llama-server.log`. Health-poll `/health` (180s budget for first
  load), then an **identity check** against `/props`: the served model file
  must equal the pinned quant name, or the manager hard-fails rather than
  use an unidentified listener.
- GPU failure at start falls back automatically to a CPU start
  (`-ngl 0`) with a visible device notice; mid-run crashes go through the
  pipeline's restart-on-CPU path (see docs/PIPELINE.md).
- Teardown is one idempotent `stop()` (terminate, 5s wait, then
  `taskkill /T /F` on Windows or kill), wired to context-manager exit,
  `atexit`, and app shutdown. Never leave an orphaned server.

## VLM engine (`engines/vlm_engine.py`)

OpenAI-compatible `/v1/chat/completions` with a base64 PNG data URL and the
manifest prompt (`page`/`region`/`table`). Sampling comes from the manifest;
the only per-request override is `repeat_penalty` for the review tab's
"retry at higher penalty" action (+0.25 over manifest). A dead server maps
to `EngineCrashedError` so the pipeline can distinguish crash from bad
request.

## Tesseract (`engines/tesseract_engine.py`)

Subprocess only (no pytesseract). Found via settings override, PATH, then
the standard Windows install dirs; fully optional. Three roles:

1. Fallback OCR engine (page PSM 3, region PSM 6).
2. Cross-check text for the `engine_disagreement` flag (run on CPU in
   parallel with the VLM).
3. Geometry oracle: TSV level-4 rows give normalized text-line boxes,
   used for the `min_region_lines` auto-switch and for region edge
   snapping (`snap_outward`: expand a box so no detected line is cut;
   column regions keep their horizontal edges because a horizontal cut is
   the user's intent).

## Downloader and store (`modelmgr/downloader.py`, `store.py`)

stdlib urllib, pinned `resolve/<revision>/<file>` URLs. Resumes into
`<file>.part` with a Range header (re-hashing the existing part first so
the streaming SHA-256 always covers every byte), verifies against the
manifest hash, renames atomically. Disk-space precheck with a 500 MB
margin. Cancel keeps the `.part` for resume; a hash mismatch discards it.
Store layout: `models/<model-id>/<file>`; `licenses.py` records the
one-time per-model license acknowledgment required before first use.

## Layout engine (`engines/layout_engine.py`)

Interface plus `NullLayoutEngine` only. PP-DocLayout-V3 integration
(auto-proposed regions) is deferred by the spec; this seam is where it
plugs in without a refactor, and no Paddle dependency ships until then.
