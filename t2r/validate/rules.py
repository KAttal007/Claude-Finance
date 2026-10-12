"""Validation rules V1-V10 (design doc 8.2).

Each rule returns a RuleResult. Rules that cannot run because an element is not tagged return
``skip``; nothing is inferred. A ``block`` failure stops auto-apply of the filing's change set.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from t2r.xbrl.elements import candidates
from t2r.xbrl.parser import ParsedFact, ParsedFiling, period_type

Status = Literal["pass", "fail", "skip"]
Action = Literal["block", "flag", "warn", "highlight", "label", "info"]

LATE_FILING_DAYS = 180
SWING_THRESHOLD = Decimal("0.5")
RELATIVE_TOLERANCE = Decimal("0.0005")


@dataclass(frozen=True)
class RuleResult:
    rule: str
    status: Status
    action: Action
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HistoryFact:
    """A latest fact already stored for this company and basis, from an earlier filing."""

    element: str
    period_start: date | None
    period_end: date
    value: Decimal
    filing_id: int


@dataclass(frozen=True)
class KpiValue:
    logical: str  # logical name from t2r.xbrl.elements, e.g. "revenue"
    period_end: date
    value: Decimal  # in full INR, same scale as XBRL


@dataclass
class ValidationContext:
    filing: ParsedFiling
    taxonomy: str = "indas"
    filed_at: date | None = None
    history: list[HistoryFact] = field(default_factory=list)
    kpis: list[KpiValue] = field(default_factory=list)

    @property
    def period_end(self) -> date | None:
        """Declared reporting period wins over context dates (V6)."""
        if self.filing.declared_end:
            return self.filing.declared_end
        ends = [f.period_end for f in self.filing.facts if not f.is_instant]
        return max(ends) if ends else None

    def fact(
        self, logical: str, *, quarter: bool = True, instant: bool = False
    ) -> ParsedFact | None:
        end = self.period_end
        for element in candidates(logical, self.taxonomy):
            for f in self.filing.facts:
                if f.element != element or f.dimensions or f.period_end != end:
                    continue
                if instant and f.is_instant:
                    return f
                if not instant and not f.is_instant:
                    is_q = period_type(f.period_start, f.period_end) == "Q"
                    if is_q == quarter:
                        return f
        return None


@dataclass
class ValidationReport:
    results: list[RuleResult]

    @property
    def blocks_auto_apply(self) -> bool:
        return any(r.status == "fail" and r.action == "block" for r in self.results)

    @property
    def failures(self) -> list[RuleResult]:
        return [r for r in self.results if r.status == "fail"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "blocks_auto_apply": self.blocks_auto_apply,
            "results": [r.__dict__ | {"details": _jsonable(r.details)} for r in self.results],
        }


def tolerance(*facts: ParsedFact) -> Decimal:
    """Rounding allowance: half a unit of each term's stated precision, or 0.05% of the largest."""
    allowance = sum(
        (Decimal(10) ** (-f.decimals) / 2 for f in facts if f.decimals is not None),
        Decimal(0),
    )
    largest = max((abs(f.value) for f in facts), default=Decimal(0))
    return max(allowance, largest * RELATIVE_TOLERANCE, Decimal(1))


def _identity(
    rule: str,
    action: Action,
    label: str,
    lhs: list[ParsedFact | None],
    rhs: ParsedFact | None,
    signs: list[int] | None = None,
) -> RuleResult:
    if rhs is None or any(f is None for f in lhs):
        return RuleResult(rule, "skip", action, f"{label}: element not tagged")
    terms = [f for f in lhs if f is not None]
    signs = signs or [1] * len(terms)
    computed = sum((s * f.value for s, f in zip(signs, terms, strict=True)), Decimal(0))
    diff = computed - rhs.value
    tol = tolerance(*terms, rhs)
    details = {"computed": computed, "reported": rhs.value, "diff": diff, "tolerance": tol}
    if abs(diff) <= tol:
        return RuleResult(rule, "pass", action, label, details)
    return RuleResult(rule, "fail", action, f"{label}: off by {diff}", details)


def v1_total_income(ctx: ValidationContext) -> RuleResult:
    return _identity(
        "V1",
        "block",
        "Revenue + other income = total income",
        [ctx.fact("revenue"), ctx.fact("other_income")],
        ctx.fact("total_income"),
    )


def v2_pbt(ctx: ValidationContext) -> RuleResult:
    exceptional = ctx.fact("exceptional_items")
    lhs = [ctx.fact("total_income"), ctx.fact("total_expenses")]
    signs = [1, -1]
    if exceptional is not None:
        # PHASE 0: confirm the sign convention of exceptional items in real filings.
        lhs.append(exceptional)
        signs.append(-1)
    return _identity(
        "V2",
        "block",
        "Total income - total expenses (- exceptional) = PBT",
        lhs,
        ctx.fact("pbt"),
        signs,
    )


def v3_pat(ctx: ValidationContext) -> RuleResult:
    pat = ctx.fact("pat_continuing") or ctx.fact("pat")
    return _identity(
        "V3", "flag", "PBT - tax = PAT", [ctx.fact("pbt"), ctx.fact("tax")], pat, [1, -1]
    )


def v4_balance_sheet(ctx: ValidationContext) -> RuleResult:
    assets = ctx.fact("total_assets", instant=True)
    eq_li = ctx.fact("equity_and_liabilities", instant=True)
    if eq_li is not None:
        return _identity("V4", "block", "Assets = equity + liabilities", [eq_li], assets)
    return _identity(
        "V4",
        "block",
        "Assets = equity + liabilities",
        [ctx.fact("total_equity", instant=True), ctx.fact("total_liabilities", instant=True)],
        assets,
    )


def v5_quarter_vs_ytd(ctx: ValidationContext) -> RuleResult:
    """Quarter = YTD - prior YTD of the same fiscal year, for revenue and PAT."""
    checked: list[dict[str, Any]] = []
    for logical in ("revenue", "pat"):
        q, ytd = ctx.fact(logical), ctx.fact(logical, quarter=False)
        if q is None or ytd is None or q.period_start is None or q.period_start == ytd.period_start:
            continue
        names = candidates(logical, ctx.taxonomy)
        prior = next(
            (
                h
                for h in ctx.history
                if h.element in names
                and h.period_start == ytd.period_start
                and q.period_start is not None
                and (q.period_start - h.period_end).days == 1
            ),
            None,
        )
        if prior is None:
            continue
        derived = ytd.value - prior.value
        diff = derived - q.value
        ok = abs(diff) <= tolerance(q, ytd)
        checked.append(
            {"logical": logical, "derived": derived, "reported": q.value, "diff": diff, "ok": ok}
        )
    if not checked:
        return RuleResult("V5", "skip", "flag", "Quarter vs YTD: no prior YTD in history")
    bad = [c for c in checked if not c["ok"]]
    status: Status = "fail" if bad else "pass"
    return RuleResult("V5", status, "flag", "Quarter = YTD - prior YTD", {"checks": checked})


def v6_declared_period(ctx: ValidationContext) -> RuleResult:
    declared = ctx.filing.declared_end
    if declared is None:
        return RuleResult("V6", "skip", "warn", "No declared reporting period in filing")
    ends = sorted({f.period_end for f in ctx.filing.facts if not f.is_instant})
    if not ends or ends[-1] == declared:
        return RuleResult("V6", "pass", "warn", "Context dates agree with declared period")
    return RuleResult(
        "V6",
        "fail",
        "warn",
        f"Latest context end {ends[-1]} != declared {declared}; using declared",
        {"declared_end": declared, "context_end": ends[-1]},
    )


def v7_swing(ctx: ValidationContext) -> RuleResult:
    swings: list[dict[str, Any]] = []
    for logical in ("revenue", "pat"):
        q = ctx.fact(logical)
        if q is None or q.period_start is None:
            continue
        names = candidates(logical, ctx.taxonomy)
        prev = next(
            (
                h
                for h in ctx.history
                if h.element in names
                and h.period_start is not None
                and period_type(h.period_start, h.period_end) == "Q"
                and (q.period_start - h.period_end).days == 1
            ),
            None,
        )
        if prev is None or prev.value == 0:
            continue
        change = (q.value - prev.value) / abs(prev.value)
        if abs(change) > SWING_THRESHOLD:
            swings.append(
                {"logical": logical, "previous": prev.value, "current": q.value, "change": change}
            )
    if swings:
        return RuleResult("V7", "fail", "highlight", "QoQ change above 50%", {"swings": swings})
    return RuleResult("V7", "pass", "highlight", "No QoQ swing above 50%")


def v8_late_filing(ctx: ValidationContext) -> RuleResult:
    end = ctx.period_end
    if ctx.filed_at is None or end is None:
        return RuleResult("V8", "skip", "label", "Filing date unknown")
    lag = (ctx.filed_at - end).days
    if lag > LATE_FILING_DAYS:
        return RuleResult(
            "V8", "fail", "label", f"Filed {lag} days after period end (late)", {"lag_days": lag}
        )
    return RuleResult(
        "V8", "pass", "label", f"Filed {lag} days after period end", {"lag_days": lag}
    )


def v9_restatement(ctx: ValidationContext) -> RuleResult:
    """Same period already stored from another filing with different values."""
    stored = {(h.element, h.period_start, h.period_end): h for h in ctx.history}
    diffs = []
    for f in ctx.filing.facts:
        if f.dimensions:
            continue
        h = stored.get((f.element, f.period_start, f.period_end))
        if h is not None and abs(h.value - f.value) > tolerance(f):
            diffs.append(
                {
                    "element": f.element,
                    "period_end": f.period_end,
                    "old": h.value,
                    "new": f.value,
                    "old_filing_id": h.filing_id,
                }
            )
    if diffs:
        return RuleResult(
            "V9", "fail", "info", f"Restatement: {len(diffs)} values changed", {"diffs": diffs}
        )
    return RuleResult("V9", "pass", "info", "No restated values")


def v10_kpi_conflict(ctx: ValidationContext) -> RuleResult:
    conflicts = []
    for k in ctx.kpis:
        for element in candidates(k.logical, ctx.taxonomy):
            f = ctx.filing.get(element, end=k.period_end)
            if f is not None and abs(f.value - k.value) > tolerance(f):
                conflicts.append({"logical": k.logical, "xbrl": f.value, "ai": k.value})
                break
    if not ctx.kpis:
        return RuleResult("V10", "skip", "flag", "No AI-extracted values to compare")
    if conflicts:
        return RuleResult(
            "V10",
            "fail",
            "flag",
            "AI value conflicts with XBRL; XBRL wins",
            {"conflicts": conflicts},
        )
    return RuleResult("V10", "pass", "flag", "AI values agree with XBRL")


RULES: list[Callable[[ValidationContext], RuleResult]] = [
    v1_total_income,
    v2_pbt,
    v3_pat,
    v4_balance_sheet,
    v5_quarter_vs_ytd,
    v6_declared_period,
    v7_swing,
    v8_late_filing,
    v9_restatement,
    v10_kpi_conflict,
]


def validate(ctx: ValidationContext) -> ValidationReport:
    return ValidationReport([rule(ctx) for rule in RULES])


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value
