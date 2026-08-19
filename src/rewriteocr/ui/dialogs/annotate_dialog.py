"""Per-page annotation dialog: the same canvas as global rules, page-scoped,
reached from a review failure. Regions drawn here apply to this page only."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
)

from rewriteocr.ui.canvas.controller import RegionController
from rewriteocr.ui.canvas.view import AnnotationView
from rewriteocr.ui.state import ProjectContext

KINDS = ("exclude", "table", "figure", "column", "heading")


class AnnotateDialog(QDialog):
    def __init__(self, context: ProjectContext, page_index: int, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self.page_index = page_index
        self.wants_reextract = False
        self.setWindowTitle(f"Annotate page {page_index + 1}")
        self.resize(900, 700)

        self.heading_spin = QSpinBox()
        self.heading_spin.setRange(1, 6)
        self.controller = RegionController(
            context, mode="page",
            heading_level_provider=lambda: self.heading_spin.value(),
        )

        layout = QVBoxLayout(self)
        tools = QHBoxLayout()
        tools.addWidget(QLabel("Draw:"))
        self._group = QButtonGroup(self)
        self._group.setExclusive(False)
        self._buttons: dict[str, QToolButton] = {}
        for kind in KINDS:
            btn = QToolButton()
            btn.setText(kind)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, k=kind: self._pick_kind(k, checked))
            tools.addWidget(btn)
            self._buttons[kind] = btn
        tools.addWidget(QLabel("Heading level:"))
        tools.addWidget(self.heading_spin)
        delete_btn = QPushButton("Delete selected")
        delete_btn.clicked.connect(self.controller.delete_selected)
        tools.addWidget(delete_btn)
        up_btn = QPushButton("Order up")
        up_btn.clicked.connect(lambda: self.controller.move_selected(-1))
        tools.addWidget(up_btn)
        down_btn = QPushButton("Order down")
        down_btn.clicked.connect(lambda: self.controller.move_selected(1))
        tools.addWidget(down_btn)
        tools.addStretch(1)
        layout.addLayout(tools)

        hint = QLabel(
            "Draw regions on the page. Numbers show the explicit reading order;"
            " column regions are read in that order. Region edges snap outward"
            " to detected text lines so no line is cut mid-sentence."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        if not context.env.has_tesseract:
            self.controller.snap_enabled = False
            snap_note = QLabel(
                "Edge snapping is off because Tesseract is not installed."
            )
            layout.addWidget(snap_note)

        self.view = AnnotationView(self.controller.scene)
        layout.addWidget(self.view, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        reextract_btn = QPushButton("Re-extract this page")
        reextract_btn.setDefault(True)
        reextract_btn.clicked.connect(self._reextract)
        reextract_btn.setEnabled(not context.read_only)
        buttons.addWidget(close_btn)
        buttons.addWidget(reextract_btn)
        layout.addLayout(buttons)

        self.controller.page_displayed.connect(lambda _i: self.view.fit_page())
        self.controller.set_page(page_index)

    def _pick_kind(self, kind: str, checked: bool) -> None:
        for k, btn in self._buttons.items():
            if k != kind:
                btn.setChecked(False)
        self.controller.set_draw_kind(kind if checked else None)

    def _reextract(self) -> None:
        self.wants_reextract = True
        self.accept()
