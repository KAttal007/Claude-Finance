"""NSE RSS feed watcher for the whole universe (design doc 9.2).

Items carry no reliable GUID, so item_key = SHA-256(link + pubDate). Every item is kept forever;
upsert on (feed, item_key) makes polling idempotent.
"""

import hashlib
from calendar import timegm
from dataclasses import dataclass
from datetime import UTC, datetime

import feedparser
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from analekh.db.models import Company, FeedItem
from analekh.ingest.http import PoliteClient
from analekh.ingest.linking import CompanyIndex

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
    parsed = feedparser.parse(data)
    items = []
    for e in parsed.entries:
        raw_date = e.get("published")
        struct = e.get("published_parsed")
        # PHASE 0: confirm NSE's pubDate format; feedparser handles RFC 822 and most variants.
        when = datetime.fromtimestamp(timegm(struct), UTC) if struct else None
        items.append(
            RssItem(
                title=(e.get("title") or "").strip() or None,
                link=(e.get("link") or "").strip() or None,
                description=(e.get("description") or e.get("summary") or "").strip() or None,
                pub_date_raw=raw_date,
                pub_date=when,
            )
        )
    return items


def store_items(
    session: Session, feed: str, items: list[RssItem], index: CompanyIndex | None = None
) -> int:
    """Insert new items and link them to universe companies; returns how many were new."""
    if not items:
        return 0
    index = index or CompanyIndex.build(session.scalars(select(Company).where(Company.is_active)))
    rows = []
    for it in items:
        company = index.match(it.title or "", it.description or "")
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
    """Remembers ETag/Last-Modified per feed between polls (in-process)."""

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
