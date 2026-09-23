"""End-to-end greenhouse design: layout -> hydraulics -> pump -> bill of materials."""

from __future__ import annotations

import logging
import tomllib
import warnings
from dataclasses import dataclass, field, fields
from os import PathLike
from pathlib import Path
from typing import Any

import pandas as pd

from hydroponics.bom import BillOfMaterials, build_bom
from hydroponics.catalog import Catalog
from hydroponics.errors import DesignError, DesignWarning
from hydroponics.hydraulics import HydraulicDesign, HydraulicSettings, design_hydraulics
from hydroponics.layout import Bench, BenchGroup, Greenhouse, LayoutPlan, plan_layout
from hydroponics.pump import PumpSelection, PumpStationSettings, select_pump

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DesignInputs:
    """Everything needed to size a greenhouse."""

    greenhouse: Greenhouse
    benches: tuple[BenchGroup, ...]
    hydraulics: HydraulicSettings = field(default_factory=HydraulicSettings)
    station: PumpStationSettings = field(default_factory=PumpStationSettings)


@dataclass(frozen=True)
class GreenhouseDesign:
    """Result of :func:`design_greenhouse`."""

    inputs: DesignInputs
    layout: LayoutPlan
    hydraulics: HydraulicDesign
    pump: PumpSelection
    bom: BillOfMaterials

    @property
    def warnings(self) -> list[str]:
        return [str(issue) for issue in self.hydraulics.velocity_issues]

    def bom_frame(self, catalog: Catalog | None = None) -> pd.DataFrame:
        return self.bom.to_frame(catalog)

    def summary(self) -> str:
        """Human-readable design summary."""
        gh, lay, hyd, pump = self.inputs.greenhouse, self.layout, self.hydraulics, self.pump
        lines = [
            "Greenhouse design summary",
            "=========================",
            f"Footprint        {gh.length_m:g} m x {gh.width_m:g} m ({gh.area_m2:,.0f} m²), "
            f"{gh.bays} bays of {gh.bay_width_m:g} m, {gh.sectors} sector(s)",
            f"Benches          {lay.total_benches} in {lay.bench_rows_used}/{gh.bench_rows} bench rows, "
            f"{lay.total_channels} NFT channels, {lay.laterals} laterals",
            f"Aisle width      {lay.aisle_width_m:.2f} m (minimum {gh.min_aisle_width_m:.2f} m)",
        ]
        for group in lay.groups:
            b = group.bench
            lines.append(
                f"  {group.count:>4} x {group.crop:<22} {b.label}, "
                f"channel spacing {b.channel_spacing_cm:.1f} cm, {group.plant_sites:,} plant sites"
            )
        lines.append(f"Plant sites      {sum(lay.plant_sites.values()):,} total")
        lines += [
            "",
            "Hydraulics (per sector)",
            f"Nominal flow     {hyd.total_flow_m3h:.2f} m³/h for the whole greenhouse "
            f"({lay.total_channels} channels x {self.inputs.hydraulics.flow_per_channel_l_min:g} L/min)",
            f"Design flow      {hyd.sector_flow_m3h:.2f} m³/h per sector "
            f"(x{self.inputs.hydraulics.flow_safety_factor:g} safety factor)",
        ]
        for s in hyd.segments:
            outlets = f"{s.outlets} outlets, F={s.reduction_factor:.3f}" if s.outlets else "plain pipe"
            lines.append(
                f"  {s.name:<10} DN{s.nominal_mm:<4} L={s.length_m:>5.1f} m  Q={s.flow_m3h:>6.2f} m³/h  "
                f"v={s.velocity_m_s:.2f} m/s  hf={s.head_loss_m:>5.2f} m  ({outlets})"
            )
        lines += [
            f"Friction         {hyd.friction_head_m:.2f} m + {hyd.minor_losses_m:.2f} m fittings",
            f"Static/component {hyd.static_head_m:.2f} m",
            f"Total head       {hyd.total_dynamic_head_m:.2f} m",
            "",
            "Pump (one per sector)",
            f"Duty point       {pump.flow_m3h:.2f} m³/h @ {pump.head_m:.1f} m",
            f"Power            hydraulic {pump.hydraulic_power_w / 1000:.2f} kW, shaft "
            f"{pump.shaft_power_w / 1000:.2f} kW at {pump.efficiency:.0%} efficiency",
            f"Motor            {pump.motor_cv:g} cv ({pump.motor_kw:.2f} kW) x {gh.sectors}",
            "",
            f"Bill of materials: {len(self.bom)} line items",
        ]
        if self.warnings:
            lines += ["", "Warnings"] + [f"  - {w}" for w in self.warnings]
        return "\n".join(lines)


def design_greenhouse(inputs: DesignInputs) -> GreenhouseDesign:
    """Run the full design.

    Raises:
        DesignError: for infeasible inputs (benches do not fit, aisles too narrow...).

    Warns:
        DesignWarning: for each pipe segment whose velocity is outside the
            recommended range.
    """
    layout = plan_layout(inputs.greenhouse, inputs.benches)
    hydraulics = design_hydraulics(layout, inputs.hydraulics)
    for issue in hydraulics.velocity_issues:
        warnings.warn(str(issue), DesignWarning, stacklevel=2)
    pump = select_pump(hydraulics.sector_flow_m3h, hydraulics.total_dynamic_head_m, inputs.station)
    bom = build_bom(layout, pump, inputs.hydraulics, inputs.station)
    logger.info("Designed %d benches, TDH %.2f m", layout.total_benches, hydraulics.total_dynamic_head_m)
    return GreenhouseDesign(inputs, layout, hydraulics, pump, bom)


def _build(cls: type, data: dict[str, Any], section: str) -> Any:
    allowed = {f.name for f in fields(cls)}
    unknown = set(data) - allowed
    if unknown:
        raise DesignError(f"[{section}] unknown key(s): {', '.join(sorted(unknown))}")
    return cls(**data)


def inputs_from_dict(config: dict[str, Any]) -> DesignInputs:
    """Build :class:`DesignInputs` from a dict with the layout of the TOML design file."""
    if "greenhouse" not in config or "benches" not in config:
        raise DesignError("Design config needs [greenhouse] and at least one [[benches]] section")
    greenhouse = _build(Greenhouse, config["greenhouse"], "greenhouse")
    groups = []
    for spec in config["benches"]:
        spec = dict(spec)
        count = spec.pop("count")
        crop = spec.pop("crop", "Lettuce")
        groups.append(BenchGroup(_build(Bench, spec, "benches"), count, crop))
    hyd_cfg = dict(config.get("hydraulics", {}))
    if "velocity_range_m_s" in hyd_cfg:
        hyd_cfg["velocity_range_m_s"] = tuple(hyd_cfg["velocity_range_m_s"])
    return DesignInputs(
        greenhouse=greenhouse,
        benches=tuple(groups),
        hydraulics=_build(HydraulicSettings, hyd_cfg, "hydraulics"),
        station=_build(PumpStationSettings, config.get("pump", {}), "pump"),
    )


def load_design_file(path: str | PathLike[str]) -> DesignInputs:
    """Read design inputs from a TOML file (see ``examples/greenhouse_51x48.toml``)."""
    with Path(path).open("rb") as fh:
        return inputs_from_dict(tomllib.load(fh))
