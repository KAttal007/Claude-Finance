import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- universe and coverage ------------------------------------------------------------------------


class SearchHitOut(BaseModel):
    id: int
    nse_symbol: str
    name: str
    isin: str | None
    sector: str | None
    is_active: bool
    score: float


class CompanyOut(ORM):
    id: int
    nse_symbol: str
    isin: str | None
    name: str
    series: str | None
    listing_date: date | None
    face_value: Decimal | None
    sector: str | None
    industry: str | None
    results_taxonomy: str | None
    is_sme: bool
    is_active: bool
    refreshed_at: datetime | None


class CompanyDetail(CompanyOut):
    coverage_level: str  # universe | numbers | deep
    watched: bool


class WatchRequest(BaseModel):
    symbol: str
    settings: dict[str, Any] = Field(default_factory=dict)  # alerts, auto-analyse


class WatchlistEntryOut(BaseModel):
    symbol: str
    name: str
    added_at: datetime
    settings: dict[str, Any]
    last_filing: date | None
    validation_blocked: bool
    pending_change_sets: int


# --- filings, facts, KPIs -------------------------------------------------------------------------


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


# --- templates, coverage, models ------------------------------------------------------------------


class TemplateOut(ORM):
    id: int
    owner: str
    name: str
    sectors: list[str]
    version: int
    status: str
    is_default: bool
    mapping: dict[str, Any] | None
    structure: dict[str, Any] | None
    created_at: datetime


class TemplateTestRequest(BaseModel):
    symbol: str


class TemplateTestOut(ORM):
    id: int
    template_id: int
    company_id: int
    result: str
    issues: dict[str, Any] | None


class CoverageRequest(BaseModel):
    symbol: str
    template_id: int | None = None  # default: the sector's default template


class AssumptionOut(ORM):
    id: int
    driver: str
    period: str | None
    proposed_value: Decimal | None
    rationale: str | None
    citations: dict[str, Any] | None
    decision: str
    final_value: Decimal | None


class AssumptionDecision(BaseModel):
    id: int
    decision: Literal["accepted", "edited", "skipped"]
    final_value: Decimal | None = None


class AssumptionDecisions(BaseModel):
    decisions: list[AssumptionDecision] = Field(default_factory=list)
    accept_all: bool = False


class ModelOut(ORM):
    id: int
    company_id: int
    template_id: int | None
    name: str
    origin: str
    doc_tag: uuid.UUID
    file_path: str | None
    last_seen: datetime | None


class BuildOut(BaseModel):
    model: ModelOut
    build_status: str
    filled_cells: int
    blank_rows: list[str]
    assumptions: list[AssumptionOut]


class WorkbookHintsIn(BaseModel):
    path: str
    tag_model_id: str | None = None
    tag_symbol: str | None = None
    text: list[str] = Field(default_factory=list)
    modified: float | None = None
    fingerprint: str | None = None


class DiscoverRequest(BaseModel):
    workbooks: list[WorkbookHintsIn]


class LinkRequest(BaseModel):
    symbol: str
    workbook: WorkbookHintsIn
    mapping: dict[str, Any] | None = None


# --- change sets ----------------------------------------------------------------------------------


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
    decisions: list[Decision] = Field(default_factory=list)
    accept_kinds: list[str] = Field(default_factory=list)  # bulk accept per kind (16.4)


class SyncRequest(BaseModel):
    filing_id: int


# --- outputs --------------------------------------------------------------------------------------


class ReportRequest(BaseModel):
    symbol: str
    kind: Literal["flash", "digest", "red_flags", "note", "initiation"]
    period_end: date
    model_id: int | None = None


class QaRequest(BaseModel):
    symbol: str
    question: str


class CompsRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    peer_list: str | None = None
