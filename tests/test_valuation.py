"""The house valuation rule — spike cap and fade detector, on the cases that
taught them (Oct 2026)."""
from strategy.market_scan import window
from strategy.valuation import MARGIN, value_months

# HKSN_SLR_ALL->ANCHOR_ALL PeakWD OPT, Sep25..Jun26 monthly payouts
HKSN = [0.08, 0.01, 0.02, 0.11, 0.94, 0.01, 0.03, 0.40, 0.02, 0.10]
# NBOHR_RN->RRANCHES_ALL Off-peak OBL: fat to June, then collapsed
NBOHR_FIT = [27.72, 21.55, 26.90, 25.39, 16.23, 9.82, 15.14, 12.72, 10.38, 9.89]
NBOHR_TAIL = [0.22, 0.19]


def test_spike_cap_prices_the_typical_month_not_the_mean():
    v = value_months(HKSN)
    assert v is not None
    assert v.typical <= v.median_month < v.mean_month
    # the limit is beaten in at least half the fitted months, by construction
    assert v.beat_rate >= 0.5
    # the old mean-based limit (mean / 1.5) was beaten in under a third
    old_limit = v.mean_month / MARGIN
    assert sum(1 for x in HKSN if x >= old_limit) / len(HKSN) < 0.34
    assert any(r.startswith("spike") for r in v.reasons)


def test_fade_detector_reads_the_held_out_tail():
    # without the tail the fitted months look healthy
    assert not value_months(NBOHR_FIT).fading
    # the two settled months after the window collapsed -> removed
    v = value_months(NBOHR_FIT, NBOHR_TAIL)
    assert v.fading
    assert any("collapse" in r for r in v.reasons)


def test_one_bad_month_is_not_a_collapse():
    assert not value_months(NBOHR_FIT, [0.22, 14.0]).fading


def test_tail_never_prices_a_path():
    # a fat tail cannot raise the value above the fitted typical month
    base = value_months(NBOHR_FIT)
    assert value_months(NBOHR_FIT, [80.0, 90.0]).typical == base.typical


def test_thin_history_is_not_valued():
    assert value_months([1.0, 2.0, 3.0]) is None


def test_target_month_caps_a_seasonal_path():
    assert value_months(NBOHR_FIT, target=[4.0]).typical == 4.0


def test_window_reproduces_the_october_run_and_derives_november():
    oct_ = window("2026-10")
    assert oct_["fit_tags"] == ["oct24", "sep25", "oct25", "nov25", "dec25", "jan26",
                                "feb26", "mar26", "apr26", "may26", "jun26"]
    assert oct_["tail_tags"] == ["jul26", "aug26"]
    nov = window("2026-11")
    assert nov["fit_tags"][0] == "nov24" and nov["fit_tags"][-1] == "jul26"
    assert nov["tail_months"] == ["2026-08", "2026-09"]
    assert nov["target_months"] == ["2024-11", "2025-11"]
    assert (nov["window_start"], nov["window_end"]) == ("2025-10-01", "2026-08-01")
    assert window("2027-01")["tail_months"] == ["2026-10", "2026-11"]
