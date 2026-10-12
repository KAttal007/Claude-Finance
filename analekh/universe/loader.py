"""Universe loader (design doc 4, 9.1): every NSE-listed company, refreshed weekly.

Source: NSE's EQUITY_L.csv (SYMBOL, NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE,
MARKET LOT, ISIN NUMBER, FACE VALUE) and the separate SME list. Rows are upserted by ISIN, so a
symbol change keeps the company's history. Companies missing from a full refresh are marked
inactive, never deleted.
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

import structlog
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from analekh.db.models import Company
from analekh.ingest.http import PoliteClient
from analekh.universe.sectors import apply_sectors

log = structlog.get_logger()

EQUITY_LIST_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
# PHASE 0: confirm the SME list's published path and columns on nsearchives.
SME_LIST_URL = "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv"


@dataclass(frozen=True)
class ListedCompany:
    symbol: str
    name: str
    isin: str | None
    series: str | None
    listing_date: date | None
    face_value: Decimal | None
    is_sme: bool


@dataclass
class LoadSummary:
    inserted: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)  # (old symbol, new symbol)
    deactivated: list[str] = field(default_factory=list)
    reactivated: list[str] = field(default_factory=list)


def _norm_header(h: str) -> str:
    return " ".join(h.replace("_", " ").strip().upper().split())


def _date(value: str) -> date | None:
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value.strip()) if value.strip() else None
    except InvalidOperation:
        return None


def parse_equity_list(data: bytes, is_sme: bool = False) -> list[ListedCompany]:
    text = data.decode("utf-8-sig", errors="replace")
    rows = []
    for raw in csv.DictReader(io.StringIO(text)):
        row = {_norm_header(k): (v or "").strip() for k, v in raw.items() if k}
        symbol = row.get("SYMBOL", "").upper()
        if not symbol:
            continue
        rows.append(
            ListedCompany(
                symbol=symbol,
                name=row.get("NAME OF COMPANY") or symbol,
                isin=(row.get("ISIN NUMBER") or None),
                series=row.get("SERIES") or None,
                listing_date=_date(row.get("DATE OF LISTING", "")),
                face_value=_decimal(row.get("FACE VALUE", "")),
                is_sme=is_sme,
            )
        )
    return rows


def upsert_universe(
    session: Session, listed: list[ListedCompany], full_refresh: bool = True
) -> LoadSummary:
    """Upsert by ISIN (falling back to symbol); deactivate companies absent from a full refresh."""
    summary = LoadSummary()
    now = datetime.now(UTC)
    by_isin = {c.isin: c for c in session.scalars(select(Company).where(Company.isin.is_not(None)))}
    by_symbol = {c.nse_symbol: c for c in session.scalars(select(Company))}
    seen: set[int] = set()

    for item in listed:
        company = (by_isin.get(item.isin) if item.isin else None) or by_symbol.get(item.symbol)
        if company is None:
            company = Company(
                nse_symbol=item.symbol,
                name=item.name,
                isin=item.isin,
                source="nse_sme_list" if item.is_sme else "nse_equity_list",
            )
            session.add(company)
            summary.inserted.append(item.symbol)
        else:
            if company.nse_symbol != item.symbol:
                summary.renamed.append((company.nse_symbol, item.symbol))
                company.nse_symbol = item.symbol
            else:
                summary.updated.append(item.symbol)
            if not company.is_active:
                summary.reactivated.append(item.symbol)
        company.name = item.name
        company.isin = item.isin or company.isin
        company.series = item.series
        company.listing_date = item.listing_date
        company.face_value = item.face_value
        company.is_sme = item.is_sme
        company.is_active = True
        company.refreshed_at = now
        session.flush()
        seen.add(company.id)

    if full_refresh and seen:
        gone = session.scalars(select(Company).where(Company.is_active, Company.id.not_in(seen)))
        summary.deactivated = [c.nse_symbol for c in gone]
        session.execute(update(Company).where(Company.id.not_in(seen)).values(is_active=False))
    apply_sectors(session)
    return summary


def refresh_from_nse(session: Session, client: PoliteClient | None = None) -> LoadSummary:
    """Weekly job: download both lists and upsert. Only the published CSVs, never the website."""
    client = client or PoliteClient()
    listed = parse_equity_list(client.get(EQUITY_LIST_URL).content)
    try:
        listed += parse_equity_list(client.get(SME_LIST_URL).content, is_sme=True)
    except Exception as exc:  # noqa: BLE001 - SME list path unconfirmed (PHASE 0)
        log.warning("sme_list_unavailable", url=SME_LIST_URL, error=str(exc))
    return upsert_universe(session, listed)
