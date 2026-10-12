"""Workbook hygiene (design doc 12, 14.4): external links, macros, hardcodes inside formula areas,
and formulas that are inconsistent across a row. Findings are reported, never auto-fixed."""

from dataclasses import dataclass

from openpyxl import Workbook
from openpyxl.formula.translate import Translator
from openpyxl.utils import get_column_letter

from analekh.workbook.periods import PeriodAxis


@dataclass(frozen=True)
class Finding:
    kind: str  # external_link, macros, hardcode_in_formula_row, inconsistent_formula, error_value
    sheet: str | None
    cell: str | None
    detail: str


ERROR_VALUES = ("#REF!", "#NAME?", "#VALUE!", "#DIV/0!", "#N/A", "#NULL!", "#NUM!")


def scan_hygiene(wb: Workbook, axis: PeriodAxis | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for link in getattr(wb, "_external_links", []) or []:
        target = getattr(getattr(link, "file_link", None), "Target", None) or "external workbook"
        findings.append(Finding("external_link", None, None, f"links to {target}"))
    if getattr(wb, "vba_archive", None) is not None:
        findings.append(Finding("macros", None, None, "workbook contains macros (kept, never run)"))

    for ws in wb.worksheets:
        for row in ws.iter_rows():
            formulas = [c for c in row if isinstance(c.value, str) and c.value.startswith("=")]
            for c in row:
                if (
                    isinstance(c.value, str)
                    and c.value.startswith("=")
                    and any(e in c.value.upper() for e in ("#REF!",))
                    or isinstance(c.value, str)
                    and c.value.strip() in ERROR_VALUES
                ):
                    findings.append(Finding("error_value", ws.title, c.coordinate, c.value))
            if len(formulas) < 3:
                continue
            # Hardcodes inside a formula row: numbers sitting between formulas, outside the
            # actual-period columns where typed inputs are expected.
            first, last = formulas[0].column, formulas[-1].column
            for c in row:
                if first < c.column < last and isinstance(c.value, int | float):
                    if axis and ws.title == axis.sheet and not axis.is_estimate(c.column):
                        continue
                    findings.append(
                        Finding(
                            "hardcode_in_formula_row",
                            ws.title,
                            c.coordinate,
                            f"typed value {c.value} among formulas",
                        )
                    )
            # Inconsistent formulas: translate each formula to its left neighbour's position;
            # a consistent row reproduces the neighbour exactly.
            for prev, cur in zip(formulas, formulas[1:], strict=False):
                if cur.column != prev.column + 1:
                    continue
                try:
                    moved = Translator(cur.value, origin=cur.coordinate).translate_formula(
                        prev.coordinate
                    )
                except Exception:  # noqa: BLE001 - unparseable formula: report, don't crash
                    continue
                if moved != prev.value:
                    findings.append(
                        Finding(
                            "inconsistent_formula",
                            ws.title,
                            cur.coordinate,
                            f"differs from {get_column_letter(prev.column)}{prev.row}: "
                            f"{cur.value} vs {prev.value}",
                        )
                    )
    return findings
