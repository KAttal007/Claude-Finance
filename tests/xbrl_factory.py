"""Builds SYNTHETIC XBRL instances shaped like BSE Ind-AS results files (in-bse-fin prefix,
OneD/FourD/OneI style contexts). Numbers are made up and internally consistent; they are not any
company's results. Replace with real files in tests/fixtures/real/ during the Phase 0 spike.
"""

from datetime import date

NS = "http://www.bseindia.com/xbrl/fin/2020-03-31/in-bse-fin"


def build_instance(
    *,
    q_start: date,
    q_end: date,
    ytd_start: date,
    values_q: dict[str, int],
    values_ytd: dict[str, int] | None = None,
    values_instant: dict[str, int] | None = None,
    declared_end: date | None = None,
    nature: str = "Consolidated",
    decimals: str = "-5",
) -> bytes:
    declared_end = declared_end or q_end
    contexts = [
        _ctx(
            "OneD",
            f"<xbrli:startDate>{q_start}</xbrli:startDate><xbrli:endDate>{q_end}</xbrli:endDate>",
        ),
        _ctx(
            "FourD",
            f"<xbrli:startDate>{ytd_start}</xbrli:startDate><xbrli:endDate>{q_end}</xbrli:endDate>",
        ),
        _ctx("OneI", f"<xbrli:instant>{q_end}</xbrli:instant>"),
    ]
    facts = [
        '<in-bse-fin:Symbol contextRef="OneD">DEMO</in-bse-fin:Symbol>',
        f'<in-bse-fin:DateOfStartOfReportingPeriod contextRef="OneD">{q_start}'
        f"</in-bse-fin:DateOfStartOfReportingPeriod>",
        f'<in-bse-fin:DateOfEndOfReportingPeriod contextRef="OneD">{declared_end}'
        f"</in-bse-fin:DateOfEndOfReportingPeriod>",
        f'<in-bse-fin:NatureOfReportStandaloneConsolidated contextRef="OneD">{nature}'
        f"</in-bse-fin:NatureOfReportStandaloneConsolidated>",
        '<in-bse-fin:WhetherResultsAreAuditedOrUnaudited contextRef="OneD">Unaudited'
        "</in-bse-fin:WhetherResultsAreAuditedOrUnaudited>",
    ]
    for ctx, values in (
        ("OneD", values_q),
        ("FourD", values_ytd or values_q),
        ("OneI", values_instant or {}),
    ):
        for name, value in values.items():
            facts.append(
                f'<in-bse-fin:{name} contextRef="{ctx}" unitRef="INR" '
                f'decimals="{decimals}">{value}</in-bse-fin:{name}>'
            )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
  xmlns:link="http://www.xbrl.org/2003/linkbase"
  xmlns:xlink="http://www.w3.org/1999/xlink"
  xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
  xmlns:in-bse-fin="{NS}">
  <link:schemaRef xlink:type="simple"
    xlink:href="http://www.bseindia.com/xbrl/fin/2020-03-31/in-bse-fin/Ind-AS_entry_point_2020-03-31.xsd"/>
  {"".join(contexts)}
  <xbrli:unit id="INR"><xbrli:measure>iso4217:INR</xbrli:measure></xbrli:unit>
  {"".join(facts)}
</xbrli:xbrl>""".encode()


def _ctx(cid: str, period: str) -> str:
    return (
        f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier '
        f'scheme="http://www.bseindia.com">999999</xbrli:identifier></xbrli:entity>'
        f"<xbrli:period>{period}</xbrli:period></xbrli:context>"
    )


def pnl(revenue: int, other: int, expenses: int, tax: int) -> dict[str, int]:
    income = revenue + other
    pbt = income - expenses
    return {
        "RevenueFromOperations": revenue,
        "OtherIncome": other,
        "Income": income,
        "Expenses": expenses,
        "ProfitBeforeTax": pbt,
        "TaxExpense": tax,
        "ProfitLossForPeriod": pbt - tax,
    }


Q1 = dict(q_start=date(2026, 4, 1), q_end=date(2026, 6, 30), ytd_start=date(2026, 4, 1))
Q2 = dict(q_start=date(2026, 7, 1), q_end=date(2026, 9, 30), ytd_start=date(2026, 4, 1))
BS = {"Assets": 5_000_000_000, "EquityAndLiabilities": 5_000_000_000}


def q1_instance() -> bytes:
    return build_instance(
        **Q1, values_q=pnl(900_000_000, 40_000_000, 720_000_000, 55_000_000), values_instant=BS
    )


def q2_instance(revenue: int = 1_000_000_000, **kw) -> bytes:
    q = pnl(revenue, 50_000_000, 800_000_000, 62_500_000)
    q1 = pnl(900_000_000, 40_000_000, 720_000_000, 55_000_000)
    ytd = {k: q[k] + q1[k] for k in q}
    return build_instance(**Q2, values_q=q, values_ytd=ytd, values_instant=BS, **kw)
