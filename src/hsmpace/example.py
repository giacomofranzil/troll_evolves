"""Example case: conventional Hot Strip Mill.

Layout with a two stand reversing roughing mill with edgers, heat conservation
panels, crop shear, seven stand finishing mill and three in-line downcoilers.
The numbers are plausible but invented: they serve to run the tool and to show
the format, they do not describe a real plant.
"""

from __future__ import annotations

from .core.model import (
    FWD,
    REV,
    Case,
    Equipment,
    Line,
    Product,
    RollingPass,
    Section,
    SimSettings,
    SpeedEvent,
    UtilityRecipe,
    WHEN_OCCUPY,
    WHEN_ROLLING,
)

_EQUIPMENT = [
    Equipment("FURN", "start", 0.0, label="Furnace exit"),
    Equipment("DS1", "marker", 15.0, label="Primary descaler", occupy=True, occupy_before=2.0, occupy_after=2.0),
    Equipment("E1", "marker", 40.5, label="Edger E1"),
    Equipment("R1", "stand", 45.0, accel=1.5, label="Roughing stand R1"),
    Equipment("E2", "marker", 125.5, label="Edger E2"),
    Equipment("R2", "stand", 130.0, accel=1.5, label="Roughing stand R2"),
    Equipment("HC_en", "marker", 152.5, label="Passive panels entry"),
    Equipment("HC_ex", "marker", 234.5, label="Passive panels exit"),
    Equipment("SHR", "marker", 252.5, label="Crop shear"),
    Equipment("DS2", "marker", 257.5, label="Finishing descaler", occupy=True, occupy_before=1.5, occupy_after=1.5),
    Equipment("F1", "stand", 261.5, accel=1.5, group="FM", label="F1"),
    Equipment("F2", "stand", 267.0, accel=1.5, group="FM", label="F2"),
    Equipment("F3", "stand", 272.5, accel=1.5, group="FM", label="F3"),
    Equipment("F4", "stand", 278.0, accel=1.5, group="FM", label="F4"),
    Equipment("F5", "stand", 283.5, accel=1.5, group="FM", label="F5"),
    Equipment("F6", "stand", 289.0, accel=1.5, group="FM", label="F6"),
    Equipment("F7", "stand", 294.5, accel=1.5, group="FM", label="F7"),
    Equipment("DC1", "coiler", 418.0, accel=0.5, label="DC1"),
    Equipment("DC2", "coiler", 427.0, accel=0.5, label="DC2"),
    Equipment("DC3", "coiler", 436.0, accel=0.5, label="DC3"),
]

_UTILITIES = [
    UtilityRecipe("DS1", "water", 120.0, WHEN_OCCUPY),
    UtilityRecipe("DS2", "water", 80.0, WHEN_OCCUPY),
    UtilityRecipe("R1", "power", 8000.0, WHEN_ROLLING),
    UtilityRecipe("R2", "power", 9000.0, WHEN_ROLLING),
    UtilityRecipe("F1", "power", 6000.0, WHEN_ROLLING),
    UtilityRecipe("F2", "power", 5500.0, WHEN_ROLLING),
    UtilityRecipe("F3", "power", 5000.0, WHEN_ROLLING),
    UtilityRecipe("F4", "power", 4500.0, WHEN_ROLLING),
    UtilityRecipe("F5", "power", 4000.0, WHEN_ROLLING),
    UtilityRecipe("F6", "power", 3500.0, WHEN_ROLLING),
    UtilityRecipe("F7", "power", 3000.0, WHEN_ROLLING),
]

_SECTIONS = [
    Section(
        "S1",
        x_start=0.0,
        length=45.0,
        label="Furnace to R1",
        events=(
            SpeedEvent("S1-1", "S1", x_trigger=0.0, v_target=1.2, direction=FWD),
        ),
    ),
    Section("S2", x_start=45.0, length=85.0, label="R1 to R2"),
    Section(
        "S3",
        x_start=130.0,
        length=122.5,
        label="Transfer table",
        events=(
            SpeedEvent("S3-1", "S3", x_trigger=135.0, v_target=5.0, direction=FWD),
            SpeedEvent("S3-2", "S3", x_trigger=225.0, v_target=1.0, direction=FWD),
        ),
    ),
    Section("S4", x_start=252.5, length=9.0, label="Shear to F1"),
    Section("S5", x_start=261.5, length=180.0, label="Finishing mill to coilers"),
]


def _passes(product_id: str, rows: list[tuple]) -> tuple[RollingPass, ...]:
    out = []
    for (
        pass_no,
        stand,
        direction,
        h_in,
        h_out,
        w_in,
        w_out,
        v_exit,
        delay,
        clearance,
        master,
        zoom_pct,
        zoom_trigger,
    ) in rows:
        out.append(
            RollingPass(
                product_id=product_id,
                pass_no=pass_no,
                equipment_id=stand,
                direction=direction,
                h_in=h_in,
                h_out=h_out,
                w_in=w_in,
                w_out=w_out,
                v_exit=v_exit,
                reversing_delay=delay,
                reversing_clearance=clearance,
                master=master,
                zoom_pct=zoom_pct,
                zoom_trigger=zoom_trigger,
            )
        )
    return tuple(out)


# delay and clearance describe the reversal that FOLLOWS the pass on the same
# row, so the last pass of each reversing stand carries none.
_P1 = [
    (1, "R1", FWD, 230.0, 185.0, 1120.0, 1130.8, 2.0, 3.0, 4.0, False, 0.0, 0.0),
    (2, "R1", REV, 185.0, 140.0, 1130.8, 1141.6, 3.0, 3.0, 6.0, False, 0.0, 0.0),
    (3, "R1", FWD, 140.0, 103.0, 1141.6, 1150.4, 4.0, 0.0, 0.0, False, 0.0, 0.0),
    (4, "R2", FWD, 103.0, 75.0, 1150.4, 1157.1, 4.5, 3.0, 4.0, False, 0.0, 0.0),
    (5, "R2", REV, 75.0, 52.0, 1157.1, 1162.5, 4.8, 3.0, 6.0, False, 0.0, 0.0),
    (6, "R2", FWD, 52.0, 35.0, 1162.5, 1166.5, 5.2, 0.0, 0.0, False, 0.0, 0.0),
    (7, "F1", FWD, 35.0, 17.0, 1166.5, 1170.8, 0.86, 0.0, 0.0, False, 0.0, 0.0),
    (8, "F2", FWD, 17.0, 8.0, 1170.8, 1172.9, 1.83, 0.0, 0.0, False, 0.0, 0.0),
    (9, "F3", FWD, 8.0, 4.6, 1172.9, 1173.7, 3.18, 0.0, 0.0, False, 0.0, 0.0),
    (10, "F4", FWD, 4.6, 3.0, 1173.7, 1174.1, 4.87, 0.0, 0.0, False, 0.0, 0.0),
    (11, "F5", FWD, 3.0, 1.9, 1174.1, 1174.3, 7.69, 0.0, 0.0, False, 0.0, 0.0),
    (12, "F6", FWD, 1.9, 1.44, 1174.3, 1174.4, 10.14, 0.0, 0.0, False, 0.0, 0.0),
    # 130 m of virtual-head travel past F7, the TRoll convention: the same
    # number on every assigned coiler, not table plus wraps on that mandrel
    (13, "F7", FWD, 1.44, 1.2, 1174.4, 1174.5, 12.17, 0.0, 0.0, True, 50.0, 130.0),
]

_P2 = [
    (1, "R1", FWD, 230.0, 188.0, 1120.0, 1130.1, 2.0, 3.0, 4.0, False, 0.0, 0.0),
    (2, "R1", REV, 188.0, 146.0, 1130.1, 1140.2, 3.0, 3.0, 6.0, False, 0.0, 0.0),
    (3, "R1", FWD, 146.0, 106.0, 1140.2, 1149.7, 4.0, 0.0, 0.0, False, 0.0, 0.0),
    (4, "R2", FWD, 106.0, 78.0, 1149.7, 1156.4, 4.5, 3.0, 4.0, False, 0.0, 0.0),
    (5, "R2", REV, 78.0, 55.0, 1156.4, 1161.8, 4.8, 3.0, 6.0, False, 0.0, 0.0),
    (6, "R2", FWD, 55.0, 38.0, 1161.8, 1165.8, 5.2, 0.0, 0.0, False, 0.0, 0.0),
    (7, "F1", FWD, 38.0, 22.0, 1165.8, 1169.6, 0.72, 0.0, 0.0, False, 0.0, 0.0),
    (8, "F2", FWD, 22.0, 12.0, 1169.6, 1172.0, 1.32, 0.0, 0.0, False, 0.0, 0.0),
    (9, "F3", FWD, 12.0, 7.0, 1172.0, 1173.1, 2.27, 0.0, 0.0, False, 0.0, 0.0),
    (10, "F4", FWD, 7.0, 4.5, 1173.1, 1173.7, 3.52, 0.0, 0.0, False, 0.0, 0.0),
    (11, "F5", FWD, 4.5, 2.75, 1173.7, 1174.1, 5.76, 0.0, 0.0, False, 0.0, 0.0),
    (12, "F6", FWD, 2.75, 2.0, 1174.1, 1174.3, 7.92, 0.0, 0.0, False, 0.0, 0.0),
    (13, "F7", FWD, 2.0, 1.6, 1174.3, 1174.4, 9.9, 0.0, 0.0, True, 50.0, 130.0),
]


def example_case() -> Case:
    products = (
        Product(
            id="P1",
            slab_thk=230.0,
            slab_wid=1120.0,
            slab_len=7.0,
            label="S235 1.2 mm x 1120 mm",
            grade="S235JR",
            passes=_passes("P1", _P1),
        ),
        Product(
            id="P2",
            slab_thk=230.0,
            slab_wid=1120.0,
            slab_len=7.0,
            label="S235 1.6 mm x 1120 mm",
            grade="S235JR",
            passes=_passes("P2", _P2),
        ),
    )
    settings = SimSettings(
        pacing=100.0,
        n_pieces=3,
        piece_products=("P1", "P2", "P1"),
        coiler_pattern=("DC1", "DC2", "DC3"),
        gap_min=5.0,
        pacing_scan_min=70.0,
        pacing_scan_max=300.0,
        pacing_scan_steps=106,
        mc_runs=600,
        mc_speed_tol_pct=2.0,
        mc_delay_sigma=1.0,
        mc_release_sigma=2.0,
    )
    return Case(
        line=Line(tuple(_EQUIPMENT), tuple(_SECTIONS)),
        products=products,
        settings=settings,
        utilities=tuple(_UTILITIES),
        info={
            "schema_version": "1",
            "mill_type": "hsm",
            "mill_name": "Example HSM",
            "notes": "Invented data, for demonstration only",
        },
    )
