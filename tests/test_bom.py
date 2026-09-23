import pandas as pd
import pytest

from hydroponics import BenchGroup, BillOfMaterials, BomItem, Catalog, design_greenhouse
from hydroponics.bom import bench_items


def test_items_with_same_product_are_summed():
    bom = BillOfMaterials()
    bom.add_item("screw", 10)
    bom.add_item("pvc-pipe-50mm", 3, unit="bar (6 m)")
    bom.add_item("screw", 5)
    assert len(bom) == 2
    assert bom["screw"].quantity == 15
    assert [i.product for i in bom] == ["screw", "pvc-pipe-50mm"]


def test_bom_does_not_share_state_between_instances():
    a, b = BillOfMaterials(), BillOfMaterials()
    a.add_item("screw", 1)
    assert "screw" not in b


def test_item_addition_rules():
    assert (BomItem("screw", 2) + BomItem("screw", 3)).quantity == 5
    with pytest.raises(ValueError, match="different products"):
        BomItem("screw", 1) + BomItem("nut", 1)
    with pytest.raises(ValueError, match="cannot add"):
        BomItem("pipe", 1, unit="m") + BomItem("pipe", 1, unit="bar (6 m)")
    with pytest.raises(ValueError):
        BomItem("screw", -1)


def test_bench_items(grow_bench):
    items = {i.product: i.quantity for i in bench_items(BenchGroup(grow_bench, 10))}
    assert items["bench-trestle-1.8m"] == 13 * 10  # one per metre + 1
    assert items["nft-channel-PS85"] == 16 * 10
    assert items["channel-end-cap-PS85"] == 8 * 10
    assert items["screw"] == 13 * 8 * 10


@pytest.mark.filterwarnings("ignore::hydroponics.errors.DesignWarning")
def test_reference_bom(reference_inputs):
    bom = design_greenhouse(reference_inputs).bom
    # screws are shared by both bench types and aggregated into one line
    assert bom["screw"].quantity == 13 * (61 * 8 + 11 * 18)
    assert bom["pvc-reducing-tee-50x32mm"].quantity == 24
    assert bom["pvc-reducing-tee-32x25mm"].quantity == 72
    assert bom["pvc-pipe-50mm"].quantity == 55  # ((51 + 5) * 5 + 48) / 6
    assert bom["pvc-pipe-32mm"].quantity == 32  # 24 laterals * 8 m / 6
    assert bom["drain-tee-75mm"].quantity == 67
    assert bom["reservoir-3000l"].quantity == 5


def test_to_frame_without_catalog():
    bom = BillOfMaterials([BomItem("screw", 4, category="Benches")])
    frame = bom.to_frame()
    assert list(frame.columns) == ["category", "product", "quantity", "unit"]
    assert frame["quantity"].tolist() == [4]


def test_to_frame_with_catalog(tmp_path, caplog):
    csv = tmp_path / "catalog.csv"
    csv.write_text("Product;Code;Description;Unit_Price\n screw ;001;Screw 4x40;0,10\npipe;002;Pipe;25\n")
    catalog = Catalog.from_csv(csv)
    bom = BillOfMaterials([BomItem("screw", 100), BomItem("pipe", 2), BomItem("glue", 1)])
    frame = bom.to_frame(catalog).set_index("product")
    assert frame.loc["screw", "code"] == "001"
    assert frame.loc["screw", "total_price"] == pytest.approx(10.0)
    assert frame.loc["pipe", "total_price"] == pytest.approx(50.0)
    assert pd.isna(frame.loc["glue", "unit_price"])
    assert "glue" in caplog.text


def test_catalog_without_prices_and_comma_delimiter(tmp_path):
    csv = tmp_path / "catalog.csv"
    csv.write_text("product,code\nscrew,A1\n")
    catalog = Catalog.from_csv(csv)
    assert catalog.lookup("screw") == {"code": "A1"}
    assert catalog.lookup("nut") is None
    frame = BillOfMaterials([BomItem("screw", 1)]).to_frame(catalog)
    assert "total_price" not in frame.columns


def test_catalog_validation():
    with pytest.raises(ValueError, match="required column"):
        Catalog(pd.DataFrame({"code": ["1"]}))
    with pytest.raises(ValueError, match="duplicated"):
        Catalog(pd.DataFrame({"product": ["a", "a"]}))
