from jevplays.brain.buckets import hp_bucket, power_bucket, pp_bucket


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
