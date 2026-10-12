"""NSE RSS feed watcher (design doc 7.1).

Items carry no reliable GUID, so item_key = SHA-256(link + pubDate). Every item is kept forever;
upsert on (feed, item_key) makes polling idempotent.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime

from lxml import etree
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from t2r.db.models import Company, FeedItem
from t2r.ingest.http import PoliteClient
from t2r.ingest.resolver import match_company

RSS_BASE = "https://nsearchives.nseindia.com/content/RSS/"

# feed name -> (file, poll class). "fast" polls at the published 5-minute TTL.
FEEDS: dict[str, tuple[str, str]] = {
    "financial_results": ("Financial_Results.xml", "fast"),
    "announcements": ("Online_announcements.xml", "fast"),
    "board_meetings": ("Board_Meetings.xml", "slow"),
    "corporate_action": ("Corporate_action.xml", "slow"),
    "insider_trading": ("Insider_Trading.xml", "slow"),
    "related_party": ("Related_Party_Trans.xml", "slow"),
    "encumbrance": ("Sast_ReasonForEncumbrance.xml", "slow"),
}


@dataclass(frozen=True)
class RssItem:
    title: str | None
    link: str | None
    description: str | None
    pub_date_raw: str | None
    pub_date: datetime | None

    @property
    def item_key(self) -> str:
        return item_key(self.link, self.pub_date_raw)


def item_key(link: str | None, pub_date_raw: str | None) -> str:
    return hashlib.sha256(f"{link or ''}|{pub_date_raw or ''}".encode()).hexdigest()


def parse_rss(data: bytes) -> list[RssItem]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=True)
    root = etree.fromstring(data, parser)
    items = []
    for el in root.iter("item"):
        raw_date = _text(el, "pubDate")
        items.append(
            RssItem(
                title=_text(el, "title"),
                link=_text(el, "link"),
                description=_text(el, "description"),
                pub_date_raw=raw_date,
                pub_date=_parse_date(raw_date),
            )
        )
    return items


def store_items(session: Session, feed: str, items: list[RssItem]) -> int:
    """Insert new items, link them to companies; returns how many were new."""
    if not items:
        return 0
    companies = list(session.scalars(select(Company)))
    rows = []
    for it in items:
        company = match_company(it.title or "", companies)
        rows.append(
            {
                "feed": feed,
                "item_key": it.item_key,
                "title": it.title,
                "link": it.link,
                "description": it.description,
                "pub_date": it.pub_date,
                "company_id": company.id if company else None,
            }
        )
    stmt = (
        insert(FeedItem)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["feed", "item_key"])
        .returning(FeedItem.id)
    )
    return len(session.execute(stmt).all())


class FeedWatcher:
    """Remembers ETag/Last-Modified per feed between polls (in-process; Redis-backed in jobs)."""

    def __init__(self, client: PoliteClient | None = None) -> None:
        self.client = client or PoliteClient()
        self.validators: dict[str, tuple[str | None, str | None]] = {}

    def poll(self, session: Session, feed: str) -> int:
        filename, _ = FEEDS[feed]
        etag, last_mod = self.validators.get(feed, (None, None))
        result = self.client.get(RSS_BASE + filename, etag=etag, last_modified=last_mod)
        if result.not_modified:
            return 0
        self.validators[feed] = (result.etag, result.last_modified)
        return store_items(session, feed, parse_rss(result.content))


def _text(el: etree._Element, tag: str) -> str | None:
    value = el.findtext(tag)
    return value.strip() if value else None


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        pass
    # PHASE 0: NSE feeds may use a non-RFC 822 format; add it here once seen.
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None
