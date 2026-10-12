"""Sector classification (design doc 4.2).

EQUITY_L.csv has no sector column. Start with a curated mapping for the Nifty 500 in
``data/sector_map.csv`` (symbol, sector, industry), let users override per company, and confirm
the results taxonomy (banking vs Ind-AS) from the first parsed filing.

PHASE 1: fill data/sector_map.csv from index constituent files; open question 28.4 decides the
source beyond the Nifty 500.
"""

import csv
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from analekh.db.models import Company

SECTOR_MAP = Path(__file__).parent / "data" / "sector_map.csv"


def load_sector_map(path: Path = SECTOR_MAP) -> dict[str, tuple[str, str | None]]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as fh:
        return {
            row["symbol"].strip().upper(): (
                row["sector"].strip(),
                (row.get("industry") or "").strip() or None,
            )
            for row in csv.DictReader(fh)
            if row.get("symbol") and row.get("sector")
        }


def taxonomy_for_sector(sector: str | None, industry: str | None = None) -> str:
    """Initial guess; the first parsed filing's schema reference confirms it."""
    text = f"{sector or ''} {industry or ''}".lower()
    if "insurance" in text:
        return "insurance"
    if "nbfc" in text or "non banking" in text or "non-banking" in text:
        return "nbfc"
    if "bank" in text:
        return "banking"
    return "indas"


def apply_sectors(
    session: Session, mapping: dict[str, tuple[str, str | None]] | None = None
) -> int:
    """Fill sector/industry where the curated map knows the symbol; never overwrite a user value."""
    mapping = load_sector_map() if mapping is None else mapping
    if not mapping:
        return 0
    n = 0
    for company in session.scalars(select(Company).where(Company.nse_symbol.in_(mapping))):
        sector, industry = mapping[company.nse_symbol]
        if company.sector is None:
            company.sector, company.industry = sector, industry
            n += 1
        if company.results_taxonomy is None:
            company.results_taxonomy = taxonomy_for_sector(company.sector, company.industry)
    return n
