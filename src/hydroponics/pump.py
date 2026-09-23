"""Pump duty point and motor sizing."""

from __future__ import annotations

from dataclasses import dataclass

from hydroponics.errors import DesignError

WATER_DENSITY_KG_M3 = 1000.0
GRAVITY_M_S2 = 9.81
#: One metric horsepower (cv / PS) in watts. Brazilian pump catalogues use cv.
CV_IN_W = 735.49875

#: Common nominal motor sizes for small centrifugal pumps, in cv.
STANDARD_MOTOR_SIZES_CV: tuple[float, ...] = (
    0.25, 0.33, 0.5, 0.75, 1, 1.5, 2, 3, 4, 5, 6, 7.5, 10, 12.5, 15, 20, 25, 30,
)  # fmt: skip


@dataclass(frozen=True)
class PumpStationSettings:
    """Per-sector pump station assumptions.

    Attributes:
        efficiency: Overall pump efficiency at the duty point (wire-to-water is
            lower; small centrifugal pumps typically reach 0.4-0.7).
        model: Optional commercial model name, only used as the BOM label.
        reservoir_volume_l: Nutrient-solution reservoir volume per sector.
    """

    efficiency: float = 0.6
    model: str | None = None
    reservoir_volume_l: int = 3000

    def __post_init__(self) -> None:
        if not 0 < self.efficiency <= 1:
            raise DesignError("Pump efficiency must be in (0, 1]")
        if self.reservoir_volume_l <= 0:
            raise DesignError("reservoir_volume_l must be positive")


def hydraulic_power_w(flow_m3h: float, head_m: float) -> float:
    """Power transferred to the water: P = ρ·g·Q·H (W)."""
    return WATER_DENSITY_KG_M3 * GRAVITY_M_S2 * (flow_m3h / 3600.0) * head_m


def nominal_motor_size_cv(shaft_power_w: float) -> float:
    """Smallest standard motor size (cv) that covers the shaft power."""
    required_cv = shaft_power_w / CV_IN_W
    for size in STANDARD_MOTOR_SIZES_CV:
        if size >= required_cv:
            return size
    raise DesignError(
        f"Required power {required_cv:.1f} cv exceeds the largest standard size "
        f"({STANDARD_MOTOR_SIZES_CV[-1]} cv); split the greenhouse into more sectors"
    )


@dataclass(frozen=True)
class PumpSelection:
    """Duty point and motor size for one sector's pump."""

    flow_m3h: float
    head_m: float
    efficiency: float
    hydraulic_power_w: float
    shaft_power_w: float
    motor_cv: float
    model: str | None = None

    @property
    def motor_kw(self) -> float:
        return self.motor_cv * CV_IN_W / 1000.0

    @property
    def label(self) -> str:
        return self.model or f"centrifugal-pump-{self.motor_cv:g}cv"

    def __str__(self) -> str:
        return (
            f"{self.label}: {self.flow_m3h:.2f} m³/h @ {self.head_m:.1f} m, "
            f"shaft power {self.shaft_power_w / 1000:.2f} kW at {self.efficiency:.0%} "
            f"-> {self.motor_cv:g} cv ({self.motor_kw:.2f} kW) motor"
        )


def select_pump(flow_m3h: float, head_m: float, settings: PumpStationSettings | None = None) -> PumpSelection:
    """Compute the duty point power and pick a nominal motor size.

    The result is a starting point: the final model must be checked against the
    manufacturer's pump curve at (``flow_m3h``, ``head_m``).
    """
    settings = settings or PumpStationSettings()
    if flow_m3h <= 0 or head_m <= 0:
        raise DesignError("Pump flow and head must be positive")
    p_hyd = hydraulic_power_w(flow_m3h, head_m)
    p_shaft = p_hyd / settings.efficiency
    return PumpSelection(
        flow_m3h=flow_m3h,
        head_m=head_m,
        efficiency=settings.efficiency,
        hydraulic_power_w=p_hyd,
        shaft_power_w=p_shaft,
        motor_cv=nominal_motor_size_cv(p_shaft),
        model=settings.model,
    )
