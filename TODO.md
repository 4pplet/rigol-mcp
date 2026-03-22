# DHO804 Support — Implementation TODO

## Overview

Add support for the Rigol DHO800/DHO900 series alongside the existing DS1000Z/MSO1000Z support.
The DHO804 uses the same SCPI-over-TCP protocol (port 5555) but differs in screen geometry,
a handful of command names, cursor addressing, and measurement item names.

**Approach:** Detect the scope model from `*IDN?` at connection time and branch on a
model-family enum (`DS1000Z` vs `DHO800`) where behaviour differs.

---

## Tasks

### Phase 1: Model detection & abstraction

- [x] **1.1** Add a `ScopeFamily` enum (`DS1000Z`, `DHO800`) to `scope.py`
- [x] **1.2** Parse `*IDN?` response at connection time in `get_scope()` to detect family
  - DS1000Z: `RIGOL TECHNOLOGIES,DS1054Z,...` or `MSO1...`
  - DHO800: `RIGOL TECHNOLOGIES,DHO804,...` or `DHO8...` / `DHO9...`
- [x] **1.3** Store detected family + model-specific constants in a module-level dataclass/dict:
  - `screen_divisions`: 12 (DS1000Z) vs 10 (DHO800)
  - `points_per_div`: 50 (DS1000Z) vs 100 (DHO800)
  - `screen_points`: 600 vs 1000
  - `screen_center`: 300 vs 500
  - `half_screen_divs`: 6 vs 5 (used in timebase offset formulas)
- [x] **1.4** Add a `get_family()` helper that returns the detected `ScopeFamily`

### Phase 2: Command differences

- [x] **2.1** Autoscale command: `:AUToscale` (DS1000Z) → `:AUToset` (DHO800)
  - Update `autoscale()` in `scope.py` to branch on family
- [x] **2.2** Screenshot command: `:DISPlay:DATA? ON,OFF,PNG` (DS1000Z) → `:DISPlay:DATA? PNG` (DHO800)
  - Update `screenshot_png()` in `scope.py` to branch on family
- [x] **2.3** Two-source measurement item names:
  - DS1000Z: `RDELAY`, `FDELAY`, `RPHASE`, `FPHASE`
  - DHO800: `RRDELAY`, `FFDELAY`, `RRPHASE`, `FFPHASE`
  - Add mapping dict and translate in `measure_between()`
  - Also add new DHO800-only cross-edge items: `RFDELAY`, `FRDELAY`, `RFPHASE`, `FRPHASE`

### Phase 3: Cursor system rewrite

- [x] **3.1** DS1000Z cursors: pixel-based via `:CURSor:MANual:AX/BX` (int 5–594)
  - Keep existing `time_to_screen_x()` / `screen_x_to_time()` for DS1000Z
- [x] **3.2** DHO800 cursors: time-based via `:CURSor:MANual:CAX/CBX` (float seconds)
  - Much simpler — no pixel conversion needed
  - Set cursor type first: `:CURSor:MANual:TYPE TIME`
- [x] **3.3** Update `set_cursor_positions()` to branch:
  - DS1000Z: convert time→pixel, write `:CURSor:MANual:AX <pixel>`
  - DHO800: write `:CURSor:MANual:CAX <seconds>` directly
- [x] **3.4** Update `get_cursor_values()` to branch:
  - DS1000Z: read pixel positions, convert to time
  - DHO800: read time values directly from `:CURSor:MANual:CAX?` / `:CURSor:MANual:CBX?`
- [x] **3.5** Update cursor mode enum: DHO800 uses `XY` instead of `AUTO`

### Phase 4: Geometry-dependent code

- [x] **4.1** Replace hardcoded `_SCREEN_DIVISIONS`, `_POINTS_PER_DIV`, `_SCREEN_POINTS`,
  `_SCREEN_CENTER` constants with model-aware values from the detected family
- [x] **4.2** Update timebase description in `server.py` tool docstrings:
  - DS1000Z: `offset − 6×scale` / `offset + 6×scale`
  - DHO800: `offset − 5×scale` / `offset + 5×scale`
  - Consider making this dynamic in the tool description or adding a note about model differences
- [x] **4.3** Update `waveform_analysis.py` line 199 right-edge warning:
  - Uses hardcoded `6×scale` — should use `half_screen_divs` from model config

### Phase 5: Server & documentation updates

- [x] **5.1** Update `server.py` tool descriptions where they reference DS1000Z-specific values
  - `set_timebase` description references `6×scale_s_div` — needs to be model-aware
  - `get_waveform` description says "~1200 points" — DHO800 returns ~1000 in NORM mode
- [x] **5.2** Update `measure_between` tool schema to include DHO800 items when DHO800 is detected
  - Or accept both naming conventions and translate internally
- [x] **5.3** Update `README.md`:
  - Add DHO800/DHO900 to supported hardware table
  - Update verification URL (DHO800 may have different welcome page)
  - Add DHO-specific notes if any
- [x] **5.4** Update module docstrings from "Rigol DS1000Z" to "Rigol DS1000Z / DHO800"

### Phase 6: Testing

- [ ] **6.1** Test with actual DHO804 hardware:
  - Connection and `*IDN?` parsing
  - All channel/timebase/trigger commands
  - Screenshot capture
  - Waveform download (verify 1000 points in NORM mode)
  - Cursor set/read in time-based mode
  - All measurement items
  - Autoscale (`:AUToset`)
- [ ] **6.2** Verify DS1000Z still works (regression test)
- [ ] **6.3** Test reconnection behaviour with DHO804

### Phase 7: Signal generator support (future)

Community mods (MatthiasElectronic AWG daughterboard + vendor.bin hack to DHO914S/DHO924S)
make signal generator support a common need. The firmware already contains all `:SOURce1:`
SCPI commands — they activate when the scope identifies as a `-S` model.

- [x] **7.1** Detect signal generator capability from `*IDN?` (look for `-S` suffix or `S` in model: DHO914S, DHO924S, DS1074Z-S, DS1104Z-S)
- [x] **7.2** Add `ScopeProfile.has_awg: bool` flag
- [x] **7.3** Implement signal generator tools:
  - `set_source` — configure waveform type, frequency, amplitude, offset, duty cycle
  - `get_source_state` — read current AWG configuration
  - `source_output` — enable/disable output
- [x] **7.4** SCPI commands implemented:
  - `:SOURce1:FUNCtion` — SIN, SQU, RAMP, PULS, NOIS, DC, ARB
  - `:SOURce1:FREQuency` — output frequency
  - `:SOURce1:VOLTage` — amplitude
  - `:SOURce1:VOLTage:OFFSet` — DC offset
  - `:SOURce1:OUTPut` — on/off
  - `:SOURce1:PULSe:DCYCle` — pulse duty cycle
  - `:SOURce1:OUTPut:IMPedance` — OMEG (high-Z) or FIFT (50 ohm)
- [x] **7.5** DS1000Z-S has 2 source channels (`:SOURce1:`, `:SOURce2:`), DHO900S has 1 — handled via `_MAX_SOURCE_CHANNELS`

---

## SCPI Command Reference (differences only)

| Feature | DS1000Z | DHO800/DHO900 |
|---|---|---|
| Screen divisions | 12 | 10 |
| Points/div (NORM) | 50 | 100 |
| Total screen points | 600 | 1000 |
| Autoscale | `:AUToscale` | `:AUToset` |
| Screenshot | `:DISPlay:DATA? ON,OFF,PNG` | `:DISPlay:DATA? PNG` |
| Cursor position | `:CURSor:MANual:AX/BX` (pixel) | `:CURSor:MANual:CAX/CBX` (seconds) |
| Cursor type | N/A | `:CURSor:MANual:TYPE TIME\|AMPLitude` |
| Two-src delay | `RDELAY/FDELAY` | `RRDELAY/FFDELAY` + `RFDELAY/FRDELAY` |
| Two-src phase | `RPHASE/FPHASE` | `RRPHASE/FFPHASE` + `RFPHASE/FRPHASE` |
| Cursor mode | `OFF/MANUAL/TRACK/AUTO` | `OFF/MANUAL/TRACK/XY` |

## Commands that are identical (no changes needed)

- Connection: port 5555, `\n` terminator, VISA socket
- `*IDN?`, `*OPC?`, `:SYSTem:ERRor?`
- `:CHANn:DISP/SCAL/OFFS/COUP/PROB`
- `:TIM:SCAL`, `:TIM:OFFS`, `:TIM:MODE`
- `:TRIGger:MODE EDGE`, `:TRIGger:EDGE:SOURce/SLOPe/LEVel`, `:TRIGger:STATus?`
- `:RUN`, `:STOP`, `:SINGle`
- `:WAV:SOUR/MODE/FORM/PRE?/DATA?` (same preamble format, same TMC block header)
- All single-source `:MEASure:ITEM` items (VMAX, VMIN, VPP, FREQUENCY, etc.)
