"""Where numbers come from when something writes to a workbook: latest XBRL facts and KPIs, each
with a source reference (design doc 1.3 traceability). Shared by Model Sync, the Coverage
Builder and template test builds."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from analekh.db.models import Fact, Filing, Kpi
from analekh.workbook.mapping import Mapping, RowMap, apply_transform


@dataclass
class SourceValue:
    value: Decimal
    fact_id: int | None
    description: str
    filing_id: int | None = None
    source_url: str | None = None
    page: int | None = None


class ValueSource(Protocol):
    def xbrl(
        self, element: str, period_start: date | None, period_end: date, consolidated: bool
    ) -> SourceValue | None: ...

    def kpi(self, name: str, period_end: date) -> SourceValue | None: ...


def quarter_start(period_end: date) -> date:
    month = period_end.month - 2
    year = period_end.year
    if month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


@dataclass
class Resolved:
    value: Decimal
    fact_id: int | None
    descriptions: list[str]
    parts: list[SourceValue]


def resolve_row(
    source: ValueSource, row: RowMap, mapping: Mapping, period_end: date
) -> Resolved | None:
    """Value for one mapped row and quarter, transformed for display; None if any term missing."""
    p_start = quarter_start(period_end)
    total, fact_id, descs, parts = Decimal(0), None, [], []
    for term in row.terms():
        sv = (
            source.xbrl(term.key, p_start, period_end, mapping.consolidated)
            if term.kind == "xbrl"
            else source.kpi(term.key, period_end)
        )
        if sv is None:
            return None
        transform = row.transform or (
            mapping.units.default_transform if term.kind == "xbrl" else "none"
        )
        total += apply_transform(sv.value, transform, term.sign)
        fact_id = fact_id or sv.fact_id
        descs.append(sv.description)
        parts.append(sv)
    return Resolved(apply_transform(total, None, row.sign), fact_id, descs, parts)


class DbValueSource:
    """Latest facts and KPIs from PostgreSQL."""

    def __init__(self, session: Session, company_id: int) -> None:
        self.session, self.company_id = session, company_id

    def xbrl(
        self, element: str, period_start: date | None, period_end: date, consolidated: bool
    ) -> SourceValue | None:
        row = self.session.execute(
            select(Fact, Filing.source_url)
            .join(Filing, Fact.filing_id == Filing.id)
            .where(
                Fact.company_id == self.company_id,
                Fact.element == element,
                Fact.period_end == period_end,
                Fact.consolidated == consolidated,
                Fact.is_latest,
                Fact.dimensions == {},
                (Fact.period_start == period_start) | Fact.is_instant,
            )
        ).first()
        if row is None:
            return None
        fact, url = row
        if fact.value is None:
            return None
        span = (
            f"{fact.period_start} to {fact.period_end}"
            if fact.period_start
            else f"at {fact.period_end}"
        )
        return SourceValue(fact.value, fact.id, f"{element}, {span}", fact.filing_id, url)

    def kpi(self, name: str, period_end: date) -> SourceValue | None:
        kpi = self.session.scalar(
            select(Kpi)
            .where(
                Kpi.company_id == self.company_id, Kpi.name == name, Kpi.period_end == period_end
            )
            .order_by(Kpi.verified.desc())
        )
        if kpi is None or kpi.value is None:
            return None
        return SourceValue(
            kpi.value, None, f"KPI {name}, page {kpi.page}", kpi.filing_id, None, kpi.page
        )

    def elements(self, period_end: date, consolidated: bool = True) -> set[str]:
        """Every element the company reported for a quarter (unmapped-facts report)."""
        return set(
            self.session.scalars(
                select(Fact.element).where(
                    Fact.company_id == self.company_id,
                    Fact.period_end == period_end,
                    Fact.consolidated == consolidated,
                    Fact.is_latest,
                    Fact.dimensions == {},
                    Fact.is_instant.is_(False),
                )
            )
        )

    def latest_quarter(self, consolidated: bool = True) -> date | None:
        return self.session.scalar(
            select(Filing.period_end)
            .where(
                Filing.company_id == self.company_id,
                Filing.kind == "results_xbrl",
                Filing.period_type == "Q",
                Filing.consolidated == consolidated,
            )
            .order_by(Filing.period_end.desc())
        )
