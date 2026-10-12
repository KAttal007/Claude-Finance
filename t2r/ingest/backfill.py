"""Backfill 8-12 quarters from manually downloaded files (design doc 7.3).

Layout: ``IMPORT_DIR/<NSE_SYMBOL>/<anything>.xml|.pdf``. XBRL goes through the same parser and
validation path as live filings; PDFs are stored for the document pipeline. Files are processed
oldest first by name so that V5/V7/V9 have history to compare against: prefix names with the
period end (e.g. ``2025-06-30_results.xml``).
"""

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from t2r.ingest.pipeline import classify_announcement, ingest_results_xbrl, store_document
from t2r.ingest.resolver import resolve
from t2r.ingest.storage import ObjectStore


@dataclass
class BackfillSummary:
    ingested: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    unknown_symbols: list[str] = field(default_factory=list)


def run_backfill(
    session: Session, store: ObjectStore, import_dir: Path, symbol: str | None = None
) -> BackfillSummary:
    summary = BackfillSummary()
    folders = (
        [import_dir / symbol] if symbol else sorted(p for p in import_dir.iterdir() if p.is_dir())
    )
    for folder in folders:
        company = resolve(session, folder.name)
        if company is None:
            summary.unknown_symbols.append(folder.name)
            continue
        for path in sorted(folder.iterdir()):
            suffix = path.suffix.lower()
            if suffix == ".xml":
                result = ingest_results_xbrl(
                    session, store, company, path.read_bytes(), source_url=f"import:{path.name}"
                )
                (summary.skipped if result.skipped else summary.ingested).append(str(path))
            elif suffix == ".pdf":
                store_document(
                    session,
                    store,
                    company,
                    path.read_bytes(),
                    kind=classify_announcement(path.stem.replace("_", " ")),
                    source_url=f"import:{path.name}",
                )
                summary.ingested.append(str(path))
    return summary
