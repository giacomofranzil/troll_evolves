"""Schema of the input workbook: sheet names, columns and units.

Units are fixed here and are not negotiable inside the file: there is no unit
column to fill in. A rigid template is far more robust when the file is passed
around between several people.
"""

from __future__ import annotations

SCHEMA_VERSION = "1"

SHEET_INFO = "Info"
SHEET_LAYOUT = "Layout"
SHEET_SECTIONS = "Sections"
SHEET_PRODUCTS = "Products"
SHEET_PASSES = "PassSchedule"
SHEET_SIM = "Simulation"
SHEET_UTILITIES = "Utilities"
SHEET_GUIDE = "Guide"

MAX_EVENTS_PER_SECTION = 7

LAYOUT_COLUMNS = [
    ("equipment_id", "Unique identifier (R1, F7, DC1, CB)"),
    ("kind", "start | stand | coiler | coilbox | marker"),
    ("x_m", "Absolute position along the line, in metres"),
    (
        "accel_mps2",
        "Acceleration = deceleration, m/s2. Read only on stand rows, where it applies "
        "while the piece is gripped, on the coiler row (final slowdown), and on the "
        "coilbox row (threading, coiling and uncoiling ramps). Ignored on start and "
        "marker rows",
    ),
    ("group", "Tandem group, for example FM for the finishing stands"),
    ("label", "Description shown on the charts"),
    (
        "occupy",
        "YES to include this device in occupancy (busy time). Empty = default: YES "
        "for stand, coiler and coilbox; NO for marker and start",
    ),
    (
        "occupy_before_m",
        "Footprint upstream of the axis, m. Occupancy starts when the piece reaches "
        "x minus this value. Empty = 0 (the axis)",
    ),
    (
        "occupy_after_m",
        "Footprint downstream of the axis, m. Occupancy ends when the piece leaves "
        "x plus this value. Empty = 0 (the axis)",
    ),
]

SECTION_COLUMNS = [
    ("section_id", "Unique identifier of the section"),
    ("label", "Description shown on the charts"),
    ("start_ref", "Reference equipment, 'prev', or empty for an absolute position"),
    ("start_offset_m", "Distance from the reference to the start of the section, m"),
    ("length_m", "Length of the section, m"),
    ("direction", "fwd | rev: direction of travel in which the events apply"),
    ("during_pass", "YES if the event applies while rolling, NO to defer it"),
    ("accel_mps2", "Roller table acceleration in this section, m/s2 (empty = global default)"),
]

SECTION_EVENT_COLUMNS = [
    ("d{}_m", "Distance from the start of the section of speed change {}, m"),
    ("v{}_mps", "New commanded speed {}, m/s"),
    ("a{}_mps2", "Acceleration of change {}, m/s2 (empty = the one of the axis)"),
]

PRODUCT_COLUMNS = [
    ("product_id", "Unique identifier of the product"),
    ("label", "Description"),
    ("grade", "Steel grade"),
    ("slab_thk_mm", "Slab thickness, mm"),
    ("slab_wid_mm", "Slab width, mm"),
    ("slab_len_m", "Slab length, m"),
    (
        "coilbox",
        "YES to send this product through the coilbox, NO to bypass it. "
        "Empty = YES when a coilbox is in the Layout. Speeds below are ignored on bypass",
    ),
    (
        "coilbox_v_thread_mps",
        "Coilbox threading speed, m/s (empty = keep the speed at arrival). "
        "Ignored if there is no coilbox or coilbox is NO",
    ),
    (
        "coilbox_v_coil_mps",
        "Coilbox coiling speed after thread_length_m of strip has entered, m/s "
        "(empty = threading speed, or the speed at arrival)",
    ),
    (
        "coilbox_v_uncoil_mps",
        "Coilbox uncoiling speed of the new head, m/s (empty = speed at the start "
        "of uncoiling). Overwritten by any speed change downstream and by F1 bite",
    ),
    (
        "coilbox_thread_length_m",
        "Length of strip that must enter the coilbox, as virtual-head travel past "
        "the axis, before switching from threading to coiling speed. Empty or 0 = "
        "switch as soon as the head is in. Mandrel-less boxes: this is not a wrap count",
    ),
    (
        "coilbox_delay_s",
        "Hold after the tail is in the coilbox, before uncoiling, s. Empty = 0",
    ),
]

PASS_COLUMNS = [
    ("product_id", "Product this pass belongs to"),
    ("pass_no", "Sequence number of the pass"),
    ("equipment_id", "Stand where the pass takes place"),
    ("direction", "fwd | rev"),
    ("h_in_mm", "Entry thickness, mm"),
    ("h_out_mm", "Exit thickness, mm"),
    ("w_in_mm", "Entry width, mm"),
    ("w_out_mm", "Exit width, mm"),
    ("v_exit_mps", "Material speed at the stand exit, m/s"),
    (
        "reversing_delay_s",
        "Dead time of the reversal that FOLLOWS this pass, s",
    ),
    (
        "reversing_clearance_m",
        "Distance between the stand and the closest extremity when the piece stops "
        "for the reversal that FOLLOWS this pass, m. This is the stop position: the "
        "model derives the tail-out speed v* that makes it. Empty = shortest stop "
        "after tail-out",
    ),
    (
        "approach_v_mps",
        "Speed at which the piece comes back towards THIS pass after a reversal "
        "(empty = entry speed of the pass)",
    ),
    ("master", "YES on the stand that sets the mass flow of the tandem group"),
    ("zoom_pct", "Zoom rolling: relative speed change in per cent (negative = slowdown)"),
    (
        "zoom_trigger_m",
        "Zoom: virtual-head travel past this stand, m (same for every coiler; TRoll)",
    ),
    ("zoom_accel_mps2", "Zoom: acceleration, m/s2 (empty = the one of the axis)"),
]

# columns introduced after the first version of the schema: their absence does
# not invalidate a workbook already in circulation
OPTIONAL_COLUMNS = {
    "reversing_clearance_m",
    "occupy",
    "occupy_before_m",
    "occupy_after_m",
    "coilbox_v_thread_mps",
    "coilbox_v_coil_mps",
    "coilbox_v_uncoil_mps",
    "coilbox_thread_length_m",
    "coilbox_delay_s",
    "coilbox",
}

UTILITY_COLUMNS = [
    ("equipment_id", "Layout identifier this recipe applies to (DS1, R2, F1, …)"),
    (
        "utility",
        "water | power. water rate is L/s, power rate is kW. Totals: m3 and kWh",
    ),
    (
        "rate",
        "Instantaneous consumption while the condition below holds. "
        "water: litres per second. power: kW",
    ),
    (
        "when",
        "occupy (default) = occupancy footprint of the device. rolling = stand "
        "occupancy only (bite to tail-out, or the stand footprint if "
        "occupy_before_m / occupy_after_m are set). rolling is valid on stands only",
    ),
]

SIM_KEYS = [
    ("pacing_s", 170.0, "Nominal cadence between one piece and the next, s"),
    ("n_pieces", 3, "Number of simulated pieces"),
    ("piece_products", "", "Comma separated product sequence (empty = repeat the first)"),
    (
        "coiler_pattern",
        "",
        "Repeating coiler cycle, comma separated (empty = the only coiler). "
        "Required when the layout has two or three coilers, e.g. DC1,DC2",
    ),
    ("gap_min_m", 5.0, "Minimum distance allowed between a tail and the next head, m"),
    ("pacing_scan_min_s", 70.0, "Lower bound of the pacing scan, s"),
    ("pacing_scan_max_s", 300.0, "Upper bound of the pacing scan, s"),
    ("pacing_scan_steps", 106, "Number of points in the scan"),
    ("mc_runs", 600, "Number of Monte Carlo runs for the robustness study"),
    ("mc_speed_tol_pct", 2.0, "Tolerance on the pass speeds, +/- %"),
    ("mc_delay_sigma_s", 1.0, "Standard deviation of the dead times, s"),
    ("mc_release_sigma_s", 2.0, "Standard deviation of the release instant, s"),
    ("mc_seed", 20260831, "Seed of the random generator, for reproducible results"),
    ("table_accel_mps2", 1.0, "Default roller table acceleration, m/s2"),
    ("coiler_v_final_mps", 1.0, "Speed the tail must have when it reaches the coiler, m/s"),
    ("max_time_s", 1800.0, "Maximum simulation time of a single piece, s"),
    ("time_axis_down", "YES", "YES for time increasing downwards on the diagram"),
]

GUIDE_TEXT = [
    ("How the model works", True),
    ("", False),
    (
        "The head commands, the tail follows. You describe the speed changes of the "
        "extremity that leads in the current direction of travel; the speed of the "
        "other extremity follows from the mass flow balance of the engaged stands:",
        False,
    ),
    ("    v_trailing = v_leading / product of the lambdas,   lambda = (h_in*w_in)/(h_out*w_out)", False),
    ("", False),
    ("Units are fixed in the file, there is no unit column to fill in:", True),
    ("    positions and lengths in m, thicknesses and widths in mm,", False),
    ("    speeds in m/s, times in s, accelerations in m/s2.", False),
    ("    utilities: water in L/s (totals in m3), electrical power in kW (totals in kWh).", False),
    ("", False),
    ("Sheet Layout: the kind column", True),
    (
        "Every row is one item of equipment placed at an absolute position. The kind "
        "column decides what the model does with it and accepts five values:",
        False,
    ),
    (
        "    start    the point where the piece is released, normally the furnace exit. "
        "Exactly one row must carry it. At release the head sits here and the tail one "
        "slab length further upstream.",
        False,
    ),
    (
        "    stand    a rolling stand. Only these can appear in the PassSchedule sheet, "
        "and their acceleration governs the piece while it is gripped.",
        False,
    ),
    (
        "    coiler   the coiler. The head stops here, and the acceleration on this row "
        "is the deceleration of the tail down to the final speed, used even while the "
        "finishing mill is still rolling. Up to three coiler rows are allowed, in line, "
        "each at its own position.",
        False,
    ),
    (
        "    coilbox  one intermediate box between roughing and finishing. Mandrel-less: "
        "the axis is the station, not a diameter. The head enters, strip is stored, then "
        "the original tail leaves first toward the finishing mill. Speeds live on the "
        "product row. At most one coilbox in the layout.",
        False,
    ),
    (
        "    marker   anything with no dynamics of its own: descalers, edgers, shears. "
        "Acceleration is ignored. Tick occupy and set a footprint if you want its busy "
        "time (water, for example); otherwise it is only a reference line on the charts.",
        False,
    ),
    ("", False),
    ("Sheet Layout: occupancy", True),
    (
        "occupy, occupy_before_m and occupy_after_m describe when a device is busy. The "
        "axis stays at x_m; the footprint is [x minus before, x plus after]. Busy time "
        "is the overlap of that interval with the piece [tail, head], so a reversing bar "
        "can occupy the same descaler twice. Empty occupy: stands, coilers and the "
        "coilbox are included; markers and start are not. Empty footprints: the axis "
        "alone, which for a stand is bite to tail-out.",
        False,
    ),
    ("", False),
    ("Sheet Layout: the group column", True),
    (
        "It is not a comment, it drives the calculation. Stands carrying the same group "
        "label form a tandem, and inside a tandem the pass flagged as master in the "
        "PassSchedule sheet sets the mass flow: the speeds of all the other stands in "
        "the group are RECOMPUTED from it and the ones you entered are only reported as "
        "a deviation. This is deliberate, because between two stands of a tandem the "
        "strip has a fixed length, so inconsistent speeds would describe an impossible "
        "motion.",
        False,
    ),
    (
        "Consequence to keep in mind: emptying the group column switches that protection "
        "off without any error message, and the speeds you entered are used as they are. "
        "Same thing if the group exists but no pass in it is flagged as master.",
        False,
    ),
    ("", False),
    ("Sheet Sections: speed changes", True),
    (
        "Roller tables have no setpoint of their own: the line is divided into sections "
        "defined by whoever fills in the file, possibly shorter than the spacing between "
        "two stands. Each section allows up to 7 speed changes, given as a distance from "
        "the start of the section plus a target speed.",
        False,
    ),
    (
        "The distance is the point where the new speed must be REACHED, not where the "
        "ramp begins: the tool anticipates the ramp by v_new^2 - v_old^2 over twice the "
        "acceleration so that the piece is at speed exactly there. If there is not enough "
        "room the ramp starts as early as it can and the difference is reported.",
        False,
    ),
    (
        "An event whose target position falls while a pass is engaged is deferred to "
        "disengagement, because while rolling it is the mill that commands and not the "
        "roller table. The same applies when a stand still to be engaged lies between the "
        "piece and the target position: a ramp cannot be planned across a pass, the bite "
        "would reset the speed anyway. Put YES in during_pass to override this.",
        False,
    ),
    (
        "If instead only the anticipation reaches back into the rolling zone, while the "
        "target position is already in free running, the ramp does start during the pass "
        "and the tool reports it: it is the mill decelerating ahead of tail-out, which is "
        "a real manoeuvre.",
        False,
    ),
    ("", False),
    ("Accelerations: three sources, one precedence", True),
    (
        "    1. the acceleration written next to a speed change applies to that ramp only, "
        "then the value below takes over again;",
        False,
    ),
    (
        "    2. while the piece is gripped, the acceleration of the stand rolling it, "
        "except during the final slowdown towards the coiler (see below);",
        False,
    ),
    (
        "    3. while the piece is free, the acceleration of the section it is in, or the "
        "global default table_accel_mps2 from the Simulation sheet when the section leaves "
        "it empty.",
        False,
    ),
    (
        "So the braking towards a reversal uses the stand acceleration while the tail is "
        "still gripped, then the roller table value after tail-out. The restart after the "
        "wait uses the table, because in that moment the bar is moved by the table and not "
        "by the mill.",
        False,
    ),
    (
        "Coilbox threading, coiling and uncoiling ramps use the acceleration on the "
        "coilbox Layout row as ramp_accel.",
        False,
    ),
    ("", False),
    ("Reversing roughing", True),
    (
        "The reversing delay and the reversing clearance on a row describe the reversal "
        "that FOLLOWS that pass. Reading the schedule downwards it says: finish this pass, "
        "back off by the clearance, wait for the delay, then go the other way. The last "
        "pass, and any pass followed by another one in the same direction, carry none: a "
        "value written there is ignored and reported as a warning.",
        False,
    ),
    (
        "The clearance is the stop position, measured from the stand to the extremity "
        "closest to it once the piece has stopped; increase it if the real constraint is "
        "the edger a few metres before. It is master: the piece stops there, it does not "
        "overrun it. The model derives the tail-out speed v* = sqrt(2 a_table C) that "
        "lets the roller table finish the stop after the tail leaves the stand. If the "
        "pass speed is higher, the mill decelerates as late as possible at the stand "
        "acceleration while the tail is still gripped, then the table takes over at the "
        "section acceleration. v* is written on the reverse_slowdown and tail_out events; "
        "it is not written back into v_exit_mps. Leaving the cell empty keeps the "
        "shortest stop after tail-out, at v^2/(2a), with no mill slowdown. If even "
        "starting from the bite is not enough, the tool reports the clearance actually "
        "achieved rather than faking an impossible braking.",
        False,
    ),
    (
        "The approach speed instead stays on the row of the pass it belongs to: it is the "
        "speed at which the piece comes back TOWARDS that pass. So for one reversal the "
        "clearance and the delay are on one row and the approach speed on the next.",
        False,
    ),
    ("", False),
    ("Zoom rolling", True),
    (
        "Zoom keeps the opposite convention on purpose, the one of the offline model TRoll: "
        "zoom_trigger_m is the point where the acceleration STARTS, not where the speed is "
        "reached. It is measured from the stand on whose row it is written, and it uses "
        "the virtual head, that is it ignores the fact that the head stops at the coiler: "
        "if the trigger falls beyond the coiler the zoom starts after a few wraps. The "
        "same number is used whichever coiler takes the strip: TRoll does not treat the "
        "downcoilers, so 130 m of virtual travel is not recomputed as table plus wraps "
        "on the assigned mandrel. Pinning and the tail slowdown use that mandrel; the "
        "zoom ramp does not. zoom_pct is a relative change: +10 speeds up by ten per "
        "cent, -20 slows down by twenty. Values of -100 or below are rejected.",
        False,
    ),
    ("", False),
    ("Coilbox", True),
    (
        "One coilbox per line, kind coilbox on the Layout. Whether a given product "
        "uses it is the coilbox tick on the Products sheet: YES or empty sends the "
        "bar through the box; NO bypasses it (the station is only a point on the "
        "line, like a marker). Threading, coiling and "
        "uncoiling speeds plus thread_length_m and delay_s are on the product. "
        "thread_length_m is the virtual-head travel past the box axis before switching "
        "from threading to coiling speed; empty or 0 switches as soon as the head is in "
        "(no mandrel diameter: the box is mandrel-less). delay_s empty = uncoiling as "
        "soon as the tail is in. While the rougher still holds the tail the mill remains "
        "master; if that overlap happens the tool warns, because it is not standard. "
        "Uncoiling speed is overwritten by any speed change further downstream and then "
        "by the finishing-mill bite. The original tail becomes the kinematic head. "
        "While the box is busy, the next piece sees the gap to the coilbox axis "
        "(or to the tail still on the roller tables, if that is closer). Uncoiling "
        "is measured in metres of transfer bar at mill entry speed, so F1 may bite "
        "while metal is still leaving the box.",
        False,
    ),
    ("", False),
    ("Arrival at the coiler", True),
    (
        "The control starts the slowdown as late as possible, so that the tail reaches "
        "the coiler at coiler_v_final_mps, using the acceleration written on the coiler "
        "row of the Layout sheet. The constraint is on the tail; the command is on the "
        "leading extremity, scaled by the remaining elongation chain: the tail is held "
        "at that deceleration and the mill at that rate times the product of the lambdas "
        "still engaged. At each tail-out the commanded rate steps down, the tail "
        "deceleration stays the same. If the tail is still in the finishing mill when "
        "the latest start arrives, the tandem slows down anyway: that is what the plant "
        "does. If even that is not enough, the tool reports the speed the tail actually "
        "arrives at rather than faking an impossible braking.",
        False,
    ),
    ("", False),
    ("Several coilers", True),
    (
        "The layout may list up to three coilers, in line, each at its own x. "
        "coiler_pattern on the Simulation sheet is a repeating cycle of their ids, "
        "the same idea as piece_products: DC1,DC2 alternates; DC1,DC2,DC3 is a "
        "round robin; DC1,DC2,DC1,DC3 is a longer cadence. Piece 1 takes the first "
        "id, piece 2 the second, then it wraps. "
        "With two or three coilers the pattern is required and must name at least two "
        "of them. If every piece goes to one mandrel, or if you use only two of three, "
        "remove the unused rows from the Layout rather than leaving them idle. A piece "
        "assigned to a downstream coiler does not stop at the one upstream: the head "
        "passes it, which is the in-line layout.",
        False,
    ),
    ("", False),
    ("Sheet Utilities", True),
    (
        "Optional. Instantaneous water and electrical power while a device is busy, "
        "applied after the run onto occupancy intervals: they do not enter the event "
        "loop. Overlapping pieces add. water rate is L/s, power rate is kW. "
        "Integrated totals are m3 of water and kWh. when=occupy uses the occupancy "
        "footprint (descalers, coilers, coilbox, stands). when=rolling is stands only.",
        False,
    ),
    (
        "Leave the sheet empty, or omit it from an older workbook, to skip the "
        "calculation. A recipe on a device with occupy off is reported and consumes "
        "nothing.",
        False,
    ),
    ("", False),
    ("What the model does not do", True),
    (
        "No interlocks and no hold points: the pieces follow their nominal profiles and "
        "the tool reports where the gap drops below the threshold, without stopping the "
        "piece behind. Roller slip neglected, infinite jerk, no thermal model, "
        "no furnace cadence constraint.",
        False,
    ),
]
