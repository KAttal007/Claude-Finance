"""Golden-set accuracy (design doc 24): hand-checked values from real filings, compared exactly.

Layout: ``tests/fixtures/golden/manifest.yaml`` lists filings and the values an analyst checked
against the published results PDF::

    filings:
      - file: muthootfin_q2fy27.xml          # XBRL instance, next to the manifest
        taxonomy: nbfc
        expect:
          - element: RevenueFromOperations
            period_end: 2026-09-30
            period_start: 2026-07-01         # omit for balance-sheet instants
            value: "12345670000"

Raw exchange files are not committed if licensing is unclear (section 23): keep the folder
local, or in a private CI artifact. Target: 100% exact match on mapped elements.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from analekh.xbrl.parser import parse_instance

DEFAULT_DIR = Path("tests/fixtures/golden")


@dataclass
class Mismatch:
    file: str
    element: str
    period_end: str
    expected: str
    actual: str | None


@dataclass
class GoldenReport:
    fixtures: int = 0
    checked: int = 0
    matched: int = 0
    mismatches: list[Mismatch] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def accuracy(self) -> float | None:
        return self.matched / self.checked if self.checked else None

    @property
    def passed(self) -> bool:
        return self.checked > 0 and self.matched == self.checked and not self.missing_files

    def as_dict(self) -> dict[str, Any]:
        return asdict(self) | {"accuracy": self.accuracy, "passed": self.passed}


def run(folder: Path = DEFAULT_DIR) -> GoldenReport:
    manifest = folder / "manifest.yaml"
    report = GoldenReport()
    if not manifest.exists():
        report.note = f"no golden set at {manifest}; add hand-checked filings (Phase 0/1)"
        return report
    spec = yaml.safe_load(manifest.read_text()) or {}
    for entry in spec.get("filings", []):
        path = folder / entry["file"]
        if not path.exists():
            report.missing_files.append(entry["file"])
            continue
        report.fixtures += 1
        filing = parse_instance(path.read_bytes())
        for exp in entry.get("expect", []):
            report.checked += 1
            end = date.fromisoformat(str(exp["period_end"]))
            start = (
                date.fromisoformat(str(exp["period_start"])) if exp.get("period_start") else None
            )
            fact = filing.get(exp["element"], end=end, start=start, instant=None if start else True)
            expected = Decimal(str(exp["value"]))
            if fact is not None and fact.value == expected:
                report.matched += 1
            else:
                report.mismatches.append(
                    Mismatch(
                        entry["file"],
                        exp["element"],
                        str(end),
                        str(expected),
                        str(fact.value) if fact else None,
                    )
                )
    return report


def write(report: GoldenReport, out: Path) -> None:
    out.write_text(json.dumps(report.as_dict(), indent=2, default=str))
