"""Annotation canvas controller tests (offscreen Qt via pytest-qt)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRectF

from rewriteocr.core.pdf_io import sha256_of_file
from rewriteocr.core.sidecar import SidecarDB
from rewriteocr.engines.tesseract_engine import LineBox, snap_outward
from rewriteocr.jobs.control import JobControl
from rewriteocr.pipeline.extract import NullReporter, run_triage
from rewriteocr.ui.canvas.controller import RegionController
from rewriteocr.ui.state import ProjectContext


@pytest.fixture
def context(qtbot, born_digital_pdf, tmp_path):
    ctx = ProjectContext()
    sc_path = tmp_path / "canvas.ocrproj"
    with SidecarDB(sc_path) as db:
        db.initialize(sha256_of_file(born_digital_pdf), "born.pdf", 6)
        run_triage(born_digital_pdf, db, JobControl(), NullReporter())
    ctx.attach_project(born_digital_pdf, sc_path, None)
    yield ctx
    ctx.shutdown()


def _controller(context, qtbot, mode="page"):
    c = RegionController(context, mode=mode)
    c.snap_enabled = False  # geometry-only tests
    # set_page is asynchronous: the pixmap lands via the render worker.
    with qtbot.waitSignal(c.page_displayed, timeout=10_000):
        c.set_page(0)
    return c


def test_create_region_persists_normalized_coords(context, qtbot):
    controller = _controller(context, qtbot)
    bounds = controller.page_bounds()
    rect = QRectF(bounds.width() * 0.1, bounds.height() * 0.2,
                  bounds.width() * 0.5, bounds.height() * 0.3)
    controller.create_region_from_rect(rect, "column")
    regions = context.db.list_regions()
    assert len(regions) == 1
    r = regions[0]
    assert r.kind == "column"
    assert r.scope == "single" and r.scope_arg == "1"
    assert r.x0 == pytest.approx(0.1, abs=0.01)
    assert r.y0 == pytest.approx(0.2, abs=0.01)
    assert r.x1 == pytest.approx(0.6, abs=0.01)
    assert r.y1 == pytest.approx(0.5, abs=0.01)


def test_items_loaded_and_reorder(context, qtbot):
    controller = _controller(context, qtbot)
    bounds = controller.page_bounds()
    for i in range(2):
        controller.create_region_from_rect(
            QRectF(10, 10 + i * 60, bounds.width() * 0.4, 50), "column"
        )
    regions = context.db.list_regions()
    assert [r.order_index for r in regions] == [0, 1]
    first = controller._items[regions[0].id]
    controller.scene.clearSelection()
    first.setSelected(True)
    controller.move_selected(1)
    regions_after = {r.id: r.order_index for r in context.db.list_regions()}
    assert regions_after[regions[0].id] == 1
    assert regions_after[regions[1].id] == 0


def test_delete_selected(context, qtbot):
    controller = _controller(context, qtbot)
    controller.create_region_from_rect(QRectF(10, 10, 100, 60), "exclude")
    region_id = context.db.list_regions()[0].id
    controller._items[region_id].setSelected(True)
    controller.delete_selected()
    assert context.db.list_regions() == []


def test_geometry_commit_updates_db(context, qtbot):
    controller = _controller(context, qtbot)
    controller.create_region_from_rect(QRectF(10, 10, 100, 60), "figure")
    region_id = context.db.list_regions()[0].id
    item = controller._items[region_id]
    item.setPos(item.pos().x() + 50, item.pos().y() + 40)
    controller.item_geometry_committed(item)
    r = context.db.list_regions()[0]
    bounds = controller.page_bounds()
    assert r.x0 == pytest.approx(60 / bounds.width(), abs=0.01)
    assert r.y0 == pytest.approx(50 / bounds.height(), abs=0.01)


def test_snap_outward_expands_to_cover_cut_lines():
    lines = [LineBox(0.1, 0.10, 0.9, 0.14), LineBox(0.1, 0.20, 0.9, 0.24)]
    # Box vertically slicing through the first line.
    x0, y0, x1, y1 = snap_outward(0.2, 0.12, 0.8, 0.30, lines)
    assert y0 == pytest.approx(0.10)
    assert y1 == pytest.approx(0.30)
    assert x0 == pytest.approx(0.1)
    # Column regions keep their horizontal edges.
    x0, _, x1, _ = snap_outward(0.2, 0.12, 0.8, 0.30, lines, snap_x=False)
    assert x0 == pytest.approx(0.2)
    assert x1 == pytest.approx(0.8)


def test_global_mode_uses_scope_provider(context, qtbot):
    controller = RegionController(
        context, mode="global", scope_provider=lambda: ("odd", None)
    )
    controller.snap_enabled = False
    with qtbot.waitSignal(controller.page_displayed, timeout=10_000):
        controller.set_page(0)
    controller.create_region_from_rect(QRectF(10, 10, 100, 60), "exclude")
    r = context.db.list_regions()[0]
    assert r.scope == "odd"
