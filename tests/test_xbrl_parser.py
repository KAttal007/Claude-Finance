from datetime import date
from decimal import Decimal

from t2r.xbrl.parser import dims_hash, parse_instance, period_type
from tests.xbrl_factory import q2_instance


def test_contexts_resolved_from_dates_not_ids():
    filing = parse_instance(q2_instance())
    q = filing.get("RevenueFromOperations", end=date(2026, 9, 30), start=date(2026, 7, 1))
    ytd = filing.get("RevenueFromOperations", end=date(2026, 9, 30), start=date(2026, 4, 1))
    assert q is not None and q.value == Decimal("1000000000")
    assert ytd is not None and ytd.value == Decimal("1900000000")
    assert q.decimals == -5 and q.unit == "INR"
    assert period_type(q.period_start, q.period_end) == "Q"
    assert period_type(ytd.period_start, ytd.period_end) == "H"


def test_instants_and_meta():
    filing = parse_instance(q2_instance())
    assets = filing.get("Assets", instant=True)
    assert assets is not None and assets.period_start is None
    assert filing.declared_end == date(2026, 9, 30)
    assert filing.consolidated is True
    assert filing.audited is False
    assert filing.prefix == "in-bse-fin"
    assert filing.taxonomy() == "indas"
    assert filing.meta["symbol"] == "DEMO"


def test_standalone_flag():
    assert parse_instance(q2_instance(nature="Standalone")).consolidated is False


def test_dims_hash_is_order_independent():
    assert dims_hash({"a": "1", "b": "2"}) == dims_hash({"b": "2", "a": "1"})
    assert dims_hash({}) != dims_hash({"a": "1"})


def test_period_type_buckets():
    assert period_type(date(2026, 4, 1), date(2027, 3, 31)) == "FY"
    assert period_type(date(2026, 4, 1), date(2026, 12, 31)) == "9M"
    assert period_type(None, date(2026, 3, 31)) is None


def test_q1_duplicate_contexts_are_deduped():
    from tests.xbrl_factory import q1_instance

    filing = parse_instance(q1_instance())
    revenue = [f for f in filing.facts if f.element == "RevenueFromOperations"]
    assert len(revenue) == 1
    assert not filing.warnings
