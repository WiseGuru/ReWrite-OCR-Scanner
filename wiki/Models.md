# Models

Modern OCR is a vision-language model that reads a page image and writes
Markdown directly. The app ships no weights; models download on first use
from Hugging Face, pinned to an exact revision and verified by SHA-256, so
every install gets identical, reproducible weights.

## Available models

| Model | Size (download) | Strengths | License |
|---|---|---|---|
| GLM-OCR 0.9B (default) | about 950 MB plus a 460 MB vision component | two-stage layout plus recognition, strong on tables | MIT |
| LightOnOCR 1B | about 800 MB plus a 420 MB vision component | single-pass page transcription | Apache-2.0 |

Each model offers quality/size options in plain language (the recommended
Q8_0 is near-full quality; F16 is maximum quality at roughly double the
download). The vision component always downloads alongside the model and
is never offered in a reduced-quality form, because degrading it visibly
hurts reading accuracy.

## Downloads

Manage models from the Import tab ("Manage models..."). Downloads show
size and memory figures per option, check free disk space first, resume
where they left off if interrupted, and are hash-verified before use. Each
model's license is shown once and must be acknowledged before its first
use.

## Running without a model

The app is fully usable with no model installed: pages with a real text
layer convert directly, and Tesseract (when installed) reads scanned pages
at lower structural fidelity. When a scanned page needs the vision model,
the app prompts for the download instead of failing.

## GPU and CPU

The model runs through llama.cpp's Vulkan backend, covering NVIDIA, AMD,
and Intel GPUs with one build. If the GPU cannot initialize, or fails
mid-run, the app switches to CPU automatically, tells you, and keeps
going; results are identical, just slower. See [[Troubleshooting]] for
details, and [[Data-Storage]] for where model files live on disk.
