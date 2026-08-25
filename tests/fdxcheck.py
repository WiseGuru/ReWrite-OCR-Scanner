#!/usr/bin/env python3
"""
fdxcheck.py - a structural sanity checker for Final Draft .fdx files.

Vendored as a test helper: tests/test_export_fdx.py runs every FDX this app
emits through check_file(), which catches structural mistakes that
hand-written assertions miss (a Character followed by the wrong element, a
malformed dual block, an untyped paragraph with no payload).

Stdlib only. Runs on Linux, Windows, and Android (Termux).

There is no official Final Draft XSD or DTD, so this does not do schema
validation. It does three things:

  1. XML well-formedness (with line/column on failure)
  2. Structural checks against the conventions real FDX writers follow
  3. Specific checks on <DualDialogue>, which is the part most third-party
     parsers get wrong

Exit codes: 0 clean, 1 warnings only, 2 errors.

Usage:
    python fdxcheck.py script.fdx [more.fdx ...]
    python fdxcheck.py --quiet script.fdx     # errors only
"""

import sys
import xml.etree.ElementTree as ET

# Paragraph Type values Final Draft and the common third-party writers emit.
# Unknown values are warned about, not rejected: the list is descriptive,
# not normative, and templates can define custom element names.
KNOWN_TYPES = {
    "Scene Heading", "Action", "Character", "Parenthetical", "Dialogue",
    "Transition", "Shot", "Cast List", "General", "New Act", "End of Act",
    "Lyrics", "Outline", "Summary", "Freeform",
}

# Child elements that legitimately appear inside <Paragraph>.
PARAGRAPH_CHILDREN = {"Text", "DualDialogue", "ScriptNote", "SceneProperties",
                      "Alignment", "Number"}

# Top-level sections under <FinalDraft>. Not exhaustive; unknown ones are ignored.
KNOWN_SECTIONS = {
    "Content", "TitlePage", "HeaderAndFooter", "SmartType", "Macros",
    "ElementSettings", "Actors", "Cast", "SplitState", "LockedPages",
    "Revisions", "SceneNumberOptions", "WatermarkingInformation",
    "SpellCheckIgnoreLists", "PageLayout", "WindowState", "TextState",
    "ScriptNoteDefinitions",
}


class Report:
    def __init__(self, path):
        self.path = path
        self.errors = []
        self.warnings = []
        self.notes = []

    def error(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)

    def note(self, msg):
        self.notes.append(msg)


def describe(el, index=None):
    """Human-readable handle for a Paragraph, since XML has no line numbers here."""
    t = el.get("Type", "(no Type)")
    text = "".join(el.itertext()).strip().replace("\n", " ")
    if len(text) > 40:
        text = text[:37] + "..."
    pos = f"paragraph {index}" if index is not None else "paragraph"
    return f'{pos} [{t}] "{text}"' if text else f"{pos} [{t}]"


def check_dual(dual, outer, outer_idx, rep):
    """
    Validate one <DualDialogue> block.

    The shape produced by Final Draft and by every writer that round-trips
    correctly is:

        <Paragraph>                     <- wrapper, no Type, no Text of its own
          <DualDialogue>
            <Paragraph Type="Character">
            <Paragraph Type="Dialogue">
            <Paragraph Type="Character">
            <Paragraph Type="Dialogue">
          </DualDialogue>
        </Paragraph>

    Two speaker blocks, no more. Parentheticals may appear between a
    Character and its Dialogue.
    """
    where = f"paragraph {outer_idx}"

    if outer.get("Type"):
        rep.warn(f"{where}: DualDialogue wrapper carries Type="
                 f'"{outer.get("Type")}"; the wrapper is normally untyped')

    stray = [c.tag for c in outer if c.tag != "DualDialogue"]
    if stray:
        rep.warn(f"{where}: DualDialogue wrapper also contains {stray}; "
                 "content outside the DualDialogue element is easy for "
                 "importers to drop")

    inner = [c for c in dual if c.tag == "Paragraph"]
    if not inner:
        rep.error(f"{where}: <DualDialogue> contains no <Paragraph> children")
        return

    non_para = [c.tag for c in dual if c.tag != "Paragraph"]
    if non_para:
        rep.warn(f"{where}: <DualDialogue> contains non-Paragraph children "
                 f"{non_para}")

    types = [p.get("Type") for p in inner]

    if types[0] != "Character":
        rep.error(f"{where}: DualDialogue must open with a Character "
                  f"paragraph, found {types[0]!r}")

    speakers = types.count("Character")
    if speakers != 2:
        rep.error(f"{where}: DualDialogue holds {speakers} Character "
                  "paragraph(s); Final Draft pairs exactly 2")

    # Every Character must be followed by Dialogue, optionally via Parenthetical.
    for i, t in enumerate(types):
        if t != "Character":
            continue
        j = i + 1
        while j < len(types) and types[j] == "Parenthetical":
            j += 1
        if j >= len(types):
            rep.error(f"{where}: Character {inner[i].findtext('Text', '?')!r} "
                      "in DualDialogue has no Dialogue after it")
        elif types[j] != "Dialogue":
            rep.error(f"{where}: Character "
                      f"{inner[i].findtext('Text', '?')!r} in DualDialogue is "
                      f"followed by {types[j]!r}, expected Dialogue")

    allowed = {"Character", "Dialogue", "Parenthetical"}
    odd = [t for t in types if t not in allowed]
    if odd:
        rep.warn(f"{where}: unexpected Type(s) inside DualDialogue: {odd}")

    if any(p.find("DualDialogue") is not None for p in inner):
        rep.error(f"{where}: nested DualDialogue")


def check_content(content, rep):
    paragraphs = [c for c in content if c.tag == "Paragraph"]
    other = [c.tag for c in content if c.tag != "Paragraph"]
    if other:
        rep.warn(f"<Content> has non-Paragraph children: {sorted(set(other))}")

    if not paragraphs:
        rep.error("<Content> has no <Paragraph> elements")
        return

    dual_count = 0
    prev_type = None
    prev_el = None

    for idx, p in enumerate(paragraphs, start=1):
        dual = p.find("DualDialogue")

        for child in p:
            if child.tag not in PARAGRAPH_CHILDREN:
                rep.warn(f"{describe(p, idx)}: unrecognised child <{child.tag}>")

        if dual is not None:
            dual_count += 1
            check_dual(dual, p, idx, rep)
            prev_type = "Dialogue"   # a dual block ends in dialogue
            prev_el = p
            continue

        ptype = p.get("Type")
        if ptype is None:
            # Untyped paragraph with no DualDialogue is almost always a bug:
            # it is the wrapper shape with the payload missing.
            if len(p) == 0:
                rep.warn(f"paragraph {idx}: empty and untyped")
            else:
                rep.error(f"paragraph {idx}: no Type attribute and no "
                          "<DualDialogue> child")
        elif ptype not in KNOWN_TYPES:
            rep.warn(f'paragraph {idx}: unrecognised Type "{ptype}"')

        if prev_type == "Character" and ptype not in ("Dialogue", "Parenthetical"):
            rep.error(f"{describe(prev_el, idx - 1)}: followed by {ptype!r}, "
                      "expected Dialogue or Parenthetical")

        if ptype == "Dialogue" and prev_type not in ("Character", "Parenthetical",
                                                     "Dialogue"):
            rep.warn(f"paragraph {idx}: Dialogue with no preceding Character")

        prev_type = ptype
        prev_el = p

    if prev_type == "Character":
        rep.error(f"{describe(prev_el)}: script ends on a Character with no Dialogue")

    rep.note(f"{len(paragraphs)} top-level paragraph(s), "
             f"{dual_count} dual dialogue block(s)")


def check_file(path):
    rep = Report(path)

    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        rep.error(f"cannot read: {exc}")
        return rep

    if raw.startswith(b"\xef\xbb\xbf"):
        rep.warn("file starts with a UTF-8 BOM; some FDX readers choke on it")

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        line, col = exc.position
        rep.error(f"not well-formed XML at line {line}, column {col}: {exc}")
        return rep

    if root.tag != "FinalDraft":
        rep.error(f"root element is <{root.tag}>, expected <FinalDraft>")
        return rep

    for attr in ("DocumentType", "Version"):
        if root.get(attr) is None:
            rep.warn(f"<FinalDraft> is missing the {attr} attribute")

    doctype = root.get("DocumentType")
    if doctype and doctype != "Script":
        rep.note(f'DocumentType is "{doctype}", not "Script"')

    unknown = {c.tag for c in root} - KNOWN_SECTIONS
    if unknown:
        rep.note(f"unfamiliar top-level section(s): {sorted(unknown)}")

    content = root.find("Content")
    if content is None:
        rep.error("no <Content> element")
        return rep

    check_content(content, rep)
    return rep


def main(argv):
    quiet = "--quiet" in argv
    paths = [a for a in argv[1:] if not a.startswith("-")]

    if not paths:
        print(__doc__.strip())
        return 2

    worst = 0
    for path in paths:
        rep = check_file(path)
        print(f"== {path}")
        for m in rep.errors:
            print(f"  ERROR   {m}")
        if not quiet:
            for m in rep.warnings:
                print(f"  WARN    {m}")
            for m in rep.notes:
                print(f"  note    {m}")
        if rep.errors:
            print("  FAILED")
            worst = max(worst, 2)
        elif rep.warnings:
            print("  ok, with warnings")
            worst = max(worst, 1)
        else:
            print("  ok")
    return worst


if __name__ == "__main__":
    sys.exit(main(sys.argv))
