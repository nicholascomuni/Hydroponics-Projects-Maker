import itertools
import math

import pytest

from hydroponics.errors import DesignError
from hydroponics.hydraulics import (
    PipeSegment,
    christiansen_factor,
    flow_velocity,
    hazen_williams_head_loss,
    inner_diameter_mm,
    smallest_pipe_for_velocity,
)


def test_hazen_williams_matches_hand_computed_reference():
    # 100 m of DN50 PVC (ID 44 mm), 10 m³/h, C = 140, worked by hand:
    #   Q = 10 / 3600 = 2.7778e-3 m³/s
    #   (Q / C)^1.852 = (1.98413e-5)^1.852 = 1.95486e-9
    #   D^4.87       = 0.044^4.87          = 2.47533e-7
    #   hf = 10.646 * 100 * 1.95486e-9 / 2.47533e-7 = 8.4075 m
    assert hazen_williams_head_loss(100, 10, 44.0, c=140) == pytest.approx(8.4075, rel=1e-4)


def test_hazen_williams_scaling_laws():
    base = hazen_williams_head_loss(50, 5, 27.8)
    assert hazen_williams_head_loss(100, 5, 27.8) == pytest.approx(2 * base)
    assert hazen_williams_head_loss(50, 10, 27.8) == pytest.approx(base * 2**1.852)
    assert hazen_williams_head_loss(50, 5, 2 * 27.8) == pytest.approx(base / 2**4.87)
    # rougher pipe (lower C) loses more head
    assert hazen_williams_head_loss(50, 5, 27.8, c=100) > base


def test_zero_flow_has_no_loss():
    assert hazen_williams_head_loss(100, 0, 44.0) == 0


@pytest.mark.parametrize(
    ("outlets", "expected"),
    # Published Christiansen table for m = 1.852
    [(1, 1.0045), (2, 0.639), (5, 0.457), (10, 0.402), (20, 0.376), (100, 0.356)],
)
def test_christiansen_factor_table(outlets, expected):
    assert christiansen_factor(outlets) == pytest.approx(expected, abs=1e-3)


def test_christiansen_factor_limit_and_monotonic():
    values = [christiansen_factor(n) for n in range(1, 50)]
    assert all(a > b for a, b in itertools.pairwise(values))
    assert christiansen_factor(100_000) == pytest.approx(1 / 2.852, abs=1e-5)


def test_christiansen_factor_rejects_zero_outlets():
    with pytest.raises(DesignError):
        christiansen_factor(0)


def test_flow_velocity():
    # 16.052 m³/h through 44 mm ID -> 2.93 m/s
    assert flow_velocity(16.052, 44.0) == pytest.approx(2.9325, abs=1e-3)
    area = math.pi * 0.05**2 / 4
    assert flow_velocity(3.6, 50.0) == pytest.approx(0.001 / area)


def test_pipe_segment_applies_christiansen_factor():
    plain = PipeSegment("plain", 51, 16.0, 50)
    manifold = PipeSegment("manifold", 51, 16.0, 50, outlets=5)
    assert manifold.head_loss_m == pytest.approx(plain.head_loss_m * christiansen_factor(5))
    assert plain.inner_diameter_mm == 44.0


def test_unknown_pipe_size():
    with pytest.raises(DesignError, match="Unknown PVC pipe size"):
        inner_diameter_mm(63)


def test_smallest_pipe_for_velocity():
    assert smallest_pipe_for_velocity(16.052, 2.0) == 60
    assert smallest_pipe_for_velocity(16.052, 1.5) == 75
    assert smallest_pipe_for_velocity(10_000, 2.0) is None
