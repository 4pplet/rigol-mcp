"""Tests for scope.py — model detection, geometry, cursor math, command translation."""

from unittest.mock import MagicMock, patch

import pytest

from rigol_mcp.scope import (
    _MAX_SOURCE_CHANNELS,
    _PROFILES,
    _TWO_SOURCE_DS_TO_DHO,
    MEASURE_ITEMS,
    MEASURE_ITEMS_TWO_SOURCE,
    MEASURE_ITEMS_TWO_SOURCE_DHO800,
    MEASURE_ITEMS_TWO_SOURCE_DS1000Z,
    SOURCE_WAVEFORMS,
    ScopeFamily,
    ScopeProfile,
    _detect_awg,
    _detect_channels,
    _detect_family,
    _parse_model,
)

# ---------------------------------------------------------------------------
# Model detection
# ---------------------------------------------------------------------------

class TestDetectFamily:
    """Test _detect_family() against known *IDN? strings."""

    @pytest.mark.parametrize("idn,expected", [
        ("RIGOL TECHNOLOGIES,DS1054Z,DS1ZA123456789,00.04.04.SP4", ScopeFamily.DS1000Z),
        ("RIGOL TECHNOLOGIES,DS1104Z,DS1ZA999999999,00.04.04.SP4", ScopeFamily.DS1000Z),
        ("RIGOL TECHNOLOGIES,DS1074Z-S,DS1ZA111111111,00.04.04", ScopeFamily.DS1000Z),
        ("RIGOL TECHNOLOGIES,MSO1104Z,MS1ZA222222222,00.04.04", ScopeFamily.DS1000Z),
        ("RIGOL TECHNOLOGIES,MSO1074Z,MS1ZA333333333,00.04.04", ScopeFamily.DS1000Z),
    ])
    def test_ds1000z_models(self, idn: str, expected: ScopeFamily) -> None:
        assert _detect_family(idn) == expected

    @pytest.mark.parametrize("idn,expected", [
        ("RIGOL TECHNOLOGIES,DHO804,DHO8A123456789,00.01.02", ScopeFamily.DHO800),
        ("RIGOL TECHNOLOGIES,DHO802,DHO8A999999999,00.01.02", ScopeFamily.DHO800),
        ("RIGOL TECHNOLOGIES,DHO814,DHO8A111111111,00.01.02", ScopeFamily.DHO800),
        ("RIGOL TECHNOLOGIES,DHO824,DHO8A222222222,00.01.02", ScopeFamily.DHO800),
        ("RIGOL TECHNOLOGIES,DHO914,DHO9A333333333,00.01.02", ScopeFamily.DHO800),
        ("RIGOL TECHNOLOGIES,DHO914S,DHO9A444444444,00.01.02", ScopeFamily.DHO800),
        ("RIGOL TECHNOLOGIES,DHO924S,DHO9A555555555,00.01.02", ScopeFamily.DHO800),
    ])
    def test_dho800_models(self, idn: str, expected: ScopeFamily) -> None:
        assert _detect_family(idn) == expected

    def test_unknown_defaults_to_ds1000z(self) -> None:
        """Unknown instruments default to DS1000Z to preserve backward compat."""
        assert _detect_family("KEYSIGHT,DSO-X 1234,SERIAL,FW") == ScopeFamily.DS1000Z
        assert _detect_family("UNKNOWN INSTRUMENT") == ScopeFamily.DS1000Z

    def test_case_insensitive(self) -> None:
        """Detection should work regardless of case."""
        assert _detect_family("rigol technologies,dho804,serial,fw") == ScopeFamily.DHO800
        assert _detect_family("Rigol Technologies,Dho914S,serial,fw") == ScopeFamily.DHO800


# ---------------------------------------------------------------------------
# Model string parsing
# ---------------------------------------------------------------------------

class TestParseModel:
    """Test _parse_model() extracts model from *IDN? response."""

    def test_standard_format(self) -> None:
        assert _parse_model("RIGOL TECHNOLOGIES,DHO804,serial,fw") == "DHO804"

    def test_ds1000z(self) -> None:
        assert _parse_model("RIGOL TECHNOLOGIES,DS1054Z,DS1ZA123,00.04.04") == "DS1054Z"

    def test_with_suffix(self) -> None:
        assert _parse_model("RIGOL TECHNOLOGIES,DS1074Z-S,serial,fw") == "DS1074Z-S"

    def test_empty_string(self) -> None:
        assert _parse_model("") == ""

    def test_no_commas(self) -> None:
        assert _parse_model("UNKNOWN") == ""

    def test_whitespace_stripped(self) -> None:
        assert _parse_model("RIGOL, DHO804 ,serial,fw") == "DHO804"


# ---------------------------------------------------------------------------
# Channel count detection
# ---------------------------------------------------------------------------

class TestDetectChannels:
    """Test _detect_channels() for 2-channel vs 4-channel models."""

    def test_dho804_is_4ch(self) -> None:
        assert _detect_channels("DHO804", ScopeFamily.DHO800) == 4

    def test_dho802_is_2ch(self) -> None:
        assert _detect_channels("DHO802", ScopeFamily.DHO800) == 2

    def test_dho812_is_2ch(self) -> None:
        assert _detect_channels("DHO812", ScopeFamily.DHO800) == 2

    def test_dho814_is_4ch(self) -> None:
        assert _detect_channels("DHO814", ScopeFamily.DHO800) == 4

    def test_dho824_is_4ch(self) -> None:
        assert _detect_channels("DHO824", ScopeFamily.DHO800) == 4

    def test_dho914s_is_4ch(self) -> None:
        assert _detect_channels("DHO914S", ScopeFamily.DHO800) == 4

    def test_ds1054z_is_4ch(self) -> None:
        assert _detect_channels("DS1054Z", ScopeFamily.DS1000Z) == 4


# ---------------------------------------------------------------------------
# AWG detection
# ---------------------------------------------------------------------------

class TestDetectAwg:
    """Test _detect_awg() for signal generator models."""

    # DHO800/900 with AWG
    def test_dho914s_has_awg(self) -> None:
        assert _detect_awg("DHO914S", ScopeFamily.DHO800) is True

    def test_dho924s_has_awg(self) -> None:
        assert _detect_awg("DHO924S", ScopeFamily.DHO800) is True

    # DHO800/900 without AWG
    def test_dho804_no_awg(self) -> None:
        assert _detect_awg("DHO804", ScopeFamily.DHO800) is False

    def test_dho824_no_awg(self) -> None:
        assert _detect_awg("DHO824", ScopeFamily.DHO800) is False

    def test_dho914_no_awg(self) -> None:
        assert _detect_awg("DHO914", ScopeFamily.DHO800) is False

    # DS1000Z with AWG
    def test_ds1074z_s_has_awg(self) -> None:
        assert _detect_awg("DS1074Z-S", ScopeFamily.DS1000Z) is True

    def test_ds1104z_s_has_awg(self) -> None:
        assert _detect_awg("DS1104Z-S", ScopeFamily.DS1000Z) is True

    # DS1000Z without AWG
    def test_ds1054z_no_awg(self) -> None:
        assert _detect_awg("DS1054Z", ScopeFamily.DS1000Z) is False

    def test_mso1104z_no_awg(self) -> None:
        assert _detect_awg("MSO1104Z", ScopeFamily.DS1000Z) is False


# ---------------------------------------------------------------------------
# Scope profiles / geometry
# ---------------------------------------------------------------------------

class TestScopeProfiles:
    """Verify geometry constants for each scope family."""

    def test_ds1000z_profile(self) -> None:
        p = _PROFILES[ScopeFamily.DS1000Z]
        assert p.screen_divisions == 12
        assert p.points_per_div == 50
        assert p.screen_points == 600
        assert p.screen_center == 300
        assert p.half_screen_divs == 6
        assert p.max_channels == 4

    def test_dho800_profile(self) -> None:
        p = _PROFILES[ScopeFamily.DHO800]
        assert p.screen_divisions == 10
        assert p.points_per_div == 100
        assert p.screen_points == 1000
        assert p.screen_center == 500
        assert p.half_screen_divs == 5

    def test_all_families_have_profiles(self) -> None:
        for family in ScopeFamily:
            assert family in _PROFILES, f"Missing profile for {family}"

    def test_profile_frozen(self) -> None:
        """Profiles should be immutable."""
        p = _PROFILES[ScopeFamily.DS1000Z]
        with pytest.raises(AttributeError):
            p.screen_divisions = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Cursor math (DS1000Z pixel conversion)
# ---------------------------------------------------------------------------

class TestCursorMath:
    """Test time↔pixel conversions for DS1000Z."""

    def _mock_scope(self, scale: float, offset: float) -> MagicMock:
        """Create a mock scope that returns given timebase values."""
        scope = MagicMock()
        def query_side_effect(cmd: str) -> str:
            if "TIM:SCAL" in cmd:
                return f"{scale}\n"
            if "TIM:OFFS" in cmd:
                return f"{offset}\n"
            return ""
        scope.query.side_effect = query_side_effect
        return scope

    @patch("rigol_mcp.scope._profile", _PROFILES[ScopeFamily.DS1000Z])
    def test_center_maps_to_offset(self) -> None:
        """Screen center (pixel 300) should map to the timebase offset."""
        from rigol_mcp.scope import screen_x_to_time
        scope = self._mock_scope(scale=0.001, offset=0.0)
        t = screen_x_to_time(scope, 300)
        assert t == pytest.approx(0.0)

    @patch("rigol_mcp.scope._profile", _PROFILES[ScopeFamily.DS1000Z])
    def test_time_to_screen_center(self) -> None:
        """Time at offset should map back to screen center."""
        from rigol_mcp.scope import time_to_screen_x
        scope = self._mock_scope(scale=0.001, offset=0.0)
        px = time_to_screen_x(scope, 0.0)
        assert px == 300

    @patch("rigol_mcp.scope._profile", _PROFILES[ScopeFamily.DS1000Z])
    def test_roundtrip(self) -> None:
        """time→pixel→time should round-trip closely."""
        from rigol_mcp.scope import screen_x_to_time, time_to_screen_x
        scope = self._mock_scope(scale=0.001, offset=0.005)
        t_original = 0.003
        px = time_to_screen_x(scope, t_original)
        t_back = screen_x_to_time(scope, px)
        assert t_back == pytest.approx(t_original, abs=0.001 / 50)  # within 1 pixel

    @patch("rigol_mcp.scope._profile", _PROFILES[ScopeFamily.DS1000Z])
    def test_clamped_to_valid_range(self) -> None:
        """Pixel values should be clamped to [5, 594]."""
        from rigol_mcp.scope import time_to_screen_x
        scope = self._mock_scope(scale=0.001, offset=0.0)
        # Way off screen left
        assert time_to_screen_x(scope, -1.0) == 5
        # Way off screen right
        assert time_to_screen_x(scope, 1.0) == 594

    @patch("rigol_mcp.scope._profile", _PROFILES[ScopeFamily.DS1000Z])
    def test_with_offset(self) -> None:
        """Verify pixel conversion respects timebase offset."""
        from rigol_mcp.scope import time_to_screen_x
        scope = self._mock_scope(scale=0.001, offset=0.010)
        # t=0.010 is at offset, should be center
        px = time_to_screen_x(scope, 0.010)
        assert px == 300


# ---------------------------------------------------------------------------
# Measurement item mapping
# ---------------------------------------------------------------------------

class TestMeasurementItems:
    """Test measurement item sets and translation."""

    def test_common_items_present(self) -> None:
        """Basic items should exist in the shared set."""
        for item in ("VMAX", "VMIN", "VPP", "FREQUENCY", "PERIOD", "VRMS"):
            assert item in MEASURE_ITEMS

    def test_two_source_ds1000z(self) -> None:
        for item in ("RDELAY", "FDELAY", "RPHASE", "FPHASE"):
            assert item in MEASURE_ITEMS_TWO_SOURCE_DS1000Z
            assert item in MEASURE_ITEMS_TWO_SOURCE

    def test_two_source_dho800(self) -> None:
        for item in ("RRDELAY", "FFDELAY", "RRPHASE", "FFPHASE",
                      "RFDELAY", "FRDELAY", "RFPHASE", "FRPHASE"):
            assert item in MEASURE_ITEMS_TWO_SOURCE_DHO800
            assert item in MEASURE_ITEMS_TWO_SOURCE

    def test_ds_to_dho_mapping_complete(self) -> None:
        """Every DS1000Z two-source item should have a DHO800 equivalent."""
        for ds_name in MEASURE_ITEMS_TWO_SOURCE_DS1000Z:
            assert ds_name in _TWO_SOURCE_DS_TO_DHO, f"Missing mapping for {ds_name}"

    def test_no_overlap_between_single_and_two_source(self) -> None:
        """Single-source and two-source sets should be disjoint."""
        overlap = MEASURE_ITEMS & MEASURE_ITEMS_TWO_SOURCE
        assert len(overlap) == 0, f"Overlap: {overlap}"

    def test_ds_to_dho_mapping_values(self) -> None:
        assert _TWO_SOURCE_DS_TO_DHO["RDELAY"] == "RRDELAY"
        assert _TWO_SOURCE_DS_TO_DHO["FDELAY"] == "FFDELAY"
        assert _TWO_SOURCE_DS_TO_DHO["RPHASE"] == "RRPHASE"
        assert _TWO_SOURCE_DS_TO_DHO["FPHASE"] == "FFPHASE"


# ---------------------------------------------------------------------------
# measure_between translation
# ---------------------------------------------------------------------------

class TestMeasureBetweenTranslation:
    """Test that measure_between translates item names between families."""

    @patch("rigol_mcp.scope._profile", _PROFILES[ScopeFamily.DHO800])
    def test_ds_name_translated_to_dho(self) -> None:
        """DS1000Z name 'RDELAY' should be sent as 'RRDELAY' on DHO800."""
        from rigol_mcp.scope import measure_between
        scope = MagicMock()
        scope.query.return_value = "1.234e-6"
        measure_between(scope, "CHAN1", "CHAN2", "RDELAY")
        # The SCPI command should use the translated name
        write_calls = [str(c) for c in scope.write.call_args_list]
        assert any("RRDELAY" in c for c in write_calls)

    @patch("rigol_mcp.scope._profile", _PROFILES[ScopeFamily.DS1000Z])
    def test_dho_name_reverse_translated_to_ds(self) -> None:
        """DHO800 name 'RRDELAY' should be sent as 'RDELAY' on DS1000Z."""
        from rigol_mcp.scope import measure_between
        scope = MagicMock()
        scope.query.return_value = "1.234e-6"
        measure_between(scope, "CHAN1", "CHAN2", "RRDELAY")
        write_calls = [str(c) for c in scope.write.call_args_list]
        assert any("RDELAY" in c for c in write_calls)

    @patch("rigol_mcp.scope._profile", _PROFILES[ScopeFamily.DS1000Z])
    def test_dho_only_item_rejected_on_ds1000z(self) -> None:
        """DHO800-only cross-edge items should be rejected on DS1000Z."""
        from rigol_mcp.scope import measure_between
        scope = MagicMock()
        with pytest.raises(ValueError, match="DHO800-only"):
            measure_between(scope, "CHAN1", "CHAN2", "RFDELAY")

    @patch("rigol_mcp.scope._profile", _PROFILES[ScopeFamily.DHO800])
    def test_native_dho_name_unchanged(self) -> None:
        """DHO800-native name should be sent as-is on DHO800."""
        from rigol_mcp.scope import measure_between
        scope = MagicMock()
        scope.query.return_value = "1.234e-6"
        measure_between(scope, "CHAN1", "CHAN2", "RFDELAY")
        write_calls = [str(c) for c in scope.write.call_args_list]
        assert any("RFDELAY" in c for c in write_calls)


# ---------------------------------------------------------------------------
# Autoscale command selection
# ---------------------------------------------------------------------------

class TestAutoscaleCommand:
    """Verify correct autoscale command per family."""

    @patch("rigol_mcp.scope._profile", _PROFILES[ScopeFamily.DS1000Z])
    def test_ds1000z_uses_autoscale(self) -> None:
        from rigol_mcp.scope import autoscale
        scope = MagicMock()
        scope.query.return_value = "1"
        with patch("rigol_mcp.scope.check_scpi_error", return_value=None):
            autoscale(scope)
        scope.query.assert_called_once_with(":AUToscale;*OPC?")

    @patch("rigol_mcp.scope._profile", _PROFILES[ScopeFamily.DHO800])
    def test_dho800_uses_autoset(self) -> None:
        from rigol_mcp.scope import autoscale
        scope = MagicMock()
        scope.query.return_value = "1"
        with patch("rigol_mcp.scope.check_scpi_error", return_value=None):
            autoscale(scope)
        scope.query.assert_called_once_with(":AUToset;*OPC?")


# ---------------------------------------------------------------------------
# Screenshot command selection
# ---------------------------------------------------------------------------

class TestScreenshotCommand:
    """Verify correct screenshot command per family."""

    @patch("rigol_mcp.scope._profile", _PROFILES[ScopeFamily.DS1000Z])
    def test_ds1000z_screenshot_command(self) -> None:
        from rigol_mcp.scope import screenshot_png
        scope = MagicMock()
        scope.read_bytes.side_effect = [b"#9", b"000000010", b"\x89PNG" + b"\x00" * 6]
        screenshot_png(scope)
        scope.write.assert_called_once_with(":DISPlay:DATA? ON,OFF,PNG")

    @patch("rigol_mcp.scope._profile", _PROFILES[ScopeFamily.DHO800])
    def test_dho800_screenshot_command(self) -> None:
        from rigol_mcp.scope import screenshot_png
        scope = MagicMock()
        scope.read_bytes.side_effect = [b"#9", b"000000010", b"\x89PNG" + b"\x00" * 6]
        screenshot_png(scope)
        scope.write.assert_called_once_with(":DISPlay:DATA? PNG")


# ---------------------------------------------------------------------------
# Signal generator (AWG)
# ---------------------------------------------------------------------------

# Helper profiles with AWG enabled
_DHO924S_PROFILE = ScopeProfile(
    family=ScopeFamily.DHO800,
    screen_divisions=10, points_per_div=100, half_screen_divs=5,
    max_channels=4, has_awg=True, model="DHO924S",
)
_DS1074ZS_PROFILE = ScopeProfile(
    family=ScopeFamily.DS1000Z,
    screen_divisions=12, points_per_div=50, half_screen_divs=6,
    max_channels=4, has_awg=True, model="DS1074Z-S",
)
_NO_AWG_PROFILE = ScopeProfile(
    family=ScopeFamily.DHO800,
    screen_divisions=10, points_per_div=100, half_screen_divs=5,
    max_channels=4, has_awg=False, model="DHO804",
)


class TestSignalGenerator:
    """Test signal generator guard and SCPI commands."""

    @patch("rigol_mcp.scope._profile", _NO_AWG_PROFILE)
    def test_check_awg_raises_without_awg(self) -> None:
        from rigol_mcp.scope import _check_awg
        with pytest.raises(RuntimeError, match="not available"):
            _check_awg()

    @patch("rigol_mcp.scope._profile", _DHO924S_PROFILE)
    def test_check_awg_ok_with_awg(self) -> None:
        from rigol_mcp.scope import _check_awg
        assert _check_awg(1) == ":SOURce1"

    @patch("rigol_mcp.scope._profile", _DS1074ZS_PROFILE)
    def test_ds1000z_s_has_two_sources(self) -> None:
        from rigol_mcp.scope import _check_awg
        assert _check_awg(1) == ":SOURce1"
        assert _check_awg(2) == ":SOURce2"

    @patch("rigol_mcp.scope._profile", _DHO924S_PROFILE)
    def test_dho900s_rejects_source_2(self) -> None:
        from rigol_mcp.scope import _check_awg
        with pytest.raises(ValueError, match="out of range"):
            _check_awg(2)

    @patch("rigol_mcp.scope._profile", _DHO924S_PROFILE)
    def test_set_source_sends_commands(self) -> None:
        from rigol_mcp.scope import set_source
        scope = MagicMock()
        with patch("rigol_mcp.scope.check_scpi_error", return_value=None):
            set_source(scope, source=1, function="SIN", frequency=1000, amplitude=2.0)
        calls = [str(c) for c in scope.write.call_args_list]
        assert any(":SOURce1:FUNCtion SIN" in c for c in calls)
        assert any(":SOURce1:FREQuency 1000" in c for c in calls)
        assert any(":SOURce1:VOLTage 2.0" in c for c in calls)

    @patch("rigol_mcp.scope._profile", _DHO924S_PROFILE)
    def test_set_source_rejects_invalid_waveform(self) -> None:
        from rigol_mcp.scope import set_source
        scope = MagicMock()
        with pytest.raises(ValueError, match="Unknown waveform"):
            set_source(scope, function="TRIANGLE")

    @patch("rigol_mcp.scope._profile", _DHO924S_PROFILE)
    def test_source_output_on(self) -> None:
        from rigol_mcp.scope import source_output
        scope = MagicMock()
        scope.query.return_value = "ON"
        with patch("rigol_mcp.scope.check_scpi_error", return_value=None):
            result = source_output(scope, enable=True)
        scope.write.assert_called_once_with(":SOURce1:OUTPut ON")
        assert result == "ON"

    @patch("rigol_mcp.scope._profile", _DHO924S_PROFILE)
    def test_source_output_off(self) -> None:
        from rigol_mcp.scope import source_output
        scope = MagicMock()
        scope.query.return_value = "OFF"
        with patch("rigol_mcp.scope.check_scpi_error", return_value=None):
            result = source_output(scope, enable=False)
        scope.write.assert_called_once_with(":SOURce1:OUTPut OFF")
        assert result == "OFF"

    @patch("rigol_mcp.scope._profile", _DS1074ZS_PROFILE)
    def test_set_source_channel_2(self) -> None:
        """DS1000Z-S source 2 should use :SOURce2 prefix."""
        from rigol_mcp.scope import set_source
        scope = MagicMock()
        with patch("rigol_mcp.scope.check_scpi_error", return_value=None):
            set_source(scope, source=2, function="SQU")
        calls = [str(c) for c in scope.write.call_args_list]
        assert any(":SOURce2:FUNCtion SQU" in c for c in calls)

    def test_source_waveforms_set(self) -> None:
        """Verify standard waveform types are in the set."""
        for wf in ("SIN", "SQU", "RAMP", "PULS", "NOIS", "DC", "ARB"):
            assert wf in SOURCE_WAVEFORMS

    def test_max_source_channels(self) -> None:
        assert _MAX_SOURCE_CHANNELS[ScopeFamily.DS1000Z] == 2
        assert _MAX_SOURCE_CHANNELS[ScopeFamily.DHO800] == 1

    @patch("rigol_mcp.scope._profile", _DHO924S_PROFILE)
    def test_check_awg_rejects_source_zero(self) -> None:
        from rigol_mcp.scope import _check_awg
        with pytest.raises(ValueError, match="out of range"):
            _check_awg(0)

    @patch("rigol_mcp.scope._profile", _DHO924S_PROFILE)
    def test_set_source_offset_and_duty_cycle(self) -> None:
        """Verify offset, duty_cycle, and impedance params are sent."""
        from rigol_mcp.scope import set_source
        scope = MagicMock()
        with patch("rigol_mcp.scope.check_scpi_error", return_value=None):
            set_source(scope, offset=0.5, duty_cycle=25.0, impedance="FIFT")
        calls = [str(c) for c in scope.write.call_args_list]
        assert any(":SOURce1:VOLTage:OFFSet 0.5" in c for c in calls)
        assert any(":SOURce1:PULSe:DCYCle 25.0" in c for c in calls)
        assert any(":SOURce1:OUTPut:IMPedance FIFT" in c for c in calls)

    @patch("rigol_mcp.scope._profile", _DHO924S_PROFILE)
    def test_get_source_state_queries(self) -> None:
        """Verify get_source_state queries the right SCPI commands."""
        from rigol_mcp.scope import get_source_state
        scope = MagicMock()
        scope.query.return_value = "SIN\n"
        state = get_source_state(scope, source=1)
        query_calls = [str(c) for c in scope.query.call_args_list]
        assert any(":SOURce1:OUTPut?" in c for c in query_calls)
        assert any(":SOURce1:FUNCtion?" in c for c in query_calls)
        assert any(":SOURce1:FREQuency?" in c for c in query_calls)
        assert any(":SOURce1:VOLTage?" in c for c in query_calls)
        assert any(":SOURce1:VOLTage:OFFSet?" in c for c in query_calls)
        assert any(":SOURce1:OUTPut:IMPedance?" in c for c in query_calls)
        assert state["source"] == 1
