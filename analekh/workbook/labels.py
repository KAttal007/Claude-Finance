"""Row labels to standard fields (design doc 12): synonym dictionary first, fuzzy match second,
AI only for what is still ambiguous. Every suggestion carries a confidence score; the user
confirms the mapping once per template or model.

Standard fields map to mapping sources (xbrl:Element or kpi:name). Element names follow
analekh.xbrl.elements; PHASE 0 confirms them against real filings.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from rapidfuzz import fuzz, process

# field -> (mapping source, synonyms). Keep synonyms lowercase and punctuation-free.
STANDARD_FIELDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "revenue": (
        "xbrl:RevenueFromOperations",
        (
            "revenue from operations",
            "revenue",
            "net sales",
            "sales",
            "income from operations",
            "total revenue from operations",
            "net revenue",
            "turnover",
            "operating revenue",
        ),
    ),
    "other_income": ("xbrl:OtherIncome", ("other income", "non operating income")),
    "total_income": ("xbrl:Income", ("total income", "total revenue")),
    "total_expenses": ("xbrl:Expenses", ("total expenses", "total expenditure")),
    "finance_costs": (
        "xbrl:FinanceCosts",
        (
            "finance costs",
            "finance cost",
            "interest expense",
            "interest expenses",
            "interest and finance charges",
            "borrowing costs",
            "interest",
        ),
    ),
    "depreciation": (
        "xbrl:DepreciationDepletionAndAmortisationExpense",
        (
            "depreciation",
            "depreciation and amortisation",
            "depreciation and amortization",
            "d and a",
            "depreciation amortisation and impairment",
        ),
    ),
    "employee_costs": (
        "xbrl:EmployeeBenefitExpense",
        (
            "employee benefit expense",
            "employee benefits expense",
            "employee costs",
            "staff costs",
            "employee expenses",
            "personnel expenses",
        ),
    ),
    "cost_of_materials": (
        "xbrl:CostOfMaterialsConsumed",
        (
            "cost of materials consumed",
            "raw material costs",
            "cogs",
            "cost of goods sold",
            "material cost",
            "raw materials consumed",
        ),
    ),
    "other_expenses": ("xbrl:OtherExpenses", ("other expenses", "other expenditure")),
    "pbt": ("xbrl:ProfitBeforeTax", ("profit before tax", "pbt", "profit before taxes")),
    "tax": (
        "xbrl:TaxExpense",
        ("tax expense", "tax", "total tax expense", "taxes", "provision for tax", "income tax"),
    ),
    "pat": (
        "xbrl:ProfitLossForPeriod",
        (
            "pat",
            "profit after tax",
            "net profit",
            "profit for the period",
            "net income",
            "profit for the year",
            "reported pat",
        ),
    ),
    "eps_basic": (
        "xbrl:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
        ("basic eps", "eps", "eps basic", "earnings per share"),
    ),
    "aum": ("kpi:aum", ("aum", "assets under management", "loan book", "gross loan book")),
    "gold_loan_aum": ("kpi:gold_loan_aum", ("gold loan aum", "gold loan book", "gold loans")),
    "nim": ("kpi:nim", ("nim", "net interest margin")),
    "gnpa": ("kpi:gnpa", ("gnpa", "gross npa", "gnpa ratio", "gross stage 3")),
    "nnpa": ("kpi:nnpa", ("nnpa", "net npa", "nnpa ratio", "net stage 3")),
    "cost_of_funds": ("kpi:cost_of_funds", ("cost of funds", "cof", "cost of borrowing")),
    "yield_on_loans": (
        "kpi:yield_on_loans",
        ("yield on loans", "loan yield", "yield on aum", "yield on advances"),
    ),
}

EXACT_CONFIDENCE = 0.98
FUZZY_FLOOR = 85  # rapidfuzz score below which a label is left for AI or the user


@dataclass(frozen=True)
class LabelMatch:
    label: str
    field: str | None
    source: str | None
    confidence: float
    method: str  # synonym, fuzzy, ai, none


def normalise(label: str) -> str:
    label = label.lower().replace("&", " and ")
    label = re.sub(r"\(.*?\)", " ", label)  # drop "(INR cr)", "(%)"
    label = re.sub(r"[^a-z0-9 ]+", " ", label)
    return " ".join(label.split())


_SYNONYMS: dict[str, str] = {
    syn: field for field, (_, syns) in STANDARD_FIELDS.items() for syn in syns
}

# A callable that resolves ambiguous labels, e.g. a small Claude model; returns (field, conf).
AiResolver = Callable[[str, list[str]], tuple[str | None, float]]


def match_label(label: str, ai: AiResolver | None = None) -> LabelMatch:
    norm = normalise(label)
    if not norm:
        return LabelMatch(label, None, None, 0.0, "none")
    if norm in _SYNONYMS:
        field = _SYNONYMS[norm]
        return LabelMatch(label, field, STANDARD_FIELDS[field][0], EXACT_CONFIDENCE, "synonym")
    best = process.extractOne(norm, list(_SYNONYMS), scorer=fuzz.token_sort_ratio)
    if best and best[1] >= FUZZY_FLOOR:
        field = _SYNONYMS[best[0]]
        conf = round(0.6 + 0.3 * (best[1] - FUZZY_FLOOR) / (100 - FUZZY_FLOOR), 2)
        return LabelMatch(label, field, STANDARD_FIELDS[field][0], conf, "fuzzy")
    if ai is not None:
        ai_field, conf = ai(label, list(STANDARD_FIELDS))
        if ai_field in STANDARD_FIELDS:
            source = STANDARD_FIELDS[ai_field][0]
            return LabelMatch(label, ai_field, source, min(conf, 0.85), "ai")
    return LabelMatch(label, None, None, 0.0, "none")
