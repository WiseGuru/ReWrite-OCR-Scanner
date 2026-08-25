"""Screenplay element classifier: canonical Markdown to a typed element stream.

Fountain, FDX and styled DOCX all need to know that one block is a Character
cue and the next is Dialogue. Nothing upstream records that, so it is
recovered here at export time.

Two signals, in that order of authority:

- **Lexical.** Screenplay layout encodes the same fact redundantly in the
  text stream: a cue is uppercase, short, preceded by a blank line and
  followed immediately by text. That holds on every path, including scanned
  pages, where no geometry exists at all.
- **Geometry.** When indents are available (born-digital pages only, see
  core/screenplay_geom.py) the column a line starts in decides the
  ambiguous cases outright. Offsets are measured relative to the document's
  own action margin, not as absolute inches, so a script printed or scanned
  with a shifted margin still classifies.

Pure and Qt-free; the output stream is never stored.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

from rewriteocr.core.models import (
    ClassifyReport,
    Element,
    ElementType,
    Screenplay,
    TitlePage,
)

# -- thresholds -------------------------------------------------------------

MAX_CUE_WORDS = 5
MAX_CUE_CHARS = 40
MAX_SCENE_HEADING_CHARS = 90
MAX_TRANSITION_CHARS = 40
# A real transition is a handful of words ("SMASH CUT TO:"). The word cap is
# what separates one from a line of action that happens to end in "TO:".
MAX_TRANSITION_WORDS = 4

# Fraction of alphabetic characters that must be uppercase. Not an equality
# test against str.upper(): OCR routinely turns I into l and O into 0 inside
# a cue, and on a 12-character name this tolerates one bad character.
UPPER_RATIO_MIN = 0.90

# A cue this long is emitted but reported as uncertain.
LOW_CONFIDENCE_CUE_WORDS = 3
CUE_CONFIDENCE_LOW = 0.6

MAX_TITLE_PAGE_ELEMENTS = 12

# Column offsets in inches from the document's action margin, with the
# tolerance each is matched within. Absolute equivalents on a 1.5in left
# margin are the conventional 1.5 / 2.5 / 3.0 / 3.7 / 5.5.
COLUMN_OFFSETS: tuple[tuple[ElementType, float, float], ...] = (
    ("action", 0.0, 0.35),
    ("dialogue", 1.0, 0.35),
    ("parenthetical", 1.5, 0.30),
    ("character", 2.2, 0.35),
    ("transition", 4.0, 0.60),
)

# -- patterns ---------------------------------------------------------------

# The lookahead is load-bearing. Without it "INTERIOR DESIGN IS A JOB"
# matches the INT. branch and becomes a scene heading.
SCENE_PREFIX_RE = re.compile(
    r"^(INT\.?/EXT\.?|EXT\.?/INT\.?|I/E\.?|INT\.?|EXT\.?|EST\.?)(?=[\s.\-]|$)"
)

CHARACTER_EXTENSION_RE = re.compile(
    r"\s*\((V\.?O\.?|O\.?S\.?|O\.?C\.?|CONT'?D|SUBTITLE|FILTERED|PRELAP|ON PHONE)"
    r"[^)]*\)\s*$",
    re.IGNORECASE,
)

# Fountain's standard title-page keys, in their canonical casing. "Draft
# date" is lowercase in the spec, so the matched key is looked up here rather
# than title-cased.
TITLE_KEYS = (
    "Title",
    "Credit",
    "Author",
    "Authors",
    "Source",
    "Draft date",
    "Contact",
    "Notes",
    "Copyright",
)
_TITLE_KEY_BY_LOWER = {k.lower(): k for k in TITLE_KEYS}

TITLE_FIELD_RE = re.compile(
    r"^(" + "|".join(TITLE_KEYS) + r")\s*:\s*(.*)$",
    re.IGNORECASE,
)

# Uppercase lines that are transitions despite not ending in "TO:".
# "FADE IN:" is deliberately absent: a real Final Draft export emits it as
# Action, and Fountain's auto-detect only fires on lines ending in "TO:".
TRANSITION_WORDS = frozenset(
    {"FADE OUT", "FADE TO BLACK", "THE END", "IRIS OUT", "SMASH TO BLACK"}
)

# Abbreviations that may legitimately end a character cue.
CUE_TRAILING_ABBREV = ("JR.", "SR.", "DR.", "MR.", "MRS.", "MS.", "ST.")

# Page furniture, matched against a whole stripped line only. "JOHN (CONT'D)"
# attached to a cue is not furniture and must not match any of these.
_ARTIFACT_RES = (
    re.compile(r"^\(?\s*MORE\s*\)?$", re.IGNORECASE),
    re.compile(r"^\(?\s*CONT(INUED)?'?D?\s*\)?[:.]?$", re.IGNORECASE),
    re.compile(r"^CONTINUED:\s*\(\d+\)$", re.IGNORECASE),
    re.compile(r"^\d{1,4}\.?$"),
    re.compile(r"^(-{3,}|\*{3,}|_{3,})$"),
    re.compile(r"^<!--\s*page break\s*-->$", re.IGNORECASE),
)

# A running-header line combining a title and a page number, e.g.
# "THE LONG GOODBYE          42.". Conservative: needs two or more spaces.
_TITLE_AND_NUMBER_RE = re.compile(r"^(?P<head>.{0,60}?)\s{2,}\d{1,4}\.?$")

# Act and scene divisions, which a stage play uses where a screenplay uses a
# slug line. Tightly anchored to a number or a spelled-out ordinal so a line
# of action starting with "ACT" cannot match.
ACT_SCENE_RE = re.compile(
    r"^(ACT|SCENE)\s+([IVXLC]+|\d+|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN)"
    r"\b\.?$|^(PROLOGUE|EPILOGUE|INTERMISSION|CURTAIN)\.?$",
    re.IGNORECASE,
)

# Stage plays (the Dramatists Play Service form) put the cue inline: "KEN. I
# am not scared." rather than a centered cue above centered dialogue. OCR
# then runs a whole exchange into one paragraph, so a line can hold several
# speeches.
STAGE_CUE_RE = re.compile(r"^([A-Z][A-Z0-9 .'\-]{0,29}?)([.:])\s+(?=\S)")
# A name must open a line this many times before it is treated as cast, and
# the document needs this many distinct cast members before inline-cue
# splitting turns on at all.
MIN_STAGE_CUE_APPEARANCES = 2
MIN_STAGE_CAST = 2
MAX_STAGE_NAME_WORDS = 4

_MD_HEADING_RE = re.compile(r"^#{1,6}\s+")
_MD_BULLET_RE = re.compile(r"^[-*+]\s+")
_MD_EMPHASIS_RE = re.compile(r"(\*\*|__|\*|_)(.+?)\1")

_FORCE_CHARS: dict[str, ElementType] = {"@": "character", "!": "action", "~": "action"}


# -- helpers ----------------------------------------------------------------


def _upper_ratio(s: str) -> float:
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def _demarkdown(line: str) -> str:
    """Strip Markdown decoration before classifying. The VLM formats scene
    headings as '## INT. KITCHEN - DAY' and cues as '**JOHN**' often enough
    that not doing this is a guaranteed misclassification. Screenplay
    formats carry no emphasis, so the stripped form is used for output too."""
    s = line.strip()
    s = _MD_HEADING_RE.sub("", s)
    s = _MD_BULLET_RE.sub("", s)
    prev = None
    while prev != s:
        prev = s
        s = _MD_EMPHASIS_RE.sub(r"\2", s)
    return s.strip()


def _is_artifact(s: str) -> bool:
    if SCENE_PREFIX_RE.match(s.upper()):
        return False
    if any(rx.match(s) for rx in _ARTIFACT_RES):
        return True
    m = _TITLE_AND_NUMBER_RE.match(s)
    return bool(m and _upper_ratio(m.group("head")) >= UPPER_RATIO_MIN)


def _strip_forcing(s: str) -> tuple[str, ElementType | None]:
    """Honor Fountain forcing characters, so re-importing our own output is
    idempotent. '.' forces a scene heading but '...' is an ellipsis.

    '>' is the one character that collides with Markdown, where it opens a
    blockquote. A Fountain transition is always uppercase, so a '>' line that
    is not resolves as a blockquote and the marker is simply stripped.
    """
    if not s:
        return s, None
    head = s[0]
    if head == "." and not s.startswith(".."):
        return s[1:].strip(), "scene_heading"
    if head == ">":
        body = s[1:-1] if s.endswith("<") else s[1:]
        body = body.strip()
        if s.endswith("<"):
            return body, "action"  # centered text has no element of its own
        if _upper_ratio(body) >= UPPER_RATIO_MIN:
            return body, "transition"
        return body, None
    forced = _FORCE_CHARS.get(head)
    if forced is not None:
        return s[1:].strip(), forced
    return s, None


def _looks_like_scene_heading(s: str) -> bool:
    return (
        bool(SCENE_PREFIX_RE.match(s.upper()))
        and _upper_ratio(s) >= UPPER_RATIO_MIN
        and len(s) <= MAX_SCENE_HEADING_CHARS
    )


def _looks_like_transition(s: str) -> bool:
    if _upper_ratio(s) < UPPER_RATIO_MIN or len(s) > MAX_TRANSITION_CHARS:
        return False
    if len(s.split()) > MAX_TRANSITION_WORDS:
        return False
    body = s.rstrip()
    return body.endswith("TO:") or body.rstrip(".").upper() in TRANSITION_WORDS


def split_cue(s: str) -> tuple[str, str, bool]:
    """Split a candidate cue into (name, extension, dual)."""
    dual = False
    body = s.rstrip()
    if body.endswith("^"):
        dual = True
        body = body[:-1].rstrip()
    extension = ""
    m = CHARACTER_EXTENSION_RE.search(body)
    if m:
        extension = m.group(0).strip()
        body = body[: m.start()].rstrip()
    return body, extension, dual


def _looks_like_character(name: str) -> bool:
    if not name or not any(c.isalpha() for c in name):
        return False
    if _upper_ratio(name) < UPPER_RATIO_MIN:
        return False
    if len(name) > MAX_CUE_CHARS or len(name.split()) > MAX_CUE_WORDS:
        return False
    if SCENE_PREFIX_RE.match(name.upper()):
        return False
    if name.endswith("TO:") or name.endswith(":"):
        return False
    if name.endswith((".", "!", "?")) and not name.upper().endswith(CUE_TRAILING_ABBREV):
        return False
    return True


# -- line model -------------------------------------------------------------


@dataclass
class _Line:
    text: str
    blank: bool
    page_index: int
    page_start: bool
    indent: float | None = None
    forced: ElementType | None = None
    next_nonblank_immediate: bool = False
    # True when this page carries no blank lines at all. PDFium's raw text
    # order does exactly that on a born-digital page, which removes the cue
    # signal the lexical rules lean on hardest.
    unblanked: bool = False


def _prepare(
    pages: list[str],
    indents: list[list[float | None]] | None,
    report: ClassifyReport,
) -> list[_Line]:
    out: list[_Line] = []
    for page_index, page in enumerate(pages):
        raw_lines = page.split("\n")
        page_indents = indents[page_index] if indents and page_index < len(indents) else None
        prepared: list[_Line] = []
        for line_no, raw in enumerate(raw_lines):
            s = _demarkdown(raw)
            if s and _is_artifact(s):
                report.dropped_artifacts.append(s)
                s = ""
            indent = None
            if page_indents is not None and line_no < len(page_indents):
                indent = page_indents[line_no]
            s, forced = _strip_forcing(s) if s else (s, None)
            prepared.append(
                _Line(
                    text=s,
                    blank=not s,
                    page_index=page_index,
                    page_start=False,
                    indent=indent,
                    forced=forced,
                )
            )
        # Trim leading and trailing blanks so page_start lands on real text.
        while prepared and prepared[0].blank:
            prepared.pop(0)
        while prepared and prepared[-1].blank:
            prepared.pop()
        if not prepared:
            continue
        prepared[0].page_start = True
        unblanked = not any(line.blank for line in prepared)
        for i, line in enumerate(prepared):
            nxt = prepared[i + 1] if i + 1 < len(prepared) else None
            line.next_nonblank_immediate = nxt is not None and not nxt.blank
            line.unblanked = unblanked
        out.extend(prepared)
    return out


# -- stage plays ------------------------------------------------------------


def _plausible_stage_name(name: str) -> bool:
    name = name.strip()
    if not name or not any(c.isalpha() for c in name):
        return False
    if len(name.split()) > MAX_STAGE_NAME_WORDS:
        return False
    if _upper_ratio(name) < UPPER_RATIO_MIN:
        return False
    return not SCENE_PREFIX_RE.match(name.upper())


def detect_stage_cast(lines: list[_Line]) -> set[str]:
    """Names that open a line as "NAME." or "NAME:" more than once.

    Two passes are needed because a mid-line cue cannot be detected safely on
    its own: "...worked at the FBI. Then we left" would split on FBI. Opening
    a line is high-confidence, so the cast is learned there first and only
    those names are then split on mid-line.
    """
    counts: dict[str, int] = {}
    for line in lines:
        if line.blank:
            continue
        m = STAGE_CUE_RE.match(line.text)
        if m and _plausible_stage_name(m.group(1)):
            name = m.group(1).strip()
            counts[name] = counts.get(name, 0) + 1
    return {n for n, c in counts.items() if c >= MIN_STAGE_CUE_APPEARANCES}


def _cast_pattern(cast: set[str]) -> re.Pattern[str]:
    # Longest first, so "MRS. VENABLE" wins over a "MRS" that also appears.
    names = sorted(cast, key=len, reverse=True)
    return re.compile(
        r"(?<=\s)(" + "|".join(re.escape(n) for n in names) + r")([.:])\s+(?=\S)"
    )


def split_stage_line(text: str, cast_re: re.Pattern[str]) -> list[tuple[ElementType, str]]:
    """Split one line into (type, text) pieces at every inline cue."""
    cues: list[tuple[int, int, str]] = []  # (cue start, dialogue start, name)
    m = STAGE_CUE_RE.match(text)
    if m and _plausible_stage_name(m.group(1)):
        cues.append((0, m.end(), m.group(1).strip()))
    start = cues[0][1] if cues else 0
    for hit in cast_re.finditer(text, start):
        cues.append((hit.start(), hit.end(), hit.group(1).strip()))

    if not cues:
        return [("action", text)]

    out: list[tuple[ElementType, str]] = []
    if cues[0][0] > 0:
        lead = text[: cues[0][0]].strip()
        if lead:
            out.append(("action", lead))
    for i, (_, body_start, name) in enumerate(cues):
        end = cues[i + 1][0] if i + 1 < len(cues) else len(text)
        body = text[body_start:end].strip()
        out.append(("character", name))
        out.extend(_split_leading_parenthetical(body))
    return [(kind, s) for kind, s in out if s]


def _split_leading_parenthetical(body: str) -> list[tuple[ElementType, str]]:
    """A stage direction opening a speech is a parenthetical; one that is the
    whole speech is a stage direction, which maps to action."""
    if not body.startswith("("):
        return [("dialogue", body)] if body else []
    depth = 0
    for i, ch in enumerate(body):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                head, tail = body[: i + 1], body[i + 1 :].strip()
                if not tail:
                    return [("action", head)]
                return [("parenthetical", head), ("dialogue", tail)]
    return [("dialogue", body)]


def _expand_stage_lines(lines: list[_Line], cast: set[str]) -> list[_Line]:
    cast_re = _cast_pattern(cast)
    out: list[_Line] = []
    for line in lines:
        if line.blank:
            out.append(line)
            continue
        pieces = split_stage_line(line.text, cast_re)
        if len(pieces) == 1 and pieces[0][0] == "action":
            out.append(line)
            continue
        for index, (kind, text) in enumerate(pieces):
            out.append(
                _Line(
                    text=text,
                    blank=False,
                    page_index=line.page_index,
                    page_start=line.page_start and index == 0,
                    forced=kind,
                    next_nonblank_immediate=True,
                )
            )
    return out


# -- geometry ---------------------------------------------------------------


def _action_baseline(lines: list[_Line]) -> float | None:
    """The document's action margin: the modal smallest indent. Everything
    else is measured as an offset from this, so a shifted margin does not
    break classification."""
    values = [line.indent for line in lines if line.indent is not None]
    if len(values) < 8:
        return None
    values.sort()
    # The 10th percentile rather than the minimum: a single stray glyph to
    # the left of the text block would otherwise define the whole baseline.
    floor = values[max(0, int(len(values) * 0.10))]
    near = [v for v in values if abs(v - floor) <= 0.35]
    return statistics.median(near) if near else floor


def _by_column(indent: float, baseline: float) -> ElementType | None:
    offset = indent - baseline
    best: tuple[float, ElementType] | None = None
    for kind, want, tol in COLUMN_OFFSETS:
        delta = abs(offset - want)
        if delta <= tol and (best is None or delta < best[0]):
            best = (delta, kind)
    return best[1] if best else None


# -- classification ---------------------------------------------------------


def parse_screenplay(
    pages: list[str], indents: list[list[float | None]] | None = None
) -> Screenplay:
    """Classify stitched page Markdown into a screenplay element stream.

    `indents` is per page, per line, in inches from the page's left edge, or
    None where unavailable. It is only ever a hint: every ambiguous case has
    a lexical answer too.
    """
    report = ClassifyReport()
    lines = _prepare(pages, indents, report)
    # Before classification: a title page's lines are consecutive and would
    # otherwise be joined into one action block, hiding every field after the
    # first behind the first line's own "key:".
    title, lines = _extract_title_page(lines, report)
    # A stage play puts its cues inline rather than in a column, so it is
    # split into cue and speech pieces before anything else looks at a line.
    cast = detect_stage_cast(lines)
    if len(cast) >= MIN_STAGE_CAST:
        lines = _expand_stage_lines(lines, cast)
        report.stage_play = True
        report.cast = sorted(cast)
    baseline = _action_baseline(lines)
    if baseline is not None:
        report.geometry_pages = len({ln.page_index for ln in lines if ln.indent is not None})

    elements: list[Element] = []
    prev_type: ElementType | None = None
    prev_text = ""
    blank_before = True

    for line in lines:
        if line.blank:
            blank_before = True
            continue
        # A page boundary is a continuation point, not a paragraph break: a
        # speech split across a page must still read as dialogue. Rule 6
        # accepts a page start in place of a blank line separately.
        if line.page_start:
            blank_before = False
        s = line.text
        # On a page with no blank lines the separator carries no information,
        # so it cannot be required. The remaining cue tests (uppercase, short,
        # no terminal punctuation, text immediately after) are strong enough
        # on their own.
        cue_ok = blank_before or line.page_start or line.unblanked

        kind, text, confidence, extension, dual = _classify(
            s, line, prev_type, prev_text, blank_before, cue_ok, baseline
        )
        _emit(
            elements, kind, text, line, confidence, extension, dual, prev_type,
            blank_before,
        )
        prev_type = kind
        prev_text = text
        blank_before = False

    for i, el in enumerate(elements):
        report.counts[el.type] = report.counts.get(el.type, 0) + 1
        if el.confidence < 1.0:
            report.low_confidence.append(i)

    return Screenplay(elements=elements, title=title, report=report)


def _classify(
    s: str,
    line: _Line,
    prev_type: ElementType | None,
    prev_text: str,
    blank_before: bool,
    cue_ok: bool,
    baseline: float | None,
) -> tuple[ElementType, str, float, str, bool]:
    """Returns (type, text to emit, confidence, extension, dual).

    The text is returned rather than reused from the input because a
    character cue is emitted without its dual-dialogue caret.
    """
    # A cue keeps its "(V.O.)" in the text (Fountain and FDX both want it
    # there) but never its caret, which is Fountain markup, not a name.
    name, extension, dual = split_cue(s)
    cue_text = f"{name} {extension}".strip() if extension else name

    if line.forced is not None:
        if line.forced == "character":
            return "character", cue_text, 1.0, extension, dual
        return line.forced, s, 1.0, "", False

    # Rules 3 and 4 are lexically certain; geometry never overrides them.
    if _looks_like_scene_heading(s) or ACT_SCENE_RE.match(s):
        return "scene_heading", s, 1.0, "", False
    if _looks_like_transition(s):
        return "transition", s, 1.0, "", False

    # Geometry decides the ambiguous middle outright when it is available.
    if baseline is not None and line.indent is not None:
        column = _by_column(line.indent, baseline)
        if column == "character" and _looks_like_character(name):
            return "character", cue_text, 1.0, extension, dual
        if column == "parenthetical" and s.startswith("("):
            return "parenthetical", s, 1.0, "", False
        if column in ("dialogue", "action", "transition"):
            return column, s, 1.0, "", False

    if s.startswith("(") and s.endswith(")") and prev_type in ("character", "dialogue"):
        return "parenthetical", s, 1.0, "", False

    if cue_ok and line.next_nonblank_immediate and _looks_like_character(name):
        uncertain = len(name.split()) > LOW_CONFIDENCE_CUE_WORDS or "," in name
        confidence = CUE_CONFIDENCE_LOW if uncertain else 1.0
        return "character", cue_text, confidence, extension, dual

    if prev_type in ("character", "parenthetical", "dialogue") and not blank_before:
        # On an unblanked page nothing marks where a speech ends, so a
        # completed sentence is the only available boundary: hard-wrapped
        # dialogue breaks mid-sentence, a new action block does not.
        if not (line.unblanked and prev_type == "dialogue" and _ends_sentence(prev_text)):
            return "dialogue", s, 1.0, "", False

    return "action", s, 1.0, "", False


def _ends_sentence(s: str) -> bool:
    return s.rstrip().endswith((".", "!", "?", '."', ".'", '"', "'"))


def _emit(
    elements: list[Element],
    kind: ElementType,
    text: str,
    line: _Line,
    confidence: float,
    extension: str,
    dual: bool,
    prev_type: ElementType | None,
    blank_before: bool,
) -> None:
    """Append, joining wrapped lines into one element.

    Screenplay text is hard-wrapped at the format's column width. Emitting
    one element per printed line reflows disastrously in Final Draft, so
    consecutive action or dialogue lines join. Joining stops at a blank line
    and at a page boundary, with one exception: a speech split across a page
    break is one speech, and leaving the tail orphaned would make a Fountain
    parser read it as action.
    """
    joinable = kind in ("action", "dialogue")
    if joinable and elements and elements[-1].type == kind:
        last = elements[-1]
        wrapped = (
            last.page_index == line.page_index and prev_type == kind and not blank_before
        )
        continued_speech = kind == "dialogue" and line.page_start
        if wrapped or continued_speech:
            last.text = f"{last.text} {text}".strip()
            return
    elements.append(
        Element(
            type=kind,
            text=text,
            page_index=line.page_index,
            extension=extension,
            dual=dual,
            confidence=confidence,
        )
    )


def _extract_title_page(
    lines: list[_Line], report: ClassifyReport
) -> tuple[TitlePage, list[_Line]]:
    """Pull a 'key: value' title block off page 0, returning the remaining
    lines. A bare title page with no key markers is left alone; guessing
    there costs more than it gains."""
    page0 = [ln for ln in lines if ln.page_index == 0 and not ln.blank]
    if not page0 or len(page0) > MAX_TITLE_PAGE_ELEMENTS:
        return TitlePage(), lines
    if not any(TITLE_FIELD_RE.match(ln.text) for ln in page0):
        return TitlePage(), lines

    fields: dict[str, str] = {}
    consumed: set[int] = set()
    for ln in page0:
        m = TITLE_FIELD_RE.match(ln.text)
        if m is None:
            continue
        key = _TITLE_KEY_BY_LOWER.get(m.group(1).lower(), m.group(1).title())
        fields[key] = m.group(2).strip()
        # Identity, not equality: two lines with the same text are equal as
        # dataclasses and both would be dropped.
        consumed.add(id(ln))
    if not fields:
        return TitlePage(), lines

    report.title_page_detected = True
    remaining = [ln for ln in lines if id(ln) not in consumed]
    # The first surviving line of each page must still read as a page start.
    seen: set[int] = set()
    for ln in remaining:
        if ln.blank or ln.page_index in seen:
            continue
        seen.add(ln.page_index)
        ln.page_start = True
    return TitlePage(fields=fields), remaining
