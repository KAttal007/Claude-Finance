"""Price fetcher via Zerodha Kite Connect (design doc 3.2, 4.1). Optional: ``pip install .[kite]``.

Kite needs a daily access token from its login flow; store it in KITE_ACCESS_TOKEN.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from analekh.config import get_settings
from analekh.db.models import Company, Price


def _client():  # pragma: no cover - needs a live Kite session
    from kiteconnect import KiteConnect

    s = get_settings()
    kite = KiteConnect(api_key=s.kite_api_key)
    kite.set_access_token(s.kite_access_token)
    return kite


def fetch_daily(
    session: Session,
    company: Company,
    start: date,
    end: date,
    shares_outstanding: Decimal | None = None,
) -> int:  # pragma: no cover
    """Upsert daily OHLC for one company. market_cap = close x shares when shares are known."""
    kite = _client()
    instruments = {i["tradingsymbol"]: i["instrument_token"] for i in kite.instruments("NSE")}
    token = instruments.get(company.nse_symbol)
    if token is None:
        raise LookupError(f"{company.nse_symbol} not found in Kite NSE instruments")
    candles = kite.historical_data(token, start, end, "day")
    rows = []
    for c in candles:
        close = Decimal(str(c["close"]))
        rows.append(
            {
                "company_id": company.id,
                "trade_date": c["date"].date(),
                "open": Decimal(str(c["open"])),
                "high": Decimal(str(c["high"])),
                "low": Decimal(str(c["low"])),
                "close": close,
                "volume": c["volume"],
                "market_cap": close * shares_outstanding if shares_outstanding else None,
            }
        )
    if not rows:
        return 0
    stmt = insert(Price).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["company_id", "trade_date"],
        set_={
            k: stmt.excluded[k] for k in ("open", "high", "low", "close", "volume", "market_cap")
        },
    )
    session.execute(stmt)
    return len(rows)
