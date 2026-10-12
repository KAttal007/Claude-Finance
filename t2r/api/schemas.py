from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TrackCompany(BaseModel):
    symbol: str


class CompanyOut(ORM):
    id: int
    nse_symbol: str
    isin: str | None
    bse_code: str | None
    name: str
    sector: str | None
    results_taxonomy: str | None
    is_tracked: bool


class FilingOut(ORM):
    id: int
    kind: str
    period_start: date | None
    period_end: date | None
    period_type: str | None
    consolidated: bool | None
    audited: bool | None
    source_url: str | None
    filed_at: datetime | None
    status: str
    meta: dict[str, Any]


class FactOut(ORM):
    id: int
    filing_id: int
    element: str
    period_start: date | None
    period_end: date
    is_instant: bool
    consolidated: bool
    value: Decimal | None
    unit: str | None
    context_ref: str | None


class KpiOut(ORM):
    id: int
    filing_id: int
    name: str
    value: Decimal | None
    unit: str | None
    period_end: date | None
    page: int | None
    quote: str | None
    confidence: Decimal | None
    verified: bool


class JobOut(BaseModel):
    job_id: str
    status: str
    result: Any = None


class ChangeItemOut(ORM):
    id: int
    kind: str
    sheet: str | None
    cell: str | None
    old_value: str | None
    new_value: str | None
    formula_before: str | None
    formula_after: str | None
    rationale: str | None
    source_fact_id: int | None
    decision: str
    final_value: str | None


class ChangeSetOut(ORM):
    id: int
    model_id: int
    base_version: int
    filing_id: int | None
    status: str
    summary: dict[str, Any] | None
    items: list[ChangeItemOut]


class Decision(BaseModel):
    item_id: int
    decision: Literal["accepted", "edited", "skipped"]
    final_value: str | None = None


class Decisions(BaseModel):
    decisions: list[Decision] = []
    accept_kinds: list[str] = []  # bulk accept per kind (design doc 10.5)


class SyncRequest(BaseModel):
    filing_id: int


class ReportRequest(BaseModel):
    symbol: str
    kind: Literal["flash", "digest", "red_flags", "note"]
    period_end: date
    model_id: int | None = None


class QaRequest(BaseModel):
    symbol: str
    question: str


class CompsRequest(BaseModel):
    symbols: list[str] = []
    peer_list: str | None = None
