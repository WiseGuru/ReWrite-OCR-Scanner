#!/usr/bin/env bash
# Build the Linux AppImage from an existing PyInstaller one-folder build.
# Usage: scripts/build_appimage.sh <version>
# Requires: dist/rewrite-ocr (from pyinstaller packaging/rewriteocr.spec),
# wget, and FUSE-less extraction support (runs appimagetool with
# --appimage-extract-and-run so no libfuse2 is needed on CI).
set -euo pipefail

VERSION="${1:?usage: build_appimage.sh <version>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
APPDIR="$DIST/AppDir"
TOOL="$DIST/appimagetool-x86_64.AppImage"
# Official appimagetool distribution. The project only publishes a moving
# "continuous" tag (the old AppImageKit/13 assets were removed upstream).
TOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"

[ -d "$DIST/rewrite-ocr" ] || { echo "dist/rewrite-ocr missing; run pyinstaller first" >&2; exit 1; }

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -r "$DIST/rewrite-ocr" "$APPDIR/usr/bin/rewrite-ocr"
cp "$ROOT/packaging/icon.png" "$APPDIR/rewrite-ocr.png"

cat > "$APPDIR/rewrite-ocr.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=ReWrite OCR Scanner
Comment=Local PDF OCR to Markdown and DOCX
Exec=rewrite-ocr
Icon=rewrite-ocr
Categories=Office;Scanning;Utility;
Terminal=false
EOF

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/rewrite-ocr/rewrite-ocr" "$@"
EOF
chmod +x "$APPDIR/AppRun"

if [ ! -f "$TOOL" ]; then
  wget -q -O "$TOOL" "$TOOL_URL"
  chmod +x "$TOOL"
fi

OUT="$DIST/ReWrite-OCR-Scanner-$VERSION-x86_64.AppImage"
ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$APPDIR" "$OUT"
echo "built $OUT"
