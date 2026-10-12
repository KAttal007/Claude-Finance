"""One path for every results file, live or backfill: hash -> store -> parse -> validate -> facts.

Results XBRL is fetched and parsed for every company that files (design doc 9.2). Announcement
PDFs are stored for everyone (cheap) but only processed by the document pipeline for watchlist or
on-demand companies.

Re-running is idempotent: a file whose hash is already stored is skipped. A different file for an
already-stored period is a restatement: new facts are inserted, old ones lose is_latest (V9);
nothing is deleted.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, select, update
from sqlalchemy.orm import Session

from analekh.db.models import Company, Fact, FeedItem, Filing
from analekh.ingest.http import PoliteClient
from analekh.ingest.storage import ObjectStore, sha256, storage_key
from analekh.validate.rules import HistoryFact, ValidationContext, ValidationReport, validate
from analekh.xbrl.parser import dims_hash, parse_instance, period_type

_NO_DIMS = dims_hash({})

ANNOUNCEMENT_KINDS = (
    ("transcript", ("transcript", "earnings call", "conference call")),
    ("presentation", ("investor presentation", "presentation")),
    ("annual_report", ("annual report",)),
)


@dataclass
class IngestResult:
    filing: Filing
    skipped: bool
    report: ValidationReport | None = None


def load_history(session: Session, company_id: int, consolidated: bool) -> list[HistoryFact]:
    rows = session.execute(
        select(Fact.element, Fact.period_start, Fact.period_end, Fact.value, Fact.filing_id).where(
            Fact.company_id == company_id,
            Fact.consolidated == consolidated,
            Fact.is_latest,
            Fact.dims_hash == _NO_DIMS,
            Fact.value.is_not(None),
        )
    ).all()
    return [
        HistoryFact(r.element, r.period_start, r.period_end, r.value, r.filing_id) for r in rows
    ]


def ingest_results_xbrl(
    session: Session,
    store: ObjectStore,
    company: Company,
    data: bytes,
    *,
    source_url: str | None = None,
    feed_item_id: int | None = None,
    filed_at: datetime | None = None,
) -> IngestResult:
    digest = sha256(data)
    existing = session.scalar(select(Filing).where(Filing.file_sha256 == digest))
    if existing is not None:
        return IngestResult(existing, skipped=True)

    key = storage_key("results_xbrl", digest, "xml", filed_at)
    store.put(key, data, "application/xml")
    parsed = parse_instance(data)

    if company.results_taxonomy is None:
        company.results_taxonomy = parsed.taxonomy()
    consolidated = parsed.consolidated if parsed.consolidated is not None else True
    history = load_history(session, company.id, consolidated)
    ctx = ValidationContext(
        parsed, company.results_taxonomy, filed_at.date() if filed_at else None, history
    )
    report = validate(ctx)

    period_end = ctx.period_end
    period_start = parsed.declared_start or next(
        (
            f.period_start
            for f in parsed.facts
            if f.period_end == period_end and period_type(f.period_start, f.period_end) == "Q"
        ),
        None,
    )
    filing = Filing(
        company_id=company.id,
        feed_item_id=feed_item_id,
        kind="results_xbrl",
        period_start=period_start,
        period_end=period_end,
        period_type=period_type(period_start, period_end) if period_end else None,
        consolidated=consolidated,
        audited=parsed.audited,
        source_url=source_url,
        file_sha256=digest,
        storage_key=key,
        filed_at=filed_at,
        status="validated",
        meta={
            "schema_ref": parsed.schema_ref,
            "declared": parsed.meta,
            "parser_warnings": parsed.warnings,
            "validation": report.as_dict(),
            "blocks_auto_apply": report.blocks_auto_apply,
        },
    )
    session.add(filing)
    session.flush()

    for f in parsed.facts:
        session.execute(
            update(Fact)
            .where(
                and_(
                    Fact.company_id == company.id,
                    Fact.element == f.element,
                    Fact.period_start.is_(None)
                    if f.period_start is None
                    else Fact.period_start == f.period_start,
                    Fact.period_end == f.period_end,
                    Fact.consolidated == consolidated,
                    Fact.dims_hash == f.dims_hash,
                    Fact.is_latest,
                )
            )
            .values(is_latest=False)
        )
        session.add(
            Fact(
                filing_id=filing.id,
                company_id=company.id,
                element=f.element,
                period_start=f.period_start,
                period_end=f.period_end,
                is_instant=f.is_instant,
                consolidated=consolidated,
                value=f.value,
                unit=f.unit,
                decimals=f.decimals,
                context_ref=f.context_ref,
                dimensions=f.dimensions,
                dims_hash=f.dims_hash,
            )
        )
    session.flush()
    return IngestResult(filing, skipped=False, report=report)


def classify_announcement(title: str | None, description: str | None = None) -> str:
    text = f"{title or ''} {description or ''}".lower()
    for kind, keywords in ANNOUNCEMENT_KINDS:
        if any(k in text for k in keywords):
            return kind
    return "other"


def process_feed_item(
    session: Session, store: ObjectStore, client: PoliteClient, item: FeedItem
) -> Filing | None:
    """Fetch the file an RSS item links to and route it. Unlinked items wait for review."""
    if item.company_id is None or not item.link:
        return None
    company = session.get(Company, item.company_id)
    if company is None:
        return None
    result = client.get(item.link)
    filing: Filing | None
    if item.feed == "financial_results":
        filing = ingest_results_xbrl(
            session,
            store,
            company,
            result.content,
            source_url=item.link,
            feed_item_id=item.id,
            filed_at=item.pub_date,
        ).filing
    else:
        filing = store_document(
            session,
            store,
            company,
            result.content,
            kind=classify_announcement(item.title, item.description),
            source_url=item.link,
            feed_item_id=item.id,
            filed_at=item.pub_date,
        )
    item.processed_at = datetime.now().astimezone()
    return filing


def store_document(
    session: Session,
    store: ObjectStore,
    company: Company,
    data: bytes,
    *,
    kind: str,
    source_url: str | None = None,
    feed_item_id: int | None = None,
    filed_at: datetime | None = None,
    ext: str = "pdf",
) -> Filing:
    """Store a PDF once; the document pipeline (analekh.docs) picks it up from status 'fetched'."""
    digest = sha256(data)
    existing = session.scalar(select(Filing).where(Filing.file_sha256 == digest))
    if existing is not None:
        return existing
    key = storage_key(kind, digest, ext, filed_at)
    store.put(key, data, "application/pdf")
    filing = Filing(
        company_id=company.id,
        feed_item_id=feed_item_id,
        kind=kind,
        source_url=source_url,
        file_sha256=digest,
        storage_key=key,
        filed_at=filed_at,
        status="fetched",
    )
    session.add(filing)
    session.flush()
    return filing
