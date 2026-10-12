"""Spec-driven generator for built-in templates (design doc 15.2).

Sheets: Cover, Data, Drivers, Model, Sector KPIs, Valuation, Sensitivities, Checks, Sources.
Actual columns hold blue input cells; estimate columns hold formulas driven by the Drivers
sheet. Columns line up across sheets, so a formula in column F always means the same period.

Formula templates use ``{c}`` for the current column, ``{p}`` for the previous column,
``[[Label]]`` for a Data row and ``{{Label}}`` for a Drivers row.
"""

import io
import re
from dataclasses import dataclass, field
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from analekh.workbook.mapping import Check, Driver, Mapping, PeriodAxis, RowMap, Units
from analekh.workbook.periods import fiscal_label

BLUE = Font(color="FF0000FF")
BOLD = Font(bold=True)
HEADER_FILL = PatternFill("solid", fgColor="FFDDEBF7")
LABEL_COL = 1
FIRST_DATA_COL = 2


@dataclass
class Line:
    label: str
    source: str | None  # mapping source for actual values, e.g. xbrl:RevenueFromOperations
    actual: str  # "input" or a formula template
    estimate: str  # formula template
    transform: str | None = None  # None = template default (INR -> INR crore)


@dataclass
class DriverSpec:
    label: str
    name: str
    default: float  # neutral starting value until the analyst accepts a proposal
    actual_label: str  # Data row whose history informs the proposal
    kind: str  # growth, ratio_to_revenue, tax_rate, ratio


@dataclass
class TemplateSpec:
    key: str
    name: str
    sectors: list[str]
    lines: list[Line]
    drivers: list[DriverSpec]
    checks: list[tuple[str, str]]  # (label, formula template evaluated per column)
    kpi_lines: list[Line] = field(default_factory=list)  # Sector KPIs sheet
    valuation: list[tuple[str, str | float | None]] = field(default_factory=list)


def quarter_ends(last_actual: date, n_hist: int, n_fcst: int) -> list[date]:
    """n_hist quarter ends up to last_actual, then n_fcst forecast quarter ends."""
    months = [3, 6, 9, 12]
    y, m = last_actual.year, last_actual.month
    out: list[date] = []
    idx = months.index(m)
    for k in range(-(n_hist - 1), n_fcst + 1):
        total = idx + k
        yy, mi = y + total // 4, months[total % 4]
        day = 31 if mi in (3, 12) else 30
        out.append(date(yy, mi, day))
    return out


def _fill(template: str, col: int, data_rows: dict[str, int], driver_rows: dict[str, int]) -> str:
    c, p = get_column_letter(col), get_column_letter(col - 1)
    out = template.replace("{c}", c).replace("{p}", p)
    out = re.sub(r"\[\[(.+?)\]\]", lambda m: str(data_rows[m.group(1)]), out)
    return re.sub(r"\{\{(.+?)\}\}", lambda m: str(driver_rows[m.group(1)]), out)


def build(
    spec: TemplateSpec, last_actual: date, n_hist: int = 8, n_fcst: int = 4
) -> tuple[bytes, Mapping]:
    periods = quarter_ends(last_actual, n_hist, n_fcst)
    cols = list(range(FIRST_DATA_COL, FIRST_DATA_COL + len(periods)))
    hist_cols, fcst_cols = cols[:n_hist], cols[n_hist:]
    last = get_column_letter(cols[-1])

    wb = Workbook()
    cover = wb.active
    cover.title = "Cover"
    data = wb.create_sheet("Data")
    drivers = wb.create_sheet("Drivers")
    model = wb.create_sheet("Model")
    kpis = wb.create_sheet("Sector KPIs")
    valuation = wb.create_sheet("Valuation")
    sens = wb.create_sheet("Sensitivities")
    checks = wb.create_sheet("Checks")
    sources = wb.create_sheet("Sources")

    data_rows = {ln.label: i for i, ln in enumerate(spec.lines, start=3)}
    driver_rows = {d.label: i for i, d in enumerate(spec.drivers, start=3)}

    # Period header and A/E flags on Data; other period sheets mirror them by formula.
    data.cell(row=1, column=LABEL_COL, value="Period").font = BOLD
    data.cell(row=2, column=LABEL_COL, value="A/E").font = BOLD
    for col, end in zip(cols, periods, strict=True):
        h = data.cell(row=1, column=col, value=fiscal_label(end))
        h.font, h.fill = BOLD, HEADER_FILL
        data.cell(row=2, column=col, value="A" if col in hist_cols else "E")
    for ws in (drivers, model, kpis, checks):
        ws.cell(row=1, column=LABEL_COL, value="Period (from Data)").font = BOLD
        for col in cols:
            ws.cell(row=1, column=col, value=f"=Data!{get_column_letter(col)}1")

    for ln in spec.lines:
        r = data_rows[ln.label]
        data.cell(row=r, column=LABEL_COL, value=ln.label)
        for col in cols:
            tmpl = ln.actual if col in hist_cols else ln.estimate
            if tmpl == "input":
                cell = data.cell(row=r, column=col)
                cell.font = BLUE
                cell.number_format = "#,##0.00"
            elif col == cols[0] and "{p}" in tmpl:
                data.cell(row=r, column=col).font = BLUE  # no previous column: input
            else:
                data.cell(row=r, column=col, value=_fill(tmpl, col, data_rows, driver_rows))

    drivers.cell(row=2, column=LABEL_COL, value="Driver").font = BOLD
    for d in spec.drivers:
        r = driver_rows[d.label]
        drivers.cell(row=r, column=LABEL_COL, value=d.label)
        for col in fcst_cols:
            cell = drivers.cell(row=r, column=col, value=d.default)
            cell.font = BLUE
            cell.number_format = "0.0000"

    model.cell(row=2, column=LABEL_COL, value="Derived metrics").font = BOLD
    derived = _derived_rows(spec, data_rows)
    for i, (label, tmpl) in enumerate(derived, start=3):
        model.cell(row=i, column=LABEL_COL, value=label)
        for col in cols:
            model.cell(row=i, column=col, value=_fill(tmpl, col, data_rows, driver_rows))

    kpi_rows = {ln.label: i for i, ln in enumerate(spec.kpi_lines, start=3)}
    for ln in spec.kpi_lines:
        r = kpi_rows[ln.label]
        kpis.cell(row=r, column=LABEL_COL, value=ln.label)
        for col in hist_cols:
            kpis.cell(row=r, column=col).font = BLUE

    for i, (label, value) in enumerate(spec.valuation, start=1):
        valuation.cell(row=i, column=1, value=label)
        if value is not None:
            c = valuation.cell(row=i, column=2, value=value)
            if not (isinstance(value, str) and value.startswith("=")):
                c.font = BLUE
    valuation.cell(
        row=len(spec.valuation) + 2,
        column=1,
        value="Rating and target price are left to the analyst (section 15.3).",
    )

    sens.cell(
        row=1, column=1, value="Sensitivities: fill once valuation inputs are set"
    ).font = BOLD

    checks.cell(row=2, column=LABEL_COL, value="Check (0 = pass)").font = BOLD
    for i, (label, tmpl) in enumerate(spec.checks, start=3):
        checks.cell(row=i, column=LABEL_COL, value=label)
        for col in cols:
            checks.cell(row=i, column=col, value=_fill(tmpl, col, data_rows, driver_rows))
    n_checks = len(spec.checks)
    summary_row = 3 + n_checks
    first = get_column_letter(cols[0])
    checks.cell(row=summary_row, column=LABEL_COL, value="All checks pass")
    checks.cell(
        row=summary_row,
        column=FIRST_DATA_COL,
        value=(
            f"=IF(AND(MAX({first}3:{last}{summary_row - 1})<0.5,"
            f"MIN({first}3:{last}{summary_row - 1})>-0.5),1,0)"
        ),
    )

    for col_i, h in enumerate(
        ("Sheet", "Cell", "Value", "Source", "Period", "Filing", "Document and page"), start=1
    ):
        sources.cell(row=1, column=col_i, value=h).font = BOLD

    cover["A1"], cover["A1"].font = spec.name, Font(bold=True, size=14)
    cover["A3"], cover["B3"] = "Company", ""
    cover["A4"], cover["B4"] = "Prepared", ""
    cover["A5"], cover["B5"] = "Template", f"{spec.key} (built-in)"
    cover["A7"] = "Sheets"
    for i, ws in enumerate(wb.worksheets, start=8):
        cover.cell(row=i, column=1, value=ws.title)

    mapping = Mapping(
        template=spec.key,
        version=1,
        sectors=spec.sectors,
        basis="consolidated",
        period_axis=PeriodAxis(sheet="Data", header_row_label="Period", flag_row_label="A/E"),
        units=Units(default_transform="div:10000000"),
        rows=[
            RowMap(
                source=ln.source,
                sheet="Data",
                row_label=ln.label,
                transform=ln.transform,
                confidence=1.0,
            )
            for ln in spec.lines
            if ln.source and ln.actual == "input"
        ]
        + [
            RowMap(
                source=ln.source,
                sheet="Sector KPIs",
                row_label=ln.label,
                transform=ln.transform or "none",
                confidence=1.0,
            )
            for ln in spec.kpi_lines
            if ln.source
        ],
        drivers=[
            Driver(
                name=d.name,
                actual_row_label=d.actual_label,
                forecast_sheet="Drivers",
                forecast_row_label=d.label,
            )
            for d in spec.drivers
        ],
        checks=[Check(sheet="Checks", cell_label="All checks pass", expect=1, tolerance=0)],
    )
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue(), mapping


def _derived_rows(spec: TemplateSpec, data_rows: dict[str, int]) -> list[tuple[str, str]]:
    rows = []
    if "Revenue from operations" in data_rows and "Profit after tax" in data_rows:
        rows.append(
            (
                "PAT margin (%)",
                "=IFERROR({c}[[Profit after tax]]/{c}[[Revenue from operations]]*100,0)",
            )
        )
    if "Revenue from operations" in data_rows:
        rows.append(
            (
                "Revenue growth QoQ (%)",
                "=IFERROR(({c}[[Revenue from operations]]/{p}[[Revenue from operations]]-1)*100,0)",
            )
        )
    rows = [
        (label, re.sub(r"\[\[(.+?)\]\]", lambda m: f"[[{m.group(1)}]]", t)) for label, t in rows
    ]
    # Model rows reference Data cells across sheets.
    return [
        (label, t.replace("{c}[[", "Data!{c}[[").replace("{p}[[", "Data!{p}[["))
        for label, t in rows
    ]
