from rewriteocr.core.flags import (
    engine_disagreement_flag,
    low_yield_flag,
    repetition_flag,
)

PROSE = (
    "The committee reviewed the annual budget in detail, noting several "
    "discrepancies between projected and actual expenditures across the "
    "various departments during the previous fiscal year."
)


def test_repetition_detects_ngram_loop():
    text = "The invoice number is 42 and " * 12
    flag = repetition_flag(0, text)
    assert flag is not None
    assert flag.kind == "repetition"
    assert flag.severity > 0.5
    assert "repeats" in flag.detail


def test_repetition_detects_tail_cycle():
    text = PROSE + " la la " * 40
    flag = repetition_flag(0, text)
    assert flag is not None


def test_repetition_passes_clean_prose():
    assert repetition_flag(0, PROSE) is None


def test_low_yield_flags_dense_page_with_tiny_output():
    # 10 percent ink on a 3M pixel render should yield thousands of chars.
    flag = low_yield_flag(0, "almost nothing", ink_ratio=0.10, image_px=3_000_000)
    assert flag is not None
    assert flag.kind == "low_yield"


def test_low_yield_ignores_blank_pages():
    assert low_yield_flag(0, "", ink_ratio=0.001, image_px=3_000_000) is None


def test_low_yield_passes_normal_output():
    text = PROSE * 20
    assert low_yield_flag(0, text, ink_ratio=0.05, image_px=1_000_000) is None


def test_disagreement_flags_divergent_engines():
    a = PROSE
    b = "Completely unrelated text about maritime navigation and celestial bodies observed at night from the deck of a sailing vessel in the southern hemisphere during winter."
    flag = engine_disagreement_flag(0, a, b)
    assert flag is not None
    assert flag.kind == "engine_disagreement"


def test_disagreement_tolerates_markdown_formatting_differences():
    a = "# Budget Report\n\n" + PROSE
    b = PROSE.upper()
    assert engine_disagreement_flag(0, a, b) is None


def test_disagreement_skips_short_texts():
    assert engine_disagreement_flag(0, "hi", "bye") is None
