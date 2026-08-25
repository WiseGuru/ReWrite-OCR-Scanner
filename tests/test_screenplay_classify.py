"""Screenplay element classifier.

Fixture text is deliberately ASCII: scripts use an em dash for interruptions
constantly, and scripts/check_dashes.py fails the build on one. Two hyphens
is how screenwriters actually type it and how Final Draft receives it.
"""

from __future__ import annotations

from rewriteocr.core.screenplay import parse_screenplay

# A stage play in the Dramatists Play Service form: the cue is inline, and
# OCR runs a whole exchange into one paragraph.
STAGE_PAGE = (
    "ACT ONE\n\nScene 1\n\nAn office. Chairs.\n\n"
    "BRENDA. My brother lives in a Jeep. He is fine.\n\n"
    "BRADLEY. I remember him.\n\n"
    "BRENDA. Everyone does.\n\n"
    "BRADLEY. What about your other brother? BRENDA. You know about him? "
    "BRADLEY. Yeah. BRENDA. He is my step-brother.\n\n"
    "BRADLEY. (Pouring a drink.) Should we talk about the movie?"
)


def types(pages: list[str]) -> list[str]:
    return [el.type for el in parse_screenplay(pages).elements]


def one(text: str) -> str:
    """Classify a line that stands alone between blank lines."""
    return types([f"Preceding action line.\n\n{text}\n\nTrailing action line."])[1]


# -- scene headings ---------------------------------------------------------


def test_every_scene_prefix_form():
    for heading in (
        "INT. KITCHEN - DAY",
        "EXT. ROOFTOP - NIGHT",
        "INT./EXT. CAR - CONTINUOUS",
        "EXT./INT. DINER - DAWN",
        "I/E. TRAIN - MOVING",
        "EST. THE COMPOUND - DAY",
        "INT KITCHEN - DAY",
    ):
        assert one(heading) == "scene_heading", heading


def test_interior_prefix_is_not_a_scene_heading():
    # Without the lookahead in SCENE_PREFIX_RE the INT. branch matches this.
    assert one("INTERIOR DESIGN IS A JOB") == "action"
    assert one("INTERNAL AFFAIRS IS WAITING") == "action"


# -- character cues vs uppercase action -------------------------------------


def test_character_cue():
    assert types(["MARLOWE\nYou should not have come here."]) == [
        "character",
        "dialogue",
    ]


def test_allcaps_action_with_terminal_punctuation_is_not_a_cue():
    assert one("THE DOOR EXPLODES INWARD.") == "action"
    assert one("WHAT WAS THAT?") == "action"


def test_allcaps_action_that_is_too_long_is_not_a_cue():
    assert one("HE SLAMS THE DOOR AND RUNS FOR THE STAIRS") == "action"


def test_allcaps_line_ending_in_a_colon_is_not_a_cue():
    assert one("SUPER: THREE YEARS EARLIER") == "action"


def test_cue_requires_a_blank_line_before_it():
    # Run into the preceding paragraph, so it is not a cue.
    assert types(["He turns.\nMARLOWE\nGet out."])[0] == "action"


def test_cue_requires_text_immediately_after_it():
    assert types(["MARLOWE\n\nHe turns away."]) == ["action", "action"]


def test_cue_extension_is_split_off():
    script = parse_screenplay(["TERRY (V.O.)\nI had no choice."])
    cue = script.elements[0]
    assert cue.type == "character"
    assert cue.extension == "(V.O.)"
    # The text keeps the extension; the split is for FDX and DOCX styling.
    assert cue.text == "TERRY (V.O.)"


def test_contd_attached_to_a_cue_survives():
    script = parse_screenplay(["MARLOWE (CONT'D)\nEverybody has a choice."])
    assert script.elements[0].type == "character"
    assert script.elements[0].extension == "(CONT'D)"
    assert not script.report.dropped_artifacts


def test_cue_with_a_trailing_abbreviation():
    assert types(["MARTIN JR.\nThat is my father."])[0] == "character"


def test_long_cue_is_emitted_but_reported_uncertain():
    script = parse_screenplay(["THE MAN IN THE HAT\nOver here."])
    assert script.elements[0].type == "character"
    assert script.elements[0].confidence < 1.0
    assert script.report.low_confidence == [0]


def test_dual_dialogue_caret_is_honored():
    script = parse_screenplay(["@STEEL ^\nGo!"])
    assert script.elements[0].dual is True
    assert script.elements[0].text == "STEEL"


# -- parentheticals ---------------------------------------------------------


def test_parenthetical_after_a_cue():
    assert types(["MARLOWE\n(quietly)\nGet out."]) == [
        "character",
        "parenthetical",
        "dialogue",
    ]


def test_parenthetical_mid_speech():
    assert types(["TERRY\nThis is where it ends.\n(beat)\nYou know that."]) == [
        "character",
        "dialogue",
        "parenthetical",
        "dialogue",
    ]


def test_standalone_parenthetical_aside_is_action():
    assert one("(A car horn blares in the distance.)") == "action"


# -- transitions ------------------------------------------------------------


def test_transitions():
    for line in ("CUT TO:", "SMASH CUT TO:", "DISSOLVE TO:", "FADE OUT.", "THE END"):
        assert one(line) == "transition", line


def test_fade_in_is_action_not_a_transition():
    # A real Final Draft export emits FADE IN: as Action, and Fountain's
    # auto-detect only fires on uppercase lines ending in TO:.
    assert one("FADE IN:") == "action"


def test_long_uppercase_line_ending_in_to_is_not_a_transition():
    assert one("HE WALKS ACROSS THE ROOM AND SPEAKS TO:") == "action"


# -- page furniture ---------------------------------------------------------


def test_page_furniture_is_dropped():
    pages = [
        "12.\n\nINT. KITCHEN - DAY\n\nHe waits.\n\n(MORE)",
        "CONTINUED:\n\nShe arrives.\n\nCONTINUED: (2)\n\n13",
    ]
    script = parse_screenplay(pages)
    assert [el.text for el in script.elements] == [
        "INT. KITCHEN - DAY",
        "He waits.",
        "She arrives.",
    ]
    assert "(MORE)" in script.report.dropped_artifacts
    assert "12." in script.report.dropped_artifacts


def test_title_and_number_running_header_is_dropped():
    script = parse_screenplay(["THE LONG GOODBYE          42.\n\nHe waits."])
    assert [el.text for el in script.elements] == ["He waits."]


# -- Markdown decoration ----------------------------------------------------


def test_markdown_decoration_is_stripped_before_classifying():
    script = parse_screenplay(["## INT. KITCHEN - DAY\n\n**MARLOWE**\nGet out."])
    assert [el.type for el in script.elements] == [
        "scene_heading",
        "character",
        "dialogue",
    ]
    # The stripped form is what gets written out.
    assert script.elements[0].text == "INT. KITCHEN - DAY"
    assert script.elements[1].text == "MARLOWE"


# -- block joining ----------------------------------------------------------


def test_wrapped_lines_join_into_one_element():
    script = parse_screenplay(
        ["TERRY\nI did not have a choice, Phil. I never\ndid have much of one."]
    )
    assert script.elements[1].text == (
        "I did not have a choice, Phil. I never did have much of one."
    )


def test_a_blank_line_stops_the_join():
    script = parse_screenplay(["First beat.\n\nSecond beat."])
    assert [el.text for el in script.elements] == ["First beat.", "Second beat."]


def test_speech_split_across_a_page_is_one_speech():
    # Otherwise the tail is orphaned, and a Fountain parser reads dialogue
    # with no cue above it as action.
    script = parse_screenplay(
        ["TERRY\nI never did have much of", "a choice in the matter."]
    )
    assert [el.type for el in script.elements] == ["character", "dialogue"]
    assert script.elements[1].text == "I never did have much of a choice in the matter."


def test_action_does_not_join_across_a_page():
    script = parse_screenplay(["He waits.", "She arrives."])
    assert [el.text for el in script.elements] == ["He waits.", "She arrives."]


def test_page_with_no_blank_lines_still_classifies():
    """PDFium's raw text order emits no blank lines at all, so every
    born-digital page arrives like this. The separator carries no information
    there and cannot be required."""
    page = (
        "FADE IN:\nINT. KITCHEN - DAY\nMARLOWE stands at the window.\n"
        "MARLOWE\n(quietly)\nYou should not have come here.\n"
        "He turns away from the glass.\nCUT TO:"
    )
    assert types([page]) == [
        "action",
        "scene_heading",
        "action",
        "character",
        "parenthetical",
        "dialogue",
        "action",
        "transition",
    ]


def test_cue_at_the_top_of_a_page_still_classifies():
    script = parse_screenplay(["He waits.", "MARLOWE\nGet out."])
    assert [el.type for el in script.elements] == ["action", "character", "dialogue"]


# -- title page -------------------------------------------------------------


def test_title_page_extracted_and_removed():
    pages = [
        "Title: The Long Goodbye\nCredit: Written by\nAuthor: Jane Doe\n"
        "Draft date: 3/12/2026\nContact: jane@example.com",
        "INT. KITCHEN - DAY\n\nHe waits.",
    ]
    script = parse_screenplay(pages)
    assert script.report.title_page_detected
    assert script.title.fields == {
        "Title": "The Long Goodbye",
        "Credit": "Written by",
        "Author": "Jane Doe",
        # Fountain's canonical key is lowercase "date"; do not title-case it.
        "Draft date": "3/12/2026",
        "Contact": "jane@example.com",
    }
    assert [el.type for el in script.elements] == ["scene_heading", "action"]


def test_bare_title_page_without_key_markers_is_left_alone():
    script = parse_screenplay(["THE LONG GOODBYE\n\nby\n\nJane Doe", "He waits."])
    assert not script.report.title_page_detected
    assert script.title.fields == {}


# -- forcing characters (idempotence) ---------------------------------------


def test_fountain_forcing_characters_are_honored():
    pages = ["!THE DOOR EXPLODES INWARD\n\n.SNIPER SCOPE POV\n\n> BURN TO WHITE."]
    assert types(pages) == ["action", "scene_heading", "transition"]


def test_forced_action_beats_the_scene_prefix():
    # Re-importing our own output must not reclassify a forced action.
    assert types(["!INT. KITCHEN - DAY"]) == ["action"]


def test_ellipsis_is_not_a_forced_scene_heading():
    assert one("...and then it was over.") == "action"


# -- stage plays ------------------------------------------------------------


def test_inline_cues_are_split_into_cue_and_speech():
    script = parse_screenplay([STAGE_PAGE])
    assert script.report.stage_play
    assert script.report.cast == ["BRADLEY", "BRENDA"]
    pairs = [(el.type, el.text) for el in script.elements]
    assert ("character", "BRENDA") in pairs
    assert ("dialogue", "My brother lives in a Jeep. He is fine.") in pairs


def test_a_run_together_exchange_splits_into_every_speech():
    script = parse_screenplay([STAGE_PAGE])
    pairs = [(el.type, el.text) for el in script.elements]
    # One OCR'd paragraph holding four speeches becomes four speeches.
    for text in (
        "What about your other brother?",
        "You know about him?",
        "Yeah.",
        "He is my step-brother.",
    ):
        assert ("dialogue", text) in pairs, text


def test_act_and_scene_divisions_are_scene_headings():
    script = parse_screenplay([STAGE_PAGE])
    headings = [el.text for el in script.elements if el.type == "scene_heading"]
    assert headings == ["ACT ONE", "Scene 1"]


def test_stage_direction_opening_a_speech_is_a_parenthetical():
    script = parse_screenplay([STAGE_PAGE])
    pairs = [(el.type, el.text) for el in script.elements]
    assert ("parenthetical", "(Pouring a drink.)") in pairs
    assert ("dialogue", "Should we talk about the movie?") in pairs


def test_a_lone_stage_direction_is_action():
    page = STAGE_PAGE + "\n\nBRENDA. (She exits.)"
    script = parse_screenplay([page])
    assert ("action", "(She exits.)") in [(el.type, el.text) for el in script.elements]


def test_a_name_seen_only_once_is_not_cast():
    # Two appearances are required, so a sentence that happens to open with an
    # uppercase word and a period cannot invent a character.
    script = parse_screenplay(["NOTE. This is a preface.\n\nOrdinary prose follows."])
    assert not script.report.stage_play


def test_mid_line_splitting_only_uses_confirmed_cast():
    """An acronym mid-sentence must not be read as a cue. Only names that
    opened a line more than once are split on inside a line."""
    page = (
        "KEN. He worked at the FBI. Then he left.\n\n"
        "KEN. That was years ago.\n\n"
        "ROTHKO. I remember it.\n\nROTHKO. Clearly."
    )
    script = parse_screenplay([page])
    assert script.report.cast == ["KEN", "ROTHKO"]
    assert ("dialogue", "He worked at the FBI. Then he left.") in [
        (el.type, el.text) for el in script.elements
    ]


def test_a_screenplay_is_not_treated_as_a_stage_play():
    script = parse_screenplay(
        ["INT. KITCHEN - DAY\n\nMARLOWE\nGet out.\n\nTERRY\nNo.\n\nMARLOWE\nNow."]
    )
    assert not script.report.stage_play
