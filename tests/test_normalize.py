from rewriteocr.core.normalize import normalize_markdown


def test_unwraps_full_output_fence():
    assert normalize_markdown("```markdown\n# Title\n\nBody\n```") == "# Title\n\nBody"


def test_keeps_inner_code_fences():
    text = "Intro\n\n```python\nprint('hi')\n```\n\nOutro"
    assert normalize_markdown(text) == text


def test_fixes_heading_spacing():
    assert normalize_markdown("##Heading") == "## Heading"


def test_collapses_blank_runs_and_line_endings():
    assert normalize_markdown("a\r\n\r\n\r\n\r\nb  ") == "a\n\nb"


def test_strips_zero_width_characters():
    assert normalize_markdown("a​b") == "ab"
