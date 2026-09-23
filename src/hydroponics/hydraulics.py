"""Hydraulic design of the nutrient-solution supply network.

Friction losses use the Hazen-Williams equation in SI units and the
Christiansen factor for pipes with evenly spaced outlets (manifolds and
laterals). See the README for the formulas and the assumptions behind them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from hydroponics.errors import DesignError
from hydroponics.layout import LayoutPlan

#: Hazen-Williams constant for SI units (Q in m³/s, D in m, head loss in m).
HAZEN_WILLIAMS_K_SI = 10.646
#: Flow exponent of the Hazen-Williams equation.
HAZEN_WILLIAMS_M = 1.852
#: Diameter exponent of the Hazen-Williams equation.
HAZEN_WILLIAMS_D_EXP = 4.87
#: Hazen-Williams roughness coefficient for new PVC pipe.
C_PVC = 140.0

#: Inner diameters (mm) of PVC solvent-weld water pipe (ABNT NBR 5648), keyed by
#: nominal outer diameter (mm). Check against your manufacturer's datasheet.
PVC_INNER_DIAMETER_MM: dict[int, float] = {
    20: 17.0,
    25: 21.6,
    32: 27.8,
    40: 35.2,
    50: 44.0,
    60: 53.4,
    75: 66.6,
    85: 75.6,
    110: 97.8,
}


def inner_diameter_mm(nominal_mm: int) -> float:
    """Inner diameter of a PVC pipe of the given nominal (outer) diameter."""
    try:
        return PVC_INNER_DIAMETER_MM[nominal_mm]
    except KeyError:
        known = ", ".join(str(k) for k in PVC_INNER_DIAMETER_MM)
        raise DesignError(f"Unknown PVC pipe size {nominal_mm} mm (known: {known})") from None


def flow_velocity(flow_m3h: float, inner_diameter_mm: float) -> float:
    """Mean flow velocity (m/s) for a flow in m³/h through a pipe of given inner diameter."""
    if inner_diameter_mm <= 0:
        raise DesignError("Pipe diameter must be positive")
    area_m2 = math.pi * (inner_diameter_mm / 1000.0) ** 2 / 4.0
    return (flow_m3h / 3600.0) / area_m2


def hazen_williams_head_loss(
    length_m: float,
    flow_m3h: float,
    inner_diameter_mm: float,
    c: float = C_PVC,
) -> float:
    """Friction head loss (m) along a plain pipe, Hazen-Williams SI form.

    h_f = 10.646 · L · (Q / C)^1.852 / D^4.87, with Q in m³/s and D in m.
    """
    if length_m < 0 or flow_m3h < 0:
        raise DesignError("Pipe length and flow must be non-negative")
    if inner_diameter_mm <= 0 or c <= 0:
        raise DesignError("Pipe diameter and Hazen-Williams C must be positive")
    q = flow_m3h / 3600.0
    d = inner_diameter_mm / 1000.0
    return HAZEN_WILLIAMS_K_SI * length_m * (q / c) ** HAZEN_WILLIAMS_M / d**HAZEN_WILLIAMS_D_EXP


def christiansen_factor(outlets: int, m: float = HAZEN_WILLIAMS_M) -> float:
    """Christiansen reduction factor F for a pipe with ``outlets`` equally spaced outlets.

    Flow drops by one outlet's share after each outlet, so the pipe loses less
    head than if it carried the full inlet flow all the way. With the first
    outlet one spacing from the inlet:

        F = 1/(m + 1) + 1/(2N) + sqrt(m - 1)/(6N²)

    F = 1 for a single outlet and tends to 1/(m + 1) ≈ 0.351 for many outlets.
    """
    if outlets < 1:
        raise DesignError("A pipe needs at least one outlet")
    n = outlets
    return 1.0 / (m + 1.0) + 1.0 / (2.0 * n) + math.sqrt(m - 1.0) / (6.0 * n * n)


def smallest_pipe_for_velocity(flow_m3h: float, max_velocity_m_s: float) -> int | None:
    """Smallest standard PVC size (nominal mm) keeping velocity at or below the limit."""
    for nominal, inner in sorted(PVC_INNER_DIAMETER_MM.items()):
        if flow_velocity(flow_m3h, inner) <= max_velocity_m_s:
            return nominal
    return None


@dataclass(frozen=True)
class PipeSegment:
    """A pipe run carrying ``flow_m3h`` at its inlet.

    ``outlets=None`` means a plain pipe (all flow exits at the end); otherwise the
    flow is split evenly between ``outlets`` equally spaced outlets.
    """

    name: str
    length_m: float
    flow_m3h: float
    nominal_mm: int
    outlets: int | None = None
    c: float = C_PVC

    @property
    def inner_diameter_mm(self) -> float:
        return inner_diameter_mm(self.nominal_mm)

    @property
    def velocity_m_s(self) -> float:
        """Velocity at the inlet, i.e. the highest velocity along the segment."""
        return flow_velocity(self.flow_m3h, self.inner_diameter_mm)

    @property
    def reduction_factor(self) -> float:
        return 1.0 if self.outlets is None else christiansen_factor(self.outlets)

    @property
    def head_loss_m(self) -> float:
        plain = hazen_williams_head_loss(self.length_m, self.flow_m3h, self.inner_diameter_mm, self.c)
        return plain * self.reduction_factor


@dataclass(frozen=True)
class HydraulicSettings:
    """Assumptions for the supply network. Defaults follow the original project.

    Attributes:
        main_pipe_mm: Nominal diameter of the feed line and sector manifold.
        lateral_pipe_mm: Nominal diameter of the laterals that cross each bay.
        bench_inlet_mm: Nominal diameter of the branch into each bench.
        flow_per_channel_l_min: Nutrient-solution flow per NFT channel.
        flow_safety_factor: Multiplier applied to the design flow.
        feed_line_extra_m: Pipe from the pump to the greenhouse, added to the
            greenhouse width to get the default feed-line length.
        feed_line_length_m: Actual pipe length from the pump to the start of the
            sector manifold. When set, it replaces the conservative default of
            greenhouse width + ``feed_line_extra_m`` (pump on the far side).
        bench_height_m: Height of the bench inlets above the pump.
        filter_head_m: Head loss across the filter.
        suction_head_m: Suction-side losses and lift.
        terrain_slope_pct: Ground slope along the greenhouse length (static lift).
        minor_loss_factor: Allowance for fittings and valves, as a fraction of
            friction losses (0.10 = +10 %).
        hazen_williams_c: Pipe roughness coefficient.
        velocity_range_m_s: Recommended velocity band; segments outside it are flagged.
    """

    main_pipe_mm: int = 50
    lateral_pipe_mm: int = 32
    bench_inlet_mm: int = 25
    flow_per_channel_l_min: float = 1.5
    flow_safety_factor: float = 1.3
    feed_line_extra_m: float = 10.0
    feed_line_length_m: float | None = None
    bench_height_m: float = 1.2
    filter_head_m: float = 1.5
    suction_head_m: float = 1.5
    terrain_slope_pct: float = 0.0
    minor_loss_factor: float = 0.10
    hazen_williams_c: float = C_PVC
    velocity_range_m_s: tuple[float, float] = (0.5, 2.0)

    def __post_init__(self) -> None:
        for size in (self.main_pipe_mm, self.lateral_pipe_mm, self.bench_inlet_mm):
            inner_diameter_mm(size)
        if self.flow_per_channel_l_min <= 0:
            raise DesignError("flow_per_channel_l_min must be positive")
        if self.flow_safety_factor < 1:
            raise DesignError("flow_safety_factor must be >= 1")
        if self.feed_line_length_m is not None and self.feed_line_length_m < 0:
            raise DesignError("feed_line_length_m must be non-negative")
        if self.minor_loss_factor < 0:
            raise DesignError("minor_loss_factor must be non-negative")
        low, high = self.velocity_range_m_s
        if not 0 <= low < high:
            raise DesignError("velocity_range_m_s must be (low, high) with 0 <= low < high")


@dataclass(frozen=True)
class VelocityIssue:
    segment: str
    velocity_m_s: float
    low: float
    high: float
    suggested_mm: int | None = None

    def __str__(self) -> str:
        if self.velocity_m_s > self.high:
            hint = (
                f"DN{self.suggested_mm} or larger" if self.suggested_mm else "parallel pipes or more sectors"
            )
            return (
                f"{self.segment}: velocity {self.velocity_m_s:.2f} m/s is above {self.high:g} m/s; use {hint}"
            )
        return (
            f"{self.segment}: velocity {self.velocity_m_s:.2f} m/s is below "
            f"{self.low:g} m/s; the pipe is oversized"
        )


@dataclass(frozen=True)
class HydraulicDesign:
    """Per-sector hydraulic result: design flow, friction and static heads."""

    sector_flow_m3h: float
    total_flow_m3h: float
    segments: tuple[PipeSegment, ...]
    static_heads: dict[str, float]
    minor_loss_factor: float
    velocity_range_m_s: tuple[float, float]

    @property
    def friction_head_m(self) -> float:
        return sum(s.head_loss_m for s in self.segments)

    @property
    def minor_losses_m(self) -> float:
        return self.friction_head_m * self.minor_loss_factor

    @property
    def static_head_m(self) -> float:
        return sum(self.static_heads.values())

    @property
    def total_dynamic_head_m(self) -> float:
        """Head the pump must deliver at the design flow (m of water column)."""
        return self.friction_head_m + self.minor_losses_m + self.static_head_m

    @property
    def velocity_issues(self) -> list[VelocityIssue]:
        low, high = self.velocity_range_m_s
        return [
            VelocityIssue(s.name, s.velocity_m_s, low, high, smallest_pipe_for_velocity(s.flow_m3h, high))
            for s in self.segments
            if not low <= s.velocity_m_s <= high
        ]

    def segments_frame(self) -> pd.DataFrame:
        """Pipe segments with diameter, velocity, Christiansen factor and head loss."""
        low, high = self.velocity_range_m_s
        return pd.DataFrame(
            [
                {
                    "segment": s.name,
                    "DN (mm)": s.nominal_mm,
                    "ID (mm)": s.inner_diameter_mm,
                    "length (m)": s.length_m,
                    "flow (m³/h)": round(s.flow_m3h, 3),
                    "outlets": s.outlets or 1,
                    "velocity (m/s)": round(s.velocity_m_s, 2),
                    "velocity ok": low <= s.velocity_m_s <= high,
                    "F": round(s.reduction_factor, 3),
                    "head loss (m)": round(s.head_loss_m, 2),
                }
                for s in self.segments
            ]
        )

    def head_budget_frame(self) -> pd.DataFrame:
        """Breakdown of the total dynamic head."""
        rows = [(s.name, "friction", s.head_loss_m) for s in self.segments]
        rows.append(
            (f"Fittings and valves (+{self.minor_loss_factor:.0%} of friction)", "minor", self.minor_losses_m)
        )
        rows += [(name, "static / component", head) for name, head in self.static_heads.items()]
        rows.append(("Total dynamic head", "total", self.total_dynamic_head_m))
        frame = pd.DataFrame(rows, columns=["item", "type", "head (m)"])
        frame["head (m)"] = frame["head (m)"].round(2)
        return frame


def design_flow(layout: LayoutPlan, settings: HydraulicSettings) -> tuple[float, float]:
    """Total and per-sector design flow (m³/h).

    Every channel receives ``flow_per_channel_l_min``; the per-sector flow is the
    total split evenly between sectors, times the safety factor.
    """
    total = layout.total_channels * settings.flow_per_channel_l_min * 60.0 / 1000.0
    sector = total / layout.greenhouse.sectors * settings.flow_safety_factor
    return total, sector


def design_hydraulics(layout: LayoutPlan, settings: HydraulicSettings | None = None) -> HydraulicDesign:
    """Size the supply network of the most demanding sector.

    The hydraulic path from the pump to the farthest bench is modelled as:

    1. **Feed line** - ``feed_line_length_m`` at the full sector flow. By default
       greenhouse width + ``feed_line_extra_m`` (conservative: the sector is
       assumed to be on the far side of the pump house).
    2. **Manifold** - runs the greenhouse length and feeds one lateral per bench
       position (Christiansen factor with N = laterals per sector).
    3. **Lateral** - crosses one bay and feeds ``benches_per_bay`` benches of the
       most demanding bench type (Christiansen factor with N = benches per bay).

    Static and component heads (bench height, filter, suction, terrain slope) are
    added on top of friction and minor losses.
    """
    settings = settings or HydraulicSettings()
    gh = layout.greenhouse
    total_flow, sector_flow = design_flow(layout, settings)

    lateral_flow = (
        gh.benches_per_bay
        * layout.max_channels_per_bench
        * settings.flow_per_channel_l_min
        * 60.0
        / 1000.0
        * settings.flow_safety_factor
    )
    c = settings.hazen_williams_c
    feed_line_m = (
        settings.feed_line_length_m
        if settings.feed_line_length_m is not None
        else gh.width_m + settings.feed_line_extra_m
    )
    segments = (
        PipeSegment("Feed line", feed_line_m, sector_flow, settings.main_pipe_mm, c=c),
        PipeSegment(
            "Manifold",
            gh.length_m,
            sector_flow,
            settings.main_pipe_mm,
            outlets=layout.laterals_per_sector,
            c=c,
        ),
        PipeSegment(
            "Lateral",
            gh.bay_width_m,
            lateral_flow,
            settings.lateral_pipe_mm,
            outlets=gh.benches_per_bay,
            c=c,
        ),
    )
    static_heads = {
        "Bench height": settings.bench_height_m,
        "Filter": settings.filter_head_m,
        "Suction": settings.suction_head_m,
        "Terrain slope": settings.terrain_slope_pct / 100.0 * gh.length_m,
    }
    return HydraulicDesign(
        sector_flow_m3h=sector_flow,
        total_flow_m3h=total_flow,
        segments=segments,
        static_heads=static_heads,
        minor_loss_factor=settings.minor_loss_factor,
        velocity_range_m_s=settings.velocity_range_m_s,
    )
