"""Diagnostics dialog with a copy button, and the About dialog with bundled
third-party license texts."""

from __future__ import annotations

from importlib import resources

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
)

from rewriteocr import __version__
from rewriteocr.engines.probe import DiagnosticInfo, EnvironmentStatus


class DiagnosticsDialog(QDialog):
    def __init__(self, info: DiagnosticInfo, env: EnvironmentStatus, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Diagnostic info")
        self.setMinimumSize(480, 320)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Include this block in bug reports:"))
        self.text = QPlainTextEdit(info.render(env))
        self.text.setReadOnly(True)
        layout.addWidget(self.text)
        copy_btn = QPushButton("Copy diagnostic info")
        copy_btn.clicked.connect(self._copy)
        layout.addWidget(copy_btn)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.text.toPlainText())


class AboutDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About ReWrite OCR Scanner")
        self.setMinimumSize(560, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"<b>ReWrite OCR Scanner</b> {__version__}<br>"
            "Local PDF OCR to Markdown and DOCX. Everything runs on your machine."
        ))
        tabs = QTabWidget()
        layout.addWidget(tabs)
        try:
            license_dir = resources.files("rewriteocr.resources").joinpath("licenses")
            entries = sorted(license_dir.iterdir(), key=lambda p: p.name)
        except (FileNotFoundError, OSError):
            entries = []
        if not entries:
            tabs.addTab(QLabel("License texts not bundled in this build."), "Licenses")
        for entry in entries:
            view = QPlainTextEdit(entry.read_text(encoding="utf-8"))
            view.setReadOnly(True)
            tabs.addTab(view, entry.name.rsplit(".", 1)[0])
