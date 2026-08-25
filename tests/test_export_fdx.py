"""Final Draft XML export.

The expected shapes here were taken from real Final Draft exports, not from
recollection: the root attributes, the Type strings, and that <Text> nests
directly inside <Paragraph> with no wrapper element.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fdxcheck import check_file

from rewriteocr.core.models import ExportOptions, PageRecord
from rewriteocr.core.screenplay import parse_screenplay
from rewriteocr.core.sidecar import SidecarDB
from rewriteocr.pipeline.export_screenplay import dual_groups, export_fdx, render_fdx

DATA = Path(__file__).parent / "data" / "fdx"

SCRIPT_PAGES = [
    "FADE IN:\n\nINT. KITCHEN - DAY\n\nMARLOWE stands at the window.\n\n"
    "MARLOWE\n(quietly)\nYou should not have come here.\n\nCUT TO:",
]


@pytest.fixture
def sidecar(tmp_path):
    db = SidecarDB(tmp_path / "d.ocrproj")
    db.initialize("h", "d.pdf", 1)
    db.insert_pages(
        [PageRecord(page_index=0, classification="scanned", width_pt=612, height_pt=792)]
    )
    db.write_page_result(0, SCRIPT_PAGES[0], "vlm", None, None, [])
    yield db
    db.close()


def render() -> bytes:
    return render_fdx(parse_screenplay(SCRIPT_PAGES))


def test_declaration_is_exact():
    # ElementTree cannot emit standalone="no", so this is written by hand and
    # must keep matching what Final Draft itself produces.
    assert render().startswith(
        b'<?xml version="1.0" encoding="UTF-8" standalone="no" ?>\n'
    )


def test_root_attributes():
    root = ET.fromstring(render().decode("utf-8"))
    assert root.tag == "FinalDraft"
    assert root.get("DocumentType") == "Script"
    assert root.get("Template") == "No"
    assert root.get("Version") == "3"
    assert [child.tag for child in root] == ["Content"]


def test_paragraph_type_sequence():
    root = ET.fromstring(render().decode("utf-8"))
    assert [p.get("Type") for p in root.iter("Paragraph")] == [
        "Action",  # FADE IN: is Action in a real Final Draft export
        "Scene Heading",
        "Action",
        "Character",
        "Parenthetical",
        "Dialogue",
        "Transition",
    ]


def test_text_nests_directly_in_paragraph():
    root = ET.fromstring(render().decode("utf-8"))
    for para in root.iter("Paragraph"):
        children = list(para)
        assert [c.tag for c in children] == ["Text"]
        assert not list(children[0])


def test_paragraph_text_content():
    root = ET.fromstring(render().decode("utf-8"))
    texts = [p.find("Text").text for p in root.iter("Paragraph")]
    assert texts[1] == "INT. KITCHEN - DAY"
    assert texts[3] == "MARLOWE"
    assert texts[5] == "You should not have come here."


def test_xml_special_characters_round_trip():
    pages = ["Smith & Wesson is < the answer > for him."]
    root = ET.fromstring(render_fdx(parse_screenplay(pages)).decode("utf-8"))
    assert root.find("Content/Paragraph/Text").text == (
        "Smith & Wesson is < the answer > for him."
    )


def test_title_fields_become_leading_general_paragraphs():
    # The real <TitlePage> is a HeaderAndFooter plus centered paragraphs with
    # layout attributes, not Fountain's key/value pairs, and no sample was
    # available to verify it. General paragraphs open correctly instead.
    pages = ["Title: The Long Goodbye\nAuthor: Jane Doe", "INT. KITCHEN - DAY"]
    root = ET.fromstring(render_fdx(parse_screenplay(pages)).decode("utf-8"))
    paragraphs = list(root.iter("Paragraph"))
    assert paragraphs[0].get("Type") == "General"
    assert paragraphs[0].find("Text").text == "Title: The Long Goodbye"
    assert root.find("TitlePage") is None


def test_export_writes_the_file(sidecar, tmp_path):
    out = tmp_path / "script.fdx"
    log = export_fdx(sidecar, None, out, ExportOptions(fmt="fdx", stitch=False))
    root = ET.parse(out).getroot()
    assert root.tag == "FinalDraft"
    assert log.screenplay is not None


# -- dual dialogue -----------------------------------------------------------

# Fountain marks the pair with a caret on the second cue.
DUAL_PAGE = (
    "INT. DINER - NIGHT\n\n"
    "MARA\n(overlapping)\nI am not doing this again.\n\n"
    "DELL ^\nYou already did.\n\n"
    "CUT TO:"
)


def dual_root():
    return ET.fromstring(render_fdx(parse_screenplay([DUAL_PAGE])).decode("utf-8"))


def only_dual(root):
    """The single <DualDialogue> in a rendered script. Found by looking for
    the child rather than by position, since the wrapper is not first."""
    blocks = [
        p.find("DualDialogue")
        for p in root.find("Content")
        if p.find("DualDialogue") is not None
    ]
    assert len(blocks) == 1
    return blocks[0]


def test_dual_wrapper_is_untyped_and_holds_only_dualdialogue():
    """The wrapper is the trap: no Type, no <Text> of its own. A parser that
    reads Type off Content's direct children gets None here."""
    content = dual_root().find("Content")
    wrappers = [p for p in content if p.find("DualDialogue") is not None]
    assert len(wrappers) == 1
    wrapper = wrappers[0]
    assert wrapper.get("Type") is None
    assert wrapper.find("Text") is None
    assert [child.tag for child in wrapper] == ["DualDialogue"]


def test_dual_children_are_a_flat_sequence_of_both_speakers():
    # Flat, not two nested columns: left speaker first, then right.
    dual = only_dual(dual_root())
    assert [p.get("Type") for p in dual] == [
        "Character",
        "Parenthetical",
        "Dialogue",
        "Character",
        "Dialogue",
    ]
    assert [p.find("Text").text for p in dual] == [
        "MARA",
        "(overlapping)",
        "I am not doing this again.",
        "DELL",
        "You already did.",
    ]


def test_the_caret_is_not_written_into_the_name():
    assert only_dual(dual_root())[3].find("Text").text == "DELL"


def test_dual_block_does_not_double_count_paragraphs():
    """`.//Paragraph` yields the inner paragraphs plus the wrapper. Direct
    children of Content must count the wrapper exactly once."""
    content = dual_root().find("Content")
    top = [p for p in content if p.tag == "Paragraph"]
    # scene heading, the dual wrapper, transition.
    assert len(top) == 3
    assert [p.get("Type") for p in top] == ["Scene Heading", None, "Transition"]


def test_matches_the_reference_sample_structure():
    """Our wrapper shape must match a known-good file element for element."""
    reference = ET.parse(DATA / "minimal-dual-dialogue.fdx").getroot()
    ref_dual = reference.find("Content/Paragraph/DualDialogue")
    ours = only_dual(dual_root())
    assert ref_dual.tag == ours.tag
    assert [p.tag for p in ref_dual] == ["Paragraph"] * 4
    assert [p.tag for p in ours] == ["Paragraph"] * 5  # ours has a parenthetical
    # Same shape, allowing for our parenthetical.
    assert [p.get("Type") for p in ref_dual] == [
        "Character",
        "Dialogue",
        "Character",
        "Dialogue",
    ]


def test_an_unpaired_dual_cue_degrades_to_an_ordinary_speech():
    """A caret with no speech before it cannot make a pair. Emitting a
    one-speaker wrapper would produce a file Final Draft rejects."""
    script = parse_screenplay(["@DELL ^\nYou already did.\n\nCUT TO:"])
    content = ET.fromstring(render_fdx(script).decode("utf-8")).find("Content")
    assert all(p.find("DualDialogue") is None for p in content)
    assert [p.get("Type") for p in content] == ["Character", "Dialogue", "Transition"]


def test_dual_survives_a_fountain_round_trip():
    """Fountain is the only one of the three formats that can carry the pair
    as markup, so the caret has to make it back through a reparse and into
    the FDX wrapper."""
    from rewriteocr.pipeline.export_screenplay import render_fountain

    first = parse_screenplay([DUAL_PAGE])
    reparsed = parse_screenplay([render_fountain(first, "none")])
    assert [el.dual for el in reparsed.elements] == [el.dual for el in first.elements]
    root = ET.fromstring(render_fdx(reparsed).decode("utf-8"))
    assert [p.get("Type") for p in only_dual(root)] == [
        "Character",
        "Parenthetical",
        "Dialogue",
        "Character",
        "Dialogue",
    ]


def test_a_cue_with_no_dialogue_is_never_wrapped():
    groups = dual_groups(parse_screenplay([DUAL_PAGE]).elements)
    assert any(is_dual for is_dual, _ in groups)
    # Both halves carry dialogue, which is what makes the pair legal.
    dual_group = next(group for is_dual, group in groups if is_dual)
    assert sum(1 for el in dual_group if el.type == "character") == 2
    assert sum(1 for el in dual_group if el.type == "dialogue") == 2


# -- independent structural check -------------------------------------------


def write(tmp_path, script, name="out.fdx") -> Path:
    out = tmp_path / name
    out.write_bytes(render_fdx(script))
    return out


@pytest.mark.parametrize(
    "pages",
    [
        pytest.param(SCRIPT_PAGES, id="screenplay"),
        pytest.param([DUAL_PAGE], id="dual-dialogue"),
        pytest.param(
            ["Title: A Play\nAuthor: Jane Doe", "INT. KITCHEN - DAY\n\nHe waits."],
            id="title-page",
        ),
        pytest.param(
            [
                "BRENDA. My brother lives in a Jeep.\n\nBRADLEY. I remember him.\n\n"
                "BRENDA. Everyone does.\n\nBRADLEY. What about the other one? "
                "BRENDA. You know about him?"
            ],
            id="stage-play",
        ),
    ],
)
def test_output_passes_the_structural_checker(tmp_path, pages):
    """Runs every shape we emit through fdxcheck, which catches structural
    mistakes hand-written assertions miss: a Character followed by the wrong
    element, a malformed dual block, an untyped paragraph with no payload."""
    report = check_file(str(write(tmp_path, parse_screenplay(pages))))
    assert report.errors == []
    assert report.warnings == []


def test_the_checker_would_catch_a_flattened_wrapper(tmp_path):
    """Guards the guard: prove the checker fails on the mistake we are
    avoiding, so a green run means something."""
    broken = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="no" ?>\n'
        b'<FinalDraft DocumentType="Script" Version="3"><Content>'
        b'<Paragraph Type="Character"><Text>MARA</Text></Paragraph>'
        b"<Paragraph><DualDialogue>"
        b'<Paragraph Type="Character"><Text>DELL</Text></Paragraph>'
        b"</DualDialogue></Paragraph>"
        b"</Content></FinalDraft>"
    )
    out = tmp_path / "broken.fdx"
    out.write_bytes(broken)
    report = check_file(str(out))
    assert report.errors
