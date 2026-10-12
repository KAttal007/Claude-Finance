"""SQLAlchemy models mirroring the core DDL (design doc v1.0.1, Appendix A).

Monetary values are NUMERIC, never float. Raw files live in object storage; rows hold keys.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 1024  # must match the embedding model; see config.embedding_dim


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB}


# --- universe and coverage (sections 4, 8) --------------------------------------------------------


class Company(Base):
    """Every NSE-listed company, preloaded from EQUITY_L.csv and the SME list."""

    __tablename__ = "companies"
    __table_args__ = (
        CheckConstraint(
            "results_taxonomy IN ('indas','banking','nbfc','insurance')",
            name="ck_companies_results_taxonomy",
        ),
        Index(
            "ix_companies_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nse_symbol: Mapped[str] = mapped_column(Text, unique=True)
    isin: Mapped[str | None] = mapped_column(String(12), unique=True)
    name: Mapped[str] = mapped_column(Text)
    series: Mapped[str | None] = mapped_column(Text)
    listing_date: Mapped[date | None] = mapped_column(Date)
    face_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    sector: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(Text)
    results_taxonomy: Mapped[str | None] = mapped_column(Text)
    is_sme: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    source: Mapped[str] = mapped_column(
        Text, default="nse_equity_list", server_default="nse_equity_list"
    )
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Watchlist(Base):
    """Companies that get deep coverage: AI extraction, model updates, reports, alerts."""

    __tablename__ = "watchlist"

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'"))

    company: Mapped[Company] = relationship()


# --- feeds, filings, facts ------------------------------------------------------------------------


class FeedItem(Base):
    __tablename__ = "feed_items"
    __table_args__ = (
        UniqueConstraint("feed", "item_key"),
        Index("ix_feed_items_pub_date", "pub_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    feed: Mapped[str] = mapped_column(Text)
    item_key: Mapped[str] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    pub_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Filing(Base):
    __tablename__ = "filings"
    __table_args__ = (Index("ix_filings_company_period", "company_id", text("period_end DESC")),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    feed_item_id: Mapped[int | None] = mapped_column(ForeignKey("feed_items.id"))
    # results_xbrl, presentation, annual_report, transcript, other
    kind: Mapped[str] = mapped_column(Text)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    period_type: Mapped[str | None] = mapped_column(Text)  # Q, H, 9M, FY
    consolidated: Mapped[bool | None] = mapped_column(Boolean)
    audited: Mapped[bool | None] = mapped_column(Boolean)
    source_url: Mapped[str | None] = mapped_column(Text)
    file_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    storage_key: Mapped[str] = mapped_column(Text)
    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # fetched, parsed, validated, failed
    status: Mapped[str] = mapped_column(Text, default="fetched", server_default="fetched")
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'"))

    company: Mapped[Company] = relationship()


class Fact(Base):
    __tablename__ = "facts"
    __table_args__ = (
        UniqueConstraint(
            "filing_id", "element", "period_start", "period_end", "consolidated", "dims_hash"
        ),
        Index(
            "ix_facts_latest",
            "company_id",
            "element",
            "period_end",
            postgresql_where=text("is_latest"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    filing_id: Mapped[int] = mapped_column(ForeignKey("filings.id"))
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    element: Mapped[str] = mapped_column(Text)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    is_instant: Mapped[bool] = mapped_column(Boolean)
    consolidated: Mapped[bool] = mapped_column(Boolean)
    value: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    unit: Mapped[str | None] = mapped_column(Text)
    decimals: Mapped[int | None] = mapped_column(Integer)
    context_ref: Mapped[str | None] = mapped_column(Text)
    dimensions: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'"))
    dims_hash: Mapped[str] = mapped_column(String(64))
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class Kpi(Base):
    __tablename__ = "kpis"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    filing_id: Mapped[int] = mapped_column(ForeignKey("filings.id"))
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(Text)
    value: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    unit: Mapped[str | None] = mapped_column(Text)
    period_end: Mapped[date | None] = mapped_column(Date)
    page: Mapped[int | None] = mapped_column(Integer)
    quote: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    method: Mapped[str | None] = mapped_column(Text)  # claude_pdf, table, manual
    verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    filing_id: Mapped[int] = mapped_column(ForeignKey("filings.id"))
    page_count: Mapped[int | None] = mapped_column(Integer)


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index(
            "ix_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    page: Mapped[int] = mapped_column(Integer)
    ord: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', text)", persisted=True)
    )


class Price(Base):
    __tablename__ = "prices"

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    low: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    close: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    market_cap: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))


# --- templates, models, builds, assumptions (sections 12-16) --------------------------------------


class Template(Base):
    __tablename__ = "templates"
    __table_args__ = (UniqueConstraint("owner", "name", "version"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    sectors: Mapped[list[str]] = mapped_column(ARRAY(Text))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    storage_key: Mapped[str] = mapped_column(Text)
    structure: Mapped[dict[str, Any] | None] = mapped_column()
    mapping: Mapped[dict[str, Any] | None] = mapped_column()
    driver_cells: Mapped[dict[str, Any] | None] = mapped_column()
    check_cells: Mapped[dict[str, Any] | None] = mapped_column()
    # draft, tested, active
    status: Mapped[str] = mapped_column(Text, default="draft", server_default="draft")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TemplateTest(Base):
    __tablename__ = "template_tests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id"))
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    result: Mapped[str] = mapped_column(Text)  # pass, fail
    issues: Mapped[dict[str, Any] | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Model(Base):
    """An analyst workbook linked to a company: discovered on disk or built from a template."""

    __tablename__ = "models"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    template_id: Mapped[int | None] = mapped_column(ForeignKey("templates.id"))
    name: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text)  # discovered, built
    # Written into the workbook's custom document properties (hidden tag, section 13.2).
    doc_tag: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, default=uuid.uuid4)
    file_path: Mapped[str | None] = mapped_column(Text)
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    structure: Mapped[dict[str, Any] | None] = mapped_column()
    mapping: Mapped[dict[str, Any] | None] = mapped_column()

    company: Mapped[Company] = relationship()


class ModelBuild(Base):
    __tablename__ = "model_builds"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"))
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id"))
    history_from: Mapped[date | None] = mapped_column(Date)
    history_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text)  # gathering, awaiting_assumptions, built, failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Assumption(Base):
    __tablename__ = "assumptions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"))
    driver: Mapped[str] = mapped_column(Text)
    period: Mapped[str | None] = mapped_column(Text)
    proposed_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    rationale: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[dict[str, Any] | None] = mapped_column()
    # pending, accepted, edited, skipped
    decision: Mapped[str] = mapped_column(Text, default="pending", server_default="pending")
    final_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("model_id", "version"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"))
    version: Mapped[int] = mapped_column(Integer)
    parent_version: Mapped[int | None] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChangeSet(Base):
    __tablename__ = "change_sets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"))
    base_version: Mapped[int] = mapped_column(Integer)
    filing_id: Mapped[int | None] = mapped_column(ForeignKey("filings.id"))
    # proposed, approved, applied, rejected
    status: Mapped[str] = mapped_column(Text, default="proposed", server_default="proposed")
    summary: Mapped[dict[str, Any] | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list["ChangeItem"]] = relationship(back_populates="change_set")


class ChangeItem(Base):
    __tablename__ = "change_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    change_set_id: Mapped[int] = mapped_column(ForeignKey("change_sets.id"))
    # actual_write, roll_forward, assumption_suggestion, label_shift
    kind: Mapped[str] = mapped_column(Text)
    sheet: Mapped[str | None] = mapped_column(Text)
    cell: Mapped[str | None] = mapped_column(Text)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    formula_before: Mapped[str | None] = mapped_column(Text)
    formula_after: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    source_fact_id: Mapped[int | None] = mapped_column(ForeignKey("facts.id"))
    # pending, accepted, edited, skipped
    decision: Mapped[str] = mapped_column(Text, default="pending", server_default="pending")
    final_value: Mapped[str | None] = mapped_column(Text)

    change_set: Mapped[ChangeSet] = relationship(back_populates="items")


# --- outputs, accounting --------------------------------------------------------------------------


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    filing_id: Mapped[int | None] = mapped_column(ForeignKey("filings.id"))
    model_id: Mapped[int | None] = mapped_column(ForeignKey("models.id"))
    kind: Mapped[str] = mapped_column(Text)  # flash, note, slides, digest, initiation, qa
    storage_key: Mapped[str | None] = mapped_column(Text)
    model_used: Mapped[str | None] = mapped_column(Text)
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    citations: Mapped[dict[str, Any] | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LlmCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    purpose: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    request_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    kind: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column()
    channel: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PeerList(Base):
    """Saved peer sets for comps (section 18)."""

    __tablename__ = "peer_lists"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    symbols: Mapped[list[str]] = mapped_column(ARRAY(Text))
