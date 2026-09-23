"""Optional product catalog used to attach codes and prices to the bill of materials.

The catalog is a user-supplied CSV file (it is not shipped with the project).
Expected columns (header names are case-insensitive):

============  ========  ==================================================
column        required  meaning
============  ========  ==================================================
product       yes       BOM product key, e.g. ``pvc-pipe-50mm``
code          no        supplier / ERP product code
description   no        human-readable description
unit_price    no        price per BOM unit (``.`` or ``,`` decimal mark)
============  ========  ==================================================

The delimiter (``,`` or ``;``) is detected automatically.
"""

from __future__ import annotations

import logging
from os import PathLike
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS: tuple[str, ...] = ("product",)
OPTIONAL_COLUMNS: tuple[str, ...] = ("code", "description", "unit_price")


class Catalog:
    """In-memory product catalog indexed by BOM product key."""

    def __init__(self, entries: pd.DataFrame) -> None:
        frame = entries.rename(columns=lambda c: str(c).strip().lower())
        missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
        if missing:
            raise ValueError(f"Catalog is missing required column(s): {', '.join(missing)}")
        frame = frame[[c for c in (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS) if c in frame.columns]].copy()
        frame["product"] = frame["product"].astype(str).str.strip()
        duplicated = frame["product"][frame["product"].duplicated()].unique()
        if len(duplicated):
            raise ValueError(f"Catalog has duplicated products: {', '.join(duplicated)}")
        if "code" in frame.columns:
            frame["code"] = frame["code"].astype("string").str.strip()
        if "unit_price" in frame.columns:
            prices = frame["unit_price"].astype(str).str.strip().str.replace(",", ".", regex=False)
            frame["unit_price"] = pd.to_numeric(prices.replace({"": None, "nan": None}))
        self._frame = frame.set_index("product")

    @classmethod
    def from_csv(cls, path: str | PathLike[str]) -> Catalog:
        """Load a catalog CSV (``,`` or ``;`` delimited)."""
        path = Path(path)
        frame = pd.read_csv(path, sep=None, engine="python", dtype=str, keep_default_na=False)
        catalog = cls(frame)
        logger.info("Loaded %d catalog entries from %s", len(catalog), path)
        return catalog

    def __len__(self) -> int:
        return len(self._frame)

    def __contains__(self, product: object) -> bool:
        return product in self._frame.index

    @property
    def columns(self) -> list[str]:
        return list(self._frame.columns)

    def lookup(self, product: str) -> dict[str, object] | None:
        """Catalog fields for ``product``, or ``None`` if it is not listed."""
        if product not in self._frame.index:
            return None
        return self._frame.loc[product].to_dict()

    def enrich(self, bom: pd.DataFrame) -> pd.DataFrame:
        """Join catalog fields onto a BOM frame and compute line totals.

        Products missing from the catalog keep empty catalog fields and are
        reported with a single warning.
        """
        missing = sorted(set(bom["product"]) - set(self._frame.index))
        if missing:
            logger.warning("%d BOM product(s) not found in catalog: %s", len(missing), ", ".join(missing))
        merged = bom.merge(self._frame, how="left", left_on="product", right_index=True)
        if "unit_price" in merged.columns:
            merged["total_price"] = merged["quantity"] * merged["unit_price"]
        return merged
