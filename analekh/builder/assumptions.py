"""First-pass assumptions (design doc 15.1 step 4, F11).

Each driver gets a proposal from history (averages and trends of the last 4 to 12 quarters),
with a one-line rationale built only from those numbers and citations to the facts used.
Management guidance from the document pipeline can refine a proposal through the optional
``refine`` hook (GenAI engine), which must keep the citations. The analyst accepts or edits each.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from statistics import mean
from typing import Any

from analekh.facts import ValueSource, resolve_row
from analekh.templates_builtin.base import quarter_ends
from analekh.workbook.mapping import Driver, Mapping, RowMap

LOOKBACK_QUARTERS = 12


@dataclass
class Proposal:
    driver: str
    value: Decimal
    rationale: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    basis: list[str] = field(default_factory=list)  # period labels used


Refiner = Callable[[Proposal], Proposal]


def _q(x: float, places: str = "0.0001") -> Decimal:
    return Decimal(str(x)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _series(
    source: ValueSource, mapping: Mapping, label: str, periods: list[date]
) -> list[tuple[date, Decimal, list[dict[str, Any]]]]:
    row = next((r for r in mapping.rows if r.row_label == label), None)
    if row is None:
        return []
    out = []
    for end in periods:
        res = resolve_row(source, row, mapping, end)
        if res is not None:
            out.append(
                (
                    end,
                    res.value,
                    [{"fact_id": p.fact_id, "source": p.description} for p in res.parts],
                )
            )
    return out


def _revenue_row(mapping: Mapping) -> RowMap | None:
    return next((r for r in mapping.rows if r.source == "xbrl:RevenueFromOperations"), None)


def propose(
    source: ValueSource,
    mapping: Mapping,
    last_actual: date,
    kinds: dict[str, str],
    refine: Refiner | None = None,
) -> list[Proposal]:
    """kinds: driver name -> growth | ratio_to_revenue | tax_rate | ratio."""
    periods = quarter_ends(last_actual, LOOKBACK_QUARTERS, 0)
    rev_row = _revenue_row(mapping)
    revenue = (
        {e: v for e, v, _ in _series(source, mapping, rev_row.row_label, periods)}
        if rev_row
        else {}
    )
    pbt_row = next((r for r in mapping.rows if r.source == "xbrl:ProfitBeforeTax"), None)
    out: list[Proposal] = []
    for d in mapping.drivers:
        p = _propose_one(source, mapping, d, kinds.get(d.name, "ratio"), periods, revenue, pbt_row)
        if p is not None:
            out.append(refine(p) if refine else p)
    return out


def _propose_one(
    source: ValueSource,
    mapping: Mapping,
    d: Driver,
    kind: str,
    periods: list[date],
    revenue: dict[date, Decimal],
    pbt_row: RowMap | None,
) -> Proposal | None:
    series = _series(source, mapping, d.actual_row_label, periods)
    if len(series) < 2:
        return None
    labels = [f"{e:%b-%y}" for e, _, _ in series]
    cites = [c for _, _, cs in series for c in cs]
    if kind == "growth":
        recent = series[-5:]
        growth = [
            float(b / a - 1) for (_, a, _), (_, b, _) in zip(recent, recent[1:], strict=False) if a
        ]
        if not growth:
            return None
        avg = mean(growth)
        return Proposal(
            d.name,
            _q(avg),
            (
                f"Average quarter-on-quarter growth of {d.actual_row_label.lower()} over the last "
                f"{len(growth)} quarters was {avg * 100:.1f}%."
            ),
            cites,
            labels,
        )
    if kind == "ratio_to_revenue":
        ratios = [float(v / revenue[e]) for e, v, _ in series[-12:] if revenue.get(e)]
        if not ratios:
            return None
        avg = mean(ratios)
        trend = ratios[-1] - ratios[0]
        direction = "rising" if trend > 0.005 else "falling" if trend < -0.005 else "stable"
        return Proposal(
            d.name,
            _q(avg),
            (
                f"{d.actual_row_label} averaged {avg * 100:.1f}% of revenue over "
                f"{len(ratios)} quarters ({direction}: {ratios[0] * 100:.1f}% to "
                f"{ratios[-1] * 100:.1f}%)."
            ),
            cites,
            labels,
        )
    if kind == "tax_rate" and pbt_row is not None:
        pbt = {e: v for e, v, _ in _series(source, mapping, pbt_row.row_label, periods)}
        rates = [float(v / pbt[e]) for e, v, _ in series[-8:] if pbt.get(e) and pbt[e] > 0]
        if not rates:
            return None
        avg = mean(rates)
        return Proposal(
            d.name,
            _q(avg),
            (f"Effective tax rate averaged {avg * 100:.1f}% over {len(rates)} quarters."),
            cites,
            labels,
        )
    values = [float(v) for _, v, _ in series[-12:]]
    avg = mean(values)
    return Proposal(
        d.name,
        _q(avg),
        (f"{d.actual_row_label} averaged {avg:.2f} over {len(values)} quarters."),
        cites,
        labels,
    )
