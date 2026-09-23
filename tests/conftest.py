import pytest

from hydroponics import Bench, BenchGroup, DesignInputs, Greenhouse, HydraulicSettings


@pytest.fixture
def grow_bench() -> Bench:
    return Bench(12, 1.8, 8, "PS85")


@pytest.fixture
def nursery_bench() -> Bench:
    return Bench(12, 1.8, 18, "PS55")


@pytest.fixture
def reference_inputs(grow_bench: Bench, nursery_bench: Bench) -> DesignInputs:
    """The 51 x 48 m greenhouse from the original notebook."""
    return DesignInputs(
        greenhouse=Greenhouse(51, 48, bay_width_m=8, benches_per_bay=3, sectors=5),
        benches=(
            BenchGroup(grow_bench, 61, "grow-out"),
            BenchGroup(nursery_bench, 11, "nursery"),
        ),
        hydraulics=HydraulicSettings(terrain_slope_pct=6.0),
    )
