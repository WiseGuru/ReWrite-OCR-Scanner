from rewriteocr.core.pdf_io import PdfDocument
from rewriteocr.core.triage import classify_page, text_sanity


def test_born_digital_pages(born_digital_pdf):
    with PdfDocument(born_digital_pdf) as doc:
        for i in range(doc.page_count):
            result = classify_page(doc, i)
            assert result.classification == "born_digital", (i, result)
            assert "body text" in result.text


def test_scanned_pages_have_no_text_layer(scanned_pdf):
    with PdfDocument(scanned_pdf) as doc:
        for i in range(doc.page_count):
            result = classify_page(doc, i)
            assert result.classification == "scanned", (i, result)


def test_mixed_page(mixed_pdf):
    with PdfDocument(mixed_pdf) as doc:
        result = classify_page(doc, 0)
        assert result.classification == "mixed", result


def test_garbage_text_layer_is_treated_as_scanned(garbage_text_pdf):
    with PdfDocument(garbage_text_pdf) as doc:
        result = classify_page(doc, 0)
        assert result.classification == "scanned", result


def test_text_sanity_rejects_garbage():
    sane, _, _ = text_sanity("¶¤¨ˆ˜ %%% ±µ !!!! ~~~~ ;;;;" * 10)
    assert not sane


def test_text_sanity_accepts_prose():
    sane, printable, alnum = text_sanity(
        "This is a perfectly ordinary paragraph of English prose with words."
    )
    assert sane
    assert printable > 0.95
    assert alnum > 0.5
