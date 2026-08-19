# Installation

## Windows

1. Download `ReWrite-OCR-Scanner-Setup-<version>.exe` from the latest
   release and run it. (A portable `.zip` is also published if you prefer
   no installer.)
2. Install llama.cpp, which provides the local AI runtime:
   `winget install ggml.llamacpp`. The default build uses Vulkan and works
   on NVIDIA, AMD, and Intel GPUs; without a usable GPU the app falls back
   to CPU automatically.
3. Optional but recommended: install Tesseract,
   `winget install UB-Mannheim.TesseractOCR`. It powers the accuracy
   cross-check, region edge snapping, and a fallback OCR engine.

## Linux

1. Download `ReWrite-OCR-Scanner-<version>-x86_64.AppImage`, make it
   executable (`chmod +x`), and run it. (A portable `.tar.gz` is also
   published.)
2. Install llama.cpp so `llama-server` is on your PATH (distribution
   package, or a release from the llama.cpp project).
3. Optional but recommended: install Tesseract from your distribution
   (`sudo apt install tesseract-ocr` or equivalent).

## From source (development)

```
git clone https://github.com/WiseGuru/ReWrite-OCR-Scanner
cd ReWrite-OCR-Scanner
python -m venv .venv
.venv/bin/pip install -e ".[dev]"    # .venv\Scripts\pip on Windows
rewrite-ocr
```

## First run

The app works immediately for PDFs that already contain text. The first
time you open a document with scanned pages, it offers to download an OCR
model (about 1.4 GB for the recommended option); see [[Models]]. Downloads
resume if interrupted and are verified before use.
