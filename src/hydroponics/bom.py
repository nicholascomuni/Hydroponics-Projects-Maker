"""Bill of materials: aggregation and quantity take-off for benches, piping and pumps.

Product keys (``pvc-pipe-50mm``, ``nft-channel-PS85``...) are the join key with
the optional :class:`~hydroponics.catalog.Catalog`.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace

import pandas as pd

from hydroponics.catalog import Catalog
from hydroponics.hydraulics import HydraulicSettings
from hydroponics.layout import BenchGroup, LayoutPlan
from hydroponics.pump import PumpSelection, PumpStationSettings

#: Pipes and channel profiles are sold in 6 m bars.
BAR_LENGTH_M = 6.0
#: Nominal diameter of the gravity drainage (sewer-grade PVC) returning solution to the reservoir.
DRAIN_PIPE_MM = 75
#: Empirical factor from the original take-off: drain runs are ~10 % shorter than supply runs.
DRAIN_LENGTH_FACTOR = 0.9
#: Greenhouse area covered by one 170 g can of PVC solvent cement.
AREA_PER_CEMENT_CAN_M2 = 200.0

BAR = "bar (6 m)"
PIECE = "pc"


def _ceil(x: float) -> int:
    """Round up, ignoring floating-point noise (24.000000001 -> 24)."""
    return math.ceil(round(x, 6))


def _bars(length_m: float) -> int:
    return _ceil(length_m / BAR_LENGTH_M)


@dataclass(frozen=True)
class BomItem:
    """A BOM line. Items with the same ``product`` are summed by :class:`BillOfMaterials`."""

    product: str
    quantity: float
    unit: str = PIECE
    category: str = ""

    def __post_init__(self) -> None:
        if not self.product:
            raise ValueError("BOM item needs a product key")
        if self.quantity < 0:
            raise ValueError(f"{self.product}: quantity must be non-negative")

    def __add__(self, other: BomItem) -> BomItem:
        if not isinstance(other, BomItem):
            return NotImplemented
        if other.product != self.product:
            raise ValueError(f"Cannot add different products: {self.product!r} and {other.product!r}")
        if other.unit != self.unit:
            raise ValueError(f"{self.product}: cannot add quantities in {self.unit!r} and {other.unit!r}")
        return replace(self, quantity=self.quantity + other.quantity)


class BillOfMaterials:
    """Ordered collection of BOM items, aggregated by product key."""

    def __init__(self, items: Iterable[BomItem] = ()) -> None:
        self._items: dict[str, BomItem] = {}
        self.extend(items)

    def add(self, item: BomItem) -> None:
        current = self._items.get(item.product)
        self._items[item.product] = item if current is None else current + item

    def add_item(self, product: str, quantity: float, unit: str = PIECE, category: str = "") -> None:
        self.add(BomItem(product, quantity, unit, category))

    def extend(self, items: Iterable[BomItem]) -> None:
        for item in items:
            self.add(item)

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[BomItem]:
        return iter(self._items.values())

    def __contains__(self, product: object) -> bool:
        return product in self._items

    def __getitem__(self, product: str) -> BomItem:
        return self._items[product]

    def to_frame(self, catalog: Catalog | None = None) -> pd.DataFrame:
        """BOM as a DataFrame; with a catalog, adds code/description/price columns."""
        frame = pd.DataFrame(
            [(i.category, i.product, i.quantity, i.unit) for i in self],
            columns=["category", "product", "quantity", "unit"],
        )
        if (frame["quantity"] % 1 == 0).all():
            frame["quantity"] = frame["quantity"].astype(int)
        return catalog.enrich(frame) if catalog is not None else frame


def bench_items(group: BenchGroup) -> list[BomItem]:
    """Structure and channels for ``group.count`` benches.

    Trestles (bench supports) go every metre plus one at the end; each channel
    rests on a clip fixed with one screw on every trestle.
    """
    b, n = group.bench, group.count
    p = b.profile.name
    trestles = b.length_m + 1
    cat = "Benches"
    return [
        BomItem(f"bench-trestle-{b.width_m:g}m", trestles * n, PIECE, cat),
        BomItem(f"inlet-trestle-{b.channels}ch-{b.width_m:g}m", n, PIECE, cat),
        BomItem(f"collector-gutter-{b.channels}ch-{b.width_m:g}m", n, PIECE, cat),
        BomItem(f"nft-channel-{p}", _ceil(b.channel_bars * n), BAR, cat),
        BomItem(f"channel-end-cap-{p}", b.channels * n, PIECE, cat),
        BomItem(f"channel-clip-{p}", trestles * b.channels * n, PIECE, cat),
        BomItem("screw", trestles * b.channels * n, PIECE, cat),
    ]


def piping_items(layout: LayoutPlan, settings: HydraulicSettings) -> list[BomItem]:
    """Supply piping (pressurised PVC) and gravity drainage.

    * Main pipe: one manifold per sector along the greenhouse (+5 m to reach the
      pump) and one header across the greenhouse width.
    * Laterals: one per group of ``benches_per_bay`` benches, one bay wide.
    """
    gh = layout.greenhouse
    main, lat, inlet = settings.main_pipe_mm, settings.lateral_pipe_mm, settings.bench_inlet_mm
    lateral_length = layout.laterals * gh.bay_width_m
    drain_length = (lateral_length + gh.length_m * gh.sectors + gh.width_m) * DRAIN_LENGTH_FACTOR
    supply, drain = "Supply piping", "Drainage"
    return [
        BomItem(f"pvc-pipe-{main}mm", _bars((gh.length_m + 5) * gh.sectors + gh.width_m), BAR, supply),
        BomItem(f"pvc-pipe-{lat}mm", _bars(lateral_length), BAR, supply),
        BomItem(f"pvc-elbow-{main}mm", 2 * gh.sectors, PIECE, supply),
        BomItem(f"pvc-reducing-tee-{main}x{lat}mm", layout.laterals, PIECE, supply),
        BomItem(f"pvc-reducing-tee-{lat}x{inlet}mm", layout.total_benches, PIECE, supply),
        BomItem(f"pvc-cap-{main}mm", gh.sectors, PIECE, supply),
        BomItem(f"pvc-cap-{lat}mm", layout.laterals, PIECE, supply),
        BomItem(f"drain-pipe-{DRAIN_PIPE_MM}mm", _bars(drain_length), BAR, drain),
        BomItem(f"drain-elbow-{DRAIN_PIPE_MM}mm", layout.laterals + gh.sectors, PIECE, drain),
        BomItem(
            f"drain-tee-{DRAIN_PIPE_MM}mm",
            max(0, gh.benches_per_bay * layout.laterals - gh.sectors),
            PIECE,
            drain,
        ),
    ]


def station_items(
    layout: LayoutPlan,
    pump: PumpSelection,
    hydraulics: HydraulicSettings,
    station: PumpStationSettings,
) -> list[BomItem]:
    """One pump station per sector, plus consumables scaled by greenhouse area."""
    gh = layout.greenhouse
    s = gh.sectors
    cat = "Pump station"
    consumable_units = _ceil(gh.area_m2 / AREA_PER_CEMENT_CAN_M2)
    return [
        BomItem(f"pump-fittings-kit-{hydraulics.main_pipe_mm}mm", s, PIECE, cat),
        BomItem(pump.label, s, PIECE, cat),
        BomItem(f"pump-control-panel-{pump.motor_cv:g}cv", s, PIECE, cat),
        BomItem(f"reservoir-{station.reservoir_volume_l}l", s, PIECE, cat),
        BomItem("pvc-solvent-cement-170g", consumable_units, PIECE, "Consumables"),
        BomItem("sandpaper-sheet", consumable_units + 3, PIECE, "Consumables"),
    ]


def build_bom(
    layout: LayoutPlan,
    pump: PumpSelection,
    hydraulics: HydraulicSettings,
    station: PumpStationSettings,
) -> BillOfMaterials:
    """Full bill of materials for a designed greenhouse."""
    bom = BillOfMaterials()
    for group in layout.groups:
        bom.extend(bench_items(group))
    bom.extend(piping_items(layout, hydraulics))
    bom.extend(station_items(layout, pump, hydraulics, station))
    return bom
