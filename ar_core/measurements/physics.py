"""Deterministic AR physical calculations.

Stable core functions do not inspect images and must not be changed by
case-specific agents to influence severity.
"""

from __future__ import annotations

import math
from typing import Sequence


def _require_positive(name: str, value: float) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _require_equal_lengths(a: Sequence[float], b: Sequence[float]) -> None:
    if len(a) != len(b):
        raise ValueError("arrays must have the same length")
    if len(a) < 2:
        raise ValueError("at least two samples are required")


def classic_pisa_surface_area_cm2(radius_cm: float) -> float:
    _require_positive("radius_cm", radius_cm)
    return 2.0 * math.pi * radius_cm ** 2


def flow_rate_ml_s(aliasing_velocity_cm_s: float, surface_area_cm2: float) -> float:
    _require_positive("aliasing_velocity_cm_s", aliasing_velocity_cm_s)
    _require_positive("surface_area_cm2", surface_area_cm2)
    return aliasing_velocity_cm_s * surface_area_cm2


def eroa_peak_cm2(aliasing_velocity_cm_s: float, pisa_surface_area_cm2: float, vmax_ar_cm_s: float) -> float:
    _require_positive("vmax_ar_cm_s", vmax_ar_cm_s)
    return flow_rate_ml_s(aliasing_velocity_cm_s, pisa_surface_area_cm2) / vmax_ar_cm_s


def regurgitant_volume_from_eroa_ml(eroa_cm2: float, vti_ar_cm: float) -> float:
    _require_positive("eroa_cm2", eroa_cm2)
    _require_positive("vti_ar_cm", vti_ar_cm)
    return eroa_cm2 * vti_ar_cm


def surface_of_revolution_cm2(radius_from_axis_cm: Sequence[float], arc_length_cm: Sequence[float]) -> float:
    _require_equal_lengths(radius_from_axis_cm, arc_length_cm)
    total = 0.0
    for left in range(len(radius_from_axis_cm) - 1):
        rho0 = radius_from_axis_cm[left]
        rho1 = radius_from_axis_cm[left + 1]
        ds = arc_length_cm[left + 1] - arc_length_cm[left]
        if rho0 < 0 or rho1 < 0:
            raise ValueError("radius_from_axis_cm must be non-negative")
        if ds < 0:
            raise ValueError("arc_length_cm must be monotonic increasing")
        total += math.pi * (rho0 + rho1) * ds
    return total


def integrated_regurgitant_volume_ml(times_s: Sequence[float], aliasing_velocity_cm_s: Sequence[float], surface_area_cm2: Sequence[float]) -> float:
    _require_equal_lengths(times_s, aliasing_velocity_cm_s)
    _require_equal_lengths(times_s, surface_area_cm2)
    flows = [flow_rate_ml_s(va, area) for va, area in zip(aliasing_velocity_cm_s, surface_area_cm2)]
    return velocity_time_integral_cm(times_s, flows)


def velocity_time_integral_cm(times_s: Sequence[float], velocities_cm_s: Sequence[float]) -> float:
    _require_equal_lengths(times_s, velocities_cm_s)
    total = 0.0
    for left in range(len(times_s) - 1):
        dt = times_s[left + 1] - times_s[left]
        if dt < 0:
            raise ValueError("times_s must be monotonic increasing")
        total += 0.5 * (velocities_cm_s[left] + velocities_cm_s[left + 1]) * dt
    return total


def pressure_half_time_ms(times_s: Sequence[float], velocities_m_s: Sequence[float]) -> float:
    _require_equal_lengths(times_s, velocities_m_s)
    for left in range(len(times_s) - 1):
        if times_s[left + 1] <= times_s[left]:
            raise ValueError("times_s must be strictly monotonic increasing")
    vmax = max(velocities_m_s)
    _require_positive("Vmax", vmax)
    peak_index = velocities_m_s.index(vmax)
    target = vmax / math.sqrt(2.0)
    for idx in range(peak_index, len(velocities_m_s) - 1):
        v0 = velocities_m_s[idx]
        v1 = velocities_m_s[idx + 1]
        if (v0 >= target >= v1) or (v1 >= target >= v0):
            if v0 == v1:
                crossing = times_s[idx]
            else:
                fraction = (target - v0) / (v1 - v0)
                crossing = times_s[idx] + fraction * (times_s[idx + 1] - times_s[idx])
            return (crossing - times_s[peak_index]) * 1000.0
    raise ValueError("half-pressure velocity crossing was not found")


def stroke_volume_ml(diameter_cm: float, vti_cm: float) -> float:
    _require_positive("diameter_cm", diameter_cm)
    _require_positive("vti_cm", vti_cm)
    return 0.785 * diameter_cm ** 2 * vti_cm


def regurgitant_volume_from_flows_ml(lvot_sv_ml: float, reference_sv_ml: float) -> float:
    _require_positive("lvot_sv_ml", lvot_sv_ml)
    if reference_sv_ml < 0:
        raise ValueError("reference_sv_ml must be non-negative")
    if lvot_sv_ml < reference_sv_ml:
        raise ValueError("lvot_sv_ml must be greater than reference_sv_ml for AR RVol")
    return lvot_sv_ml - reference_sv_ml


def regurgitant_fraction(rvol_ml: float, lvot_sv_ml: float) -> float:
    _require_positive("lvot_sv_ml", lvot_sv_ml)
    if rvol_ml < 0:
        raise ValueError("rvol_ml must be non-negative")
    if rvol_ml > lvot_sv_ml:
        raise ValueError("rvol_ml cannot exceed lvot_sv_ml")
    return 100.0 * rvol_ml / lvot_sv_ml
