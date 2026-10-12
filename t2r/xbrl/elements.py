"""Fixed XBRL vocabulary for results filings (design doc 8.1).

Element names follow the BSE Ind-AS results taxonomy (prefix ``in-bse-fin``). Banking, NBFC and
insurance filers use different element sets; each taxonomy gets its own table here.

PHASE 0: confirm every name below against real instance files (open question 22.1). Names marked
``# verify`` were taken from the taxonomy's conventions, not yet from a sampled file.
"""

# Logical name -> candidate element local-names, first match wins.
INDAS: dict[str, tuple[str, ...]] = {
    "revenue": ("RevenueFromOperations",),
    "other_income": ("OtherIncome",),
    "total_income": ("Income", "TotalIncome"),  # verify
    "total_expenses": ("Expenses", "TotalExpenses"),  # verify
    "finance_costs": ("FinanceCosts",),
    "depreciation": ("DepreciationDepletionAndAmortisationExpense",),  # verify
    "exceptional_items": ("ExceptionalItemsBeforeTax",),  # verify
    "pbt": ("ProfitBeforeTax",),
    "tax": ("TaxExpense",),  # verify
    "pat_continuing": ("ProfitLossForPeriodFromContinuingOperations",),  # verify
    "pat": ("ProfitLossForPeriod",),
    "eps_basic": ("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",),  # verify
    "total_assets": ("Assets",),
    "equity_and_liabilities": ("EquityAndLiabilities",),  # verify
    "total_equity": ("Equity",),  # verify
    "total_liabilities": ("Liabilities",),  # verify
    "borrowings_noncurrent": ("BorrowingsNoncurrent",),
    "cfo": ("CashFlowsFromUsedInOperatingActivities",),
}

# Banks file Schedule-based results (interest earned, provisions, NPAs). Fill in during Phase 0.
BANKING: dict[str, tuple[str, ...]] = {}
NBFC: dict[str, tuple[str, ...]] = {}
INSURANCE: dict[str, tuple[str, ...]] = {}

BY_TAXONOMY = {"indas": INDAS, "banking": BANKING, "nbfc": NBFC, "insurance": INSURANCE}

# Non-numeric facts that describe the filing itself. verify all in Phase 0.
META_ELEMENTS = {
    "symbol": "Symbol",
    "scrip_code": "ScripCode",
    "company_name": "NameOfTheCompany",
    "fy_start": "DateOfStartOfFinancialYear",
    "fy_end": "DateOfEndOfFinancialYear",
    "period_start": "DateOfStartOfReportingPeriod",
    "period_end": "DateOfEndOfReportingPeriod",
    "nature": "NatureOfReportStandaloneConsolidated",
    "audited": "WhetherResultsAreAuditedOrUnaudited",
}


def candidates(logical: str, taxonomy: str = "indas") -> tuple[str, ...]:
    table = BY_TAXONOMY.get(taxonomy) or INDAS
    return table.get(logical) or INDAS.get(logical, ())
