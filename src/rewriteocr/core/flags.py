"""Failure detection flags. Cheap heuristics that drive review ordering.

Severity is 0.0-1.0; the review queue sorts by max severity descending.
Detail strings are shown to users, so they are plain language.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from rewriteocr.core.models import Flag

# repetition: any 5-gram appearing more than this many times.
NGRAM_N = 5
NGRAM_MAX_REPEATS = 4
# repetition: tail window scanned for a repeating cycle.
TAIL_WINDOW_CHARS = 400
TAIL_MIN_CYCLES = 3
# low_yield: flag when output chars fall below this fraction of expected.
LOW_YIELD_FRACTION = 0.25
# low_yield: ignore pages with almost no ink (genuinely blank).
MIN_INK_RATIO = 0.02
# low_yield calibration: rough ink pixels per character at model DPI.
INK_PX_PER_CHAR = 250.0
# engine_disagreement: flag below this normalized similarity.
DISAGREEMENT_THRESHOLD = 0.80


def repetition_flag(page_index: int, text: str) -> Flag | None:
    words = text.split()
    if len(words) >= NGRAM_N * 2:
        counts: dict[tuple[str, ...], int] = {}
        best_gram, best_count = None, 0
        for i in range(len(words) - NGRAM_N + 1):
            gram = tuple(words[i : i + NGRAM_N])
            c = counts.get(gram, 0) + 1
            counts[gram] = c
            if c > best_count:
                best_gram, best_count = gram, c
        if best_count > NGRAM_MAX_REPEATS:
            phrase = " ".join(best_gram or ())
            return Flag(
                page_index,
                "repetition",
                min(1.0, 0.5 + (best_count - NGRAM_MAX_REPEATS) / 16),
                f"Output repeats the phrase '{phrase}' {best_count} times,"
                " which usually means extraction failed.",
            )
    cycle = _tail_cycle(text)
    if cycle:
        return Flag(
            page_index,
            "repetition",
            0.9,
            f"Output ends in a repeating cycle of '{cycle[:60]}',"
            " which usually means extraction failed.",
        )
    return None


def _tail_cycle(text: str) -> str | None:
    tail = text[-TAIL_WINDOW_CHARS:].strip()
    if len(tail) < 12:
        return None
    # Smallest period p of the suffix: s is periodic with period p when
    # s appears in (s+s) at an offset p < len(s).
    idx = (tail + tail).find(tail, 1)
    if 0 < idx < len(tail) and len(tail) // idx >= TAIL_MIN_CYCLES:
        return tail[:idx]
    return None


def low_yield_flag(
    page_index: int, text: str, ink_ratio: float, image_px: int
) -> Flag | None:
    if ink_ratio < MIN_INK_RATIO:
        return None
    expected_chars = (ink_ratio * image_px) / INK_PX_PER_CHAR
    if expected_chars < 100:
        return None
    actual = len(re.sub(r"\s", "", text))
    if actual >= expected_chars * LOW_YIELD_FRACTION:
        return None
    shortfall = 1.0 - (actual / (expected_chars * LOW_YIELD_FRACTION))
    return Flag(
        page_index,
        "low_yield",
        min(1.0, 0.4 + 0.6 * shortfall),
        f"The page looks dense but extraction returned only {actual} characters."
        " Extraction may have died partway through.",
    )


_MD_SYNTAX = re.compile(r"[#*_`|>\[\]()!-]|\d+\.")
_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")


def _normalize_for_compare(text: str) -> str:
    text = _MD_SYNTAX.sub(" ", text)
    text = _PUNCT.sub("", text.lower())
    return _WS.sub(" ", text).strip()


def engine_disagreement_flag(
    page_index: int, vlm_text: str, tess_text: str
) -> Flag | None:
    a, b = _normalize_for_compare(vlm_text), _normalize_for_compare(tess_text)
    if len(a) < 40 or len(b) < 40:
        return None
    matcher = SequenceMatcher(None, a, b, autojunk=True)
    if matcher.quick_ratio() >= DISAGREEMENT_THRESHOLD:
        ratio = matcher.ratio()
        if ratio >= DISAGREEMENT_THRESHOLD:
            return None
    else:
        ratio = matcher.ratio()
        if ratio >= DISAGREEMENT_THRESHOLD:
            return None
    return Flag(
        page_index,
        "engine_disagreement",
        min(1.0, (DISAGREEMENT_THRESHOLD - ratio) / DISAGREEMENT_THRESHOLD + 0.3),
        "The AI model and the traditional OCR engine read this page very"
        f" differently (similarity {ratio:.0%}). One of them is probably wrong.",
    )
