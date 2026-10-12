"""Grounded report generation (design doc 11): flash, call digest, red flags, draft note, Q&A.

A manual tool loop keeps every tool result of the run so the grounding check can verify each
number in the output. Ungrounded output is returned blocked, never silently shown.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from analekh.genai.client import Claude
from analekh.genai.grounding import GroundingResult, check
from analekh.genai.tools import TOOL_DEFS, ToolExecutor, to_json

SYSTEM = (
    "You are an equity research associate covering Indian listed companies. Write for a "
    "professional analyst: concise, specific, no filler. Rules:\n"
    "1. State only numbers returned by a tool in this conversation, or computed with the calc "
    "tool. Never compute in your head; call calc for every growth rate, margin or variance.\n"
    "2. After each figure or claim, cite its source in square brackets using the 'source' field "
    "the tool returned, e.g. [fact:123 filing:9 context:OneD] or [filing:4 page:7].\n"
    "3. No buy/sell/hold ratings and no target prices.\n"
    "4. If data needed for a point is missing, say so instead of filling the gap."
)

PROMPTS = {
    "flash": (
        "Write a one-page results flash for {company} for the period ending {period_end}. "
        "Compare actuals with the previous quarter, the same quarter last year and, if a model "
        "id is given ({model_id}), the analyst's estimates. Include key KPIs and three to five "
        "bullets on what changed."
    ),
    "digest": (
        "Write an earnings call digest for {company}, period ending {period_end}: guidance "
        "changes versus the previous call, recurring analyst concerns, topics management "
        "deflected, and tone shift. Use search_filings to find the transcript passages."
    ),
    "red_flags": (
        "List red flags for {company} as of {period_end}: auditor qualifications, promoter "
        "pledges, related-party transactions, insider sales, late filings, restatements. "
        "Only list items supported by a tool result."
    ),
    "note": (
        "Draft a three-to-five page results note for {company}, period ending {period_end}, "
        "built from the reported numbers, KPIs and call commentary. Sections: Summary, Results, "
        "Segments/KPIs, Commentary and guidance, Risks, Model changes."
    ),
    "initiation": (
        "Draft an initiation report for {company} from its built model (model id {model_id}) "
        "and sourced research, as of {period_end}. Sections: Investment summary, Business and "
        "segments, Industry backdrop, Management and governance, Financial analysis, Forecasts, "
        "Valuation, Risks. Read forecasts and valuation inputs with get_model_values; mark any "
        "industry context drawn from public sources 'for verification'. Compute valuation "
        "figures but leave the rating and target price for the analyst."
    ),
    "qa": "{question}\n(Company: {company}.) Answer from the filings with page citations.",
}


@dataclass
class ReportRun:
    kind: str
    text: str
    grounding: GroundingResult
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def blocked(self) -> bool:
        return not self.grounding.ok


def run_report(
    claude: Claude, executor: ToolExecutor, kind: str, max_turns: int = 20, **params: Any
) -> ReportRun:
    prompt = PROMPTS[kind].format(**{"model_id": None, **params})
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    system = [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]
    calls: list[dict[str, Any]] = []
    results: list[Any] = []
    tokens_in = tokens_out = 0

    for _ in range(max_turns):
        res = claude.create(
            f"report:{kind}",
            system=system,
            messages=messages,
            tools=TOOL_DEFS,
            effort="high",
            max_tokens=32000,
        )
        tokens_in += res.input_tokens
        tokens_out += res.output_tokens
        msg = res.message
        messages.append({"role": "assistant", "content": msg.content})
        if msg.stop_reason != "tool_use":
            grounding = check(res.text, results)
            return ReportRun(kind, res.text, grounding, calls, tokens_in, tokens_out)

        tool_results = []
        for block in msg.content:
            if block.type != "tool_use":
                continue
            args = block.input if isinstance(block.input, dict) else json.loads(block.input)
            try:
                output = executor.run(block.name, args)
                results.append(output)
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": to_json(output)}
                )
            except Exception as exc:  # noqa: BLE001 - surface to the model, keep going
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(exc),
                        "is_error": True,
                    }
                )
            calls.append({"tool": block.name, "input": args})
        messages.append({"role": "user", "content": tool_results})

    raise RuntimeError(f"report {kind} did not finish within {max_turns} turns")
