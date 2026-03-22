"""VISA connection and SCPI helpers for Rigol DS1000Z and DHO800/DHO900."""

import contextlib
import os
from dataclasses import dataclass
from enum import Enum

import pyvisa

# ---------------------------------------------------------------------------
# Scope family detection & model-specific constants
# ---------------------------------------------------------------------------

class ScopeFamily(Enum):
    DS1000Z = "DS1000Z"
    DHO800 = "DHO800"


@dataclass(frozen=True)
class ScopeProfile:
    """Model-specific constants derived from the programming guide."""
    family: ScopeFamily
    screen_divisions: int
    points_per_div: int
    half_screen_divs: int          # divisions from center to edge
    max_channels: int              # number of analog channels (2 or 4)
    has_awg: bool = False          # signal generator present (-S models)
    model: str = ""                # raw model string from *IDN? (e.g. "DHO804")

    @property
    def screen_points(self) -> int:
        return self.screen_divisions * self.points_per_div

    @property
    def screen_center(self) -> int:
        return self.screen_points // 2


_PROFILES: dict[ScopeFamily, ScopeProfile] = {
    ScopeFamily.DS1000Z: ScopeProfile(
        family=ScopeFamily.DS1000Z,
        screen_divisions=12,
        points_per_div=50,       # 600 total screen points
        half_screen_divs=6,
        max_channels=4,          # DS1000Z series is always 4-channel
    ),
    ScopeFamily.DHO800: ScopeProfile(
        family=ScopeFamily.DHO800,
        screen_divisions=10,
        points_per_div=100,      # 1000 total screen points
        half_screen_divs=5,
        max_channels=4,          # default; refined by _detect_channels()
    ),
}


def _detect_family(idn_string: str) -> ScopeFamily:
    """Determine the scope family from the *IDN? response."""
    model = idn_string.upper()
    if "DHO" in model:
        return ScopeFamily.DHO800
    # Default to DS1000Z for DS/MSO models and unknown instruments
    return ScopeFamily.DS1000Z


def _parse_model(idn_string: str) -> str:
    """Extract the model string from the *IDN? response.

    *IDN? format: 'RIGOL TECHNOLOGIES,<model>,<serial>,<firmware>'
    Returns the model string (e.g. 'DHO804', 'DS1054Z'), or '' if unparseable.
    """
    parts = idn_string.split(",")
    if len(parts) >= 2:
        return parts[1].strip()
    return ""


def _detect_channels(model: str, family: ScopeFamily) -> int:
    """Determine the number of analog channels from the model string.

    DHO802/DHO812 have 2 channels; all others have 4.
    DS1000Z/MSO1000Z series are always 4-channel.
    """
    if family == ScopeFamily.DHO800:
        m = model.upper()
        # DHO802, DHO812 → 2 channels; DHO804, DHO814, DHO824, DHO9xx → 4
        if m.endswith("02") or m.endswith("12"):
            return 2
    return 4


def _detect_awg(model: str, family: ScopeFamily) -> bool:
    """Detect whether the scope has a built-in signal generator.

    DS1000Z: models ending in '-S' (DS1074Z-S, DS1104Z-S)
    DHO800:  models ending in 'S' (DHO914S, DHO924S)
    """
    m = model.upper()
    if family == ScopeFamily.DS1000Z:
        return m.endswith("-S") or m.endswith("-S PLUS")
    if family == ScopeFamily.DHO800:
        return m.endswith("S") and not m.endswith("SS")
    return False


# ---------------------------------------------------------------------------
# Module-level cached connection + detected profile
# ---------------------------------------------------------------------------

_rm: pyvisa.ResourceManager | None = None
_scope: pyvisa.resources.Resource | None = None
_profile: ScopeProfile | None = None


def get_resource_string() -> str:
    ip = os.environ.get("RIGOL_IP")
    if not ip:
        raise RuntimeError("RIGOL_IP environment variable is not set")
    return f"TCPIP0::{ip}::5555::SOCKET"


def get_scope() -> pyvisa.resources.Resource:
    """Return cached VISA connection, opening it if needed.

    On first connect the scope is queried with *IDN? and the model family
    is detected automatically (DS1000Z vs DHO800/DHO900).
    """
    global _rm, _scope, _profile
    if _scope is None:
        _rm = pyvisa.ResourceManager()
        _scope = _rm.open_resource(get_resource_string())
        _scope.timeout = 30_000
        _scope.chunk_size = 1024 * 1024
        _scope.write_termination = "\n"
        _scope.read_termination = "\n"
        _scope.clear()  # flush any stale data left in the TCP receive buffer
        # Detect model family, channel count, and AWG capability
        idn_resp = _scope.query("*IDN?").strip()
        family = _detect_family(idn_resp)
        model_str = _parse_model(idn_resp)
        base = _PROFILES[family]
        n_ch = _detect_channels(model_str, family)
        awg = _detect_awg(model_str, family)
        if n_ch != base.max_channels or awg or model_str:
            _profile = ScopeProfile(
                family=base.family,
                screen_divisions=base.screen_divisions,
                points_per_div=base.points_per_div,
                half_screen_divs=base.half_screen_divs,
                max_channels=n_ch,
                has_awg=awg,
                model=model_str,
            )
        else:
            _profile = base
    return _scope


def get_profile() -> ScopeProfile:
    """Return the detected scope profile. Raises if not yet connected."""
    if _profile is None:
        raise RuntimeError("Scope not connected — call get_scope() first")
    return _profile


def get_family() -> ScopeFamily:
    """Return the detected scope family. Raises if not yet connected."""
    return get_profile().family


def invalidate_scope() -> None:
    """Close and discard the cached connection so the next call reconnects."""
    global _scope, _profile
    if _scope is not None:
        with contextlib.suppress(Exception):
            _scope.clear()
        with contextlib.suppress(Exception):
            _scope.close()
        _scope = None
        _profile = None


def check_scpi_error(scope: pyvisa.resources.Resource) -> str | None:
    """Query the SCPI error queue. Returns error string if an error is present, None if clear."""
    response = scope.query(":SYSTem:ERRor?").strip()
    # No error returns '0' or '0,"No error"'
    if response == "0" or response.startswith("0,"):
        return None
    return response


def screen_x_to_time(scope: pyvisa.resources.Resource, screen_x: int) -> float:
    """Convert a screen X pixel position back to time in seconds (DS1000Z only)."""
    prof = get_profile()
    scale = float(scope.query(":TIM:SCAL?").strip())
    offset = float(scope.query(":TIM:OFFS?").strip())
    return (screen_x - prof.screen_center) * scale / prof.points_per_div + offset


def time_to_screen_x(scope: pyvisa.resources.Resource, time_s: float) -> int:
    """Convert a time value (seconds) to a screen X position integer (DS1000Z only).

    Formula derived from DS1000Z geometry (50 pts/div, 12 div, 600 total):
        screen_x = (time - offset) * points_per_div / scale + screen_center
    """
    prof = get_profile()
    scale = float(scope.query(":TIM:SCAL?").strip())
    offset = float(scope.query(":TIM:OFFS?").strip())
    screen_x = int(round((time_s - offset) * prof.points_per_div / scale + prof.screen_center))
    max_px = prof.screen_points - 6  # DS1000Z cursor range: 5–594
    return max(5, min(max_px, screen_x))


def get_cursor_mode(scope: pyvisa.resources.Resource) -> str:
    return scope.query(":CURSor:MODE?").strip()


def set_cursor_mode(scope: pyvisa.resources.Resource, mode: str) -> None:
    """Set cursor mode: OFF, MANUAL, TRACK."""
    scope.write(f":CURSor:MODE {mode.upper()}")
    if err := check_scpi_error(scope):
        raise RuntimeError(f"SCPI error after :CURSor:MODE: {err}")


def set_cursor_positions(
    scope: pyvisa.resources.Resource,
    mode: str,
    ax: float | None = None,
    bx: float | None = None,
) -> None:
    """Set cursor A and/or B X positions (in seconds). mode: MANUAL or TRACK.

    DS1000Z: time values are converted to screen pixel positions.
    DHO800:  time values are sent directly in seconds.
    """
    family = get_family()
    is_track = mode.upper() in ("TRACK", "TRAC")

    if family == ScopeFamily.DHO800:
        # DHO800 accepts cursor positions directly in seconds
        prefix = ":CURSor:TRACk" if is_track else ":CURSor:MANual"
        if not is_track:
            scope.write(f"{prefix}:TYPE TIME")
        if ax is not None:
            scope.write(f"{prefix}:CAX {ax}")
            if err := check_scpi_error(scope):
                raise RuntimeError(f"SCPI error after {prefix}:CAX: {err}")
        if bx is not None:
            scope.write(f"{prefix}:CBX {bx}")
            if err := check_scpi_error(scope):
                raise RuntimeError(f"SCPI error after {prefix}:CBX: {err}")
    else:
        # DS1000Z uses pixel positions
        prefix = ":CURSor:TRACk" if is_track else ":CURSor:MANual"
        if ax is not None:
            screen_x = time_to_screen_x(scope, ax)
            scope.write(f"{prefix}:AX {screen_x}")
            if err := check_scpi_error(scope):
                raise RuntimeError(f"SCPI error after {prefix}:AX: {err}")
        if bx is not None:
            screen_x = time_to_screen_x(scope, bx)
            scope.write(f"{prefix}:BX {screen_x}")
            if err := check_scpi_error(scope):
                raise RuntimeError(f"SCPI error after {prefix}:BX: {err}")


def get_cursor_values(scope: pyvisa.resources.Resource) -> dict:
    """Read current cursor mode and all available readouts. AX_s/BX_s are in seconds."""
    family = get_family()
    mode = scope.query(":CURSor:MODE?").strip()
    result: dict = {"mode": mode}

    if mode in ("MANUAL", "MAN"):
        p = ":CURSor:MANual"
        if family == ScopeFamily.DHO800:
            result.update({
                "AX_s":        float(scope.query(f"{p}:CAX?").strip()),
                "BX_s":        float(scope.query(f"{p}:CBX?").strip()),
                "AX_value":    scope.query(f"{p}:AXValue?").strip(),
                "BX_value":    scope.query(f"{p}:BXValue?").strip(),
                "delta_x":     scope.query(f"{p}:XDELta?").strip(),
                "inv_delta_x": scope.query(f"{p}:IXDELta?").strip(),
            })
        else:
            ax_px = int(float(scope.query(f"{p}:AX?").strip()))
            bx_px = int(float(scope.query(f"{p}:BX?").strip()))
            result.update({
                "AX_s":        screen_x_to_time(scope, ax_px),
                "BX_s":        screen_x_to_time(scope, bx_px),
                "AX_value":    scope.query(f"{p}:AXValue?").strip(),
                "BX_value":    scope.query(f"{p}:BXValue?").strip(),
                "delta_x":     scope.query(f"{p}:XDELta?").strip(),
                "inv_delta_x": scope.query(f"{p}:IXDELta?").strip(),
            })
    elif mode in ("TRACK", "TRAC"):
        p = ":CURSor:TRACk"
        if family == ScopeFamily.DHO800:
            result.update({
                "AX_s":        float(scope.query(f"{p}:CAX?").strip()),
                "BX_s":        float(scope.query(f"{p}:CBX?").strip()),
                "AX_value":    scope.query(f"{p}:AXValue?").strip(),
                "AY_value":    scope.query(f"{p}:AYValue?").strip(),
                "BX_value":    scope.query(f"{p}:BXValue?").strip(),
                "BY_value":    scope.query(f"{p}:BYValue?").strip(),
                "delta_x":     scope.query(f"{p}:XDELta?").strip(),
                "delta_y":     scope.query(f"{p}:YDELta?").strip(),
                "inv_delta_x": scope.query(f"{p}:IXDELta?").strip(),
            })
        else:
            ax_px = int(float(scope.query(f"{p}:AX?").strip()))
            bx_px = int(float(scope.query(f"{p}:BX?").strip()))
            result.update({
                "AX_s":        screen_x_to_time(scope, ax_px),
                "BX_s":        screen_x_to_time(scope, bx_px),
                "AX_value":    scope.query(f"{p}:AXValue?").strip(),
                "AY_value":    scope.query(f"{p}:AYValue?").strip(),
                "BX_value":    scope.query(f"{p}:BXValue?").strip(),
                "BY_value":    scope.query(f"{p}:BYValue?").strip(),
                "delta_x":     scope.query(f"{p}:XDELta?").strip(),
                "delta_y":     scope.query(f"{p}:YDELta?").strip(),
                "inv_delta_x": scope.query(f"{p}:IXDELta?").strip(),
            })
    return result


def send_raw(scope: pyvisa.resources.Resource, command: str) -> str:
    """Send an arbitrary SCPI command; returns response for queries, empty string otherwise.
    Automatically checks the error queue after writes and raises on SCPI errors."""
    if command.strip().endswith("?"):
        return scope.query(command).strip()
    scope.write(command)
    if err := check_scpi_error(scope):
        raise RuntimeError(f"SCPI error after '{command}': {err}")
    return ""


def run(scope: pyvisa.resources.Resource) -> str:
    """Start continuous acquisition. Returns trigger status."""
    scope.write(":RUN")
    if err := check_scpi_error(scope):
        raise RuntimeError(f"SCPI error after :RUN: {err}")
    return scope.query(":TRIGger:STATus?").strip()


def stop(scope: pyvisa.resources.Resource) -> str:
    """Stop acquisition and freeze the display. Returns trigger status."""
    scope.write(":STOP")
    if err := check_scpi_error(scope):
        raise RuntimeError(f"SCPI error after :STOP: {err}")
    return scope.query(":TRIGger:STATus?").strip()


def single(scope: pyvisa.resources.Resource) -> str:
    """Capture a single acquisition then stop. Returns trigger status."""
    scope.write(":SINGle")
    if err := check_scpi_error(scope):
        raise RuntimeError(f"SCPI error after :SINGle: {err}")
    return scope.query(":TRIGger:STATus?").strip()


def autoscale(scope: pyvisa.resources.Resource) -> None:
    """Run the scope's auto-setup (timebase, vertical scale, trigger).

    DS1000Z uses :AUToscale, DHO800 uses :AUToset.
    """
    cmd = ":AUToset" if get_family() == ScopeFamily.DHO800 else ":AUToscale"
    scope.query(f"{cmd};*OPC?")  # chain OPC? so we block until complete
    if err := check_scpi_error(scope):
        raise RuntimeError(f"SCPI error after {cmd}: {err}")


def idn(scope: pyvisa.resources.Resource) -> str:
    """Return the instrument identification string."""
    return scope.query("*IDN?").strip()


# Single-source measurement items — shared across all families
MEASURE_ITEMS = frozenset({
    # Voltage
    "VMAX", "VMIN", "VPP", "VTOP", "VBASE", "VAMP", "VAVG", "VRMS",
    "OVERSHOOT", "PRESHOOT", "MAREA", "MPAREA",
    "VUPPER", "VMID", "VLOWER", "VARIANCE", "PVRMS",
    # Time (single-source)
    "PERIOD", "FREQUENCY", "RTIME", "FTIME",
    "PWIDTH", "NWIDTH", "PDUTY", "NDUTY",
    "TVMAX", "TVMIN", "PSLEWRATE", "NSLEWRATE",
    "PPULSES", "NPULSES", "PEDGES", "NEDGES",
})

# Two-source measurements — require both source1 and source2.
# DS1000Z names: RDELAY, FDELAY, RPHASE, FPHASE
# DHO800 names:  RRDELAY, FFDELAY, RRPHASE, FFPHASE  (+ cross-edge: RFDELAY, FRDELAY, RFPHASE, FRPHASE)
# We accept both sets and translate internally.
MEASURE_ITEMS_TWO_SOURCE_DS1000Z = frozenset({
    "RDELAY", "FDELAY", "RPHASE", "FPHASE",
})

MEASURE_ITEMS_TWO_SOURCE_DHO800 = frozenset({
    "RRDELAY", "FFDELAY", "RRPHASE", "FFPHASE",
    "RFDELAY", "FRDELAY", "RFPHASE", "FRPHASE",
})

# Mapping from DS1000Z names → DHO800 equivalents (for user convenience)
_TWO_SOURCE_DS_TO_DHO: dict[str, str] = {
    "RDELAY": "RRDELAY", "FDELAY": "FFDELAY",
    "RPHASE": "RRPHASE", "FPHASE": "FFPHASE",
}

MEASURE_ITEMS_TWO_SOURCE = MEASURE_ITEMS_TWO_SOURCE_DS1000Z | MEASURE_ITEMS_TWO_SOURCE_DHO800


def measure(scope: pyvisa.resources.Resource, channel: str, item: str) -> str:
    """Query a single-source built-in measurement. Returns the raw value string."""
    ch = channel.upper()
    it = item.upper()
    if it in MEASURE_ITEMS_TWO_SOURCE:
        raise ValueError(f"'{item}' requires two sources — use measure_between()")
    if it not in MEASURE_ITEMS:
        raise ValueError(f"Unknown item '{item}'. Valid: {sorted(MEASURE_ITEMS)}")
    scope.write(f":MEASure:ITEM {it},{ch}")
    return scope.query(f":MEASure:ITEM? {it},{ch}").strip()


def measure_between(
    scope: pyvisa.resources.Resource,
    source1: str,
    source2: str,
    item: str,
) -> str:
    """Query a two-source measurement (delay or phase) between two channels.

    Accepts both DS1000Z names (RDELAY, FDELAY, RPHASE, FPHASE) and
    DHO800 names (RRDELAY, FFDELAY, RRPHASE, FFPHASE, plus cross-edge
    variants RFDELAY, FRDELAY, RFPHASE, FRPHASE).

    source1/source2: CHAN1–CHAN4.
    Returns the raw value string (delay in seconds, phase in degrees).
    """
    it = item.upper()
    if it not in MEASURE_ITEMS_TWO_SOURCE:
        raise ValueError(
            f"'{item}' is not a two-source item. Valid: {sorted(MEASURE_ITEMS_TWO_SOURCE)}"
        )

    # Translate item name if needed for the connected scope family
    family = get_family()
    if family == ScopeFamily.DHO800 and it in _TWO_SOURCE_DS_TO_DHO:
        it = _TWO_SOURCE_DS_TO_DHO[it]
    elif family == ScopeFamily.DS1000Z and it in MEASURE_ITEMS_TWO_SOURCE_DHO800:
        # Reverse lookup: DHO800 name used with DS1000Z scope
        reverse = {v: k for k, v in _TWO_SOURCE_DS_TO_DHO.items()}
        if it in reverse:
            it = reverse[it]
        else:
            raise ValueError(
                f"'{item}' is a DHO800-only item and not supported on DS1000Z"
            )

    s1 = source1.upper()
    s2 = source2.upper()
    scope.write(f":MEASure:ITEM {it},{s1},{s2}")
    return scope.query(f":MEASure:ITEM? {it},{s1},{s2}").strip()


def get_scope_state(scope: pyvisa.resources.Resource) -> dict:
    """Return a snapshot of the scope's current configuration."""
    prof = get_profile()
    state: dict = {
        "model": prof.model,
        "scope_family": prof.family.value,
        "analog_channels": prof.max_channels,
        "has_awg": prof.has_awg,
        "half_screen_divs": prof.half_screen_divs,
    }

    state["timebase"] = {
        "scale_s_div": scope.query(":TIM:SCAL?").strip(),
        "offset_s":    scope.query(":TIM:OFFS?").strip(),
        "mode":        scope.query(":TIM:MODE?").strip(),
    }

    state["channels"] = {}
    for i in range(1, prof.max_channels + 1):
        ch = f"CHAN{i}"
        state["channels"][ch] = {
            "display":    scope.query(f":{ch}:DISP?").strip(),
            "scale_v_div": scope.query(f":{ch}:SCAL?").strip(),
            "offset_v":   scope.query(f":{ch}:OFFS?").strip(),
            "coupling":   scope.query(f":{ch}:COUP?").strip(),
            "probe":      scope.query(f":{ch}:PROB?").strip(),
        }

    trig_mode = scope.query(":TRIGger:MODE?").strip()
    state["trigger"] = {
        "mode":   trig_mode,
        "status": scope.query(":TRIGger:STATus?").strip(),
    }
    if trig_mode.upper() in ("EDGE", "EDGMODE"):
        state["trigger"].update({
            "source":  scope.query(":TRIGger:EDGE:SOURce?").strip(),
            "slope":   scope.query(":TRIGger:EDGE:SLOPe?").strip(),
            "level_v": scope.query(":TRIGger:EDGE:LEVel?").strip(),
        })

    return state


def set_channel(
    scope: pyvisa.resources.Resource,
    channel: str,
    display: bool | None = None,
    scale: float | None = None,
    offset: float | None = None,
    coupling: str | None = None,
    probe: float | None = None,
) -> None:
    """Configure a channel. Only specified parameters are changed."""
    ch = channel.upper()
    if display is not None:
        scope.write(f":{ch}:DISP {'ON' if display else 'OFF'}")
    if scale is not None:
        scope.write(f":{ch}:SCAL {scale}")
    if offset is not None:
        scope.write(f":{ch}:OFFS {offset}")
    if coupling is not None:
        scope.write(f":{ch}:COUP {coupling.upper()}")
    if probe is not None:
        scope.write(f":{ch}:PROB {probe}")
    if err := check_scpi_error(scope):
        raise RuntimeError(f"SCPI error in set_channel({ch}): {err}")


def set_timebase(
    scope: pyvisa.resources.Resource,
    scale: float | None = None,
    offset: float | None = None,
) -> None:
    """Set timebase scale (s/div) and/or offset (s)."""
    if scale is not None:
        scope.write(f":TIM:SCAL {scale}")
    if offset is not None:
        scope.write(f":TIM:OFFS {offset}")
    if err := check_scpi_error(scope):
        raise RuntimeError(f"SCPI error in set_timebase: {err}")


def set_trigger(
    scope: pyvisa.resources.Resource,
    source: str | None = None,
    slope: str | None = None,
    level: float | None = None,
) -> None:
    """Configure edge trigger. source: CHAN1–CHAN4, EXT. slope: POS, NEG, RFAL."""
    scope.write(":TRIGger:MODE EDGE")
    if source is not None:
        scope.write(f":TRIGger:EDGE:SOURce {source.upper()}")
    if slope is not None:
        scope.write(f":TRIGger:EDGE:SLOPe {slope.upper()}")
    if level is not None:
        scope.write(f":TRIGger:EDGE:LEVel {level}")
    if err := check_scpi_error(scope):
        raise RuntimeError(f"SCPI error in set_trigger: {err}")


def get_waveform(scope: pyvisa.resources.Resource, channel: str) -> dict:
    """Download waveform data for a channel (screen buffer, NORM mode).

    Returns time/voltage arrays plus summary statistics.
    Stop or single-trigger the scope first for consistent data.
    """
    ch = channel.upper()
    scope.write(f":WAV:SOUR {ch}")
    scope.write(":WAV:MODE NORM")
    scope.write(":WAV:FORM ASC")

    pre_str = scope.query(":WAV:PRE?").strip()
    pre = pre_str.split(",")
    x_inc   = float(pre[4])
    x_origin = float(pre[5])
    x_ref   = float(pre[6])

    data_str = scope.query(":WAV:DATA?").strip()
    # Strip SCPI definite-length block header (#NXXXXXXXXX...) if present
    if data_str.startswith("#"):
        n_digits = int(data_str[1])
        data_str = data_str[2 + n_digits:]
    voltages = [float(v) for v in data_str.split(",")]
    n = len(voltages)
    times = [x_origin + (i - x_ref) * x_inc for i in range(n)]

    return {
        "channel":        ch,
        "points":         n,
        "time_increment_s": x_inc,
        "time_start_s":   times[0] if times else 0.0,
        "time_end_s":     times[-1] if times else 0.0,
        "vmin_v":         min(voltages),
        "vmax_v":         max(voltages),
        "vmean_v":        sum(voltages) / n if n else 0.0,
        "times_s":        times,
        "voltages_v":     voltages,
    }


def screenshot_png(scope: pyvisa.resources.Resource) -> bytes:
    """Return raw PNG bytes from the scope display.

    DS1000Z: :DISPlay:DATA? ON,OFF,PNG  (ON/OFF control header/footer elements)
    DHO800:  :DISPlay:DATA? PNG          (no element control parameters)

    Strips the IEEE 488.2 TMC block header (#NXXXXXXXXX) and trailing \\n.
    """
    if get_family() == ScopeFamily.DHO800:
        scope.write(":DISPlay:DATA? PNG")
    else:
        scope.write(":DISPlay:DATA? ON,OFF,PNG")
    # Read the TMC block header: #<n><length_digits><data>
    # Must read by exact byte count — read_raw() stops at 0x0A which appears in PNG data
    prefix = scope.read_bytes(2)  # '#' + digit-count byte
    if prefix[0:1] != b"#":
        raise ValueError(f"Expected TMC block header starting with '#', got {prefix!r}")
    n = int(prefix[1:2])
    data_length = int(scope.read_bytes(n))
    return scope.read_bytes(data_length)


# ---------------------------------------------------------------------------
# Signal generator (AWG) — available on -S models and community AWG mods
# ---------------------------------------------------------------------------

# Waveform types supported by :SOURce:FUNCtion
SOURCE_WAVEFORMS = frozenset({
    "SIN", "SQU", "RAMP", "PULS", "NOIS", "DC", "ARB",
})

# Max source channels per family: DS1000Z-S has 2, DHO900S has 1
_MAX_SOURCE_CHANNELS: dict[ScopeFamily, int] = {
    ScopeFamily.DS1000Z: 2,
    ScopeFamily.DHO800: 1,
}


def _check_awg(source: int = 1) -> str:
    """Validate AWG is available and return the :SOURce prefix.

    Raises RuntimeError if the connected scope has no signal generator.
    """
    prof = get_profile()
    if not prof.has_awg:
        raise RuntimeError(
            f"Signal generator not available on {prof.model}. "
            "Requires a -S model (DS1074Z-S, DHO914S, DHO924S, etc.)"
        )
    max_ch = _MAX_SOURCE_CHANNELS.get(prof.family, 1)
    if source < 1 or source > max_ch:
        raise ValueError(
            f"Source channel {source} out of range (1–{max_ch} for {prof.model})"
        )
    return f":SOURce{source}"


def get_source_state(scope: pyvisa.resources.Resource, source: int = 1) -> dict:
    """Return a snapshot of a signal generator channel's configuration."""
    p = _check_awg(source)
    return {
        "source":     source,
        "output":     scope.query(f"{p}:OUTPut?").strip(),
        "function":   scope.query(f"{p}:FUNCtion?").strip(),
        "frequency":  scope.query(f"{p}:FREQuency?").strip(),
        "amplitude":  scope.query(f"{p}:VOLTage?").strip(),
        "offset":     scope.query(f"{p}:VOLTage:OFFSet?").strip(),
        "phase":      scope.query(f"{p}:PHASe?").strip(),
        "duty_cycle": scope.query(f"{p}:PULSe:DCYCle?").strip(),
        "impedance":  scope.query(f"{p}:OUTPut:IMPedance?").strip(),
    }


def set_source(
    scope: pyvisa.resources.Resource,
    source: int = 1,
    function: str | None = None,
    frequency: float | None = None,
    amplitude: float | None = None,
    offset: float | None = None,
    phase: float | None = None,
    duty_cycle: float | None = None,
    impedance: str | None = None,
) -> None:
    """Configure a signal generator channel. Only specified parameters are changed.

    function: SIN, SQU, RAMP, PULS, NOIS, DC, ARB.
    frequency: Hz. amplitude: Vpp. offset: V. phase: degrees (0–360).
    duty_cycle: % (pulse only). impedance: OMEG (high-Z) or FIFT (50 ohm).
    """
    p = _check_awg(source)
    if function is not None:
        fn = function.upper()
        if fn not in SOURCE_WAVEFORMS:
            raise ValueError(f"Unknown waveform '{function}'. Valid: {sorted(SOURCE_WAVEFORMS)}")
        scope.write(f"{p}:FUNCtion {fn}")
    if frequency is not None:
        scope.write(f"{p}:FREQuency {frequency}")
    if amplitude is not None:
        scope.write(f"{p}:VOLTage {amplitude}")
    if offset is not None:
        scope.write(f"{p}:VOLTage:OFFSet {offset}")
    if phase is not None:
        scope.write(f"{p}:PHASe {phase}")
    if duty_cycle is not None:
        scope.write(f"{p}:PULSe:DCYCle {duty_cycle}")
    if impedance is not None:
        scope.write(f"{p}:OUTPut:IMPedance {impedance.upper()}")
    if err := check_scpi_error(scope):
        raise RuntimeError(f"SCPI error in set_source: {err}")


def source_output(
    scope: pyvisa.resources.Resource,
    enable: bool,
    source: int = 1,
) -> str:
    """Enable or disable a signal generator output. Returns the resulting state."""
    p = _check_awg(source)
    scope.write(f"{p}:OUTPut {'ON' if enable else 'OFF'}")
    if err := check_scpi_error(scope):
        raise RuntimeError(f"SCPI error after {p}:OUTPut: {err}")
    return scope.query(f"{p}:OUTPut?").strip()
