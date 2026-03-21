"""Tests for scope.py — model detection, geometry, cursor math, command translation."""

from unittest.mock import MagicMock, patch

import pytest

from rigol_mcp.scope import (
    _PROFILES,
    _TWO_SOURCE_DS_TO_DHO,
    MEASURE_ITEMS,
    MEASURE_ITEMS_TWO_SOURCE,
    MEASURE_ITEMS_TWO_SOURCE_DHO800,
    MEASURE_ITEMS_TWO_SOURCE_DS1000Z,
    ScopeFamily,
    _detect_channels,
    _detect_family,
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
# Channel count detection
# ---------------------------------------------------------------------------

class TestDetectChannels:
    """Test _detect_channels() for 2-channel vs 4-channel models."""

    def test_dho804_is_4ch(self) -> None:
        assert _detect_channels("RIGOL TECHNOLOGIES,DHO804,serial,fw", ScopeFamily.DHO800) == 4

    def test_dho802_is_2ch(self) -> None:
        assert _detect_channels("RIGOL TECHNOLOGIES,DHO802,serial,fw", ScopeFamily.DHO800) == 2

    def test_dho812_is_2ch(self) -> None:
        assert _detect_channels("RIGOL TECHNOLOGIES,DHO812,serial,fw", ScopeFamily.DHO800) == 2

    def test_dho814_is_4ch(self) -> None:
        assert _detect_channels("RIGOL TECHNOLOGIES,DHO814,serial,fw", ScopeFamily.DHO800) == 4

    def test_dho824_is_4ch(self) -> None:
        assert _detect_channels("RIGOL TECHNOLOGIES,DHO824,serial,fw", ScopeFamily.DHO800) == 4

    def test_dho914s_is_4ch(self) -> None:
        assert _detect_channels("RIGOL TECHNOLOGIES,DHO914S,serial,fw", ScopeFamily.DHO800) == 4

    def test_ds1054z_is_4ch(self) -> None:
        assert _detect_channels("RIGOL TECHNOLOGIES,DS1054Z,serial,fw", ScopeFamily.DS1000Z) == 4


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
