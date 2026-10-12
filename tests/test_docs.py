from decimal import Decimal

import pymupdf

from analekh.docs.chunking import chunk_pages
from analekh.docs.classifier import select_pages
from analekh.docs.extract import extraction_schema, map_back
from analekh.docs.pdf import PageText, read_pages, subset
from analekh.docs.transcripts import parse_turns


def make_pdf(pages: list[str]) -> bytes:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data


def test_read_and_subset_pdf():
    data = make_pdf(["Cover page for the quarter", "Gold loan AUM 82,000 crore", "Thank you"])
    pages = read_pages(data, ocr=False)
    assert [p.number for p in pages] == [1, 2, 3]
    sub = read_pages(subset(data, [2]), ocr=False)
    assert len(sub) == 1 and "82,000" in sub[0].text


def test_classifier_selects_kpi_and_statement_pages():
    pages = [
        PageText(1, "Investor presentation cover"),
        PageText(
            2,
            "Key highlights AUM 82,000 Net interest margin 11.2 % GNPA 3.4 % "
            "Stage 3 2.9 % 1,234 5,678 9,012",
        ),
        PageText(
            3,
            "Statement of profit and loss Total income 1,050 Profit before tax 250 120 340 560 780",
        ),
        PageText(4, "Disclaimer and safe harbour"),
    ]
    chosen = [s.page for s in select_pages(pages, "presentation")]
    assert chosen == [2, 3]


def test_map_back_translates_pages_and_checks_quotes():
    from analekh.docs.classifier import PageScore

    selected = [PageScore(7, "kpi_table", 5), PageScore(12, "asset_quality", 4)]
    pages = {
        7: PageText(7, "Gold loan AUM stood at Rs 82,000 crore"),
        12: PageText(12, "GNPA 3.4%"),
    }
    raw = {
        "period_end": "2026-09-30",
        "guidance": [],
        "red_flags": [{"type": "pledge", "detail": "x", "page": 2}],
        "kpis": [
            {
                "name": "gold_loan_aum",
                "value": 82000,
                "unit": "INR crore",
                "page": 1,
                "quote": "AUM stood at Rs 82,000 crore",
                "confidence": 0.95,
            },
            {
                "name": "gnpa",
                "value": 3.9,
                "unit": "percent",
                "page": 2,
                "quote": "GNPA 3.9%",
                "confidence": 0.9,
            },
        ],
    }
    out = map_back(raw, selected, pages)
    aum, gnpa = out.kpis
    assert aum.page == 7 and aum.quote_found and aum.value == Decimal("82000")
    assert gnpa.page == 12 and not gnpa.quote_found and gnpa.confidence <= Decimal("0.3")
    assert out.red_flags[0]["page"] == 12


def test_extraction_schema_is_strict():
    schema = extraction_schema(["aum"])
    assert schema["additionalProperties"] is False
    item = schema["properties"]["kpis"]["items"]
    assert item["additionalProperties"] is False and "quote" in item["required"]


def test_chunks_keep_page_numbers():
    pages = [PageText(1, "a" * 1000 + "\n\n" + "b" * 1000), PageText(2, "short")]
    chunks = chunk_pages(pages, target=1200, overlap=100)
    assert {c.page for c in chunks} == {1, 2}
    assert all(len(c.text) <= 2400 for c in chunks)


def test_transcript_roles():
    pages = [
        PageText(
            3,
            "Moderator: The next question is from Priya Shah from ABC Securities.\n"
            "Priya Shah: What is the guidance on AUM growth?\n"
            "Ravi Kumar: We expect 15% growth.\nmore detail here",
        )
    ]
    turns = parse_turns(pages)
    roles = {t.speaker: t.role for t in turns}
    assert roles == {"Moderator": "moderator", "Priya Shah": "analyst", "Ravi Kumar": "management"}
    assert turns[-1].text.endswith("more detail here")
