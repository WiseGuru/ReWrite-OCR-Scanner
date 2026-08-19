# Releasing

Prerelease-first and tag-driven: every stable release is a previously
published prerelease that passed real testing, plus only a version bump. CI
builds and attests all assets; never hand-upload an asset.

## Project specifics

- **Version owner**: `src/rewriteocr/__init__.py` (`__version__`).
  `pyproject.toml` reads it dynamically; nothing else states the version.
- **Tags**: bare version for stable (`0.2.0`, no `v` prefix). Any tag
  containing `-` publishes as a prerelease (`0.2.0-alpha`, `0.2.0-beta.2`).
  CI refuses a stable tag that does not equal `__version__`.
- **Assets** (built by `.github/workflows/release.yml` on both platforms):
  - `ReWrite-OCR-Scanner-Setup-<tag>.exe` (Windows installer, Inno Setup)
  - `ReWrite-OCR-Scanner-<tag>-windows-x64.zip` (portable folder)
  - `ReWrite-OCR-Scanner-<tag>-x86_64.AppImage` (Linux)
  - `ReWrite-OCR-Scanner-<tag>-linux-x64.tar.gz` (portable folder)
- **Not in the assets**: model weights (downloaded at runtime, pinned and
  hash-verified), llama-server, and Tesseract (detected on the system; see
  README requirements).
- CI runs the license gate and the test suite before building; a red gate
  blocks the release.

## Procedure

1. **Prerelease.** On `main`, clean tree, everything to ship committed. Do
   NOT bump `__version__` yet.

   ```
   git tag -a 0.2.0-alpha -m "Pre-release 0.2.0-alpha"
   git push origin 0.2.0-alpha
   ```

2. **Test the published prerelease assets**, not a local build:
   - Windows: download the Setup exe from the prerelease page, install,
     open a scanned PDF, extract on GPU, review a page, export both
     formats, uninstall.
   - Linux: `chmod +x` the AppImage and run the same pass.
   - Confirm the About dialog shows the prerelease tag as its version.

   Fixes go to `main` and get a further suffixed tag (`0.2.0-alpha.2`,
   `0.2.0-beta`). Re-test what changed plus a clean open.

3. **Stable.** Only after a green pass, and with no artifact-affecting
   commits since the tested prerelease tag (doc-only commits are fine):

   ```
   # bump __version__ in src/rewriteocr/__init__.py to 0.2.0
   git commit -am "0.2.0"
   git tag -a 0.2.0 -m "Release 0.2.0"
   git push origin HEAD
   git push origin 0.2.0
   ```

4. **Verify.**

   ```
   gh run watch --exit-status
   gh release download 0.2.0 --dir %TEMP%\rel --clobber
   gh attestation verify %TEMP%\rel\ReWrite-OCR-Scanner-Setup-0.2.0.exe --repo WiseGuru/ReWrite-OCR-Scanner
   ```

   The release page must show the bare tag with all four assets and the
   attestation check must exit 0.

## Local build (for development only, never for publishing)

```
pip install pyinstaller
pyinstaller --noconfirm packaging/rewriteocr.spec     # dist/rewrite-ocr/
iscc /DAppVersion=dev packaging/installer.iss          # Windows installer
bash scripts/build_appimage.sh dev                     # Linux AppImage
```
