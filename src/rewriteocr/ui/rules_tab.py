"""Rules tab: pre-extraction region drawing on a representative page with
scope selection (all/odd/even/range/single), a three-page preview, and
region profiles for document series."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from rewriteocr.core import profiles
from rewriteocr.core.rules import RuleError, parse_range
from rewriteocr.ui.canvas.controller import RegionController
from rewriteocr.ui.canvas.view import AnnotationView
from rewriteocr.ui.state import ProjectContext

RULE_KINDS = ("exclude", "column")


class PreviewDialog(QDialog):
    """Render the region overlay on first, middle, and last page of the
    scope so the user sees where boxes land before running 300 pages."""

    def __init__(self, context: ProjectContext, sample_pages: list[int], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Region preview")
        self.resize(1000, 480)
        layout = QHBoxLayout(self)
        for index in sample_pages:
            column = QVBoxLayout()
            column.addWidget(QLabel(f"Page {index + 1}"), alignment=Qt.AlignHCenter)
            controller = RegionController(context, mode="global")
            view = AnnotationView(controller.scene)
            view.setInteractive(False)
            controller.page_displayed.connect(lambda _i, v=view: v.fit_page())
            controller.set_page(index)
            column.addWidget(view, 1)
            layout.addLayout(column)
            # Keep the controller alive alongside its view.
            view._preview_controller = controller


class RulesTab(QWidget):
    def __init__(self, context: ProjectContext) -> None:
        super().__init__()
        self.context = context

        self.scope_combo = QComboBox()
        for label, value in (
            ("All pages", "all"), ("Odd pages", "odd"), ("Even pages", "even"),
            ("Page range", "range"), ("Single page", "single"),
        ):
            self.scope_combo.addItem(label, value)
        self.scope_arg_edit = QLineEdit()
        self.scope_arg_edit.setPlaceholderText("12-48")
        self.scope_arg_edit.setMaximumWidth(90)
        self.scope_arg_edit.setEnabled(False)
        self.scope_combo.currentIndexChanged.connect(
            lambda: self.scope_arg_edit.setEnabled(
                self.scope_combo.currentData() in ("range", "single")
            )
        )

        self.controller = RegionController(
            context, mode="global", scope_provider=self._current_scope
        )
        self.controller.regions_edited.connect(self._refresh_note)

        layout = QVBoxLayout(self)
        tools = QHBoxLayout()
        tools.addWidget(QLabel("Page:"))
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.valueChanged.connect(self._on_page_changed)
        tools.addWidget(self.page_spin)
        tools.addWidget(QLabel("Scope for new regions:"))
        tools.addWidget(self.scope_combo)
        tools.addWidget(self.scope_arg_edit)
        tools.addWidget(QLabel("Draw:"))
        self._buttons: dict[str, QToolButton] = {}
        for kind in RULE_KINDS:
            btn = QToolButton()
            btn.setText(kind)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, k=kind: self._pick_kind(k, checked))
            tools.addWidget(btn)
            self._buttons[kind] = btn
        delete_btn = QPushButton("Delete selected")
        delete_btn.clicked.connect(self.controller.delete_selected)
        tools.addWidget(delete_btn)
        tools.addStretch(1)
        layout.addLayout(tools)

        actions = QHBoxLayout()
        preview_btn = QPushButton("Preview on three pages")
        preview_btn.clicked.connect(self._preview)
        actions.addWidget(preview_btn)
        save_profile_btn = QPushButton("Save as profile...")
        save_profile_btn.clicked.connect(self._save_profile)
        actions.addWidget(save_profile_btn)
        self.profile_combo = QComboBox()
        actions.addWidget(self.profile_combo)
        apply_profile_btn = QPushButton("Apply profile")
        apply_profile_btn.clicked.connect(self._apply_profile)
        actions.addWidget(apply_profile_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.note_label = QLabel(
            "Optional: draw exclude boxes over headers, footers, and margin"
            " notes, or column boxes to fix reading order. Odd and even scopes"
            " handle mirrored book margins."
        )
        self.note_label.setWordWrap(True)
        layout.addWidget(self.note_label)

        self.view = AnnotationView(self.controller.scene)
        layout.addWidget(self.view, 1)
        self.controller.page_displayed.connect(lambda _i: self.view.fit_page())

        # Canvas renders are deferred until this tab is actually visible:
        # rendering during project open blocks the GUI thread on the global
        # PDFium lock while the thumbnail loader is running.
        self._pending_page: int | None = None
        context.project_opened.connect(self._on_project_opened)
        self._reload_profiles()

    def _current_scope(self) -> tuple[str, str | None]:
        scope = self.scope_combo.currentData()
        arg = self.scope_arg_edit.text().strip() or None
        if scope in ("range", "single"):
            try:
                parse_range(arg)
            except RuleError:
                fallback = str(self.page_spin.value())
                arg = fallback
        else:
            arg = None
        return scope, arg

    def _pick_kind(self, kind: str, checked: bool) -> None:
        for k, btn in self._buttons.items():
            if k != kind:
                btn.setChecked(False)
        self.controller.set_draw_kind(kind if checked else None)

    def _on_project_opened(self) -> None:
        if not self.context.is_open:
            return
        self.page_spin.setMaximum(max(1, self.context.doc.page_count))
        self.page_spin.setValue(1)
        self._show_or_defer(0)

    def _on_page_changed(self, value: int) -> None:
        if self.context.is_open:
            self._show_or_defer(value - 1)

    def _show_or_defer(self, page_index: int) -> None:
        if self.isVisible():
            self.controller.set_page(page_index)
            self._pending_page = None
        else:
            self._pending_page = page_index

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._pending_page is not None and self.context.is_open:
            pending, self._pending_page = self._pending_page, None
            self.controller.set_page(pending)

    def _refresh_note(self) -> None:
        count = len(self.context.db.list_regions()) if self.context.is_open else 0
        self.note_label.setText(f"{count} region rule(s) defined.")

    def _preview(self) -> None:
        if not self.context.is_open:
            return
        n = self.context.doc.page_count
        samples = sorted({0, n // 2, n - 1})
        PreviewDialog(self.context, samples, self).exec()

    # -- profiles ------------------------------------------------------------

    def _reload_profiles(self) -> None:
        self.profile_combo.clear()
        for profile in profiles.list_profiles():
            self.profile_combo.addItem(profile.name, profile)

    def _save_profile(self) -> None:
        if not self.context.is_open:
            return
        regions = self.context.db.list_regions()
        if not regions:
            QMessageBox.information(self, "Nothing to save", "No regions are defined.")
            return
        name, ok = QInputDialog.getText(self, "Save profile", "Profile name:")
        if not ok or not name.strip():
            return
        try:
            profiles.save_profile(name.strip(), "", regions)
        except profiles.ProfileError as exc:
            QMessageBox.warning(self, "Could not save profile", str(exc))
            return
        self._reload_profiles()

    def _apply_profile(self) -> None:
        profile = self.profile_combo.currentData()
        if profile is None or not self.context.is_open or self.context.read_only:
            return
        for region in profile.regions:
            self.context.db.add_region(region)
        self.controller.reload_regions()
        self.context.regions_changed.emit()
        self._refresh_note()
