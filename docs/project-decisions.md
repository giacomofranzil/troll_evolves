# TRoll Evolves — Project Decision Record

**Last updated:** 2 October 2026  
**Purpose:** One readable record of product, architecture and modelling decisions made through P2 and
the initial P3 thermal-model discussion.

Status labels:

- **Accepted** — current project decision;
- **Proposed** — recommended direction, pending confirmation;
- **Deferred** — intentionally outside the current phase;
- **Open** — requires a decision or data.

## 1. Product direction

| Decision | Status | Record |
|---|---|---|
| Product home | Accepted | `troll_evolves` is the product repository. `hsm_logistic` is frozen for this work. |
| Product purpose | Accepted | TRoll Evolves is an offline process simulator and a possible future Level 2 physics engine. |
| Primary emphasis | Accepted | The main purpose is evolving from pacing analysis to rolling-process simulation: thermal physics first, then mechanical and other process models. Pacing becomes an auxiliary capability. |
| Core/adapters split | Accepted | Calculation core is independent of GUI, Excel, XML and plotting. I/O formats and plant-specific mappings are adapters. |
| Online architecture | Accepted | Physics remains callable as a deterministic library/service. GUI and persistence are not embedded in the calculation core. |
| Official use | Accepted | One web instance is the preferred distribution; a packaged desktop executable remains a fallback. |

## 2. Completed roadmap

### P0 — Documentation

**Status: completed**

- The calculation conventions and boundaries were documented before adding process physics.
- The JSON contract is the Level 2-facing machine interface.
- Input and result files remain separate.
- Explicit non-goals are documented rather than hidden.

### P0.5 — Occupancy separation

**Status: completed**

- Device occupancy is post-processing on exact head/tail trajectories.
- Occupancy is not part of the kinematic event loop.
- A device footprint is represented by distances before and after its reference coordinate.
- Stand, coilbox, coiler and marker occupancy share the same geometric overlap mechanism.

### P1 — TRoll XML import

**Status: completed and merged**

#### Canonical model and import flow

- TRoll XML is an adapter to the canonical `Case`; it is not the internal schema.
- XML is not simulated directly.
- Importing XML produces a populated input workbook.
- The user edits the workbook and then loads that workbook to run the model.
- The command-line flow is `hsmpace import dump.xml case.xlsx`, followed by
  `hsmpace run case.xlsx`.
- `run` and `to-json` reject XML as a simulation input.
- In the web application, XML upload shows import remarks and layout, offers the workbook for
  download, and stops before simulation.

#### Imported layout and schedule

- `x = 0` is the furnace reference.
- A tunnel furnace uses its exit as the release point.
- A walking-beam furnace uses its centre; the slab midpoint starts at `x = 0`.
- Device positions accumulate `DistanceFromPreviousDevice`, including the distance occupied by
  skipped devices.
- Predicted pass thickness and width are imported.
- `PredictedExitSpeedHead` in m/s is the pass speed command.
- `SpeedHead`, `SpeedTail` and roll-surface values are rpm and are ignored.
- Finishing-mill pass direction is always forward; `MovingUpStream` there describes material
  orientation, not a reversing pass.
- Reversing time and clearance are mapped from TRoll reversing data.
- Zoom uses TRoll's virtual-head convention and the last rolling device.
- Products are imported as a catalogue. The user defines the production sequence through
  `piece_products`.

#### Coilbox

- The coilbox is imported when present.
- Coiling speed defaults to the last roughing-pass exit speed.
- Uncoiling speed defaults to F1 head-entry speed.
- Detailed coilbox speeds absent from TRoll remain editable after import.

#### Deliberate omissions

- Coilers are not supplied by the TRoll dump. No row with an empty `x` is created; the user adds
  coiler rows with explicit `x_m`.
- Cooling devices (`Cool*`) are omitted in P1.
- Confidential production dumps are not committed; an anonymous fixture supports tests.

### P2 — Occupancy and utilities

**Status: completed and merged**

#### Occupancy

- Occupancy is derived from overlap between the piece envelope and each device footprint.
- Occupancy intervals distinguish:
  - **working** — the device is processing that piece;
  - **blocked/passage** — the strip occupies the space but the device is not working on that piece.
- For multiple in-line coilers, a strip passing an unassigned coiler blocks its space but does not
  operate that mandrel.
- The Gantt chart uses the piece colour and reduced opacity for blocked/passage intervals.

#### Utility recipes

- Utilities are applied after simulation to occupancy intervals; they never alter the event loop.
- Water-rate input is m³/h and integrated output is m³.
- Electrical-power input is kW and integrated output is kWh.
- Simultaneous pieces add their instantaneous rates.
- `when=occupy` applies to working occupancy.
- `when=rolling` applies only to rolling stands.
- Blocked/passage occupancy consumes neither water nor power.
- P2 water consumption is not automatically a thermal heat-transfer boundary condition.

## 3. P3 — Thermal model

### 3.1 Strategic role

| Decision | Status | Record |
|---|---|---|
| Next physics module | Accepted | Thermal modelling is P3. Mechanical modelling follows; optimisation follows validated physics. |
| Process scope | Accepted | Initial thermal scope runs from furnace discharge through finishing-mill exit. |
| Open-loop | Accepted | Thermal calculation evaluates the prescribed kinematic history and does not alter speed, pacing or device commands. |
| Pacing relation | Accepted | With current open-loop trajectories, pacing only shifts absolute time; it does not change a piece's thermal history. Closed-loop thermal pacing is very-future work and may serve a different product destination. |
| Initial temperature | Accepted | Furnace-discharge temperature is an input. |
| Run-out table | Deferred | Run-out-table cooling, transformations and coiling temperature are a second thermal phase. |
| Early water processes | Accepted | Descaling and interstand cooling are included from the first physically useful version. |

### 3.2 Physical state

- **Accepted:** use multiple Lagrangian material cross-sections along the strip.
- **Accepted:** each cross-section solves one-dimensional heat conduction through the full thickness.
- **Accepted:** calculate surface, centre and mean temperatures.
- **Accepted:** preserve material identity through elongation, reversals and coilbox LIFO inversion.
- **Accepted:** neglect longitudinal and widthwise conduction in the first model.
- **Proposed:** start with head, centre and tail for early verification, then use a configurable
  production mesh such as 11 or 21 material sections.
- **Proposed:** use an enthalpy formulation and an implicit finite-difference/finite-volume solver.

### 3.3 Heat-transfer mechanisms

| Mechanism | Status | Treatment |
|---|---|---|
| Air radiation/convection | Accepted | Temperature-dependent surface boundary conditions between active devices. |
| Plastic deformation | Accepted | Volumetric heat source at passes. Empirical until the mechanical model supplies plastic work. |
| Work-roll contact | Accepted | Contact cooling based on bite/contact time and a calibrated coefficient; mechanical pressure may improve it later. |
| Descaling | Accepted | Extended top/bottom water-cooling zone from the first useful model. |
| Interstand cooling | Accepted | Extended top/bottom cooling zones from the first useful model. |
| Induction heating | Accepted | Volumetric heat-generation term over an explicit inlet/outlet zone. |
| Coilbox | Accepted, simplified | Reduce exposed-air heat losses while each material section is stored. Use a calibratable exposure factor (or separate radiation/convection factors). |
| Run-out-table cooling | Deferred | Add with transformation kinetics in a later thermal phase. |

### 3.4 Induction heating

- An inductor has a physical inlet and outlet; it is not a point device placed at the outlet.
- Induction heating contributes a volumetric source \(\dot q'''_\mathrm{ind}(z,t)\).
- A target outlet temperature may be used to solve the required source amplitude.
- The initial model should report required absorbed thermal power and energy.
- Electrical supply power is reported only when an efficiency is declared.
- A detailed electromagnetic and equipment-power module — frequency, penetration depth, coil,
  converter, magnetic properties and capacity — is deferred.
- **Proposed:** default target quantity is mass-average cross-sectional temperature, with surface and
  centre targets explicitly selectable.

### 3.5 Forced device outlet temperature

TRoll currently allows the user to force an outlet temperature for a device.

**Proposed clearer semantics:**

1. `calculated` — no override;
2. `target-controlled` — an active physical source/sink is adjusted and required energy is reported;
3. `hard-override` — an explicit correction is applied and reported as unmodelled energy.

**Proposed:** when only mean temperature is forced, shift specific enthalpy across the existing profile
rather than making the section isothermal. This preserves gradients while exposing the energy
correction.

**Open:** confirm what temperature quantity the legacy TRoll value represents.

### 3.6 Coilbox

- Detailed coil geometry and wrap-to-wrap conduction are not justified in the first phase.
- While a material section is stored, radiation/convection loss is multiplied by a factor below one.
- Normal boundary conditions resume when the section pays out.
- The factor is a calibration parameter, not a universal material property.
- Layer conduction, edge losses and temperature redistribution are deferred.

### 3.7 Device geometry

**Accepted direction:** the layout must distinguish point events from finite process zones.

- A rolling stand is naturally anchored at a roll axis.
- An inductor, descaler or cooling bank has explicit `x_in` and `x_out`.
- A physical assembly may contain both a point axis and one or more process zones.
- Temperature is reported at every device inlet and outlet without requiring fake devices.
- Explicit virtual observation points may be added later if users need arbitrary report locations.
- Occupancy extent, thermal process extent and safety clearance remain separate concepts even if they
  share a common spatial-extent value object.

### 3.8 Material properties

- Initial TRoll practice uses old BISRA literature properties.
- **Accepted direction:** move to temperature- and grade/composition-dependent, versioned properties
  with explicit provenance and validity range.
- Preferred sources are plant-validated data or tables generated from current CALPHAD/properties
  systems such as Thermo-Calc/TCFE or JMatPro, subject to licensing.
- Runtime dependence on proprietary tools is not required; versioned tables may be generated offline.
- Literature correlations remain valid fallback providers when source and applicability are recorded.
- Emissivity and water heat-transfer coefficients are process/surface parameters, not freely tuned
  bulk material properties.
- Property extrapolation outside the validated range must generate an error or explicit warning.
- Phase-transformation kinetics are deferred with run-out-table cooling.

### 3.9 Temperature observations and validation

- TRoll does not identify pyrometers in its layout.
- It calculates inlet and outlet temperature for every device; equal values are legitimate for devices
  with no thermal effect.
- The new model shall also report device inlet and outlet temperature without requiring a pyrometer row.
- Plant pyrometers or trusted histories should be imported as a separate validation dataset, not
  confused with process devices.
- No fixed accuracy target has yet been accepted; it must reflect location and instrument uncertainty.

## 4. Input and persistence direction

| Decision | Status | Record |
|---|---|---|
| Move away from Excel | Accepted direction | Excel is inadequate as the long-term canonical project editor. Keep it for transition, engineering review and interchange. |
| GUI editing | Accepted direction | Routine model input should be entered and validated in the application GUI. |
| Canonical model | Accepted | The GUI edits the same versioned domain model consumed by the physics core. |
| Encoding | Proposed | Promote the existing versioned JSON contract as the canonical encoding. Keep TRoll XML as an import/export adapter. |
| Project container | Open | Choose plain JSON or a packaged project archive containing JSON, material tables and attachments. |
| Schema migrations | Accepted direction | Persisted projects require explicit version migrations. |
| Input/output separation | Accepted | Simulation results are separate from immutable input projects. |
| XML role | Accepted | XML interoperability is useful, but XML itself is not evidence of a state-of-the-art design; validation, provenance, migrations and APIs matter more. |

Suggested migration path:

1. formalise the canonical project schema independently of Excel;
2. keep current Excel and TRoll XML adapters;
3. add GUI editors for layout, products, schedules, materials and thermal zones;
4. save/load the canonical project format;
5. leave Excel as optional import/export rather than the source of truth.

## 5. Thermal development sequence

### P3.A — Data and schema specification

- Audit thermal fields in real TRoll dumps.
- Audit available material composition, property and plant measurement data.
- Agree units, device-zone geometry and forced-temperature semantics.
- Select canonical project format and first property provider.

### P3.B — Dry-line thermal core

- Lagrangian material sections.
- One-dimensional enthalpy solver.
- Radiation/convection in air.
- Conservative thickness remapping.
- Device inlet/outlet reporting and energy ledger.

### P3.C — Rolling and primary process devices

- Deformation heating and roll-contact cooling.
- Descaling and interstand cooling.
- Induction source and target-temperature mode.
- Simplified coilbox shielding.

### P3.D — GUI and validation

- Project editor independent of Excel.
- Temperature plots and device summaries.
- Validation-data import and residual metrics.
- Plant calibration.

### P3.E — Deferred thermal/metallurgical scope

- Run-out-table cooling.
- Austenite transformation and latent heat.
- Coiling temperature.
- Detailed electromagnetic induction model.
- Detailed coilbox model.

### Later roadmap

1. mechanical model: flow stress, force, torque, spread;
2. microstructure/property evolution;
3. outer schedule optimisation using validated kinematic, thermal and mechanical solvers.

## 6. Open information requested

The next specification review needs:

1. definition of initial temperature: uniform scalar or optional through-thickness profile;
2. meaning of the legacy forced outlet temperature;
3. first grades/compositions and available property sources;
4. descaler and interstand header data: pressure, flow, water temperature, top/bottom state and geometry;
5. induction topology, frequency range, rated power and any existing efficiency curves;
6. available plant temperature measurements, even though they are not layout devices;
7. desired number and placement of longitudinal material sections;
8. canonical project choice: plain JSON or packaged project archive.

