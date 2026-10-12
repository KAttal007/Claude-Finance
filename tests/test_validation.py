from datetime import date
from decimal import Decimal

from analekh.validate.rules import HistoryFact, KpiValue, ValidationContext, validate
from analekh.xbrl.parser import parse_instance
from tests.xbrl_factory import BS, Q2, build_instance, pnl, q2_instance

Q1_HISTORY = [
    HistoryFact(
        "RevenueFromOperations", date(2026, 4, 1), date(2026, 6, 30), Decimal(900_000_000), 1
    ),
    HistoryFact(
        "ProfitLossForPeriod", date(2026, 4, 1), date(2026, 6, 30), Decimal(165_000_000), 1
    ),
]


def by_rule(report):
    return {r.rule: r for r in report.results}


def test_consistent_filing_passes_everything():
    ctx = ValidationContext(
        parse_instance(q2_instance()), filed_at=date(2026, 11, 10), history=Q1_HISTORY
    )
    report = validate(ctx)
    results = by_rule(report)
    for rule in ("V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9"):
        assert results[rule].status == "pass", results[rule]
    assert results["V10"].status == "skip"
    assert not report.blocks_auto_apply


def test_v1_failure_blocks_auto_apply():
    values = pnl(1_000_000_000, 50_000_000, 800_000_000, 62_500_000)
    values["Income"] += 10_000_000
    report = validate(
        ValidationContext(parse_instance(build_instance(**Q2, values_q=values, values_instant=BS)))
    )
    assert by_rule(report)["V1"].status == "fail"
    assert report.blocks_auto_apply


def test_v4_balance_sheet_mismatch():
    report = validate(
        ValidationContext(
            parse_instance(
                build_instance(
                    **Q2,
                    values_q=pnl(1, 0, 0, 0),
                    values_instant={"Assets": 5_000_000_000, "EquityAndLiabilities": 4_000_000_000},
                )
            )
        )
    )
    assert by_rule(report)["V4"].status == "fail"


def test_untagged_elements_skip_not_fail():
    report = validate(
        ValidationContext(
            parse_instance(build_instance(**Q2, values_q={"RevenueFromOperations": 100}))
        )
    )
    results = by_rule(report)
    assert results["V1"].status == "skip"
    assert results["V4"].status == "skip"
    assert not report.blocks_auto_apply


def test_v5_detects_quarter_not_matching_ytd():
    history = [
        HistoryFact(
            "RevenueFromOperations", date(2026, 4, 1), date(2026, 6, 30), Decimal(800_000_000), 1
        )
    ]
    result = by_rule(validate(ValidationContext(parse_instance(q2_instance()), history=history)))[
        "V5"
    ]
    assert result.status == "fail"


def test_v6_declared_period_wins():
    ctx = ValidationContext(parse_instance(q2_instance(declared_end=date(2026, 9, 29))))
    assert by_rule(validate(ctx))["V6"].status == "fail"
    assert ctx.period_end == date(2026, 9, 29)


def test_v7_swing_highlighted():
    history = [
        HistoryFact(
            "RevenueFromOperations", date(2026, 4, 1), date(2026, 6, 30), Decimal(500_000_000), 1
        )
    ]
    result = by_rule(validate(ValidationContext(parse_instance(q2_instance()), history=history)))[
        "V7"
    ]
    assert result.status == "fail" and result.action == "highlight"


def test_v8_late_filing():
    ctx = ValidationContext(parse_instance(q2_instance()), filed_at=date(2027, 4, 15))
    assert by_rule(validate(ctx))["V8"].status == "fail"


def test_v9_restatement_diff():
    history = [
        HistoryFact(
            "RevenueFromOperations", date(2026, 7, 1), date(2026, 9, 30), Decimal(990_000_000), 7
        )
    ]
    result = by_rule(validate(ValidationContext(parse_instance(q2_instance()), history=history)))[
        "V9"
    ]
    assert result.status == "fail"
    assert result.details["diffs"][0]["old_filing_id"] == 7


def test_v10_ai_value_conflict():
    kpis = [KpiValue("revenue", date(2026, 9, 30), Decimal(1_200_000_000))]
    result = by_rule(validate(ValidationContext(parse_instance(q2_instance()), kpis=kpis)))["V10"]
    assert result.status == "fail"


def test_report_is_json_serialisable():
    import json

    report = validate(ValidationContext(parse_instance(q2_instance()), history=Q1_HISTORY))
    json.dumps(report.as_dict())
