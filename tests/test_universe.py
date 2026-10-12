from datetime import date
from decimal import Decimal

from sqlalchemy import select

from analekh import coverage
from analekh.db.models import Company
from analekh.universe.loader import parse_equity_list, upsert_universe
from analekh.universe.search import search
from analekh.universe.sectors import apply_sectors

# Column layout of NSE's EQUITY_L.csv (design doc 3.1). Companies are SYNTHETIC.
EQUITY_L = (
    b"SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER,"
    b" FACE VALUE\n"
    b"""DEMOFIN,Demo Finance Limited,EQ,05-Jan-2012,10,1,INE000D01011,10
ACMEIND,Acme Industries Limited,EQ,17-Mar-2005,2,1,INE000A01022,2
OLDCO,Old Company Limited,BE,01-Jan-2000,10,1,INE000O01033,10
"""
)
SME_L = (
    b"SYMBOL,NAME_OF_COMPANY,SERIES,DATE_OF_LISTING,PAID_UP_VALUE,MARKET_LOT,ISIN_NUMBER,"
    b"FACE_VALUE\n"
    b"""TINYSME,Tiny SME Limited,SM,12-Aug-2024,10,1200,INE000T01044,10
"""
)


def test_parse_equity_list_handles_both_header_styles():
    rows = parse_equity_list(EQUITY_L) + parse_equity_list(SME_L, is_sme=True)
    demo = rows[0]
    assert demo.symbol == "DEMOFIN" and demo.series == "EQ" and demo.isin == "INE000D01011"
    assert demo.listing_date == date(2012, 1, 5) and demo.face_value == Decimal("10")
    sme = rows[-1]
    assert sme.symbol == "TINYSME" and sme.is_sme and sme.listing_date == date(2024, 8, 12)


def test_upsert_by_isin_renames_and_deactivates(db):
    first = upsert_universe(db, parse_equity_list(EQUITY_L))
    assert sorted(first.inserted) == ["ACMEIND", "DEMOFIN", "OLDCO"]

    # Next week: DEMOFIN renamed to DEMOFINANCE (same ISIN), OLDCO delisted.
    week2 = EQUITY_L.replace(b"DEMOFIN,", b"DEMOFINANCE,").replace(
        b"OLDCO,Old Company Limited,BE,01-Jan-2000,10,1,INE000O01033,10\n", b""
    )
    second = upsert_universe(db, parse_equity_list(week2))
    assert second.renamed == [("DEMOFIN", "DEMOFINANCE")]
    assert second.deactivated == ["OLDCO"]
    old = db.scalar(select(Company).where(Company.nse_symbol == "OLDCO"))
    assert old is not None and not old.is_active
    assert (
        db.scalar(select(Company).where(Company.isin == "INE000D01011")).nse_symbol == "DEMOFINANCE"
    )


def test_search_symbol_prefix_and_fuzzy_name(db):
    upsert_universe(db, parse_equity_list(EQUITY_L))
    assert search(db, "demofin")[0].nse_symbol == "DEMOFIN"
    assert search(db, "acme industr")[0].nse_symbol == "ACMEIND"
    assert search(db, "INE000A01022")[0].nse_symbol == "ACMEIND"
    assert search(db, "") == []


def test_sector_map_and_taxonomy(db):
    upsert_universe(db, parse_equity_list(EQUITY_L))
    apply_sectors(db, {"DEMOFIN": ("Financial Services", "NBFC")})
    demo = db.scalar(select(Company).where(Company.nse_symbol == "DEMOFIN"))
    assert demo.sector == "Financial Services" and demo.results_taxonomy == "nbfc"


def test_watchlist_controls_coverage_level(db):
    upsert_universe(db, parse_equity_list(EQUITY_L))
    demo = db.scalar(select(Company).where(Company.nse_symbol == "DEMOFIN"))
    assert coverage.level(db, demo) == "universe"
    coverage.add(db, demo, settings={"alerts": True})
    coverage.add(db, demo, settings={"alerts": False})  # idempotent upsert
    assert coverage.level(db, demo) == "deep"
    assert [w.settings for w in coverage.entries(db)] == [{"alerts": False}]
    coverage.remove(db, demo)
    assert not coverage.is_watched(db, demo.id)
