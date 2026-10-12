"""Template and model mapping (design doc 12, 14.2, Appendix B).

A mapping says where each fact or KPI goes in a workbook. It is suggested by the workbook
understanding engine, confirmed once per template (or discovered model), and reused for every
company built from it. Rows are located by label, not fixed row number, so inserted rows do not
break a mapping. Each row carries the suggestion's confidence.
Sources: ``xbrl:Element``, ``kpi:name``, or sums like ``xbrl:A + xbrl:B``.
Transforms: ``none``, ``div:N``, ``mul:N``; ``sign: -1`` flips the sign after the transform.
"""

from decimal import Decimal
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator


class PeriodAxis(BaseModel):
    sheet: str
    header_row_label: str = "Period"
    flag_row_label: str = "A/E"
    label_column: int = 1  # column holding row labels (1 = A)


class Units(BaseModel):
    default_transform: str = "none"


class SourceTerm(BaseModel):
    kind: Literal["xbrl", "kpi"]
    key: str
    sign: int = 1


class RowMap(BaseModel):
    source: str
    sheet: str
    row_label: str
    transform: str | None = None
    sign: int = 1
    confidence: float = 1.0

    @field_validator("source")
    @classmethod
    def _check_source(cls, v: str) -> str:
        parse_source(v)
        return v

    def terms(self) -> list[SourceTerm]:
        return parse_source(self.source)


class Driver(BaseModel):
    name: str
    actual_row_label: str
    forecast_sheet: str
    forecast_row_label: str
    actual_sheet: str | None = None  # defaults to period_axis.sheet


class Check(BaseModel):
    sheet: str
    cell_label: str
    expect: float = 0
    tolerance: float = 0.5


class Mapping(BaseModel):
    template: str | None = None
    model: str | None = None
    company: str | None = None  # set for a discovered model; templates serve any company
    version: int = 1
    sectors: list[str] = Field(default_factory=list)
    basis: Literal["consolidated", "standalone"] = "consolidated"
    period_axis: PeriodAxis
    units: Units = Field(default_factory=Units)
    rows: list[RowMap]
    drivers: list[Driver] = Field(default_factory=list)
    checks: list[Check] = Field(default_factory=list)

    @property
    def name(self) -> str:
        return self.template or self.model or "unnamed"

    def low_confidence_rows(self, threshold: float = 0.8) -> list[RowMap]:
        return [r for r in self.rows if r.confidence < threshold]

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.model_dump(exclude_none=True), sort_keys=False)

    @property
    def consolidated(self) -> bool:
        return self.basis == "consolidated"


def parse_source(source: str) -> list[SourceTerm]:
    terms: list[SourceTerm] = []
    for raw in source.replace("-", "+-").split("+"):
        raw = raw.strip()
        if not raw:
            continue
        sign = -1 if raw.startswith("-") else 1
        kind, _, key = raw.lstrip("-").strip().partition(":")
        if kind not in ("xbrl", "kpi") or not key:
            raise ValueError(f"bad source term {raw!r}; expected xbrl:Name or kpi:name")
        terms.append(SourceTerm(kind=kind, key=key.strip(), sign=sign))  # type: ignore[arg-type]
    if not terms:
        raise ValueError("empty source")
    return terms


def apply_transform(value: Decimal, transform: str | None, sign: int = 1) -> Decimal:
    t = (transform or "none").strip()
    if t != "none":
        op, _, arg = t.partition(":")
        if op == "div":
            value = value / Decimal(arg)
        elif op == "mul":
            value = value * Decimal(arg)
        else:
            raise ValueError(f"unknown transform {transform!r}")
    return value * sign


def load_mapping(text: str) -> Mapping:
    return Mapping.model_validate(yaml.safe_load(text))
