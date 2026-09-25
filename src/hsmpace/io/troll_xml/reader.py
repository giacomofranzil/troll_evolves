"""Map a TRoll ProcessData dump onto the canonical Case.

TRoll units in the dump: thicknesses and widths mm, lengths and positions m,
temperatures °C, slab weight t, input speeds m/min, predicted speeds m/s,
SpeedHead/SpeedTail/roll surface rpm (ignored), SpeedUpAccel m/min/s.
Cooling banks are omitted in P1. Coilers are omitted: add them in Excel after
import. Coilbox coiling speed defaults to the last rougher exit, uncoiling to
F1 entry.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ...core.model import (
    FWD,
    KIND_COILBOX,
    KIND_MARKER,
    KIND_STAND,
    KIND_START,
    MILL_HSM,
    REV,
    Case,
    Equipment,
    Line,
    Product,
    RollingPass,
    Section,
    SimSettings,
    SpeedEvent,
)

_XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"

_STAND_TYPES = frozenset({"RoughingStand", "FinishingStand"})
_COILBOX_TYPES = frozenset({"CoilBox"})
_SKIP_TYPE_PREFIXES = ("Cool",)

_START_ID = "FURN"


class TrollImportError(ValueError):
    """The dump cannot be mapped onto a Case."""


def case_from_troll(path: str | Path) -> Case:
    """Map a TRoll XML dump onto the canonical Case."""
    xml_path = Path(path)
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError as exc:
        raise TrollImportError(f"invalid TRoll XML ({xml_path}): {exc}") from exc
    if root.tag != "ProcessData":
        raise TrollImportError(
            f"unrecognised TRoll root {root.tag!r}, expected ProcessData"
        )
    return _case_from_root(root, xml_path.name)


def _leaf(parent: ET.Element | None, tag: str, default: str | None = None) -> str | None:
    if parent is None:
        return default
    el = parent.find(tag)
    if el is None:
        return default
    if el.get(_XSI_NIL) == "true":
        return default
    text = (el.text or "").strip()
    if not text or text.lower() == "nan":
        return default
    return text


def _float(parent: ET.Element | None, tag: str, default: float | None = None) -> float | None:
    raw = _leaf(parent, tag)
    if raw is None:
        return default
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return default


def _bool_text(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() == "true"


def _case_from_root(root: ET.Element, source_name: str) -> Case:
    plant = root.find("PlantData")
    if plant is None:
        raise TrollImportError("TRoll dump has no PlantData")
    plant_name = plant.get("PlantName") or "TRoll mill"
    tunnel = _bool_text(_leaf(plant, "HasTunnelFurnace"), default=False)
    reverse_time = _float(plant, "ReverseTime", 0.0) or 0.0
    reverse_len = _float(plant, "ReverseLength", 0.0) or 0.0
    furnace_mpm = _float(plant, "FurnaceTranspSpeed")
    # PlantData has no furnace speed; SlabData does. Filled per product below.
    _ = furnace_mpm

    devices_el = root.find("Devices")
    if devices_el is None or not list(devices_el):
        raise TrollImportError("TRoll dump has no Devices")

    by_id: dict[str, ET.Element] = {}
    equipment: list[Equipment] = [
        Equipment(_START_ID, KIND_START, 0.0, label="Furnace"),
    ]
    x = 0.0
    skipped_cooling = 0
    last_rolling_id = ""
    for dev in devices_el:
        did = dev.get("DeviceID") or ""
        by_id[did] = dev
        x += _float(dev.find("EntryData"), "DistanceFromPreviousDevice", 0.0) or 0.0
        dtype = dev.get("DeviceType") or ""
        name = (dev.get("DeviceName") or f"D{did}").strip()
        label = (dev.get("DeviceTypeName") or name).strip()
        flags = dev.find("DeviceFlags")
        if flags is not None and flags.get("IsLastRollingDevice") == "true":
            last_rolling_id = name
        if dtype.startswith(_SKIP_TYPE_PREFIXES):
            skipped_cooling += 1
            continue
        if dtype in _STAND_TYPES:
            group = "FM" if dtype == "FinishingStand" else ""
            equipment.append(
                Equipment(name, KIND_STAND, x, accel=1.0, group=group, label=label)
            )
        elif dtype in _COILBOX_TYPES:
            equipment.append(Equipment(name, KIND_COILBOX, x, accel=1.0, label=label))
        else:
            equipment.append(Equipment(name, KIND_MARKER, x, label=label))

    if not any(e.kind == KIND_STAND for e in equipment):
        raise TrollImportError("TRoll dump has no rolling stands")

    pieces_el = root.find("Pieces")
    if pieces_el is None or not list(pieces_el):
        raise TrollImportError("TRoll dump has no Pieces")

    products: list[Product] = []
    furnace_mps = 0.0
    for piece in pieces_el:
        product, slab_furnace_mpm = _product_from_piece(
            piece,
            by_id,
            last_rolling_id=last_rolling_id,
            reverse_time=reverse_time,
            reverse_len=reverse_len,
            has_coilbox=any(e.kind == KIND_COILBOX for e in equipment),
        )
        products.append(product)
        if slab_furnace_mpm and not furnace_mps:
            furnace_mps = slab_furnace_mpm / 60.0

    if not furnace_mps:
        first_stand = next(e for e in equipment if e.kind == KIND_STAND)
        first_pass = next(
            (rp for rp in products[0].passes if rp.equipment_id == first_stand.id),
            products[0].passes[0],
        )
        furnace_mps = first_pass.v_entry

    max_slab = max(p.slab_len for p in products)
    x_lo = min(0.0, -max_slab)
    x_hi = max(e.x for e in equipment)
    section = Section(
        "S1",
        x_start=x_lo,
        length=max(x_hi - x_lo, 1.0),
        label="Line",
        events=(
            SpeedEvent(
                "S1-1",
                "S1",
                x_trigger=0.0,
                v_target=furnace_mps,
                direction=FWD,
            ),
        ),
    )

    remarks = [
        f"Imported from TRoll XML ({source_name}). Add coiler rows (kind=coiler, x_m) "
        "before pinning and tail slowdown.",
    ]
    if skipped_cooling:
        remarks.append(
            f"{skipped_cooling} cooling banks omitted (not imported in this version)."
        )
    if any(e.kind == KIND_COILBOX for e in equipment):
        remarks.append(
            "Coilbox coiling speed = last rougher PredictedExitSpeedHead; "
            "uncoiling = F1 PredictedEntrySpeedHead."
        )

    settings = SimSettings(
        n_pieces=1,
        tunnel_furnace=tunnel,
    )
    return Case(
        line=Line(tuple(equipment), (section,)),
        products=tuple(products),
        settings=settings,
        mill_type=MILL_HSM,
        info={
            "schema_version": "1",
            "mill_type": MILL_HSM,
            "mill_name": plant_name,
            "notes": f"Imported from {source_name}",
        },
        warnings=tuple(remarks),
    )


def _product_from_piece(
    piece: ET.Element,
    by_id: dict[str, ET.Element],
    *,
    last_rolling_id: str,
    reverse_time: float,
    reverse_len: float,
    has_coilbox: bool,
) -> tuple[Product, float]:
    pid = (piece.get("PieceName") or piece.get("PieceID") or "P").strip()
    slab = piece.find("SlabData")
    speedup = piece.find("SpeedupData")
    slab_thk = _float(slab, "SlabThickn")
    slab_wid = _float(slab, "SlabWidth")
    slab_len = _float(slab, "SlabLength")
    if slab_thk is None or slab_wid is None or slab_len is None:
        raise TrollImportError(f"piece {pid}: missing slab dimensions")
    furnace_mpm = _float(slab, "FurnaceTranspSpeed", 0.0) or 0.0

    zoom_pct = _float(speedup, "FinalSpeedUpIncrement", 0.0) or 0.0
    zoom_trigger = _float(speedup, "InitialSpeedUpLenght", 0.0) or 0.0
    zoom_accel_raw = _float(speedup, "SpeedUpAccel")
    zoom_accel = (zoom_accel_raw / 60.0) if zoom_accel_raw else None

    stand_passes: list[tuple[ET.Element, str, str]] = []
    pass_list = piece.find("PassList")
    if pass_list is None:
        raise TrollImportError(f"piece {pid}: no PassList")
    for pas in pass_list:
        did = pas.get("DeviceID") or ""
        dev = by_id.get(did)
        dtype = (dev.get("DeviceType") if dev is not None else "") or ""
        name = (pas.get("DeviceName") or (dev.get("DeviceName") if dev is not None else "") or "").strip()
        if dtype not in _STAND_TYPES:
            continue
        stand_passes.append((pas, name, dtype))
    if not stand_passes:
        raise TrollImportError(f"piece {pid}: no stand passes")

    rolling: list[RollingPass] = []
    for i, (pas, name, dtype) in enumerate(stand_passes, start=1):
        geo = pas.find("GeometricalData")
        spd = pas.find("SpeedData")
        flags = pas.find("PassFlags")
        h_in = _float(geo, "PredictedEntryThickn")
        h_out = _float(geo, "PredictedExitThickn")
        w_in = _float(geo, "PredictedEntryWidth")
        w_out = _float(geo, "PredictedExitWidth")
        v_exit = _float(spd, "PredictedExitSpeedHead")
        if h_in is None or h_out is None or w_in is None or w_out is None or v_exit is None:
            raise TrollImportError(f"piece {pid} pass {i}: missing predicted geometry or speed")
        if dtype == "FinishingStand":
            direction = FWD
        else:
            upstream = _bool_text(_leaf(flags, "MovingUpStream"))
            direction = REV if upstream else FWD

        delay = 0.0
        clearance = 0.0
        if i < len(stand_passes):
            nxt, nxt_name, _nxt_type = stand_passes[i]
            if nxt_name == name:
                nxt_flags = nxt.find("PassFlags")
                nxt_time = nxt.find("TimeData")
                this_time = pas.find("TimeData")
                delay = (
                    _float(this_time, "PredictedPassReversingTime")
                    or _float(nxt_time, "PredictedPassReversingTime")
                    or reverse_time
                )
                dev = by_id.get(pas.get("DeviceID") or "")
                proc = dev.find("ProcessData") if dev is not None else None
                nxt_up = _bool_text(_leaf(nxt_flags, "MovingUpStream"))
                if nxt_up:
                    clearance = _float(proc, "ReversingLenUpStream", reverse_len) or reverse_len
                else:
                    clearance = _float(proc, "ReversingLenDownStream", reverse_len) or reverse_len

        is_zoom = name == last_rolling_id
        if not last_rolling_id and dtype == "FinishingStand":
            later_fm = any(t == "FinishingStand" for _p, _n, t in stand_passes[i:])
            is_zoom = not later_fm
        rolling.append(
            RollingPass(
                product_id=pid,
                pass_no=i,
                equipment_id=name,
                direction=direction,
                h_in=h_in,
                h_out=h_out,
                w_in=w_in,
                w_out=w_out,
                v_exit=v_exit,
                reversing_delay=delay,
                reversing_clearance=clearance,
                zoom_pct=zoom_pct if is_zoom else 0.0,
                zoom_trigger=zoom_trigger if is_zoom else 0.0,
                zoom_accel=zoom_accel if is_zoom else None,
            )
        )

    last_rm = next((rp for rp in reversed(rolling) if _is_rougher(rp, stand_passes)), None)
    first_fm = next((rp for rp in rolling if _is_finisher(rp, stand_passes)), None)
    v_coil = last_rm.v_exit if last_rm is not None else 0.0
    v_uncoil = 0.0
    if first_fm is not None:
        pas_fm = next(p for p, n, _t in stand_passes if n == first_fm.equipment_id)
        v_uncoil = _float(pas_fm.find("SpeedData"), "PredictedEntrySpeedHead", first_fm.v_entry) or 0.0

    product = Product(
        id=pid,
        slab_thk=slab_thk,
        slab_wid=slab_wid,
        slab_len=slab_len,
        label=pid,
        grade=(piece.get("PlantMaterialName") or "").strip(),
        passes=tuple(rolling),
        use_coilbox=True if has_coilbox else None,
        coilbox_v_coil=v_coil if has_coilbox else 0.0,
        coilbox_v_uncoil=v_uncoil if has_coilbox else 0.0,
    )
    return product, furnace_mpm


def _is_rougher(rp: RollingPass, stand_passes: list[tuple[ET.Element, str, str]]) -> bool:
    for _pas, name, dtype in stand_passes:
        if name == rp.equipment_id:
            return dtype == "RoughingStand"
    return False


def _is_finisher(rp: RollingPass, stand_passes: list[tuple[ET.Element, str, str]]) -> bool:
    for _pas, name, dtype in stand_passes:
        if name == rp.equipment_id:
            return dtype == "FinishingStand"
    return False
