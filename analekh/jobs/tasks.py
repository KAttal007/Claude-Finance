"""Idempotent background jobs (design doc 2.2, 4, 9). Re-running any task never duplicates rows.

Coverage levels decide the work: results XBRL is fetched and parsed for every filer; announcement
PDFs are stored for everyone but the document pipeline runs only for watchlist companies or a
company someone asked to analyse.
"""

from pathlib import Path

from sqlalchemy import exists, select

from analekh.config import get_settings
from analekh.db.models import FeedItem, Filing, Watchlist
from analekh.db.session import session_scope
from analekh.ingest.backfill import run_backfill
from analekh.ingest.feeds import FeedWatcher
from analekh.ingest.http import PoliteClient
from analekh.ingest.pipeline import process_feed_item
from analekh.ingest.storage import default_store
from analekh.jobs.app import app
from analekh.universe.search import get as get_company

_watcher: FeedWatcher | None = None
NIFTY500 = Path(__file__).resolve().parent.parent / "universe" / "data" / "nifty500.csv"


def watcher() -> FeedWatcher:
    global _watcher
    if _watcher is None:
        _watcher = FeedWatcher()
    return _watcher


@app.task(bind=True, max_retries=5, retry_backoff=True)
def poll_feed(self, feed: str) -> int:
    try:
        with session_scope() as s:
            return watcher().poll(s, feed)
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@app.task
def process_pending(limit: int = 100) -> int:
    """Fetch the files new feed items link to, for every linked company (cheap, no AI)."""
    store, client, done = default_store(), PoliteClient(), 0
    with session_scope() as s:
        items = s.scalars(
            select(FeedItem)
            .where(FeedItem.processed_at.is_(None), FeedItem.company_id.is_not(None))
            .order_by(FeedItem.pub_date)
            .limit(limit)
        ).all()
        for item in items:
            with s.begin_nested():
                process_feed_item(s, store, client, item)
                done += 1
    return done


@app.task
def process_documents(limit: int = 10, company_id: int | None = None) -> int:
    """Document pipeline (AI) for watchlist companies, or one company on demand."""
    from analekh.docs.pipeline import process_document
    from analekh.genai.client import Claude

    store, done = default_store(), 0
    with session_scope() as s:
        claude = Claude(s) if get_settings().anthropic_api_key else None
        q = select(Filing).where(Filing.status == "fetched", Filing.kind != "results_xbrl")
        if company_id is not None:
            q = q.where(Filing.company_id == company_id)
        else:
            q = q.where(exists().where(Watchlist.company_id == Filing.company_id))
        for filing in s.scalars(q.limit(limit)).all():
            with s.begin_nested():
                process_document(s, store, filing, claude, embedder=None)
                done += 1
    return done


@app.task
def refresh_company(symbol: str) -> dict:
    """Newest results filing for a ticker (workflow 6.1 steps 2-4)."""
    with session_scope() as s:
        company = get_company(s, symbol)
        if company is None:
            return {"error": f"unknown symbol {symbol}"}
        pending = s.scalars(
            select(FeedItem).where(
                FeedItem.company_id == company.id,
                FeedItem.feed == "financial_results",
                FeedItem.processed_at.is_(None),
            )
        ).all()
        store, client = default_store(), PoliteClient()
        for item in pending:
            process_feed_item(s, store, client, item)
        latest = s.scalar(
            select(Filing)
            .where(Filing.company_id == company.id, Filing.kind == "results_xbrl")
            .order_by(Filing.period_end.desc().nulls_last())
        )
        return {
            "filing_id": latest.id if latest else None,
            "period_end": str(latest.period_end) if latest else None,
            "fetched": len(pending),
        }


@app.task
def analyse_company(symbol: str) -> dict:
    """On-demand deep coverage (section 4.1): backfill history, then run the document pipeline."""
    result = backfill(symbol)
    with session_scope() as s:
        company = get_company(s, symbol)
        company_id = company.id if company else None
    docs = process_documents(limit=50, company_id=company_id) if company_id else 0
    return {"backfill": result, "documents_processed": docs}


@app.task
def backfill(symbol: str | None = None) -> dict:
    with session_scope() as s:
        summary = run_backfill(s, default_store(), Path(get_settings().import_dir), symbol)
        return summary.__dict__


@app.task
def background_backfill(batch: int = 5) -> dict:
    """Nightly, lowest priority: backfill Nifty 500 constituents that have no history yet.
    PHASE 1: fill universe/data/nifty500.csv (symbol column) from the index constituent file."""
    import csv

    if not NIFTY500.exists():
        return {"skipped": "universe/data/nifty500.csv not present"}
    with NIFTY500.open(newline="") as fh:
        symbols = [r["symbol"].strip().upper() for r in csv.DictReader(fh) if r.get("symbol")]
    done = []
    with session_scope() as s:
        for sym in symbols:
            c = get_company(s, sym)
            if c is None or s.scalar(select(exists().where(Filing.company_id == c.id))):
                continue
            done.append(sym)
            if len(done) >= batch:
                break
    return {"queued": [backfill.delay(sym).id for sym in done], "symbols": done}


@app.task
def refresh_universe() -> dict:
    """Weekly (UNIVERSE_REFRESH_CRON): new listings, symbol changes and delistings."""
    from analekh.universe.loader import refresh_from_nse

    with session_scope() as s:
        summary = refresh_from_nse(s)
        return {k: len(v) for k, v in summary.__dict__.items()}


@app.task
def sync_model(model_id: int, filing_id: int) -> dict:
    """Build a change set for a linked model from new results (section 16)."""
    from analekh.db.models import Model, ModelVersion
    from analekh.facts import DbValueSource
    from analekh.modelsync.changeset import build_change_set, save_proposal
    from analekh.workbook.mapping import Mapping
    from analekh.workbook.reader import load

    store = default_store()
    with session_scope() as s:
        model = s.get(Model, model_id)
        filing = s.get(Filing, filing_id)
        if model is None or filing is None or filing.period_end is None:
            return {"error": "model or filing not found"}
        if model.mapping is None:
            return {"error": "model mapping not confirmed"}
        version = s.scalar(
            select(ModelVersion)
            .where(ModelVersion.model_id == model_id)
            .order_by(ModelVersion.version.desc())
        )
        if version is None:
            return {"error": "model has no saved version"}
        proposal = build_change_set(
            load(store.get(version.storage_key)),
            Mapping.model_validate(model.mapping),
            filing.period_end,
            DbValueSource(s, filing.company_id),
            last_fingerprint=model.fingerprint,
        )
        if filing.meta.get("blocks_auto_apply"):
            proposal.warnings.insert(0, "Validation failures on this filing: review before apply")
        cs = save_proposal(s, model_id, version.version, filing_id, proposal)
        return {"change_set_id": cs.id, **proposal.summary}
