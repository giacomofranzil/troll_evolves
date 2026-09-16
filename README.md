# hsmpace

Space-time diagram and pacing analysis for a **Hot Strip Mill**. This repository is **TRoll Evolves**:
the `hsmpace` package is the first mill type of a shared physics core (offline tool and future Level 2
engine). Other mill types plug in later; the calculation core stays free of Excel, Plotly and Streamlit.

The tool draws the head and tail position of the pieces travelling along the line, checks that a
sufficient gap always remains between the tail of one piece and the head of the next, and determines
the minimum cadence at which pieces can enter the process.

![space-time diagram](docs/img/space-time-diagram.png)

## What it does

* **Space-time diagram**: position on the horizontal axis, like the plant layout, and time on the
  vertical axis increasing downwards. Every piece is a band between head and tail, so a collision
  reads as two bands touching rather than as four lines crossing.
* **Gap between pieces**, in metres and in seconds, with the critical point located by instant,
  position and section of the line. Every pair of pieces that coexists on the line is compared, not
  only the adjacent ones: with a reversing roughing mill the constraint often falls between piece N
  and N+2.
* **Minimum gap versus pacing curve**, from which the minimum feasible cadence and the margin being
  worked with are read directly.

  ![pacing curve](docs/img/pacing-curve.png)

* **Monte Carlo robustness**: probability of a violation once pass speeds, dead times and release
  instants have the dispersion they have in the plant.
* **Occupancy** as a Gantt chart of every device marked busy (stands, coilers, coilbox, descalers)
  and a full event log. Optional **utilities**: instantaneous water (L/s) and electrical power (kW)
  on those busy intervals, with totals in m³ and kWh over the simulated sequence.
* **Coilbox**, one per line, used or bypassed per product: when used, the piece shrinks to the axis,
  the original tail leaves first toward the finishing mill, and the gap while the box is busy is
  taken to the axis (or to the tail still on the roller tables, if that is closer).
* **Comparison against measured tracking**, to validate the model on real data.

## How to use it

### Web interface

```bash
pip install -e .
hsmpace app                      # opens http://127.0.0.1:8731
```

The same application runs in two ways, and the choice can be deferred:

* **locally** on the machine of whoever uses it, as a process serving `127.0.0.1`: no server, no
  network, no port to open towards the outside;
* **on an office server**, with `hsmpace app --address 0.0.0.0`, with colleagues opening a URL.

On the diagram, **Show the virtual head** keeps the unconstrained head after the coiler (the
zoom trigger), and **Material points** draws 2, 3, 5, … or 21 traces along the current length.

If Python cannot be installed on the machine, the package can be bundled into a single executable with
PyInstaller and the behaviour stays identical.

### Command line

```bash
hsmpace template input.xlsx                  # empty template to fill in
hsmpace template example.xlsx --with-example # example already filled in
hsmpace run input.xlsx --scan --monte-carlo 2000 --excel results.xlsx
hsmpace to-json input.xlsx -o case.json      # contract for the Level 2 system
hsmpace run case.json --json report.json
```

`hsmpace run` returns 2 when the minimum gap drops below the threshold, so it can be used in checking
scripts.

## The model in two lines

**The head commands, the tail follows.** The user describes the speed changes of the extremity leading
in the current direction of travel; the speed of the other extremity follows from the mass flow balance
of the engaged stands:

```
v_trailing = v_leading / product of the lambdas        lambda = (h_in * w_in) / (h_out * w_out)
```

The discontinuities at engagement changes are physically correct: at **bite** the trailing extremity
stays continuous, because the body of the bar has mass and cannot change speed instantly, while the
leading one jumps by a factor lambda because it is gripped by the rolls; at **tail-out** the opposite
happens. With a schedule consistent with the mass flow balance, the jump at bite lands exactly on the
pass speed and produces no spurious ramps.

Motion is represented by **analytic segments** of uniform acceleration: trajectories are exact, the
chart has dozens of points instead of hundreds of thousands, and the instant at which the gap touches
the threshold is found by solving a quadratic equation rather than by sampling. A complete simulation
costs about 0.4 ms, which makes the pacing scan and the Monte Carlo essentially free. Details are in
[docs/algorithm-spec.md](docs/algorithm-spec.md).

Other conventions worth knowing:

* **Speed changes**: the distance written in a section is where the new speed must be **reached**, not
  where the ramp starts. The tool anticipates the ramp so that the piece is at speed exactly there, and
  reports the shortfall when there is not enough room. An event whose target position falls while a
  pass is engaged, or beyond a stand still to be engaged, is deferred to disengagement: a ramp cannot
  be planned across a pass because the bite resets the speed anyway.
* **Accelerations**, in order of precedence: the one written next to a speed change applies to that
  ramp only; while the piece is gripped, the one of the stand rolling it; while it is free, the one of
  the section it is in, or the global `table_accel_mps2` default.
* **Reversals**: the `reversing_delay_s` and `reversing_clearance_m` on a row describe the reversal
  that **follows** that pass, so the schedule reads downwards as "finish this pass, back off, wait,
  then go the other way". The `approach_v_mps` instead stays on the row of the pass it approaches.
  The clearance is the **stop position**, measured from the stand (increase it if the real constraint
  is the edger). It is master: the piece stops there. The model derives the tail-out speed
  `v* = sqrt(2 a_table C)` that lets the table finish the stop; if the pass is faster, the mill
  decelerates as late as possible at the stand acceleration while the tail is still gripped. `v*`
  is written on the `reverse_slowdown` and `tail_out` events, not back into `v_exit_mps`. Leaving
  the cell empty keeps the shortest stop after tail-out, at `v^2/(2a)`. If even starting from the
  bite is not enough, the tool reports the clearance actually achieved rather than faking an
  impossible braking.
* **Zoom rolling**: keeps the opposite convention on purpose, the one of the offline model TRoll, so its
  trigger is where the acceleration **starts**. It uses the **virtual head**, that is it ignores the
  fact that the head stops at the coiler: if it falls beyond the coiler the zoom starts after a few
  wraps. The trigger is the virtual travel past the stand, **the same for every assigned coiler**:
  TRoll does not treat the downcoilers, so the number is not recomputed as table plus wraps on that
  mandrel. Pinning and the tail slowdown use the assigned coiler; the zoom ramp does not.
  `zoom_pct` is signed: `+10` speeds up by ten per cent, `-20` slows down by twenty.
  Values of `-100` or below are rejected.
* **Arrival at the coiler**: the slowdown starts as late as possible so that the tail reaches the
  coiler at `coiler_v_final_mps`, using the acceleration on the coiler row, including while the
  finishing mill is still rolling. The constraint is on the tail; the command is on the leading
  extremity, scaled by the remaining elongation chain. If even that is not enough, the tool reports
  the speed the tail actually arrives at.
* **Several coilers**: up to three in-line downcoilers, each at its own `x`. `coiler_pattern` on the
  Simulation sheet is a repeating cycle of their ids, the same idea as `piece_products`
  (`DC1,DC2` alternates; `DC1,DC2,DC3` is a round robin). With two or three coilers the pattern is
  required and must name at least two of them. A piece assigned to a downstream coiler does not stop
  at the one upstream. Do not put the coiler on the product row: the same product often alternates.
* **Coiler**: on gripping, the physical head is pinned and the length on the line decreases, while the
  virtual head carries on.
* **Origin of the axis**: at release the head sits at the furnace exit and the tail one slab length
  further upstream, so the first few tens of metres of tail at negative values represent the slab still
  being extracted.

## The input file

An `.xlsx` without macros, read only: results always go to a separate file. Units are fixed in the
template and there is no unit column to fill in: **positions and lengths in m, thicknesses and widths
in mm, speeds in m/s, times in s, accelerations in m/s2, water in L/s, electrical power in kW**.

| Sheet | Content |
|---|---|
| `Info` | `schema_version`, mill name, notes |
| `Layout` | equipment with position, kind (`start`, `stand`, `coiler`, `coilbox`, `marker`), acceleration, tandem group, occupancy (`occupy`, `occupy_before_m`, `occupy_after_m`) |
| `Sections` | line sections with their own acceleration and up to 7 speed changes each, given as a distance from the section start plus a speed |
| `Products` | slab dimensions, and coilbox use (`YES` / `NO` / empty) plus threading, coiling, uncoiling speeds, `coilbox_thread_length_m` and `coilbox_delay_s` |
| `PassSchedule` | per pass: stand, direction, reduction, widths, speed, reversing delay and clearance, tandem master, zoom |
| `Simulation` | pacing, number of pieces, product sequence, coiler cycle, minimum gap, roller table acceleration, final speed at the coiler, scan and Monte Carlo parameters |
| `Utilities` | optional recipes: `equipment_id`, `utility` (`water` \| `power`), `rate` (L/s or kW), `when` (`occupy` \| `rolling`). Older workbooks without the sheet still load |

The `kind` column decides what the model does with a row, and `group` is functional rather than
informative: stands sharing a group label form a tandem, and inside it the pass flagged as `master`
sets the mass flow while the other speeds are recomputed from it. Acceleration is only read on `stand`
rows, where it applies while the piece is gripped, on the `coiler` row, where it sets the final
slowdown, and on the `coilbox` row, where it sets the threading, coiling and uncoiling ramps. It is
ignored on `start` and `marker`. Empty `occupy` includes stands, coilers and the coilbox; markers
and start are omitted unless ticked. The `Guide` sheet inside the workbook explains all of this in
place.

Sections need not match the spacing between stands: a physical section can be split into sub-sections
at any notable point. An event that would fire while a pass is engaged is **deferred to
disengagement**, because while rolling it is the mill that commands, not the roller table; putting
`YES` in `during_pass` makes it apply anyway.

Every input error is reported with sheet, cell and reason:

```
Invalid input (2 problems):
  - Layout!C5: x_m: 'twenty five' is not a number
  - PassSchedule!B4: product P1 pass 3: invalid reduction (135.0 -> 200.0 mm)
```

## Comparison against measured tracking

The **Measurements** tab accepts a CSV in the format

```
piece_id,time_s,head_m,tail_m
A1234,0.00,0.0,-10.5
A1234,0.50,0.6,-9.9
```

with `tail_m` optional and positions referred to the same origin as the layout. The measurements are
overlaid on the simulation, with an adjustable time shift to align the starting instants.

## What the tool does not do

Explicit choices, not oversights:

* **no interlocks and no hold points**: the pieces follow their nominal profiles and the tool reports
  where the gap drops below the threshold, without stopping the piece behind as the plant logic would;
* roller slip neglected, infinite jerk, acceleration equal to deceleration;
* no speed constraint tied to a position window: that is expressed with sections and events;
* no thermal, roll force or spread model;
* furnace cadence out of scope, to be assessed separately. The coiler cycle (`coiler_pattern`) is
  in scope.

## Project structure

```
src/hsmpace/
  core/        calculation core in pure arithmetic, no external dependency
    kinematics.py   analytic segments, quadratic roots, difference of trajectories
    model.py        layout, sections, events, pass schedule, validation
    occupancy.py    busy intervals from [tail, head] vs station footprints
    utilities.py    water and power from occupancy (post-process)
    coilbox.py      commanded speeds of the box (state stays in the event loop)
    coiler.py       tail waypoints for coiler slowdown and reversing stop
    simulate.py     event-driven simulator
    analysis.py     gap, geometric extremities, mass balance
    studies.py      gap versus pacing curve, minimum pacing, Monte Carlo
    contract.py     JSON contract for input and output
    tracking.py     import of measured tracking
  plants/      mill-type adapters (HSM today)
  io/          Excel and TRoll XML adapters (not imported by core)
  io_excel/    compatibility shim → io.excel
  viz/         charts (plotly)
  app/         web interface (streamlit)
  cli.py       command line
```

The `core` package does not import openpyxl, plotly or streamlit, has no global state and is
deterministic: it is meant to be rewritten in C++ or C# for the Level 2 system following
[docs/algorithm-spec.md](docs/algorithm-spec.md). In the meantime a Level 2 system can already invoke
the executable passing a case as JSON.

## Development

```bash
pip install -e ".[dev]"
pytest
```

## Documents

* [docs/algorithm-spec.md](docs/algorithm-spec.md) - specification of the algorithm for the porting
* [docs/grill-review-hsm-pacing.md](docs/grill-review-hsm-pacing.md) - critical review of the project,
  open points and decisions taken
