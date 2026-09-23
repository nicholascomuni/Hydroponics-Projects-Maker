import pytest

from hydroponics import Bench, BenchGroup, ChannelProfile, DesignError, Greenhouse, plan_layout


def test_bench_geometry(grow_bench, nursery_bench):
    # 8 channels x 12 m / 6 m bars x 23 holes = 368 plant sites
    assert grow_bench.plant_sites == 368
    assert nursery_bench.plant_sites == 18 * 2 * 58
    assert grow_bench.channel_bars == 16
    # (180 - 8 * 5.5) / 7 + 5.5
    assert grow_bench.channel_spacing_cm == pytest.approx(24.93, abs=0.01)


def test_custom_profile():
    profile = ChannelProfile("X100", holes_per_channel=24, channel_length_m=4, width_cm=10)
    bench = Bench(8, 1.0, 4, profile)
    assert bench.plant_sites == 4 * 8 * 6
    assert profile.hole_spacing_cm == pytest.approx(16.67, abs=0.01)


def test_reference_layout_counts(reference_inputs):
    layout = plan_layout(reference_inputs.greenhouse, reference_inputs.benches)
    gh = reference_inputs.greenhouse
    assert gh.bays == 6
    assert gh.bench_rows == 18
    assert layout.total_benches == 72
    assert layout.bench_rows_used == 18  # 4 benches of 12 m per 51 m row
    assert layout.total_channels == 61 * 8 + 11 * 18
    assert layout.laterals == 24
    assert layout.laterals_per_sector == 5
    assert layout.aisle_width_m == pytest.approx(0.8667, abs=1e-3)
    assert layout.plant_sites == {"grow-out": 22448, "nursery": 22968}


def test_single_bay_has_outer_aisles():
    gh = Greenhouse(20, 8, bay_width_m=8, benches_per_bay=3)
    assert gh.aisle_width(1.8) == pytest.approx((8 - 5.4) / 4)


def test_plant_sites_aggregate_by_crop(grow_bench):
    layout = plan_layout(
        Greenhouse(51, 48),
        [BenchGroup(grow_bench, 10, "lettuce"), BenchGroup(grow_bench, 5, "lettuce")],
    )
    assert layout.plant_sites == {"lettuce": 15 * 368}


@pytest.mark.parametrize(
    ("greenhouse", "count", "match"),
    [
        (Greenhouse(51, 48, benches_per_bay=4), 10, "below the minimum"),
        (Greenhouse(51, 48, benches_per_bay=5), 10, "do not fit"),
        (Greenhouse(51, 48), 73, "bench rows"),
        (Greenhouse(10, 48), 1, "does not fit"),
    ],
)
def test_layout_validation_errors(grow_bench, greenhouse, count, match):
    with pytest.raises(DesignError, match=match):
        plan_layout(greenhouse, [BenchGroup(grow_bench, count)])


def test_min_aisle_is_configurable(grow_bench):
    # 4 benches of 1.8 m in an 8 m bay leave 0.2 m aisles
    gh = Greenhouse(51, 48, benches_per_bay=4, min_aisle_width_m=0.2)
    assert plan_layout(gh, [BenchGroup(grow_bench, 10)]).aisle_width_m == pytest.approx(0.2)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"length_m": 0, "width_m": 10},
        {"length_m": 10, "width_m": 5, "bay_width_m": 8},
        {"length_m": 10, "width_m": 10, "sectors": 0},
        {"length_m": 10, "width_m": 10, "benches_per_bay": 0},
    ],
)
def test_invalid_greenhouse(kwargs):
    with pytest.raises(DesignError):
        Greenhouse(**kwargs)


def test_invalid_benches():
    with pytest.raises(DesignError, match="at least 2 channels"):
        Bench(12, 1.8, 1, "PS85")
    with pytest.raises(DesignError, match="do not fit"):
        Bench(12, 0.5, 10, "PS85")
    with pytest.raises(DesignError, match="Unknown channel profile"):
        Bench(12, 1.8, 8, "PS99")
    with pytest.raises(DesignError):
        BenchGroup(Bench(12, 1.8, 8, "PS85"), 0)
    with pytest.raises(DesignError, match="At least one"):
        plan_layout(Greenhouse(51, 48), [])
