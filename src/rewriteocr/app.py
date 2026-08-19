"""Application entry point."""

from __future__ import annotations

import logging
import sys
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox

from rewriteocr.logging_setup import setup_logging

log = logging.getLogger("rewriteocr.app")


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
    app = QApplication(sys.argv)
    app.setApplicationName("ReWrite OCR Scanner")
    app.setOrganizationName("ReWriteOCR")
    _install_excepthook()

    from rewriteocr.ui.main_window import MainWindow

    window = MainWindow()
    app.aboutToQuit.connect(window.context.shutdown)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
