from jevplays.brain.buckets import (
    hp_bucket,
    money_bucket,
    power_bucket,
    pp_bucket,
    quantity_bucket,
    readiness_bucket,
)


def test_hp_buckets_follow_the_spec_thresholds():
    assert hp_bucket(19, 19) == "full"
    assert hp_bucket(12, 19) == "healthy"  # 63%
    assert hp_bucket(8, 19) == "hurt"  # 42%
    assert hp_bucket(3, 19) == "low"  # 15%
    assert hp_bucket(1, 19) == "critical"
    assert hp_bucket(0, 0) == "critical"


def test_pp_and_power_buckets():
    assert pp_bucket(0) == "out" and pp_bucket(5) == "low" and pp_bucket(6) == "plenty"
    assert (
        power_bucket(0) == "none"
        and power_bucket(40) == "weak"
        and power_bucket(60) == "medium"
        and power_bucket(80) == "strong"
    )


def test_money_bucket_follows_the_spec_thresholds():
    assert money_bucket(0) == "broke" and money_bucket(499) == "broke"
    assert money_bucket(500) == "some" and money_bucket(1999) == "some"
    assert money_bucket(2000) == "comfortable" and money_bucket(9999) == "comfortable"
    assert money_bucket(10000) == "rich"


def test_quantity_bucket_follows_the_spec_thresholds():
    assert quantity_bucket(0) == "none"
    assert quantity_bucket(1) == "few" and quantity_bucket(3) == "few"
    assert quantity_bucket(4) == "plenty"


def test_readiness_bucket_compares_the_lead_with_what_the_milestone_expects():
    """#42: four runs walked into the Pewter Gym at levels 9 to 12 and lost ten battles between
    them, because nothing in what Jev sees says a level-9 lead is not ready for a level-14 Onix.
    The comparison is code's to make; the word is what Jev judges with."""
    assert readiness_bucket(9, 14) == "outmatched"
    assert readiness_bucket(12, 14) == "close"
    assert readiness_bucket(14, 14) == "ready"
    assert readiness_bucket(18, 14) == "ready"


def test_readiness_bucket_has_no_opinion_without_an_expectation():
    assert readiness_bucket(9, None) is None
