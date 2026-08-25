"""Tab visibility invariant (TR-1): exactly one tab page is ever visible, and
the page strip never drives the tab bar while it repopulates.

Needs an offscreen Qt platform; CI sets QT_QPA_PLATFORM=offscreen for the
whole run.
"""

from __future__ import annotations

import time

import pytest
from conftest import make_born_digital_pdf

QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        try:
            app = QtWidgets.QApplication([])
        except Exception as exc:  # no usable platform plugin
            pytest.skip(f"Qt cannot start here: {exc}")
    return app


@pytest.fixture
def window(qapp):
    from rewriteocr.ui.main_window import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()
    try:
        yield win
    finally:
        win.close()
        qapp.processEvents()


def pump(qapp, window, timeout: float = 60.0) -> None:
    """Run the event loop until the job queue goes idle."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if not window.context.jobs.busy:
            qapp.processEvents()
            return
        time.sleep(0.01)
    raise AssertionError("job queue never went idle")


def visible_pages(window) -> list[str]:
    tabs = window.tabs
    return [
        tabs.tabText(i)
        for i in range(tabs.count())
        if tabs.widget(i) is not None and tabs.widget(i).isVisible()
    ]


def assert_single_page(window) -> None:
    tabs = window.tabs
    current = tabs.tabText(tabs.currentIndex())
    assert visible_pages(window) == [current], (
        f"expected only {current!r} visible, got {visible_pages(window)}"
    )


def test_importing_a_second_pdf_leaves_one_visible_page(qapp, window, tmp_path):
    from rewriteocr.ui.main_window import TAB_EXTRACT

    first = make_born_digital_pdf(tmp_path / "first.pdf", n_pages=3)
    second = make_born_digital_pdf(tmp_path / "second.pdf", n_pages=4)

    selected: list[int] = []
    closed: list[int] = []
    window.strip.page_selected.connect(selected.append)
    window.context.project_closed.connect(lambda: closed.append(1))

    window.import_tab.open_path(first)
    pump(qapp, window)
    assert window.context.is_open
    assert window.tabs.currentIndex() == TAB_EXTRACT
    assert_single_page(window)
    assert closed == [], "nothing was open, so project_closed must not fire"

    # The failing flow: back to Import, then a different, never-opened PDF.
    window.tabs.setCurrentIndex(0)
    qapp.processEvents()
    window.import_tab.open_path(second)
    pump(qapp, window)

    assert window.context.pdf_path == second
    assert window.tabs.currentIndex() == TAB_EXTRACT
    assert_single_page(window)
    assert len(closed) == 1, "project_closed must fire once per open, not twice"
    assert selected == [], "repopulating the strip must not select a page"


def test_reopening_from_the_review_tab_keeps_one_visible_page(qapp, window, tmp_path):
    from rewriteocr.ui.main_window import TAB_REVIEW

    first = make_born_digital_pdf(tmp_path / "a.pdf", n_pages=3)
    second = make_born_digital_pdf(tmp_path / "b.pdf", n_pages=3)

    window.import_tab.open_path(first)
    pump(qapp, window)
    window.tabs.setCurrentIndex(TAB_REVIEW)
    qapp.processEvents()
    assert_single_page(window)

    window.import_tab.open_path(second)
    pump(qapp, window)
    assert_single_page(window)


def test_strip_reload_does_not_emit_page_selected(qapp, window, tmp_path):
    pdf = make_born_digital_pdf(tmp_path / "strip.pdf", n_pages=3)
    window.import_tab.open_path(pdf)
    pump(qapp, window)

    selected: list[int] = []
    window.strip.page_selected.connect(selected.append)
    window.strip.setCurrentRow(1)
    assert selected == [1], "a real selection must still reach the app"

    selected.clear()
    window.strip.reload()
    qapp.processEvents()
    assert selected == [], "reload clears and refills, which moves the current row"


def test_enforcer_hides_a_stray_visible_page(qapp, window):
    from rewriteocr.ui.main_window import TAB_EXPORT

    # Force the fault TR-1 reported: a page visible that is not the current one.
    window.export_tab.show()
    qapp.processEvents()
    assert window.tabs.tabText(TAB_EXPORT) in visible_pages(window)

    window._enforce_single_page()
    assert_single_page(window)


# -- export format selection -------------------------------------------------


def format_keys(window) -> list[str]:
    combo = window.export_tab.fmt_combo
    return [combo.itemData(i) for i in range(combo.count())]


def select_format(window, key: str) -> None:
    combo = window.export_tab.fmt_combo
    index = combo.findData(key)
    assert index >= 0, f"{key} not offered: {format_keys(window)}"
    combo.setCurrentIndex(index)


def open_screenplay_project(qapp, window, tmp_path):
    pdf = make_born_digital_pdf(tmp_path / "script.pdf", n_pages=3)
    window.import_tab.open_path(pdf)
    pump(qapp, window)
    window.import_tab.screenplay_radio.setChecked(True)
    qapp.processEvents()
    return pdf


def test_prose_project_does_not_offer_screenplay_formats(qapp, window, tmp_path):
    pdf = make_born_digital_pdf(tmp_path / "prose.pdf", n_pages=3)
    window.import_tab.open_path(pdf)
    pump(qapp, window)
    assert format_keys(window) == ["markdown", "docx"]


def test_screenplay_mode_offers_the_screenplay_formats(qapp, window, tmp_path):
    open_screenplay_project(qapp, window, tmp_path)
    assert "fountain" in format_keys(window)
    assert "fdx" in format_keys(window)
    assert "screenplay_docx" in format_keys(window)


def test_mode_is_persisted_to_the_sidecar(qapp, window, tmp_path):
    open_screenplay_project(qapp, window, tmp_path)
    assert window.context.db.project_info().document_mode == "screenplay"


def test_format_choice_syncs_the_output_extension(qapp, window, tmp_path):
    open_screenplay_project(qapp, window, tmp_path)
    tab = window.export_tab

    select_format(window, "fountain")
    qapp.processEvents()
    assert tab.path_edit.text().endswith(".fountain")

    select_format(window, "fdx")
    qapp.processEvents()
    assert tab.path_edit.text().endswith(".fdx")

    select_format(window, "markdown")
    qapp.processEvents()
    assert tab.path_edit.text().endswith(".md")


def test_screenplay_formats_disable_the_page_break_option(qapp, window, tmp_path):
    open_screenplay_project(qapp, window, tmp_path)
    tab = window.export_tab

    select_format(window, "fountain")
    qapp.processEvents()
    assert not tab.break_combo.isEnabled()
    assert tab.format_hint.text()

    select_format(window, "markdown")
    qapp.processEvents()
    assert tab.break_combo.isEnabled()
    assert not tab.format_hint.text()
