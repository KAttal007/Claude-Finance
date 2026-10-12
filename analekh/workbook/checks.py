"""Run a workbook's Checks (design doc 14.3, 15.1 step 5): every check row must evaluate to its
expected value within tolerance before a template is activated or a built model is saved."""

from dataclasses import dataclass, field
from typing import Any

from openpyxl import Workbook

from analekh.workbook.locate import find_row
from analekh.workbook.mapping import Mapping
from analekh.workbook.reader import load
from analekh.workbook.recalc import evaluate, lookup

ERRORS = ("#REF!", "#NAME?", "#VALUE!", "#DIV/0!", "#N/A", "#NULL!", "#NUM!")


@dataclass
class CheckResult:
    label: str
    passed: bool
    failures: dict[str, Any] = field(default_factory=dict)  # cell -> evaluated value


@dataclass
class CheckRun:
    results: list[CheckResult]
    broken_formulas: dict[str, str]  # sheet!cell -> error

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results) and not self.broken_formulas

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": [
                {
                    "label": r.label,
                    "passed": r.passed,
                    "failures": {k: str(v) for k, v in r.failures.items()},
                }
                for r in self.results
            ],
            "broken_formulas": self.broken_formulas,
        }


def run_checks(data: bytes, mapping: Mapping, wb: Workbook | None = None) -> CheckRun:
    wb = wb or load(data)
    values = evaluate(data)
    results = []
    for check in mapping.checks:
        ws = wb[check.sheet]
        r = find_row(ws, check.cell_label, 1)
        if r is None:
            results.append(CheckResult(check.cell_label, False, {"row": "not found"}))
            continue
        failures: dict[str, Any] = {}
        for c in ws[r][1:]:
            if not (isinstance(c.value, str) and c.value.startswith("=")):
                continue
            v = lookup(values, ws.title, c.coordinate)
            if v is None or v == "":
                continue
            try:
                ok = abs(float(v) - check.expect) <= check.tolerance
            except (TypeError, ValueError):
                ok = False
            if not ok:
                failures[c.coordinate] = v
        results.append(CheckResult(check.cell_label, not failures, failures))
    broken = {
        f"{s}!{c}": str(v)
        for (s, c), v in values.items()
        if isinstance(v, str) and v.strip() in ERRORS
    }
    broken |= {f"{s}!{c}": str(v) for (s, c), v in values.items() if type(v).__name__ == "XlError"}
    return CheckRun(results, broken)
