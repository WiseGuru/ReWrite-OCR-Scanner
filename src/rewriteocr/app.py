"""Application entry point."""

from __future__ import annotations

import logging
import sys
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox

from rewriteocr.logging_setup import setup_logging

log = logging.getLogger("rewriteocr.app")


def _set_window_icon(app: QApplication) -> None:
    from importlib import resources

    from PySide6.QtGui import QIcon

    try:
        icon_res = resources.files("rewriteocr.resources").joinpath("icon.png")
        with resources.as_file(icon_res) as path:
            app.setWindowIcon(QIcon(str(path)))
    except (OSError, FileNotFoundError):
        log.warning("Window icon resource missing; using the platform default.")


def _install_excepthook() -> None:
    def hook(exc_type, exc, tb) -> None:
        detail = "".join(traceback.format_exception(exc_type, exc, tb))
        log.critical("Unhandled exception:\n%s", detail)
        try:
            QMessageBox.critical(
                None,
                "Unexpected error",
                "Something went wrong. Your progress is saved in the project"
                f" file.\n\n{exc}",
            )
        except Exception:
            pass

    sys.excepthook = hook


def main() -> int:
    setup_logging()
    from rewriteocr.config import clean_stale_temp

    clean_stale_temp()
    if sys.platform == "win32":
        # Give the process its own taskbar identity; otherwise Windows
        # groups the window under the Python interpreter's icon.
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "ReWriteOCR.Scanner"
        )
    app = QApplication(sys.argv)
    app.setApplicationName("ReWrite OCR Scanner")
    app.setOrganizationName("ReWriteOCR")
    _set_window_icon(app)
    _install_excepthook()

    from rewriteocr.ui.main_window import MainWindow

    window = MainWindow()
    app.aboutToQuit.connect(window.context.shutdown)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
