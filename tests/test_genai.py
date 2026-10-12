from decimal import Decimal
from types import SimpleNamespace

import pytest

from analekh.genai.calc import CalcError, calc
from analekh.genai.grounding import check, extract_numbers
from analekh.genai.reports import run_report


def test_calc_is_exact_and_safe():
    assert calc("(a-b)/b*100", {"a": 120, "b": 100}) == Decimal(20)
    assert calc("round(a/b, 2)", {"a": 1, "b": 3}) == Decimal("0.33")
    for bad in ("__import__('os')", "a.b", "[1,2]", "x"):
        with pytest.raises(CalcError):
            calc(bad, {"a": 1})
    with pytest.raises(CalcError):
        calc("a/0", {"a": 1})


def test_extract_numbers_skips_citations_labels_and_dates():
    text = (
        "Revenue rose 11.1% to INR 1,000 crore in Q2FY27 [fact:12 filing:3 context:OneD], "
        "vs (25.5) on 30 Sep 2026 and 2026-09-30."
    )
    raws = [r for r, _ in extract_numbers(text)]
    assert raws == ["11.1%", "1,000", "(25.5)"]
    assert extract_numbers("loss of (25.5)")[0][1] == Decimal("-25.5")


def test_grounding_matches_scaled_and_rounded_values():
    tools = [
        [{"element": "RevenueFromOperations", "value": "10000000000"}],
        {"result": "11.1111"},
        [{"name": "gnpa", "value": "3.42"}],
    ]
    ok = check("Revenue was INR 1,000 crore, up 11.1% [fact:1]; GNPA 3.4%.", tools)
    assert ok.ok, ok.unmatched
    bad = check("Revenue was INR 1,050 crore and margin 18.2%.", tools)
    assert not bad.ok and bad.unmatched == ["1,050", "18.2%"]


def test_grounding_checks_bare_large_numbers_like_2045():
    assert check("PAT was 2045 crore.", []).unmatched == ["2045"]


def test_small_counting_words_not_flagged():
    assert check("Three things changed: 3 segments grew.", []).ok


class FakeClaude:
    """Scripted responses: first asks for a tool, then writes text."""

    model = "fake"

    def __init__(self, final_text: str):
        self.final_text = final_text
        self.turn = 0

    def create(self, purpose, **kwargs):
        self.turn += 1
        if self.turn == 1:
            block = SimpleNamespace(
                type="tool_use",
                id="t1",
                name="calc",
                input={
                    "expression": "a/b*100",
                    "inputs": [{"name": "a", "value": 1}, {"name": "b", "value": 8}],
                },
            )
            msg = SimpleNamespace(stop_reason="tool_use", content=[block])
            return SimpleNamespace(text="", message=msg, input_tokens=10, output_tokens=5)
        msg = SimpleNamespace(
            stop_reason="end_turn", content=[SimpleNamespace(type="text", text=self.final_text)]
        )
        return SimpleNamespace(text=self.final_text, message=msg, input_tokens=10, output_tokens=5)


def test_report_loop_runs_tools_and_grounds_output():
    from analekh.genai.tools import ToolExecutor

    executor = ToolExecutor(session=None)  # calc needs no database
    good = run_report(
        FakeClaude("Margin was 12.5% [calc]."),
        executor,
        "flash",
        company="DEMO",
        period_end="2026-09-30",
    )
    assert not good.blocked and good.tool_calls[0]["tool"] == "calc"
    bad = run_report(
        FakeClaude("Margin was 14.0%."), executor, "flash", company="DEMO", period_end="2026-09-30"
    )
    assert bad.blocked and bad.grounding.unmatched == ["14.0%"]
