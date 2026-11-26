"""TRoll XML → Case mapper."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from hsmpace.core.contract import case_from_dict, case_to_dict
from hsmpace.core.model import FWD, REV, KIND_COILER, KIND_START, validate_case
from hsmpace.core.simulate import simulate_piece
from hsmpace.io.excel import write_case, read_case
from hsmpace.io.troll_xml import case_from_troll

FIXTURE = Path(__file__).parent / "data" / "troll_cbx.xml"
# a full TRoll dump is plant data and stays out of the repository: point this
# variable at one to run the check against it
REAL_CBX = Path(os.environ.get("HSMPACE_REAL_TROLL_XML", "/tmp/troll-xml2/real_cbx_dump.xml"))


def test_troll_fixture_maps_layout_without_coilers_or_cooling():
    case = case_from_troll(FIXTURE)
    ids = [e.id for e in case.line.equipment]
    kinds = {e.id: e.kind for e in case.line.equipment}

    assert ids[0] == "FURN" and kinds["FURN"] == KIND_START
    assert case.line.get("FURN").x == 0.0
    assert case.line.get("R1").x == pytest.approx(100.0)
    assert case.line.get("R2").x == pytest.approx(178.0)
    assert case.line.get("CBX").x == pytest.approx(256.0)
    assert case.line.get("CBX").kind == "coilbox"
    assert case.line.get("WD2").kind == "marker"
    assert case.line.get("F1").kind == "stand" and case.line.get("F1").group == "FM"
    assert case.line.get("F7").x == pytest.approx(283.5)
    assert case.line.get("RT1").kind == "marker"
    assert "PL1" not in kinds
    assert not any(e.kind == KIND_COILER for e in case.line.equipment)
    assert case.settings.tunnel_furnace is False
    assert any("coiler" in w.lower() for w in case.warnings)
    assert any("cooling" in w.lower() for w in case.warnings)


def test_troll_fixture_pass_schedule_uses_predicted_head_exit_speed():
    case = case_from_troll(FIXTURE)
    p = case.products[0]
    assert p.id == "P1"
    assert p.slab_thk == 220.0 and p.slab_wid == 1200.0 and p.slab_len == 12.0
    assert p.grade == "Grade A"

    r1a, r1b, r2, f1, f7 = p.passes
    assert r1a.equipment_id == "R1" and r1a.direction == FWD
    assert r1a.h_out == 150.0 and r1a.w_out == 1210.0 and r1a.v_exit == 2.5
    assert r1a.reversing_delay == pytest.approx(3.0)
    assert r1a.reversing_clearance == pytest.approx(6.0)

    assert r1b.equipment_id == "R1" and r1b.direction == REV
    assert r1b.v_exit == 3.0
    assert r1b.reversing_delay == 0.0

    assert r2.equipment_id == "R2" and r2.direction == FWD and r2.v_exit == 5.0
    assert f1.equipment_id == "F1" and f1.direction == FWD and f1.v_exit == 2.0
    assert f7.equipment_id == "F7" and f7.direction == FWD
    assert f7.v_exit == 8.0
    assert f7.h_out == 4.0 and f7.w_out == 1212.0
    assert f7.zoom_trigger == pytest.approx(100.0)
    assert f7.zoom_pct == pytest.approx(-7.0)
    assert f7.zoom_accel == pytest.approx(10.0 / 60.0)
    assert f1.zoom_pct == 0.0


def test_troll_coilbox_defaults_from_last_rougher_and_f1_entry():
    case = case_from_troll(FIXTURE)
    p = case.products[0]
    assert p.use_coilbox is True
    assert p.coilbox_v_coil == pytest.approx(5.0)
    assert p.coilbox_v_uncoil == pytest.approx(1.2)


def _without_coilbox(tmp_path, drop_f1_entry_speed: bool = False) -> Path:
    """The fixture with the coilbox taken out of the line, as in a bypass dump.

    The transfer table is stretched to 157 m so that the 66 m bar is free of R2
    before it reaches F1, as on a line built without a coilbox.
    """
    tree = ET.parse(FIXTURE)
    root = tree.getroot()
    devices = root.find("Devices")
    for dev in list(devices):
        if dev.get("DeviceType") == "CoilBox":
            devices.remove(dev)
        elif dev.get("DeviceName") == "WD2":
            dev.find("EntryData").find("DistanceFromPreviousDevice").text = "150"
    for piece in root.find("Pieces"):
        passes = piece.find("PassList")
        for pas in list(passes):
            if pas.get("DeviceName") == "CBX":
                passes.remove(pas)
            elif pas.get("DeviceName") == "F1" and drop_f1_entry_speed:
                speed = pas.find("SpeedData")
                speed.remove(speed.find("PredictedEntrySpeedHead"))
    path = tmp_path / "troll_bypass.xml"
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path


def test_troll_with_a_coilbox_leaves_the_f1_approach_to_uncoiling():
    case = case_from_troll(FIXTURE)
    assert all(rp.approach_v is None for rp in case.products[0].passes)
    assert not any("approach_v_mps" in w for w in case.warnings)


def test_troll_without_a_coilbox_puts_the_f1_entry_speed_on_the_f1_pass(tmp_path):
    case = case_from_troll(_without_coilbox(tmp_path))
    p = case.products[0]
    r1a, r1b, r2, f1, f7 = p.passes

    assert not any(e.kind == "coilbox" for e in case.line.equipment)
    assert p.use_coilbox is None and p.coilbox_v_uncoil == 0.0
    # TRoll PredictedEntrySpeedHead of F1, per product
    assert f1.approach_v == pytest.approx(1.2)
    assert all(rp.approach_v is None for rp in (r1a, r1b, r2, f7))
    assert any("approach_v_mps on the first finishing pass" in w for w in case.warnings)
    assert [pr for pr in validate_case(case) if not pr.is_warning] == []


def test_troll_without_a_coilbox_slows_the_bar_to_f1_entry_speed(tmp_path):
    case = case_from_troll(_without_coilbox(tmp_path))
    res = simulate_piece(case, case.products[0])
    bite = next(e for e in res.events if e.kind == "bite" and e.equipment_id == "F1")

    # the bar leaves R2 at 5 m/s and reaches F1 at the imported entry speed
    assert res.head.v_at(bite.t - 5.0) == pytest.approx(5.0)
    assert res.head.v_at(bite.t - 1e-6) == pytest.approx(1.2, abs=1e-4)


def test_troll_f1_approach_falls_back_to_the_mass_flow_entry_speed(tmp_path):
    case = case_from_troll(_without_coilbox(tmp_path, drop_f1_entry_speed=True))
    f1 = next(rp for rp in case.products[0].passes if rp.equipment_id == "F1")

    assert f1.approach_v == pytest.approx(f1.v_entry)
    res = simulate_piece(case, case.products[0])
    bite = next(e for e in res.events if e.kind == "bite" and e.equipment_id == "F1")
    assert res.head.v_at(bite.t + 1e-6) == pytest.approx(f1.v_exit, abs=1e-4)
    assert not any("on F1" in w for w in res.warnings)


def test_troll_f1_approach_round_trips_through_excel(tmp_path):
    from hsmpace.io.troll_xml import write_troll_case

    dest = tmp_path / "bypass.xlsx"
    write_troll_case(_without_coilbox(tmp_path), dest, source_name="bypass.xml")
    loaded = read_case(dest)
    f1 = next(rp for rp in loaded.products[0].passes if rp.equipment_id == "F1")

    assert f1.approach_v == pytest.approx(1.2)
    assert "approach_v_mps on the first finishing pass" in (loaded.info.get("notes") or "")


def test_source_name_is_used_in_import_warnings():
    case = case_from_troll(FIXTURE, source_name="uploaded_dump.xml")
    assert any("uploaded_dump.xml" in w for w in case.warnings)
    assert not any(FIXTURE.name in w for w in case.warnings)


def test_walking_beam_releases_the_slab_midpoint_at_the_furnace():
    case = case_from_troll(FIXTURE)
    res = simulate_piece(case, case.products[0])
    assert res.head.x_at(0.0) == pytest.approx(6.0)
    assert res.tail.x_at(0.0) == pytest.approx(-6.0)
    assert res.coiler_id == ""
    assert res.x_coiler is None
    assert any(e.kind == "coilbox_in" for e in res.events)


def test_troll_case_round_trips_through_excel_and_json(tmp_path):
    original = case_from_troll(FIXTURE)
    loaded = read_case(write_case(original, tmp_path / "from_troll.xlsx"))
    assert loaded.settings.tunnel_furnace is False
    assert loaded.line.get("CBX").kind == "coilbox"
    assert loaded.products[0].coilbox_v_coil == pytest.approx(5.0)
    assert not any(e.kind == KIND_COILER for e in loaded.line.equipment)

    payload = case_to_dict(original)
    again = case_from_dict(payload)
    assert again.settings.tunnel_furnace is False
    assert payload["settings"]["tunnel_furnace"] is False


def test_json_without_tunnel_furnace_defaults_to_tunnel():
    payload = case_to_dict(case_from_troll(FIXTURE))
    del payload["settings"]["tunnel_furnace"]
    loaded = case_from_dict(payload)
    assert loaded.settings.tunnel_furnace is True


def test_unknown_troll_root_is_rejected(tmp_path):
    path = tmp_path / "other.xml"
    path.write_text("<NotProcessData/>", encoding="utf-8")
    with pytest.raises(ValueError, match="ProcessData"):
        case_from_troll(path)


def test_imported_case_has_no_blocking_model_errors():
    case = case_from_troll(FIXTURE)
    blocking = [p for p in validate_case(case) if not p.is_warning]
    assert blocking == []


@pytest.mark.skipif(not REAL_CBX.exists(), reason="full TRoll dump not in this environment")
def test_real_cbx_dump_maps_r1_r2_coilbox_and_skips_cooling():
    case = case_from_troll(REAL_CBX)
    assert case.line.get("R1").kind == "stand"
    assert case.line.get("R2").kind == "stand"
    assert case.line.get("CBX").kind == "coilbox"
    assert case.line.get("F7").kind == "stand"
    assert not any(e.id.startswith("PL") for e in case.line.equipment)
    assert not any(e.kind == KIND_COILER for e in case.line.equipment)
    p = next(pr for pr in case.products if pr.id == "01PROD")
    last_rm = next(rp for rp in reversed(p.passes) if rp.equipment_id == "R2")
    first_fm = next(rp for rp in p.passes if rp.equipment_id == "F1")
    piece = next(
        el
        for el in ET.parse(REAL_CBX).getroot().find("Pieces")
        if (el.get("PieceName") or el.get("PieceID")) == "01PROD"
    )
    f1_entry = float(
        next(pas for pas in piece.find("PassList") if pas.get("DeviceName") == "F1")
        .find("SpeedData")
        .findtext("PredictedEntrySpeedHead")
    )
    assert p.coilbox_v_coil == pytest.approx(last_rm.v_exit)
    assert p.coilbox_v_uncoil == pytest.approx(f1_entry)
    assert first_fm.direction == FWD
    assert all(rp.direction == FWD for rp in p.passes if rp.equipment_id.startswith("F"))


def test_write_troll_case_is_the_import_artefact(tmp_path):
    from hsmpace.io.troll_xml import write_troll_case

    dest = tmp_path / "mapped.xlsx"
    write_troll_case(FIXTURE, dest, source_name="troll_cbx.xml")
    loaded = read_case(dest)
    notes = loaded.info.get("notes") or ""
    assert "Imported from TRoll XML (troll_cbx.xml)" in notes
    assert "cooling" in notes.lower()
    assert loaded.line.get("CBX").kind == "coilbox"
    assert loaded.products[0].coilbox_v_coil == pytest.approx(5.0)
    assert loaded.products[0].coilbox_v_uncoil == pytest.approx(1.2)
    assert not any(e.kind == KIND_COILER for e in loaded.line.equipment)


def test_cli_import_writes_workbook_and_run_rejects_xml(tmp_path, capsys):
    from hsmpace.cli import main

    dest = tmp_path / "from_cli.xlsx"
    assert main(["import", str(FIXTURE), str(dest)]) == 0
    assert dest.exists()
    out = capsys.readouterr().out
    assert "mapped workbook" in out.lower() or "Written the mapped workbook" in out

    assert main(["run", str(FIXTURE)]) == 1
    err = capsys.readouterr().err
    assert "not a simulation input" in err
    assert main(["to-json", str(FIXTURE)]) == 1
    err = capsys.readouterr().err
    assert "not a simulation input" in err
