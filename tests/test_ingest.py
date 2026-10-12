from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from analekh.db.models import Company, Fact, FeedItem, Filing
from analekh.ingest.backfill import run_backfill
from analekh.ingest.feeds import item_key, parse_rss, store_items
from analekh.ingest.http import DisallowedHostError, PoliteClient
from analekh.ingest.linking import CompanyIndex, normalise_name
from analekh.ingest.pipeline import classify_announcement, ingest_results_xbrl
from analekh.universe.sectors import taxonomy_for_sector
from tests.xbrl_factory import q1_instance, q2_instance

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<title>Financial Results</title><ttl>5</ttl>
<item><title>Demo Finance Limited</title>
<link>https://nsearchives.nseindia.com/corporate/xbrl/INDAS_1.xml</link>
<description>Financial results for the quarter ended 30-Sep-2026</description>
<pubDate>Tue, 10 Nov 2026 18:05:00 +0530</pubDate></item>
<item><title>Unknown Co Ltd</title><link>https://nsearchives.nseindia.com/x.xml</link>
<pubDate>Tue, 10 Nov 2026 18:06:00 +0530</pubDate></item>
</channel></rss>"""


def test_parse_rss_and_item_key():
    items = parse_rss(RSS)
    assert len(items) == 2
    assert items[0].pub_date is not None and items[0].pub_date.year == 2026
    assert items[0].item_key == item_key(items[0].link, items[0].pub_date_raw)
    assert items[0].item_key != items[1].item_key


def test_name_matching():
    c = Company(id=1, nse_symbol="DEMOFIN", name="Demo Finance Limited", isin="INE000D01011")
    other = Company(id=2, nse_symbol="ACME", name="Acme Industries Ltd")
    index = CompanyIndex.build([c, other])
    assert normalise_name("Demo Finance Ltd.") == normalise_name("DEMO FINANCE LIMITED")
    assert index.match("Demo Finance Limited") is c
    assert index.match("ACME - results") is other
    assert index.match("Results", "ISIN INE000D01011 quarter ended") is c
    assert index.match("Totally Different Corp") is None


def test_taxonomy_guess():
    assert taxonomy_for_sector("Banks") == "banking"
    assert taxonomy_for_sector("Financial Services", "NBFC") == "nbfc"
    assert taxonomy_for_sector("Insurance") == "insurance"
    assert taxonomy_for_sector("Capital Goods") == "indas"


def test_announcement_classifier():
    assert classify_announcement("Transcript of Earnings Call") == "transcript"
    assert classify_announcement("Investor Presentation Q2FY27") == "presentation"
    assert classify_announcement("Change in Directors") == "other"


def test_client_refuses_other_hosts():
    with pytest.raises(DisallowedHostError):
        PoliteClient().get("https://www.nseindia.com/api/anything")


def test_client_retries_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        assert request.headers["User-Agent"].startswith("Analekh")
        return httpx.Response(200, content=b"ok", headers={"ETag": "abc"})

    client = PoliteClient(transport=httpx.MockTransport(handler), backoff_base=0)
    result = client.get("https://nsearchives.nseindia.com/content/RSS/Financial_Results.xml")
    assert result.content == b"ok" and result.etag == "abc" and calls["n"] == 3


# --- database integration (needs PostgreSQL) ---------------------------------------------------


@pytest.fixture
def company(db):
    c = Company(nse_symbol="DEMOFIN", name="Demo Finance Limited")
    db.add(c)
    db.flush()
    return c


def test_store_items_is_idempotent_and_links_companies(db, company):
    items = parse_rss(RSS)
    assert store_items(db, "financial_results", items) == 2
    assert store_items(db, "financial_results", items) == 0
    linked = db.scalar(select(FeedItem).where(FeedItem.title == "Demo Finance Limited"))
    assert linked is not None and linked.company_id == company.id


def test_ingest_dedupes_and_handles_restatement(db, store, company):
    first = ingest_results_xbrl(db, store, company, q1_instance())
    assert not first.skipped and first.report is not None
    assert first.filing.period_type == "Q" and first.filing.consolidated is True
    assert company.results_taxonomy == "indas"

    assert ingest_results_xbrl(db, store, company, q1_instance()).skipped

    q2 = ingest_results_xbrl(db, store, company, q2_instance())
    assert q2.report is not None and not q2.report.blocks_auto_apply
    v5 = next(r for r in q2.report.results if r.rule == "V5")
    assert v5.status == "pass"  # used Q1 from history

    restated = ingest_results_xbrl(db, store, company, q2_instance(revenue=1_010_000_000))
    v9 = next(r for r in restated.report.results if r.rule == "V9")
    assert v9.status == "fail"

    rows = db.scalars(
        select(Fact).where(
            Fact.company_id == company.id,
            Fact.element == "RevenueFromOperations",
            Fact.period_start == date(2026, 7, 1),
        )
    ).all()
    assert len(rows) == 2
    latest = [r for r in rows if r.is_latest]
    assert len(latest) == 1 and latest[0].value == Decimal("1010000000")
    assert store.exists(restated.filing.storage_key)


def test_backfill_from_import_folder(db, store, company, tmp_path):
    folder = tmp_path / "import" / "DEMOFIN"
    folder.mkdir(parents=True)
    (folder / "2026-06-30_results.xml").write_bytes(q1_instance())
    (folder / "2026-09-30_results.xml").write_bytes(q2_instance())
    (tmp_path / "import" / "NOSUCH").mkdir()
    summary = run_backfill(db, store, tmp_path / "import")
    assert len(summary.ingested) == 2 and summary.unknown_symbols == ["NOSUCH"]
    assert len(db.scalars(select(Filing).where(Filing.company_id == company.id)).all()) == 2
