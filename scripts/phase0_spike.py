"""Phase 0 spike (design doc 26): prove the data path on a machine that can reach NSE.

1. Loads the universe: downloads the published equity list (and SME list) and parses it.
2. Polls two feeds: Financial_Results and Online_announcements (subject census, to answer open
   question 28.5 on transcript subject lines).
3. Downloads the XBRL files the results feed links to for the given symbols (or the first N
   items), parses and validates them.
4. Optionally pulls one price series via Kite (--price SYMBOL; needs KITE_* in .env).

Writes a JSON + console summary. No database needed. Polite by construction: only nsearchives
hosts, 1 request/second, a descriptive User-Agent (set USER_AGENT in .env).

    uv run python scripts/phase0_spike.py --limit 10
    uv run python scripts/phase0_spike.py --symbols MUTHOOTFIN HDFCBANK BAJFINANCE

Output: out/phase0/<timestamp>/ with raw files (gitignored), summary.json and elements.csv
(every element name seen per taxonomy, to fill analekh/xbrl/elements.py for banks and NBFCs).
"""

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analekh.ingest.feeds import FEEDS, RSS_BASE, parse_rss  # noqa: E402
from analekh.ingest.http import PoliteClient  # noqa: E402
from analekh.universe.loader import EQUITY_LIST_URL, SME_LIST_URL, parse_equity_list  # noqa: E402
from analekh.validate.rules import ValidationContext, validate  # noqa: E402
from analekh.xbrl.parser import parse_instance  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=[], help="match against item titles")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--price", help="NSE symbol for one Kite price pull (optional)")
    args = ap.parse_args()

    out = Path("out/phase0") / datetime.now().strftime("%Y%m%d-%H%M%S")
    (out / "raw").mkdir(parents=True)
    client = PoliteClient()
    spike: dict[str, object] = {}

    # 1. Universe (design doc 4.1)
    universe: dict[str, object] = {}
    for label, url, is_sme in (("main", EQUITY_LIST_URL, False), ("sme", SME_LIST_URL, True)):
        try:
            data = client.get(url).content
        except Exception as exc:  # noqa: BLE001 - SME path is unconfirmed
            universe[label] = {"url": url, "error": str(exc)}
            continue
        (out / "raw" / Path(url).name).write_bytes(data)
        listed = parse_equity_list(data, is_sme=is_sme)
        universe[label] = {
            "url": url,
            "rows": len(listed),
            "with_isin": sum(1 for c in listed if c.isin),
            "series": Counter(c.series for c in listed).most_common(10),
        }
        print(f"universe {label}: {len(listed)} companies")
    spike["universe"] = universe

    # 2. Second feed: subject census of announcements
    ann = parse_rss(client.get(RSS_BASE + FEEDS["announcements"][0]).content)
    subjects = Counter((i.title or "").split(" - ")[-1].strip()[:80] for i in ann)
    spike["announcements"] = {"items": len(ann), "top_subjects": subjects.most_common(30)}
    print(f"announcements: {len(ann)} items")

    # 3. Results XBRL
    feed = client.get(RSS_BASE + FEEDS["financial_results"][0])
    (out / "Financial_Results.xml").write_bytes(feed.content)
    items = parse_rss(feed.content)
    print(f"feed: {len(items)} items")

    wanted = [s.upper() for s in args.symbols]
    if wanted:
        items = [i for i in items if any(s in (i.title or "").upper() for s in wanted)]
    items = items[: args.limit]

    summary: list[dict[str, object]] = []
    elements: dict[str, Counter[str]] = defaultdict(Counter)
    for item in items:
        if not item.link:
            continue
        try:
            data = client.get(item.link).content
        except Exception as exc:  # noqa: BLE001
            summary.append({"title": item.title, "link": item.link, "error": str(exc)})
            continue
        (out / "raw" / Path(item.link).name).write_bytes(data)
        try:
            parsed = parse_instance(data)
        except Exception as exc:  # noqa: BLE001
            summary.append({"title": item.title, "link": item.link, "parse_error": str(exc)})
            continue
        taxonomy = parsed.taxonomy()
        for f in parsed.facts:
            elements[taxonomy][f.element] += 1
        report = validate(ValidationContext(parsed, taxonomy))
        summary.append(
            {
                "title": item.title,
                "link": item.link,
                "schema_ref": parsed.schema_ref,
                "taxonomy_guess": taxonomy,
                "meta": parsed.meta,
                "facts": len(parsed.facts),
                "warnings": parsed.warnings,
                "validation": report.as_dict(),
            }
        )
        fails = [r.rule for r in report.failures]
        skips = [r.rule for r in report.results if r.status == "skip"]
        print(
            f"- {item.title}: {len(parsed.facts)} facts, {taxonomy}, "
            f"fail={fails or '-'} skip={skips or '-'}"
        )

    spike["results"] = summary

    # 4. One price pull
    if args.price:
        spike["price"] = _price(args.price)

    (out / "summary.json").write_text(json.dumps(spike, indent=2, default=str))
    with (out / "elements.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["taxonomy", "element", "files_seen"])
        for tax, counter in elements.items():
            for el, n in counter.most_common():
                w.writerow([tax, el, n])
    print(f"\nwrote {out}/summary.json and elements.csv")
    print(
        "Next: compare 10 values per file against the published results PDF by hand,"
        " then update analekh/xbrl/elements.py (# verify markers) and tests/fixtures/real/."
    )


def _price(symbol: str) -> dict[str, object]:
    """Last 10 daily candles for one symbol via Kite Connect (design doc 3.2)."""
    from datetime import timedelta

    try:
        from analekh.market.kite import _client

        kite = _client()
        token = next(
            i["instrument_token"] for i in kite.instruments("NSE") if i["tradingsymbol"] == symbol
        )
        end = datetime.now().date()
        candles = kite.historical_data(token, end - timedelta(days=15), end, "day")
    except Exception as exc:  # noqa: BLE001 - optional step
        print(f"price {symbol}: {exc}")
        return {"symbol": symbol, "error": str(exc)}
    print(f"price {symbol}: {len(candles)} candles")
    return {"symbol": symbol, "candles": candles}


if __name__ == "__main__":
    main()
