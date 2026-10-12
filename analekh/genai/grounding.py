"""Grounding check (design doc 11.3).

Every number in generated text must match a value returned by a tool call (or calc) in the same
run. Unmatched numbers block the output and are shown to the analyst. Matching allows for the
ways analysts write numbers: thousands separators, Indian grouping, % vs ratio, crore/lakh
scaling, and display rounding.
"""

import contextlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

# Numbers like 1,234.5  12,34,567  -3.2  (4.5)  18%  but not dates or fiscal labels.
_NUM = re.compile(r"(?<![\w.])\(?-?\d[\d,]*(?:\.\d+)?\)?%?(?![\w])")
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
# Masked before matching: citations like [fact:12 filing:3], fiscal labels, years, dates.
_IGNORE_CONTEXT = re.compile(
    r"\[[^\]]*\]"
    r"|\b(?:Q[1-4]|H[12]|9M)?\s*FY\s*'?\d{2,4}\b|\bQ[1-4]\b|\b9M\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    # Years only in date context, so a bare value like 2045 (crore) is still checked.
    rf"|\b\d{{1,2}}[- ]?{_MONTH}[- ,]*(?:19|20)\d{{2}}\b"
    rf"|\b{_MONTH}\s+(?:\d{{1,2}},?\s+)?(?:19|20)\d{{2}}\b"
    r"|\b(?:since|until|CY)\s*(?:19|20)\d{2}\b",
    re.IGNORECASE,
)
SCALES = (Decimal(1), Decimal(100), Decimal("1e5"), Decimal("1e7"), Decimal("1e9"), Decimal("0.01"))
SMALL_INTEGERS = set(range(0, 11))  # "three bullets", "two quarters": not data


@dataclass
class GroundingResult:
    ok: bool
    numbers: list[str]
    unmatched: list[str]


def extract_numbers(text: str) -> list[tuple[str, Decimal]]:
    masked = _IGNORE_CONTEXT.sub(lambda m: " " * len(m.group(0)), text)
    found = []
    for m in _NUM.finditer(masked):
        raw = m.group(0)
        cleaned = raw.strip("()%").replace(",", "")
        try:
            value = Decimal(cleaned)
        except InvalidOperation:
            continue
        if raw.startswith("(") and raw.endswith(")"):
            value = -value
        found.append((raw, value))
    return found


def collect_values(obj: Any) -> set[Decimal]:
    """All numeric leaves from tool results (nested dicts/lists, numeric strings)."""
    values: set[Decimal] = set()
    if isinstance(obj, bool):
        return values
    if isinstance(obj, int | float | Decimal):
        values.add(Decimal(str(obj)))
    elif isinstance(obj, str):
        with contextlib.suppress(InvalidOperation):
            values.add(Decimal(obj.replace(",", "")))
    elif isinstance(obj, dict):
        for v in obj.values():
            values |= collect_values(v)
    elif isinstance(obj, list | tuple | set):
        for v in obj:
            values |= collect_values(v)
    return values


def _decimals(raw: str) -> int:
    core = raw.strip("()%").replace(",", "")
    return len(core.split(".")[1]) if "." in core else 0


def matches(raw: str, value: Decimal, sources: Iterable[Decimal]) -> bool:
    places = _decimals(raw)
    half_unit = Decimal(10) ** (-places) / 2
    for src in sources:
        for scale in SCALES:
            scaled = src / scale
            if abs(abs(scaled) - abs(value)) <= half_unit:
                return True
    return False


def check(text: str, tool_results: list[Any]) -> GroundingResult:
    sources = collect_values(tool_results)
    numbers = extract_numbers(text)
    unmatched = [
        raw
        for raw, v in numbers
        if not (v == v.to_integral_value() and abs(v) in SMALL_INTEGERS and "%" not in raw)
        and not matches(raw, v, sources)
    ]
    return GroundingResult(ok=not unmatched, numbers=[r for r, _ in numbers], unmatched=unmatched)
