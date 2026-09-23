"""Command-line interface: ``python -m hydroponics design ...``."""

from __future__ import annotations

import argparse
import logging
import math
import sys
import warnings
from collections.abc import Sequence
from typing import Any

import pandas as pd

from hydroponics.catalog import Catalog
from hydroponics.design import design_greenhouse, inputs_from_dict, load_design_file
from hydroponics.errors import DesignError, DesignWarning

DEFAULT_BENCH = {"length_m": 12.0, "width_m": 1.8, "channels": 8, "profile": "PS85", "crop": "Lettuce"}

BENCH_HELP = (
    "Bench group as COUNT:LENGTH:WIDTH:CHANNELS:PROFILE[:CROP], e.g. 61:12:1.8:8:PS85:grow-out. "
    "Repeatable. Without it, every bench row is filled with 12 x 1.8 m benches of 8 PS85 channels."
)


def parse_bench(spec: str) -> dict[str, Any]:
    """Parse a ``COUNT:LENGTH:WIDTH:CHANNELS:PROFILE[:CROP]`` bench spec."""
    parts = spec.split(":")
    if len(parts) not in (5, 6):
        raise argparse.ArgumentTypeError(
            f"invalid bench spec {spec!r}; expected COUNT:LENGTH:WIDTH:CHANNELS:PROFILE[:CROP]"
        )
    try:
        bench = {
            "count": int(parts[0]),
            "length_m": float(parts[1]),
            "width_m": float(parts[2]),
            "channels": int(parts[3]),
            "profile": parts[4],
        }
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid bench spec {spec!r}: {exc}") from None
    if len(parts) == 6:
        bench["crop"] = parts[5]
    return bench


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hydroponics", description="Size an NFT hydroponic greenhouse.")
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("design", help="Design a greenhouse and print a summary")
    d.add_argument("--config", help="TOML design file (replaces the layout/hydraulics options below)")

    g = d.add_argument_group("greenhouse")
    g.add_argument("--length", type=float, help="Greenhouse length in m (benches run along it)")
    g.add_argument("--width", type=float, help="Greenhouse width in m")
    g.add_argument("--bay-width", type=float, default=8.0, help="Bay width in m (default: 8)")
    g.add_argument("--benches-per-bay", type=int, default=3, help="Benches side by side per bay (default: 3)")
    g.add_argument("--sectors", type=int, default=1, help="Independent irrigation sectors (default: 1)")
    g.add_argument("--min-aisle", type=float, default=0.53, help="Minimum aisle width in m (default: 0.53)")
    g.add_argument("--bench", action="append", type=parse_bench, default=[], help=BENCH_HELP)

    h = d.add_argument_group("hydraulics and pump")
    h.add_argument(
        "--main-pipe", type=int, default=50, help="Feed line / manifold PVC DN in mm (default: 50)"
    )
    h.add_argument("--lateral-pipe", type=int, default=32, help="Lateral PVC DN in mm (default: 32)")
    h.add_argument("--flow-per-channel", type=float, default=1.5, help="L/min per NFT channel (default: 1.5)")
    h.add_argument(
        "--terrain-slope", type=float, default=0.0, help="Ground slope along the length in %% (default: 0)"
    )
    h.add_argument("--pump-efficiency", type=float, default=0.6, help="Pump efficiency 0-1 (default: 0.6)")
    h.add_argument("--pump-model", help="Commercial pump model used as the BOM label")
    h.add_argument(
        "--reservoir", type=int, default=3000, help="Reservoir volume per sector in L (default: 3000)"
    )

    o = d.add_argument_group("output")
    o.add_argument("--catalog", help="Product catalog CSV (columns: product, code, description, unit_price)")
    o.add_argument("--bom", action="store_true", help="Also print the bill of materials")
    o.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    return parser


def _config_from_args(args: argparse.Namespace) -> dict[str, Any]:
    if args.length is None or args.width is None:
        raise DesignError("--length and --width are required unless --config is given")
    benches = args.bench
    if not benches:
        bays = math.floor(args.width / args.bay_width + 1e-9)
        per_row = math.floor(args.length / DEFAULT_BENCH["length_m"] + 1e-9)
        count = bays * args.benches_per_bay * per_row
        if count < 1:
            raise DesignError("The greenhouse is too small for the default 12 m bench; pass --bench")
        benches = [{**DEFAULT_BENCH, "count": count}]
    return {
        "greenhouse": {
            "length_m": args.length,
            "width_m": args.width,
            "bay_width_m": args.bay_width,
            "benches_per_bay": args.benches_per_bay,
            "sectors": args.sectors,
            "min_aisle_width_m": args.min_aisle,
        },
        "benches": benches,
        "hydraulics": {
            "main_pipe_mm": args.main_pipe,
            "lateral_pipe_mm": args.lateral_pipe,
            "flow_per_channel_l_min": args.flow_per_channel,
            "terrain_slope_pct": args.terrain_slope,
        },
        "pump": {
            "efficiency": args.pump_efficiency,
            "model": args.pump_model,
            "reservoir_volume_l": args.reservoir,
        },
    }


def run_design(args: argparse.Namespace) -> int:
    inputs = load_design_file(args.config) if args.config else inputs_from_dict(_config_from_args(args))
    with warnings.catch_warnings():
        # Velocity issues are already listed in the summary's "Warnings" section.
        warnings.simplefilter("ignore", DesignWarning)
        design = design_greenhouse(inputs)
    print(design.summary())
    if args.bom or args.catalog:
        catalog = Catalog.from_csv(args.catalog) if args.catalog else None
        with pd.option_context("display.max_rows", None, "display.width", 120):
            print()
            print(design.bom_frame(catalog).to_string(index=False))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return run_design(args)
    except (DesignError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
