"""Comparable companies table (design doc 12).

EV = market cap + debt - cash from the latest balance sheet. TTM figures are the sum of the last
four reported quarters. Multiples that would divide by zero or a negative denominator are left
blank (shown as "n.m."), never forced.
"""

import io
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import xlsxwriter
from sqlalchemy import select
from sqlalchemy.orm import Session

from t2r.db.models import Company, Fact, Price
from t2r.xbrl.elements import candidates
from t2r.xbrl.parser import period_type

CRORE = Decimal(10_000_000)


@dataclass
class CompInputs:
    symbol: str
    name: str
    market_cap: Decimal | None
    debt: Decimal | None
    cash: Decimal | None
    ttm_revenue: Decimal | None
    ttm_ebitda: Decimal | None
    ttm_pat: Decimal | None
    book_value: Decimal | None
    as_of: date | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class CompRow:
    inputs: CompInputs
    ev: Decimal | None
    ev_sales: Decimal | None
    ev_ebitda: Decimal | None
    pe: Decimal | None
    pb: Decimal | None


def _ratio(num: Decimal | None, den: Decimal | None) -> Decimal | None:
    if num is None or den is None or den <= 0:
        return None
    return (num / den).quantize(Decimal("0.1"))


def compute(inputs: CompInputs) -> CompRow:
    ev = None
    if inputs.market_cap is not None:
        ev = inputs.market_cap + (inputs.debt or 0) - (inputs.cash or 0)
    return CompRow(
        inputs,
        ev,
        _ratio(ev, inputs.ttm_revenue),
        _ratio(ev, inputs.ttm_ebitda),
        _ratio(inputs.market_cap, inputs.ttm_pat),
        _ratio(inputs.market_cap, inputs.book_value),
    )


def summary_stats(rows: list[CompRow]) -> dict[str, dict[str, Decimal | None]]:
    out: dict[str, dict[str, Decimal | None]] = {}
    for metric in ("ev_sales", "ev_ebitda", "pe", "pb"):
        vals = sorted(v for r in rows if (v := getattr(r, metric)) is not None)
        if not vals:
            out[metric] = {"median": None, "mean": None}
            continue
        mid = len(vals) // 2
        median = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
        out[metric] = {
            "median": median.quantize(Decimal("0.1")),
            "mean": (sum(vals) / len(vals)).quantize(Decimal("0.1")),
        }
    return out


def ttm(
    session: Session,
    company_id: int,
    logical: str,
    taxonomy: str = "indas",
    consolidated: bool = True,
) -> tuple[Decimal | None, list[str]]:
    """Sum of the latest four quarterly facts; None if any quarter is missing."""
    names = candidates(logical, taxonomy)
    facts = session.scalars(
        select(Fact)
        .where(
            Fact.company_id == company_id,
            Fact.element.in_(names),
            Fact.is_latest,
            Fact.consolidated == consolidated,
            Fact.dimensions == {},
            Fact.is_instant.is_(False),
        )
        .order_by(Fact.period_end.desc())
    ).all()
    quarters = []
    seen = set()
    for f in facts:
        if period_type(f.period_start, f.period_end) == "Q" and f.period_end not in seen:
            seen.add(f.period_end)
            quarters.append(f)
        if len(quarters) == 4:
            break
    if len(quarters) < 4 or any(q.value is None for q in quarters):
        return None, [f"{logical}: only {len(quarters)} quarters available"]
    return sum((q.value for q in quarters if q.value is not None), Decimal(0)), []


def gather(session: Session, symbol: str) -> CompInputs:
    """PHASE 5: EBITDA and debt/cash element choices need confirming per taxonomy."""
    company = session.scalar(select(Company).where(Company.nse_symbol == symbol))
    if company is None:
        raise LookupError(symbol)
    tax = company.results_taxonomy or "indas"
    notes: list[str] = []
    revenue, n1 = ttm(session, company.id, "revenue", tax)
    pat, n2 = ttm(session, company.id, "pat", tax)
    notes += n1 + n2
    price = session.scalar(
        select(Price).where(Price.company_id == company.id).order_by(Price.trade_date.desc())
    )
    if price is None or price.market_cap is None:
        notes.append("no market cap: load prices first")
    return CompInputs(
        symbol,
        company.name,
        price.market_cap if price else None,
        debt=None,
        cash=None,
        ttm_revenue=revenue,
        ttm_ebitda=None,
        ttm_pat=pat,
        book_value=None,
        as_of=price.trade_date if price else None,
        notes=notes,
    )


def to_xlsx(rows: list[CompRow], title: str = "Comparable companies") -> bytes:
    out = io.BytesIO()
    wb = xlsxwriter.Workbook(out, {"in_memory": True})
    ws = wb.add_worksheet("Comps")
    bold = wb.add_format({"bold": True, "bottom": 1})
    num = wb.add_format({"num_format": "#,##0"})
    mult = wb.add_format({"num_format": '0.0"x"'})
    ws.write(0, 0, title, wb.add_format({"bold": True, "font_size": 14}))
    ws.write(1, 0, "INR crore; multiples on TTM; n.m. = not meaningful")
    headers = [
        "Company",
        "Mkt cap",
        "EV",
        "TTM revenue",
        "TTM PAT",
        "EV/Sales",
        "EV/EBITDA",
        "P/E",
        "P/B",
    ]
    for c, h in enumerate(headers):
        ws.write(3, c, h, bold)
    for r, row in enumerate(rows, start=4):
        i = row.inputs
        ws.write(r, 0, i.name)
        for c, v in enumerate([i.market_cap, row.ev, i.ttm_revenue, i.ttm_pat], start=1):
            ws.write(r, c, float(v / CRORE), num) if v is not None else ws.write(r, c, "n.a.")
        for c, v in enumerate([row.ev_sales, row.ev_ebitda, row.pe, row.pb], start=5):
            ws.write(r, c, float(v), mult) if v is not None else ws.write(r, c, "n.m.")
    stats = summary_stats(rows)
    base = 4 + len(rows) + 1
    for k, label in enumerate(("median", "mean")):
        ws.write(base + k, 0, label.capitalize(), bold)
        for c, metric in enumerate(("ev_sales", "ev_ebitda", "pe", "pb"), start=5):
            v = stats[metric][label]
            ws.write(base + k, c, float(v), mult) if v is not None else ws.write(
                base + k, c, "n.m."
            )
    ws.set_column(0, 0, 32)
    ws.set_column(1, 8, 12)
    wb.close()
    return out.getvalue()
