"""Fast lxml parser for plain XBRL instance files (design doc 8.1).

Contexts are resolved from their actual start/end/instant dates, never from their ids
(OneD, FourD, OneI ...). Values stay in full INR as filed; display scaling lives in model mappings.
Use Arelle (``pip install .[xbrl]``) when full taxonomy validation is needed.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from lxml import etree

from t2r.xbrl.elements import META_ELEMENTS

XBRLI = "http://www.xbrl.org/2003/instance"
LINK = "http://www.xbrl.org/2003/linkbase"
XLINK = "http://www.w3.org/1999/xlink"
XBRLDI = "http://xbrl.org/2006/xbrldi"


@dataclass(frozen=True)
class Context:
    id: str
    start: date | None
    end: date
    is_instant: bool
    dimensions: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedFact:
    element: str
    period_start: date | None
    period_end: date
    is_instant: bool
    value: Decimal
    unit: str | None
    decimals: int | None
    context_ref: str
    dimensions: dict[str, str]
    dims_hash: str

    @property
    def days(self) -> int | None:
        return None if self.period_start is None else (self.period_end - self.period_start).days + 1


@dataclass
class ParsedFiling:
    schema_ref: str | None
    prefix: str | None
    facts: list[ParsedFact]
    meta: dict[str, str]
    warnings: list[str] = field(default_factory=list)

    @property
    def declared_start(self) -> date | None:
        return _date_or_none(self.meta.get("period_start"))

    @property
    def declared_end(self) -> date | None:
        return _date_or_none(self.meta.get("period_end"))

    @property
    def consolidated(self) -> bool | None:
        nature = self.meta.get("nature", "").lower()
        if "consolidated" in nature:
            return True
        if "standalone" in nature:
            return False
        return None

    @property
    def audited(self) -> bool | None:
        audited = self.meta.get("audited", "").lower()
        if not audited:
            return None
        return audited.startswith("audited")

    def taxonomy(self) -> str:
        """Best guess of results_taxonomy from the schema reference (confirmed per company)."""
        ref = (self.schema_ref or "").lower()
        if "bank" in ref:
            return "banking"
        if "nbfc" in ref:
            return "nbfc"
        if "insurance" in ref:
            return "insurance"
        return "indas"

    def get(
        self,
        element: str,
        *,
        end: date | None = None,
        start: date | None = None,
        instant: bool | None = None,
    ) -> ParsedFact | None:
        """First non-dimensional fact matching element and (optionally) period."""
        for f in self.facts:
            if f.element != element or f.dimensions:
                continue
            if end is not None and f.period_end != end:
                continue
            if start is not None and f.period_start != start:
                continue
            if instant is not None and f.is_instant != instant:
                continue
            return f
        return None


def period_type(start: date | None, end: date) -> str | None:
    """Q, H, 9M or FY from a duration's length."""
    if start is None:
        return None
    days = (end - start).days + 1
    for label, lo, hi in (("Q", 80, 100), ("H", 170, 190), ("9M", 260, 280), ("FY", 355, 370)):
        if lo <= days <= hi:
            return label
    return None


def dims_hash(dimensions: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(dimensions, sort_keys=True).encode()).hexdigest()


def parse_instance(data: bytes) -> ParsedFiling:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    root = etree.fromstring(data, parser)

    schema_ref = None
    sref = root.find(f"{{{LINK}}}schemaRef")
    if sref is not None:
        schema_ref = sref.get(f"{{{XLINK}}}href")

    contexts = {c.id: c for c in (_parse_context(el) for el in root.iter(f"{{{XBRLI}}}context"))}
    units = {u.get("id"): _unit_label(u) for u in root.iter(f"{{{XBRLI}}}unit")}

    facts: list[ParsedFact] = []
    meta: dict[str, str] = {}
    warnings: list[str] = []
    meta_by_local = {v: k for k, v in META_ELEMENTS.items()}
    prefix: str | None = None

    for el in root:
        if not isinstance(el.tag, str) or el.get("contextRef") is None:
            continue
        qname = etree.QName(el)
        if qname.namespace in (XBRLI, LINK):
            continue
        prefix = prefix or el.prefix
        local = qname.localname
        text = (el.text or "").strip()
        ctx = contexts.get(el.get("contextRef", ""))
        if ctx is None:
            warnings.append(f"{local}: unknown context {el.get('contextRef')}")
            continue

        if el.get("unitRef") is None:
            if local in meta_by_local and text:
                meta.setdefault(meta_by_local[local], text)
            continue
        if el.get("{http://www.w3.org/2001/XMLSchema-instance}nil") == "true" or not text:
            continue
        try:
            value = Decimal(text)
        except InvalidOperation:
            warnings.append(f"{local}: non-numeric value {text!r}")
            continue

        decimals_attr = el.get("decimals")
        decimals = None if decimals_attr in (None, "INF") else int(decimals_attr)
        facts.append(
            ParsedFact(
                element=local,
                period_start=ctx.start,
                period_end=ctx.end,
                is_instant=ctx.is_instant,
                value=value,
                unit=units.get(el.get("unitRef")),
                decimals=decimals,
                context_ref=ctx.id,
                dimensions=ctx.dimensions,
                dims_hash=dims_hash(ctx.dimensions),
            )
        )

    return ParsedFiling(
        schema_ref=schema_ref,
        prefix=prefix,
        facts=_dedupe(facts, warnings),
        meta=meta,
        warnings=warnings,
    )


def _dedupe(facts: list[ParsedFact], warnings: list[str]) -> list[ParsedFact]:
    """Q1 filings report the same period under both quarter and YTD contexts; keep one copy."""
    seen: dict[tuple[object, ...], ParsedFact] = {}
    for f in facts:
        key = (f.element, f.period_start, f.period_end, f.is_instant, f.dims_hash)
        first = seen.get(key)
        if first is None:
            seen[key] = f
        elif first.value != f.value:
            warnings.append(
                f"{f.element}: contexts {first.context_ref} and {f.context_ref} "
                f"disagree ({first.value} vs {f.value}); kept the first"
            )
    return list(seen.values())


def _parse_context(el: etree._Element) -> Context:
    period = el.find(f"{{{XBRLI}}}period")
    if period is None:
        raise ValueError(f"context {el.get('id')} has no period")
    instant = period.findtext(f"{{{XBRLI}}}instant")
    dims = {
        m.get("dimension", ""): (m.text or "").strip()
        for m in el.iter(f"{{{XBRLDI}}}explicitMember", f"{{{XBRLDI}}}typedMember")
    }
    if instant:
        return Context(el.get("id", ""), None, date.fromisoformat(instant.strip()), True, dims)
    start = period.findtext(f"{{{XBRLI}}}startDate") or ""
    end = period.findtext(f"{{{XBRLI}}}endDate") or ""
    return Context(
        el.get("id", ""),
        date.fromisoformat(start.strip()),
        date.fromisoformat(end.strip()),
        False,
        dims,
    )


def _unit_label(el: etree._Element) -> str:
    measures = [m.text.split(":")[-1] for m in el.iter(f"{{{XBRLI}}}measure") if m.text]
    return "/".join(measures)


def _date_or_none(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None
