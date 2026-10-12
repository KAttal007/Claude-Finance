"""KPI, guidance and red-flag extraction from selected PDF pages (design doc 9.1 step 4, 9.2).

Only the selected pages are sent (as a sub-PDF). Every value comes back with a page number,
a verbatim quote and a confidence; quotes are checked against the locally extracted page text
and values whose quote cannot be found are marked low confidence for review.
"""

import contextlib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from t2r.db.models import Filing, Kpi
from t2r.docs.classifier import PageScore
from t2r.docs.pdf import PageText, subset
from t2r.genai.client import Claude, pdf_block

SYSTEM = (
    "You extract figures from Indian listed-company filings for an equity research analyst. "
    "Report only values printed on the pages provided. For each value give the page number "
    "within the attached PDF (first page = 1) and a short verbatim quote containing the number. "
    "If a KPI is not on these pages, leave it out; never estimate or compute. Convert values to "
    "the unit requested for that KPI and say so in the unit field. Confidence is your probability "
    "that value, unit and period are all correct."
)


def extraction_schema(kpi_names: list[str]) -> dict[str, Any]:
    kpi_item = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "enum": kpi_names} if kpi_names else {"type": "string"},
            "value": {"type": "number"},
            "unit": {"type": "string"},
            "page": {"type": "integer"},
            "quote": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "required": ["name", "value", "unit", "page", "quote", "confidence"],
        "additionalProperties": False,
    }
    note = {
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "statement": {"type": "string"},
            "page": {"type": "integer"},
        },
        "required": ["topic", "statement", "page"],
        "additionalProperties": False,
    }
    flag = {
        "type": "object",
        "properties": {
            "type": {"type": "string"},
            "detail": {"type": "string"},
            "page": {"type": "integer"},
        },
        "required": ["type", "detail", "page"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "period_end": {"type": "string", "description": "YYYY-MM-DD"},
            "kpis": {"type": "array", "items": kpi_item},
            "guidance": {"type": "array", "items": note},
            "red_flags": {"type": "array", "items": flag},
        },
        "required": ["period_end", "kpis", "guidance", "red_flags"],
        "additionalProperties": False,
    }


@dataclass
class ExtractedKpi:
    name: str
    value: Decimal
    unit: str
    page: int  # original document page
    quote: str
    confidence: Decimal
    quote_found: bool


@dataclass
class Extraction:
    period_end: date | None
    kpis: list[ExtractedKpi] = field(default_factory=list)
    guidance: list[dict[str, Any]] = field(default_factory=list)
    red_flags: list[dict[str, Any]] = field(default_factory=list)


def build_prompt(company: str, kpis: dict[str, str], period_hint: str | None) -> str:
    wanted = "\n".join(f"- {name} ({unit})" for name, unit in kpis.items())
    period = f" Reporting period: {period_hint}." if period_hint else ""
    return (
        f"Company: {company}.{period}\nKPIs to extract (name and target unit):\n{wanted}\n\n"
        "Also list forward-looking guidance statements and possible red flags "
        "(auditor qualifications, pledges, related-party transactions, restatements)."
    )


def map_back(
    raw: dict[str, Any], selected: list[PageScore], pages: dict[int, PageText]
) -> Extraction:
    """Translate sub-PDF page numbers to original pages and verify quotes locally."""
    order = [s.page for s in selected]

    def original(p: int) -> int:
        return order[p - 1] if 1 <= p <= len(order) else -1

    period = None
    with contextlib.suppress(ValueError):
        period = date.fromisoformat(raw.get("period_end", "")[:10])
    out = Extraction(period_end=period)
    for k in raw.get("kpis", []):
        page = original(int(k["page"]))
        try:
            value = Decimal(str(k["value"]))
        except InvalidOperation:
            continue
        found = page in pages and _quote_in(k["quote"], pages[page].text)
        confidence = Decimal(str(round(float(k["confidence"]), 2)))
        out.kpis.append(
            ExtractedKpi(
                k["name"],
                value,
                k["unit"],
                page,
                k["quote"],
                confidence if found else min(confidence, Decimal("0.3")),
                found,
            )
        )
    for g in raw.get("guidance", []):
        out.guidance.append(g | {"page": original(int(g["page"]))})
    for f in raw.get("red_flags", []):
        out.red_flags.append(f | {"page": original(int(f["page"]))})
    return out


def extract(
    claude: Claude,
    pdf: bytes,
    pages: list[PageText],
    selected: list[PageScore],
    company: str,
    kpis: dict[str, str],
    period_hint: str | None = None,
) -> Extraction:
    sub = subset(pdf, [s.page for s in selected])
    raw = claude.create_json(
        "kpi_extraction",
        extraction_schema(list(kpis)),
        system=SYSTEM,
        messages=[
            {
                "role": "user",
                "content": [
                    pdf_block(sub),
                    {"type": "text", "text": build_prompt(company, kpis, period_hint)},
                ],
            }
        ],
        effort="medium",
    )
    return map_back(raw, selected, {p.number: p for p in pages})


def batch_params(
    model: str,
    pdf_subset: bytes,
    company: str,
    kpis: dict[str, str],
    period_hint: str | None = None,
) -> dict[str, Any]:
    """Message params for the Batch API (backfill, design doc 7.3). No fallbacks on batches."""
    return {
        "model": model,
        "max_tokens": 16000,
        "system": SYSTEM,
        "output_config": {
            "effort": "medium",
            "format": {"type": "json_schema", "schema": extraction_schema(list(kpis))},
        },
        "messages": [
            {
                "role": "user",
                "content": [
                    pdf_block(pdf_subset),
                    {"type": "text", "text": build_prompt(company, kpis, period_hint)},
                ],
            }
        ],
    }


def save_kpis(session: Session, filing: Filing, extraction: Extraction) -> int:
    for k in extraction.kpis:
        session.add(
            Kpi(
                filing_id=filing.id,
                company_id=filing.company_id,
                name=k.name,
                value=k.value,
                unit=k.unit,
                period_end=extraction.period_end,
                page=k.page,
                quote=k.quote,
                confidence=k.confidence,
                method="claude_pdf",
            )
        )
    filing.meta = {
        **(filing.meta or {}),
        "guidance": extraction.guidance,
        "red_flags": extraction.red_flags,
    }
    return len(extraction.kpis)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace(",", "")).strip().lower()


def _quote_in(quote: str, page_text: str) -> bool:
    return bool(quote) and _norm(quote) in _norm(page_text)
