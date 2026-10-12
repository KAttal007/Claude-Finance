"""Idempotent background jobs. Re-running any task never duplicates rows (design doc 2.2)."""

from pathlib import Path

from sqlalchemy import select

from t2r.config import get_settings
from t2r.db.models import Company, FeedItem, Filing
from t2r.db.session import session_scope
from t2r.ingest.backfill import run_backfill
from t2r.ingest.feeds import FeedWatcher
from t2r.ingest.http import PoliteClient
from t2r.ingest.pipeline import process_feed_item
from t2r.ingest.storage import default_store
from t2r.jobs.app import app

_watcher: FeedWatcher | None = None


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
def process_pending(limit: int = 50) -> int:
    """Fetch files for new feed items of tracked companies."""
    store, client, done = default_store(), PoliteClient(), 0
    with session_scope() as s:
        items = s.scalars(
            select(FeedItem)
            .join(Company, FeedItem.company_id == Company.id)
            .where(FeedItem.processed_at.is_(None), Company.is_tracked)
            .order_by(FeedItem.pub_date)
            .limit(limit)
        ).all()
        for item in items:
            with s.begin_nested():
                process_feed_item(s, store, client, item)
                done += 1
    return done


@app.task
def process_documents(limit: int = 10) -> int:
    from t2r.docs.pipeline import process_document
    from t2r.genai.client import Claude

    store, done = default_store(), 0
    with session_scope() as s:
        claude = Claude(s) if get_settings().anthropic_api_key else None
        filings = s.scalars(
            select(Filing)
            .where(Filing.status == "fetched", Filing.kind != "results_xbrl")
            .limit(limit)
        ).all()
        for filing in filings:
            with s.begin_nested():
                process_document(s, store, filing, claude, embedder=None)
                done += 1
    return done


@app.task
def refresh_company(symbol: str) -> dict:
    """Newest results filing for a ticker (design doc 5, steps 2-4)."""
    with session_scope() as s:
        company = s.scalar(select(Company).where(Company.nse_symbol == symbol.upper()))
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
            .order_by(Filing.period_end.desc())
        )
        return {
            "filing_id": latest.id if latest else None,
            "period_end": str(latest.period_end) if latest else None,
            "fetched": len(pending),
        }


@app.task
def backfill(symbol: str | None = None) -> dict:
    with session_scope() as s:
        summary = run_backfill(s, default_store(), Path(get_settings().import_dir), symbol)
        return summary.__dict__


@app.task
def sync_model(model_id: int, filing_id: int) -> dict:
    """Build a change set for a registered model (design doc 10)."""
    import io

    from openpyxl import load_workbook

    from t2r.db.models import Model, ModelVersion
    from t2r.modelsync.changeset import DbValueSource, build_change_set, save_proposal
    from t2r.modelsync.mapping import load_mapping

    store = default_store()
    with session_scope() as s:
        model = s.get(Model, model_id)
        filing = s.get(Filing, filing_id)
        if model is None or filing is None or filing.period_end is None:
            return {"error": "model or filing not found"}
        version = s.scalar(
            select(ModelVersion)
            .where(ModelVersion.model_id == model_id)
            .order_by(ModelVersion.version.desc())
        )
        if version is None:
            return {"error": "model has no saved version"}
        wb = load_workbook(io.BytesIO(store.get(version.storage_key)))
        proposal = build_change_set(
            wb,
            load_mapping(model.mapping_yaml),
            filing.period_end,
            DbValueSource(s, filing.company_id),
        )
        if filing.meta.get("blocks_auto_apply"):
            proposal.warnings.insert(0, "Validation failures on this filing: review before apply")
        cs = save_proposal(s, model_id, version.version, filing_id, proposal)
        return {"change_set_id": cs.id, **proposal.summary}
