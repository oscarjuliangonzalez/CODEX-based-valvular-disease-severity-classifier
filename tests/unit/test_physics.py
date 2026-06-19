import math

import pytest

from ar_core.evidence.interpretation import (
    interpret_jet_width_ratio,
    interpret_pressure_half_time,
    interpret_vena_contracta_width,
)
from ar_core.measurements.physics import (
    classic_pisa_surface_area_cm2,
    eroa_peak_cm2,
    pressure_half_time_ms,
    regurgitant_fraction,
    regurgitant_volume_from_flows_ml,
    stroke_volume_ml,
    surface_of_revolution_cm2,
    velocity_time_integral_cm,
)


def test_classic_pisa_surface_matches_hemisphere_formula():
    assert classic_pisa_surface_area_cm2(1.2) == pytest.approx(2 * math.pi * 1.2**2)


def test_hemispherical_profile_surface_of_revolution_matches_pisa_surface():
    radius = 0.9
    steps = 2000
    theta = [(math.pi / 2) * i / steps for i in range(steps + 1)]
    rho = [radius * math.sin(value) for value in theta]
    arc = [radius * value for value in theta]

    result = surface_of_revolution_cm2(rho, arc)

    assert result == pytest.approx(2 * math.pi * radius**2, rel=2e-4)


def test_velocity_time_integral_uses_trapezoidal_integration():
    times_s = [0.0, 0.1, 0.2, 0.3]
    velocities_cm_s = [100.0, 120.0, 80.0, 0.0]

    assert velocity_time_integral_cm(times_s, velocities_cm_s) == pytest.approx(25.0)


def test_pressure_half_time_interpolates_half_pressure_velocity():
    times_s = [0.0, 0.1, 0.2, 0.3]
    velocities_m_s = [4.0, 3.2, 2.0, 1.0]

    assert pressure_half_time_ms(times_s, velocities_m_s) == pytest.approx(130.0, abs=1.0)


def test_pressure_half_time_rejects_nonmonotonic_timing():
    with pytest.raises(ValueError, match="monotonic"):
        pressure_half_time_ms([0.0, 0.2, 0.1], [4.0, 3.0, 2.0])


def test_stroke_volume_and_regurgitant_fraction():
    lvot_sv = stroke_volume_ml(diameter_cm=2.0, vti_cm=20.0)
    rvol = regurgitant_volume_from_flows_ml(lvot_sv_ml=lvot_sv, reference_sv_ml=42.8)

    assert lvot_sv == pytest.approx(62.8)
    assert rvol == pytest.approx(20.0)
    assert regurgitant_fraction(rvol_ml=rvol, lvot_sv_ml=lvot_sv) == pytest.approx(31.847, rel=1e-3)


def test_eroa_peak_converts_aliasing_flow_to_cm2():
    assert eroa_peak_cm2(aliasing_velocity_cm_s=40.0, pisa_surface_area_cm2=6.0, vmax_ar_cm_s=400.0) == pytest.approx(0.6)


def test_threshold_interpretations_use_ase_defaults():
    assert interpret_vena_contracta_width(0.29)["classification"] == "mild_supporting"
    assert interpret_vena_contracta_width(0.30)["classification"] == "moderate_supporting"
    assert interpret_vena_contracta_width(0.61)["classification"] == "severe_supporting"
    assert interpret_jet_width_ratio(0.68, central_single_jet=True)["classification"] == "severe_supporting"
    assert interpret_jet_width_ratio(0.68, central_single_jet=False)["technical_validity"] == "limited"
    assert interpret_pressure_half_time(180)["classification"] == "severe_supporting"
    assert interpret_pressure_half_time(650)["limitations"] == ["load_dependent"]


def test_invalid_units_and_missing_calibration_raise_clear_errors():
    with pytest.raises(ValueError, match="positive"):
        classic_pisa_surface_area_cm2(-1.0)
    with pytest.raises(ValueError, match="same length"):
        velocity_time_integral_cm([0.0, 0.1], [100.0])
    with pytest.raises(ValueError, match="greater than reference"):
        regurgitant_volume_from_flows_ml(lvot_sv_ml=30.0, reference_sv_ml=40.0)
