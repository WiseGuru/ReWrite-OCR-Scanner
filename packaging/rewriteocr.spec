# PyInstaller one-folder build.
# Build from the repo root with the project installed in the environment:
#   pyinstaller --noconfirm packaging/rewriteocr.spec
#
# Output: dist/rewrite-ocr/ (one folder, entry executable rewrite-ocr).
# Model weights are never bundled (downloaded at runtime). llama-server and
# tesseract are detected on the system; a distribution build may place
# prebuilt binaries next to the executable instead.

from pathlib import Path

repo_root = Path(SPECPATH).parent
src = repo_root / "src"

datas = [(str(src / "rewriteocr" / "resources"), "rewriteocr/resources")]

a = Analysis(
    [str(src / "rewriteocr" / "app.py")],
    pathex=[str(src)],
    datas=datas,
    hiddenimports=[],
    excludes=[
        "tkinter",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.Qt3DCore",
        "PySide6.QtMultimedia",
        "PySide6.QtCharts",
        "PySide6.QtPdf",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="rewrite-ocr",
    console=False,
    icon=str(repo_root / "packaging" / "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="rewrite-ocr",
)
