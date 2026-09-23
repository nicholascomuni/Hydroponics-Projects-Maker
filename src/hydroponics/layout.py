"""Greenhouse and NFT bench layout.

Geometry conventions
--------------------
* The greenhouse is ``length_m`` long and ``width_m`` wide. Its width is split
  into *bays* (the spans between structural posts) of ``bay_width_m``.
* Each bay holds ``benches_per_bay`` benches side by side. Benches run along the
  greenhouse length, so every bay contains ``benches_per_bay`` *bench rows* and
  each bench row can take as many benches as fit in the greenhouse length.
* A bench is a set of parallel NFT (Nutrient Film Technique) channels: shallow
  plastic profiles with planting holes, through which a thin film of nutrient
  solution flows by gravity.
* Benches are fed by *laterals*: one lateral pipe crosses a bay and feeds the
  ``benches_per_bay`` benches that sit side by side in it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from hydroponics.errors import DesignError

_EPS = 1e-9


@dataclass(frozen=True)
class ChannelProfile:
    """An NFT channel profile (the plastic gutter that holds the plants).

    Attributes:
        name: Profile designation used by the supplier (e.g. ``"PS85"``).
        holes_per_channel: Planting holes in one channel bar.
        channel_length_m: Length of one channel bar as sold.
        width_cm: Outer width of the profile, used for channel spacing.
    """

    name: str
    holes_per_channel: int
    channel_length_m: float = 6.0
    width_cm: float = 5.5

    def __post_init__(self) -> None:
        if self.holes_per_channel <= 0:
            raise DesignError(f"Profile {self.name}: holes_per_channel must be positive")
        if self.channel_length_m <= 0 or self.width_cm <= 0:
            raise DesignError(f"Profile {self.name}: dimensions must be positive")

    @property
    def holes_per_metre(self) -> float:
        return self.holes_per_channel / self.channel_length_m

    @property
    def hole_spacing_cm(self) -> float:
        return 100.0 * self.channel_length_m / self.holes_per_channel


#: Profiles used in the original project. Hole counts are per 6 m channel bar:
#: dense profiles (PS55) are used for nurseries, sparse ones (PS85) for grow-out.
CHANNEL_PROFILES: dict[str, ChannelProfile] = {
    "PS55": ChannelProfile("PS55", holes_per_channel=58),
    "PS65": ChannelProfile("PS65", holes_per_channel=39),
    "PS85": ChannelProfile("PS85", holes_per_channel=23),
}


def get_profile(profile: ChannelProfile | str) -> ChannelProfile:
    """Resolve a profile name to a :class:`ChannelProfile`."""
    if isinstance(profile, ChannelProfile):
        return profile
    try:
        return CHANNEL_PROFILES[profile]
    except KeyError:
        known = ", ".join(sorted(CHANNEL_PROFILES))
        raise DesignError(
            f"Unknown channel profile {profile!r} (known: {known}); "
            "pass a ChannelProfile instance to use a custom one"
        ) from None


@dataclass(frozen=True)
class Bench:
    """An NFT bench: ``channels`` parallel channels of ``length_m`` over ``width_m``."""

    length_m: float
    width_m: float
    channels: int
    profile: ChannelProfile | str

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile", get_profile(self.profile))
        if self.length_m <= 0 or self.width_m <= 0:
            raise DesignError("Bench length and width must be positive")
        if self.channels < 2:
            raise DesignError("A bench needs at least 2 channels")
        if self.channel_spacing_cm < self.profile.width_cm:
            raise DesignError(
                f"{self.channels} x {self.profile.name} channels "
                f"({self.profile.width_cm:g} cm wide) do not fit in a {self.width_m:g} m bench"
            )

    @property
    def channel_spacing_cm(self) -> float:
        """Centre-to-centre distance between adjacent channels.

        With ``n`` channels of width ``w`` spread edge to edge over the bench width
        ``W``: gap = (W - n·w) / (n - 1) and spacing = gap + w.
        """
        width_cm = self.width_m * 100.0
        w = self.profile.width_cm
        n = self.channels
        return (width_cm - n * w) / (n - 1) + w

    @property
    def channel_bars(self) -> float:
        """Number of channel bars (as sold) needed for one bench."""
        return self.channels * self.length_m / self.profile.channel_length_m

    @property
    def plant_sites(self) -> int:
        """Number of planting holes on the bench."""
        return int(self.channels * self.length_m * self.profile.holes_per_metre + _EPS)

    @property
    def label(self) -> str:
        return f"{self.length_m:g} x {self.width_m:g} m, {self.channels} x {self.profile.name} channels"


@dataclass(frozen=True)
class BenchGroup:
    """``count`` identical benches dedicated to one crop / production stage."""

    bench: Bench
    count: int
    crop: str = "Lettuce"

    def __post_init__(self) -> None:
        if self.count <= 0:
            raise DesignError(f"Bench group {self.crop!r}: count must be positive")

    @property
    def channels(self) -> int:
        return self.bench.channels * self.count

    @property
    def plant_sites(self) -> int:
        return self.bench.plant_sites * self.count


@dataclass(frozen=True)
class Greenhouse:
    """Greenhouse footprint and how it is divided into bays and irrigation sectors.

    Attributes:
        length_m: Greenhouse length (direction the benches run).
        width_m: Greenhouse width (split into bays).
        bay_width_m: Width of one bay (span between structural posts).
        benches_per_bay: Benches placed side by side in each bay.
        sectors: Independent irrigation sectors, each with its own pump and reservoir.
        min_aisle_width_m: Smallest acceptable walkway between benches.
    """

    length_m: float
    width_m: float
    bay_width_m: float = 8.0
    benches_per_bay: int = 3
    sectors: int = 1
    min_aisle_width_m: float = 0.53

    def __post_init__(self) -> None:
        if self.length_m <= 0 or self.width_m <= 0 or self.bay_width_m <= 0:
            raise DesignError("Greenhouse dimensions must be positive")
        if self.bay_width_m > self.width_m + _EPS:
            raise DesignError(
                f"Bay width ({self.bay_width_m:g} m) exceeds greenhouse width ({self.width_m:g} m)"
            )
        if self.benches_per_bay < 1:
            raise DesignError("benches_per_bay must be at least 1")
        if self.sectors < 1:
            raise DesignError("sectors must be at least 1")

    @property
    def area_m2(self) -> float:
        return self.length_m * self.width_m

    @property
    def bays(self) -> int:
        """Whole bays that fit in the greenhouse width."""
        return math.floor(self.width_m / self.bay_width_m + _EPS)

    @property
    def bench_rows(self) -> int:
        return self.bays * self.benches_per_bay

    def aisle_width(self, bench_width_m: float) -> float:
        """Walkway width between benches inside a bay.

        With several bays, the bay's posts sit in a walkway shared with the
        neighbouring bay, so the free width is split into ``benches_per_bay``
        aisles. A single-bay greenhouse also needs a walkway on both sides,
        giving ``benches_per_bay + 1`` aisles.
        """
        free = self.bay_width_m - self.benches_per_bay * bench_width_m
        aisles = self.benches_per_bay if self.bays > 1 else self.benches_per_bay + 1
        return free / aisles


@dataclass(frozen=True)
class LayoutPlan:
    """Derived layout quantities for a greenhouse populated with bench groups."""

    greenhouse: Greenhouse
    groups: tuple[BenchGroup, ...]
    aisle_width_m: float
    bench_rows_used: int
    total_benches: int
    total_channels: int
    laterals: int
    laterals_per_sector: int
    plant_sites: dict[str, int] = field(default_factory=dict)

    @property
    def max_channels_per_bench(self) -> int:
        return max(g.bench.channels for g in self.groups)


def plan_layout(greenhouse: Greenhouse, groups: list[BenchGroup] | tuple[BenchGroup, ...]) -> LayoutPlan:
    """Check that the benches fit in the greenhouse and derive layout quantities.

    Raises:
        DesignError: if there are no benches, the benches are wider than the bay,
            the aisles are narrower than ``greenhouse.min_aisle_width_m`` or the
            benches need more bench rows than the greenhouse has.
    """
    groups = tuple(groups)
    if not groups:
        raise DesignError("At least one bench group is required")

    widest = max(g.bench.width_m for g in groups)
    aisle = greenhouse.aisle_width(widest)
    if aisle <= 0:
        raise DesignError(
            f"{greenhouse.benches_per_bay} benches of {widest:g} m do not fit "
            f"in a {greenhouse.bay_width_m:g} m bay"
        )
    if aisle < greenhouse.min_aisle_width_m - _EPS:
        raise DesignError(
            f"Aisle width {aisle:.2f} m is below the minimum of "
            f"{greenhouse.min_aisle_width_m:.2f} m; use narrower benches, fewer "
            "benches per bay or a wider bay"
        )

    longest = max(g.bench.length_m for g in groups)
    if longest > greenhouse.length_m + _EPS:
        raise DesignError(f"A {longest:g} m bench does not fit in a {greenhouse.length_m:g} m greenhouse")
    # Benches of the same length are packed end to end along a bench row; rows are
    # not shared between bench lengths (a conservative simplification).
    benches_by_length: dict[float, int] = {}
    for g in groups:
        benches_by_length[g.bench.length_m] = benches_by_length.get(g.bench.length_m, 0) + g.count
    rows_needed = sum(
        math.ceil(count / math.floor(greenhouse.length_m / length + _EPS))
        for length, count in benches_by_length.items()
    )
    if rows_needed > greenhouse.bench_rows:
        raise DesignError(
            f"The benches need {rows_needed} bench rows but the greenhouse has "
            f"{greenhouse.bench_rows} ({greenhouse.bays} bays x {greenhouse.benches_per_bay})"
        )

    total_benches = sum(g.count for g in groups)
    laterals = math.ceil(total_benches / greenhouse.benches_per_bay)
    plant_sites: dict[str, int] = {}
    for g in groups:
        plant_sites[g.crop] = plant_sites.get(g.crop, 0) + g.plant_sites

    return LayoutPlan(
        greenhouse=greenhouse,
        groups=groups,
        aisle_width_m=aisle,
        bench_rows_used=rows_needed,
        total_benches=total_benches,
        total_channels=sum(g.channels for g in groups),
        laterals=laterals,
        laterals_per_sector=math.ceil(laterals / greenhouse.sectors),
        plant_sites=plant_sites,
    )
