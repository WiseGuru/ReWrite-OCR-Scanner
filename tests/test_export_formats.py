"""Export format registry invariants.

These are cheap and they catch the "added a format, forgot a site" class of
bug that the old two-branch dispatch made easy: an unknown fmt silently
exported Markdown instead of failing.
"""

from __future__ import annotations

from typing import get_args

import pytest

from rewriteocr.core.models import ExportFormat
from rewriteocr.pipeline.formats import EXPORT_FORMATS, format_spec, formats_for_mode


def test_registry_covers_every_declared_format():
    # Fails loudly if a format is half-landed: declared in the Literal but
    # not registered, or the other way round.
    assert {spec.key for spec in EXPORT_FORMATS} == set(get_args(ExportFormat))


def test_keys_are_unique():
    keys = [spec.key for spec in EXPORT_FORMATS]
    assert len(keys) == len(set(keys))


def test_suffixes_are_well_formed():
    for spec in EXPORT_FORMATS:
        assert spec.suffix.startswith("."), spec.key
        assert spec.suffix == spec.suffix.lower(), spec.key
        assert spec.suffix.lstrip(".") in spec.file_filter, spec.key


def test_every_exporter_is_callable():
    for spec in EXPORT_FORMATS:
        assert callable(spec.exporter), spec.key


def test_format_spec_lookup():
    assert format_spec("fountain").suffix == ".fountain"
    assert format_spec("fdx").screenplay is True
    assert format_spec("markdown").screenplay is False


def test_unknown_format_raises():
    # The old dispatch fell through to Markdown, so a typo produced the wrong
    # file rather than an error.
    with pytest.raises(ValueError):
        format_spec("nope")


def test_prose_mode_hides_screenplay_formats():
    keys = {spec.key for spec in formats_for_mode("prose")}
    assert keys == {"markdown", "docx"}


def test_screenplay_mode_offers_everything():
    assert formats_for_mode("screenplay") == EXPORT_FORMATS
