"""Sector KPI templates (design doc 9.2). Units are what the model mapping expects.

Phase 3 builds out three sectors against the golden set; extend the others the same way.
"""

SECTOR_KPIS: dict[str, dict[str, str]] = {
    "nbfc": {
        "aum": "INR crore",
        "gold_loan_aum": "INR crore",
        "disbursements": "INR crore",
        "nim": "percent",
        "cost_of_funds": "percent",
        "yield_on_loans": "percent",
        "gnpa": "percent",
        "nnpa": "percent",
        "stage3_assets": "percent",
        "credit_cost": "percent",
        "capital_adequacy": "percent",
        "branches": "count",
        "gold_tonnage": "tonnes",
    },
    "banking": {
        "advances": "INR crore",
        "deposits": "INR crore",
        "casa_ratio": "percent",
        "nim": "percent",
        "gnpa": "percent",
        "nnpa": "percent",
        "pcr": "percent",
        "credit_cost": "percent",
        "cet1": "percent",
    },
    "consumer": {
        "volume_growth": "percent",
        "same_store_growth": "percent",
        "gross_margin": "percent",
        "ad_spend": "INR crore",
        "stores": "count",
    },
    "industrials": {
        "order_book": "INR crore",
        "order_inflow": "INR crore",
        "capacity_utilisation": "percent",
    },
    "it_services": {
        "cc_revenue_growth": "percent",
        "deal_tcv": "USD million",
        "headcount": "count",
        "attrition": "percent",
        "utilisation": "percent",
    },
}


def kpis_for(sector: str | None) -> dict[str, str]:
    return SECTOR_KPIS.get((sector or "").lower(), {})
