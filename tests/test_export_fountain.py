"""Fountain export.

Fixture text is ASCII only; scripts/check_dashes.py fails the build on an em
or en dash, and screenplay dialogue is full of them. Two hyphens is the
convention screenwriters type anyway.
"""

from __future__ import annotations

import pytest

from rewriteocr.core.models import ExportOptions, PageRecord
from rewriteocr.core.screenplay import parse_screenplay
from rewriteocr.core.sidecar import SidecarDB
from rewriteocr.pipeline.export_screenplay import export_fountain, render_fountain

SCRIPT_PAGES = [
    "Title: The Long Goodbye\nAuthor: Jane Doe",
    "FADE IN:\n\nINT. KITCHEN - DAY\n\nMARLOWE stands at the window.\n\n"
    "MARLOWE\n(quietly)\nYou should not have come here.\n\nCUT TO:",
    "EXT. ROOFTOP - NIGHT\n\nTERRY\nThis is where it ends -- for both of us.",
]


@pytest.fixture
def sidecar(tmp_path):
    db = SidecarDB(tmp_path / "d.ocrproj")
    db.initialize("h", "d.pdf", len(SCRIPT_PAGES))
    db.insert_pages(
        [
            PageRecord(page_index=i, classification="scanned", width_pt=612, height_pt=792)
            for i in range(len(SCRIPT_PAGES))
        ]
    )
    for i, text in enumerate(SCRIPT_PAGES):
        db.write_page_result(i, text, "vlm", None, None, [])
    yield db
    db.close()


def render(page_break: str = "none") -> str:
    return render_fountain(parse_screenplay(SCRIPT_PAGES), page_break)


def test_every_element_uses_its_forcing_character():
    out = render()
    assert ".INT. KITCHEN - DAY" in out
    assert "!MARLOWE stands at the window." in out
    assert "@MARLOWE" in out
    assert "> CUT TO:" in out
    # Parenthetical and dialogue have no forcing character in the syntax and
    # need none: the cue above them is forced with @.
    assert "\n(quietly)\n" in out
    assert "\nYou should not have come here.\n" in out


def test_a_speech_has_no_internal_blank_lines():
    # A blank line here would end the speech and orphan the dialogue, which a
    # Fountain parser then reads as action.
    out = render()
    assert "@MARLOWE\n(quietly)\nYou should not have come here." in out


def test_title_page_precedes_the_body():
    out = render()
    lines = out.split("\n")
    assert lines[0] == "Title: The Long Goodbye"
    assert lines[1] == "Author: Jane Doe"
    assert lines[2] == ""


def test_page_break_marker_follows_the_option():
    assert "\n===\n" in render("rule")
    assert "===" not in render("none")


def test_page_break_is_its_own_block():
    out = render("rule")
    assert "\n\n===\n\n" in out


EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


def test_no_unicode_dashes_are_emitted():
    # Built with chr(), not written literally: scripts/check_dashes.py scans
    # this file too and would fail on a literal, which is what it did the
    # first time round.
    out = render()
    assert EM_DASH not in out
    assert EN_DASH not in out


def test_notes_and_boneyard_are_defused():
    pages = ["He reads the sign [[ WET PAINT ]] and stops. /* not a comment */"]
    out = render_fountain(parse_screenplay(pages), "none")
    assert "[[" not in out
    assert "]]" not in out
    assert "/*" not in out
    assert "*/" not in out


def test_dual_dialogue_caret_is_emitted():
    pages = ["@STEEL ^\nGo!"]
    out = render_fountain(parse_screenplay(pages), "none")
    assert "@STEEL ^" in out


def test_round_trip_is_idempotent():
    """Re-parsing our own Fountain gives the same element sequence. This is
    what the forcing characters buy, and it is a strong regression net."""
    first = parse_screenplay(SCRIPT_PAGES)
    fountain = render_fountain(first, "none")
    second = parse_screenplay([fountain])
    assert [el.type for el in second.elements] == [el.type for el in first.elements]
    assert [el.text for el in second.elements] == [el.text for el in first.elements]
    assert second.title.fields == first.title.fields


def test_export_writes_the_file(sidecar, tmp_path):
    out = tmp_path / "script.fountain"
    log = export_fountain(sidecar, None, out, ExportOptions(fmt="fountain", stitch=False))
    text = out.read_text(encoding="utf-8")
    assert text.startswith("Title: The Long Goodbye")
    assert ".INT. KITCHEN - DAY" in text
    assert log.screenplay is not None
    assert log.screenplay.counts["character"] == 2
    # No source PDF was passed, so no geometry was available.
    assert log.screenplay.geometry_pages == 0
