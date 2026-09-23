from pathlib import Path

import pytest

from hydroponics import DesignError, DesignWarning, HydraulicSettings, design_greenhouse, load_design_file
from hydroponics.cli import main, parse_bench
from hydroponics.design import DesignInputs, inputs_from_dict
from hydroponics.pump import PumpStationSettings, hydraulic_power_w, nominal_motor_size_cv, select_pump

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "greenhouse_51x48.toml"


def test_reference_design_flow_and_head(reference_inputs):
    with pytest.warns(DesignWarning):
        design = design_greenhouse(reference_inputs)
    hyd = design.hydraulics
    # 686 channels x 1.5 L/min = 61.74 m³/h; / 5 sectors x 1.3 = 16.052 m³/h
    assert hyd.total_flow_m3h == pytest.approx(61.74)
    assert hyd.sector_flow_m3h == pytest.approx(16.0524)
    # bench height + filter + suction + 6 % slope over 51 m
    assert hyd.static_head_m == pytest.approx(1.2 + 1.5 + 1.5 + 3.06)
    assert hyd.total_dynamic_head_m == pytest.approx(hyd.friction_head_m * 1.1 + hyd.static_head_m)
    assert {i.segment for i in hyd.velocity_issues} == {"Feed line", "Manifold", "Lateral"}


def test_upsized_pipes_clear_velocity_warnings(reference_inputs):
    inputs = DesignInputs(
        reference_inputs.greenhouse,
        reference_inputs.benches,
        HydraulicSettings(main_pipe_mm=60, lateral_pipe_mm=40, terrain_slope_pct=6.0),
    )
    design = design_greenhouse(inputs)
    assert design.warnings == []
    assert design.hydraulics.total_dynamic_head_m < 20


def test_pump_selection():
    # 36 m³/h = 0.01 m³/s against 20 m: rho g Q H = 1962 W
    assert hydraulic_power_w(36, 20) == pytest.approx(1962)
    pump = select_pump(36, 20, PumpStationSettings(efficiency=0.5))
    assert pump.shaft_power_w == pytest.approx(3924)
    assert pump.motor_cv == 6  # 5.34 cv -> next standard size
    assert nominal_motor_size_cv(735.0) == 1
    with pytest.raises(DesignError):
        nominal_motor_size_cv(1e6)
    with pytest.raises(DesignError):
        PumpStationSettings(efficiency=0)


def test_invalid_hydraulic_settings():
    with pytest.raises(DesignError):
        HydraulicSettings(main_pipe_mm=63)
    with pytest.raises(DesignError):
        HydraulicSettings(velocity_range_m_s=(2.0, 1.0))
    with pytest.raises(DesignError):
        HydraulicSettings(flow_safety_factor=0.9)


def test_example_file_matches_fixture(reference_inputs):
    loaded = load_design_file(EXAMPLE)
    assert loaded.greenhouse == reference_inputs.greenhouse
    assert [(g.bench, g.count) for g in loaded.benches] == [
        (g.bench, g.count) for g in reference_inputs.benches
    ]


def test_config_rejects_unknown_keys():
    with pytest.raises(DesignError, match="unknown key"):
        inputs_from_dict({"greenhouse": {"length_m": 10, "width_m": 8, "colour": "red"}, "benches": []})
    with pytest.raises(DesignError, match="needs"):
        inputs_from_dict({"greenhouse": {"length_m": 10, "width_m": 8}})


def test_summary_mentions_key_results(reference_inputs):
    with pytest.warns(DesignWarning):
        summary = design_greenhouse(reference_inputs).summary()
    assert "72 in 18/18 bench rows" in summary
    assert "16.05 m³/h per sector" in summary
    assert "DN60 or larger" in summary


def test_parse_bench():
    assert parse_bench("61:12:1.8:8:PS85:grow") == {
        "count": 61,
        "length_m": 12.0,
        "width_m": 1.8,
        "channels": 8,
        "profile": "PS85",
        "crop": "grow",
    }


def test_cli_design_with_defaults(capsys):
    assert main(["design", "--length", "50", "--width", "20", "--main-pipe", "75", "--bom"]) == 0
    out = capsys.readouterr().out
    assert "24 in 6/6 bench rows" in out
    assert "nft-channel-PS85" in out
    assert "Warnings" not in out


def test_cli_config_and_catalog(tmp_path, capsys):
    csv = tmp_path / "catalog.csv"
    csv.write_text("product;unit_price\nscrew;0.1\n")
    assert main(["design", "--config", str(EXAMPLE), "--catalog", str(csv)]) == 0
    out = capsys.readouterr().out
    assert "total_price" in out
    assert "Warnings" in out


def test_cli_reports_design_errors(capsys):
    assert main(["design", "--length", "50", "--width", "20", "--benches-per-bay", "4"]) == 2
    assert "below the minimum" in capsys.readouterr().err
    assert main(["design", "--width", "20"]) == 2


def test_feed_line_length_override(reference_inputs):
    def feed_line(settings):
        design = design_greenhouse(
            DesignInputs(reference_inputs.greenhouse, reference_inputs.benches, settings)
        )
        return next(s for s in design.hydraulics.segments if s.name == "Feed line"), design

    with pytest.warns(DesignWarning):
        default, default_design = feed_line(HydraulicSettings())
        short, short_design = feed_line(HydraulicSettings(feed_line_length_m=12.0))
    assert default.length_m == pytest.approx(48.0 + 10.0)
    assert short.length_m == pytest.approx(12.0)
    assert short_design.hydraulics.total_dynamic_head_m < default_design.hydraulics.total_dynamic_head_m


def test_negative_feed_line_length_rejected():
    with pytest.raises(DesignError):
        HydraulicSettings(feed_line_length_m=-1.0)
