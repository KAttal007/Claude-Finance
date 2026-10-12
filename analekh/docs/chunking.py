"""Chunk pages for search and Q&A (design doc 9.1 step 5). Chunks never cross pages, so every
search hit carries an exact page reference."""

from dataclasses import dataclass

from analekh.docs.pdf import PageText

TARGET_CHARS = 1500
OVERLAP_CHARS = 200


@dataclass
class TextChunk:
    page: int
    ord: int
    text: str


def chunk_pages(
    pages: list[PageText], target: int = TARGET_CHARS, overlap: int = OVERLAP_CHARS
) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    for page in pages:
        paragraphs = [p.strip() for p in page.text.split("\n\n") if p.strip()]
        buf = ""
        for para in paragraphs or [page.text.strip()]:
            if buf and len(buf) + len(para) + 1 > target:
                chunks.append(TextChunk(page.number, len(chunks), buf))
                buf = buf[-overlap:] + "\n" + para if overlap else para
            else:
                buf = f"{buf}\n{para}" if buf else para
            while len(buf) > target * 2:  # one giant paragraph
                chunks.append(TextChunk(page.number, len(chunks), buf[:target]))
                buf = buf[target - overlap :]
        if buf.strip():
            chunks.append(TextChunk(page.number, len(chunks), buf))
    return chunks
