"""Ticker resolver and company master (design doc 7.4).

The master comes from NSE's equity list CSV (symbol, name, ISIN), downloaded by hand and refreshed
monthly. Run: ``python -m t2r.ingest.resolver path/to/EQUITY_L.csv``.
"""

import csv
import re
import sys
from collections.abc import Iterable
from pathlib import Path

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from t2r.db.models import Company

FUZZY_THRESHOLD = 92

_SUFFIXES = re.compile(r"\b(limited|ltd|private|pvt|the|india|co|company|corporation|corp)\b\.?")


def normalise_name(name: str) -> str:
    name = name.lower().replace("&", " and ")
    name = _SUFFIXES.sub(" ", name)
    return re.sub(r"[^a-z0-9]+", " ", name).strip()


def taxonomy_for_sector(sector: str | None, industry: str | None = None) -> str:
    """Initial guess; confirmed from the first parsed filing's schema reference."""
    text = f"{sector or ''} {industry or ''}".lower()
    if "bank" in text and "non" not in text:
        return "banking"
    if "nbfc" in text or "non banking" in text or "finance" in text:
        return "nbfc"
    if "insurance" in text:
        return "insurance"
    return "indas"


def match_company(title: str, companies: Iterable[Company]) -> Company | None:
    """Match an RSS item title to the master: exact symbol, normalised name, then fuzzy."""
    companies = list(companies)
    if not title or not companies:
        return None
    upper = title.upper()
    for c in companies:
        if re.search(rf"\b{re.escape(c.nse_symbol)}\b", upper):
            return c
    norm = normalise_name(title)
    by_norm = {normalise_name(c.name): c for c in companies}
    if norm in by_norm:
        return by_norm[norm]
    best = process.extractOne(norm, list(by_norm), scorer=fuzz.token_set_ratio)
    if best and best[1] >= FUZZY_THRESHOLD:
        return by_norm[best[0]]
    return None


def resolve(session: Session, symbol: str) -> Company | None:
    return session.scalar(select(Company).where(Company.nse_symbol == symbol.upper()))


def load_master(session: Session, csv_path: Path) -> int:
    """Upsert companies from NSE's EQUITY_L.csv (column names to verify in Phase 0)."""
    rows = []
    with csv_path.open(newline="", encoding="utf-8-sig") as fh:
        for raw in csv.DictReader(fh):
            row = {k.strip().upper(): (v or "").strip() for k, v in raw.items() if k}
            symbol = row.get("SYMBOL")
            if not symbol:
                continue
            rows.append(
                {
                    "nse_symbol": symbol,
                    "name": row.get("NAME OF COMPANY") or symbol,
                    "isin": row.get("ISIN NUMBER") or None,
                }
            )
    if not rows:
        return 0
    stmt = insert(Company).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["nse_symbol"],
        set_={"name": stmt.excluded.name, "isin": stmt.excluded.isin},
    )
    session.execute(stmt)
    return len(rows)


if __name__ == "__main__":
    from t2r.db.session import session_scope

    with session_scope() as s:
        print(f"loaded {load_master(s, Path(sys.argv[1]))} companies")
