"""Tools exposed to the model (design doc 11.2). Every number the model may state must come from
one of these; the grounding check verifies it afterwards."""

import json
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from t2r.db.models import Company, Fact, Kpi, Price
from t2r.genai.calc import CalcError, calc


def _tool(
    name: str, description: str, properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


_STR_LIST = {"type": "array", "items": {"type": "string"}}

TOOL_DEFS: list[dict[str, Any]] = [
    _tool(
        "get_facts",
        "Reported XBRL facts (full INR) with source references.",
        {
            "company": {"type": "string", "description": "NSE symbol"},
            "elements": _STR_LIST,
            "periods": {
                "type": "array",
                "items": {"type": "string"},
                "description": "period end dates YYYY-MM-DD",
            },
        },
        ["company", "elements", "periods"],
    ),
    _tool(
        "get_kpis",
        "AI-extracted sector KPIs with page references and confidence.",
        {"company": {"type": "string"}, "names": _STR_LIST, "periods": _STR_LIST},
        ["company", "names", "periods"],
    ),
    _tool(
        "get_model_values",
        "Values and estimates from the analyst's Excel model.",
        {"model_id": {"type": "integer"}, "ranges": _STR_LIST},
        ["model_id", "ranges"],
    ),
    _tool(
        "search_filings",
        "Text chunks from the company's filings with document and page.",
        {"company": {"type": "string"}, "query": {"type": "string"}, "k": {"type": "integer"}},
        ["company", "query", "k"],
    ),
    _tool(
        "get_prices",
        "Daily close and market cap.",
        {"company": {"type": "string"}, "from": {"type": "string"}, "to": {"type": "string"}},
        ["company", "from", "to"],
    ),
    _tool(
        "calc",
        "Deterministic arithmetic: growth, margins, variances. Use for every derived "
        "number. Example: expression='(a-b)/b*100', "
        "inputs=[{'name': 'a', 'value': 120}, {'name': 'b', 'value': 100}].",
        {
            "expression": {"type": "string"},
            "inputs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "value"],
                    "properties": {"name": {"type": "string"}, "value": {"type": "number"}},
                },
            },
        },
        ["expression", "inputs"],
    ),
]


class ToolExecutor:
    def __init__(self, session: Session, model_reader: Any = None, embedder: Any = None) -> None:
        self.session = session
        self.model_reader = model_reader  # callable(model_id, ranges) -> dict
        self.embedder = embedder

    def run(self, name: str, args: dict[str, Any]) -> Any:
        handler = getattr(self, f"_t_{name}", None)
        if handler is None:
            raise ValueError(f"unknown tool {name}")
        return handler(**args)

    def _company(self, symbol: str) -> Company:
        c = self.session.scalar(select(Company).where(Company.nse_symbol == symbol.upper()))
        if c is None:
            raise ValueError(f"unknown company {symbol}")
        return c

    def _t_get_facts(self, company: str, elements: list[str], periods: list[str]) -> list[dict]:
        c = self._company(company)
        rows = self.session.scalars(
            select(Fact).where(
                Fact.company_id == c.id,
                Fact.element.in_(elements),
                Fact.is_latest,
                Fact.period_end.in_([date.fromisoformat(p) for p in periods]),
                Fact.dimensions == {},
            )
        )
        return [
            {
                "element": f.element,
                "period_start": str(f.period_start or ""),
                "period_end": str(f.period_end),
                "consolidated": f.consolidated,
                "value": str(f.value),
                "unit": f.unit,
                "source": f"fact:{f.id} filing:{f.filing_id} context:{f.context_ref}",
            }
            for f in rows
        ]

    def _t_get_kpis(self, company: str, names: list[str], periods: list[str]) -> list[dict]:
        c = self._company(company)
        rows = self.session.scalars(
            select(Kpi).where(
                Kpi.company_id == c.id,
                Kpi.name.in_(names),
                Kpi.period_end.in_([date.fromisoformat(p) for p in periods]),
            )
        )
        return [
            {
                "name": k.name,
                "period_end": str(k.period_end),
                "value": str(k.value),
                "unit": k.unit,
                "page": k.page,
                "confidence": str(k.confidence),
                "source": f"kpi:{k.id} filing:{k.filing_id} page:{k.page}",
            }
            for k in rows
        ]

    def _t_get_model_values(self, model_id: int, ranges: list[str]) -> dict:
        if self.model_reader is None:
            raise ValueError("model values unavailable: no model reader configured")
        return self.model_reader(model_id, ranges)

    def _t_search_filings(self, company: str, query: str, k: int) -> list[dict]:
        from t2r.genai.qa import hybrid_search

        return hybrid_search(
            self.session, self._company(company).id, query, min(k, 20), self.embedder
        )

    def _t_get_prices(self, company: str, **period: str) -> list[dict]:
        c = self._company(company)
        start, end = date.fromisoformat(period["from"]), date.fromisoformat(period["to"])
        rows = self.session.scalars(
            select(Price)
            .where(Price.company_id == c.id, Price.trade_date.between(start, end))
            .order_by(Price.trade_date)
        )
        return [
            {
                "date": str(p.trade_date),
                "close": str(p.close),
                "market_cap": str(p.market_cap) if p.market_cap else None,
            }
            for p in rows
        ]

    def _t_calc(self, expression: str, inputs: list[dict[str, Any]]) -> dict:
        try:
            values = {i["name"]: i["value"] for i in inputs}
            return {"expression": expression, "result": str(calc(expression, values))}
        except CalcError as exc:
            return {"error": str(exc)}


def to_json(value: Any) -> str:
    return json.dumps(value, default=lambda o: str(o) if isinstance(o, Decimal | date) else o)
