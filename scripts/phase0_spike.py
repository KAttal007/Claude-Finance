"""Phase 0 spike (design doc 20): prove the data path on a machine that can reach NSE.

Reads the Financial_Results RSS feed once, downloads the XBRL files it links to for the given
symbols (or the first N items), parses and validates them, and writes a JSON + console summary.
No database needed. Polite by construction: only nsearchives hosts, 1 request/second, a
descriptive User-Agent (set USER_AGENT in .env).

    uv run python scripts/phase0_spike.py --limit 10
    uv run python scripts/phase0_spike.py --symbols MUTHOOTFIN HDFCBANK BAJFINANCE

Output: out/phase0/<timestamp>/ with raw files (gitignored), summary.json and elements.csv
(every element name seen per taxonomy, to fill t2r/xbrl/elements.py for banks and NBFCs).
"""

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from t2r.ingest.feeds import FEEDS, RSS_BASE, parse_rss  # noqa: E402
from t2r.ingest.http import PoliteClient  # noqa: E402
from t2r.validate.rules import ValidationContext, validate  # noqa: E402
from t2r.xbrl.parser import parse_instance  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=[], help="match against item titles")
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()

    out = Path("out/phase0") / datetime.now().strftime("%Y%m%d-%H%M%S")
    (out / "raw").mkdir(parents=True)
    client = PoliteClient()

    feed = client.get(RSS_BASE + FEEDS["financial_results"][0])
    (out / "Financial_Results.xml").write_bytes(feed.content)
    items = parse_rss(feed.content)
    print(f"feed: {len(items)} items")

    wanted = [s.upper() for s in args.symbols]
    if wanted:
        items = [i for i in items if any(s in (i.title or "").upper() for s in wanted)]
    items = items[: args.limit]

    summary, elements = [], defaultdict(Counter)
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

    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    with (out / "elements.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["taxonomy", "element", "files_seen"])
        for tax, counter in elements.items():
            for el, n in counter.most_common():
                w.writerow([tax, el, n])
    print(f"\nwrote {out}/summary.json and elements.csv")
    print(
        "Next: compare 10 values per file against the published results PDF by hand,"
        " then update t2r/xbrl/elements.py (# verify markers) and tests/fixtures/real/."
    )


if __name__ == "__main__":
    main()
