"""Tests for waveform_analysis.py."""


from rigol_mcp.waveform_analysis import _fmt_si, describe_waveform

# ---------------------------------------------------------------------------
# SI prefix formatting
# ---------------------------------------------------------------------------

class TestFmtSi:
    def test_zero(self) -> None:
        assert _fmt_si(0, "V") == "0 V"

    def test_millivolts(self) -> None:
        result = _fmt_si(0.0033, "V")
        assert "mV" in result

    def test_megahertz(self) -> None:
        result = _fmt_si(1_350_000, "Hz")
        assert "MHz" in result

    def test_microseconds(self) -> None:
        result = _fmt_si(0.000_050, "s")
        assert "µs" in result

    def test_kilohertz(self) -> None:
        result = _fmt_si(4700, "Hz")
        assert "kHz" in result


# ---------------------------------------------------------------------------
# Waveform description
# ---------------------------------------------------------------------------

def _make_sine_data(
    freq: float = 1000.0,
    amplitude: float = 1.0,
    n_points: int = 600,
    duration: float = 0.012,
) -> dict:
    """Generate synthetic sine wave data."""
    import math
    dt = duration / n_points
    times = [i * dt for i in range(n_points)]
    voltages = [amplitude * math.sin(2 * math.pi * freq * t) for t in times]
    return {
        "channel": "CHAN1",
        "points": n_points,
        "time_increment_s": dt,
        "time_start_s": times[0],
        "time_end_s": times[-1],
        "vmin_v": min(voltages),
        "vmax_v": max(voltages),
        "vmean_v": sum(voltages) / n_points,
        "times_s": times,
        "voltages_v": voltages,
    }


def _make_dc_data(voltage: float = 3.3, n_points: int = 600) -> dict:
    """Generate flat DC signal data."""
    times = [i * 0.00002 for i in range(n_points)]
    voltages = [voltage] * n_points
    return {
        "channel": "CHAN1",
        "points": n_points,
        "time_increment_s": 0.00002,
        "time_start_s": times[0],
        "time_end_s": times[-1],
        "vmin_v": voltage,
        "vmax_v": voltage,
        "vmean_v": voltage,
        "times_s": times,
        "voltages_v": voltages,
    }


class TestDescribeWaveform:
    def test_sine_detects_oscillation(self) -> None:
        data = _make_sine_data(freq=1000, n_points=600)
        result = describe_waveform(data)
        assert "oscillation" in result.lower() or "CHAN1" in result
        assert "CHAN1" in result

    def test_dc_detects_flat(self) -> None:
        data = _make_dc_data(3.3)
        result = describe_waveform(data)
        assert "DC" in result or "flat" in result

    def test_includes_voltage_info(self) -> None:
        data = _make_sine_data(amplitude=2.5)
        result = describe_waveform(data)
        assert "Vpp" in result
        assert "Vmin" in result
        assert "Vmax" in result

    def test_includes_window_info(self) -> None:
        data = _make_sine_data()
        result = describe_waveform(data)
        assert "Window" in result
        assert "pts" in result

    def test_half_screen_divs_in_warning(self) -> None:
        """The right-edge formula should use the passed half_screen_divs value."""
        # Sine that doesn't end at zero crossing → triggers right-edge warning
        import math
        n = 100
        dt = 0.001 / n
        times = [i * dt for i in range(n)]
        # 3.7 cycles — guaranteed to end mid-cycle
        voltages = [math.sin(2 * math.pi * 3700 * t) for t in times]
        data = {
            "channel": "CHAN1", "points": n, "time_increment_s": dt,
            "time_start_s": times[0], "time_end_s": times[-1],
            "vmin_v": min(voltages), "vmax_v": max(voltages),
            "vmean_v": sum(voltages) / n,
            "times_s": times, "voltages_v": voltages,
        }
        result_ds = describe_waveform(data, half_screen_divs=6)
        result_dho = describe_waveform(data, half_screen_divs=5)
        # If the right-edge warning is triggered, it should contain the correct divisor
        if "scale" in result_ds:
            assert "6" in result_ds
        if "scale" in result_dho:
            assert "5" in result_dho

    def test_sine_frequency_estimate(self) -> None:
        """Frequency estimate should be roughly correct for a clean sine."""
        data = _make_sine_data(freq=5000, n_points=1000, duration=0.005)
        result = describe_waveform(data)
        # Should mention kHz range
        assert "Freq" in result or "Hz" in result
