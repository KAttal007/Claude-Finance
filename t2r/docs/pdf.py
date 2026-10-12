"""Local PDF reading with PyMuPDF (design doc 9.1 step 1). Free and fast; no AI here."""

import re
from dataclasses import dataclass

import pymupdf

MIN_TEXT_CHARS = 40


@dataclass
class PageText:
    number: int  # 1-based, as cited to the analyst
    text: str
    ocr: bool = False

    @property
    def numeric_density(self) -> float:
        """Share of tokens that are numbers: a cheap table-likeness signal."""
        tokens = self.text.split()
        if not tokens:
            return 0.0
        numeric = sum(1 for t in tokens if re.fullmatch(r"\(?-?[\d,]+(\.\d+)?\)?%?", t))
        return numeric / len(tokens)


def read_pages(data: bytes, ocr: bool = True) -> list[PageText]:
    pages = []
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text")
            if ocr and len(text.strip()) < MIN_TEXT_CHARS:
                ocr_text = _ocr(page)
                if ocr_text:
                    pages.append(PageText(i, ocr_text, ocr=True))
                    continue
            pages.append(PageText(i, text))
    return pages


def subset(data: bytes, page_numbers: list[int]) -> bytes:
    """A new PDF containing only the selected (1-based) pages, in the given order."""
    with pymupdf.open(stream=data, filetype="pdf") as src, pymupdf.open() as out:
        for n in page_numbers:
            out.insert_pdf(src, from_page=n - 1, to_page=n - 1)
        return out.tobytes()


def _ocr(page: "pymupdf.Page") -> str:
    """Tesseract fallback for scanned pages; empty when tesseract is not installed."""
    try:
        tp = page.get_textpage_ocr(full=True)
        return page.get_text("text", textpage=tp)
    except Exception:  # noqa: BLE001 - tesseract missing or failed
        return ""
