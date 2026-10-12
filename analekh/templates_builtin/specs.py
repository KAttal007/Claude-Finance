"""Built-in template specs (design doc 15.2, Phase 2): NBFC, and manufacturing/consumer.

Quarterly results XBRL carries the P&L, so these are quarterly P&L models with sector KPIs; the
balance sheet and cash flow sections land with annual-report backfill (PHASE 2).
"""

from analekh.templates_builtin.base import DriverSpec, Line, TemplateSpec

REV = "Revenue from operations"
OI = "Other income"
TI = "Total income"
FC = "Finance costs"
EMP = "Employee benefit expense"
OTH = "Other expenses"
TE = "Total expenses"
PBT = "Profit before tax"
TAX = "Tax expense"
PAT = "Profit after tax"

NBFC = TemplateSpec(
    key="nbfc_quarterly",
    name="NBFC quarterly model (built-in)",
    sectors=["NBFC", "Gold Finance", "Housing Finance", "Vehicle Finance"],
    lines=[
        Line(
            REV,
            "xbrl:RevenueFromOperations",
            "input",
            "=ROUND({p}[[" + REV + "]]*(1+Drivers!{c}{{Revenue growth (QoQ)}}),2)",
        ),
        Line(OI, "xbrl:OtherIncome", "input", "={p}[[" + OI + "]]"),
        Line(
            TI,
            None,
            "={c}[[" + REV + "]]+{c}[[" + OI + "]]",
            "={c}[[" + REV + "]]+{c}[[" + OI + "]]",
        ),
        Line(
            FC,
            "xbrl:FinanceCosts",
            "input",
            "=ROUND({c}[[" + REV + "]]*Drivers!{c}{{Finance costs / revenue}},2)",
        ),
        Line(
            EMP,
            "xbrl:EmployeeBenefitExpense",
            "input",
            "=ROUND({c}[[" + REV + "]]*Drivers!{c}{{Employee costs / revenue}},2)",
        ),
        Line(
            OTH,
            "xbrl:OtherExpenses",
            "input",
            "=ROUND({c}[[" + REV + "]]*Drivers!{c}{{Other expenses / revenue}},2)",
        ),
        Line(
            TE, "xbrl:Expenses", "input", "={c}[[" + FC + "]]+{c}[[" + EMP + "]]+{c}[[" + OTH + "]]"
        ),
        Line(
            PBT,
            None,
            "={c}[[" + TI + "]]-{c}[[" + TE + "]]",
            "={c}[[" + TI + "]]-{c}[[" + TE + "]]",
        ),
        Line(
            TAX, "xbrl:TaxExpense", "input", "=ROUND({c}[[" + PBT + "]]*Drivers!{c}{{Tax rate}},2)"
        ),
        Line(PAT, "xbrl:ProfitLossForPeriod", "input", "={c}[[" + PBT + "]]-{c}[[" + TAX + "]]"),
    ],
    drivers=[
        DriverSpec("Revenue growth (QoQ)", "revenue_growth", 0.0, REV, "growth"),
        DriverSpec("Finance costs / revenue", "finance_cost_ratio", 0.0, FC, "ratio_to_revenue"),
        DriverSpec("Employee costs / revenue", "employee_ratio", 0.0, EMP, "ratio_to_revenue"),
        DriverSpec("Other expenses / revenue", "other_exp_ratio", 0.0, OTH, "ratio_to_revenue"),
        DriverSpec("Tax rate", "tax_rate", 0.0, TAX, "tax_rate"),
    ],
    checks=[
        (
            "Total income difference",
            "=ROUND(Data!{c}[[" + TI + "]]-(Data!{c}[[" + REV + "]]+Data!{c}[[" + OI + "]]),2)",
        ),
        (
            "PAT difference",
            "=ROUND(Data!{c}[[" + PBT + "]]-Data!{c}[[" + TAX + "]]-Data!{c}[[" + PAT + "]],2)",
        ),
    ],
    kpi_lines=[
        Line("Gold loan AUM", "kpi:gold_loan_aum", "input", "", transform="none"),
        Line("AUM", "kpi:aum", "input", "", transform="none"),
        Line("Yield on loans", "kpi:yield_on_loans", "input", "", transform="none"),
        Line("Cost of funds", "kpi:cost_of_funds", "input", "", transform="none"),
        Line("GNPA", "kpi:gnpa", "input", "", transform="none"),
        Line("NNPA", "kpi:nnpa", "input", "", transform="none"),
    ],
    valuation=[
        ("Valuation (P/B versus ROE)", None),
        ("Cost of equity", None),
        ("Terminal growth", None),
        ("Forward ROE", None),
        ("Justified P/B", "=IFERROR((B4-B3)/(B2-B3),0)"),
        ("Book value per share", None),
    ],
)

CONSUMER = TemplateSpec(
    key="consumer_quarterly",
    name="Manufacturing / consumer quarterly model (built-in)",
    sectors=["Consumer", "FMCG", "Manufacturing", "Industrials", "Auto"],
    lines=[
        Line(
            REV,
            "xbrl:RevenueFromOperations",
            "input",
            "=ROUND({p}[[" + REV + "]]*(1+Drivers!{c}{{Revenue growth (QoQ)}}),2)",
        ),
        Line(OI, "xbrl:OtherIncome", "input", "={p}[[" + OI + "]]"),
        Line(
            "Cost of materials consumed",
            "xbrl:CostOfMaterialsConsumed",
            "input",
            "=ROUND({c}[[" + REV + "]]*Drivers!{c}{{Material cost / revenue}},2)",
        ),
        Line(
            EMP,
            "xbrl:EmployeeBenefitExpense",
            "input",
            "=ROUND({c}[[" + REV + "]]*Drivers!{c}{{Employee costs / revenue}},2)",
        ),
        Line(
            OTH,
            "xbrl:OtherExpenses",
            "input",
            "=ROUND({c}[[" + REV + "]]*Drivers!{c}{{Other expenses / revenue}},2)",
        ),
        Line(
            "EBITDA",
            None,
            "={c}[["
            + REV
            + "]]-{c}[[Cost of materials consumed]]-{c}[["
            + EMP
            + "]]-{c}[["
            + OTH
            + "]]",
            "={c}[["
            + REV
            + "]]-{c}[[Cost of materials consumed]]-{c}[["
            + EMP
            + "]]-{c}[["
            + OTH
            + "]]",
        ),
        Line(
            "Depreciation and amortisation",
            "xbrl:DepreciationDepletionAndAmortisationExpense",
            "input",
            "={p}[[Depreciation and amortisation]]",
        ),
        Line(FC, "xbrl:FinanceCosts", "input", "={p}[[" + FC + "]]"),
        Line(
            PBT,
            "xbrl:ProfitBeforeTax",
            "input",
            "={c}[[EBITDA]]+{c}[["
            + OI
            + "]]-{c}[[Depreciation and amortisation]]-{c}[["
            + FC
            + "]]",
        ),
        Line(
            TAX, "xbrl:TaxExpense", "input", "=ROUND({c}[[" + PBT + "]]*Drivers!{c}{{Tax rate}},2)"
        ),
        Line(PAT, "xbrl:ProfitLossForPeriod", "input", "={c}[[" + PBT + "]]-{c}[[" + TAX + "]]"),
    ],
    drivers=[
        DriverSpec("Revenue growth (QoQ)", "revenue_growth", 0.0, REV, "growth"),
        DriverSpec(
            "Material cost / revenue",
            "material_ratio",
            0.0,
            "Cost of materials consumed",
            "ratio_to_revenue",
        ),
        DriverSpec("Employee costs / revenue", "employee_ratio", 0.0, EMP, "ratio_to_revenue"),
        DriverSpec("Other expenses / revenue", "other_exp_ratio", 0.0, OTH, "ratio_to_revenue"),
        DriverSpec("Tax rate", "tax_rate", 0.0, TAX, "tax_rate"),
    ],
    checks=[
        (
            "PAT difference",
            "=ROUND(Data!{c}[[" + PBT + "]]-Data!{c}[[" + TAX + "]]-Data!{c}[[" + PAT + "]],2)",
        ),
    ],
    kpi_lines=[
        Line("Volume growth", "kpi:volume_growth", "input", "", transform="none"),
        Line("Gross margin", "kpi:gross_margin", "input", "", transform="none"),
    ],
    valuation=[
        ("Valuation (DCF and relative)", None),
        ("Cost of capital", None),
        ("Terminal growth", None),
        ("Forward EPS", None),
    ],
)

BUILTIN = {s.key: s for s in (NBFC, CONSUMER)}
