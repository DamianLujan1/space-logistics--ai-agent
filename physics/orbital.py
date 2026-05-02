"""
Orbital mechanics for the space logistics simulator.

All distances in AU, velocities in m/s, times in hours.

Model: simplified coplanar circular Keplerian orbits connected by
Hohmann transfer ellipses.  This gives physically realistic Δv and
transfer-time estimates without requiring numerical integration.

Key formulae
────────────
Circular orbit speed:   v_c(r) = √(μ / r)           μ = G·M_sun

Hohmann departure burn: Δv₁ = v_transfer_peri − v₁
Hohmann arrival burn:   Δv₂ = v₂ − v_transfer_apo
Transfer time:          t = π · √((r₁ + r₂)³ / (8μ))

Fuel mass (Tsiolkovsky): m_fuel = m_dry · (exp(Δv / v_e) − 1)
"""

import math
from typing import Tuple, Dict

from config import G, M_SUN, AU, G0, TRANSIT_SPEED_AU_PER_HOUR


# Gravitational parameter [m³/s²]
MU = G * M_SUN


# ─────────────────────────────────────────────────────────────────────────────
# Basic orbital quantities
# ─────────────────────────────────────────────────────────────────────────────

def circular_speed_m_s(radius_au: float) -> float:
    """Circular orbit speed at *radius_au* from the star [m/s]."""
    r_m = radius_au * AU
    return math.sqrt(MU / r_m)


def orbital_period_hours(radius_au: float) -> float:
    """Keplerian orbital period at *radius_au* [hours]."""
    r_m = radius_au * AU
    period_s = 2.0 * math.pi * math.sqrt(r_m ** 3 / MU)
    return period_s / 3_600.0


# ─────────────────────────────────────────────────────────────────────────────
# Hohmann transfer
# ─────────────────────────────────────────────────────────────────────────────

def hohmann_delta_v(r1_au: float, r2_au: float) -> Tuple[float, float, float]:
    """
    Δv budget for a two-burn Hohmann transfer between circular orbits.

    Returns (dv1, dv2, total_dv) all in m/s.
    dv1 = departure burn (tangential prograde)
    dv2 = arrival circularisation burn
    """
    r1 = r1_au * AU
    r2 = r2_au * AU

    v1 = circular_speed_m_s(r1_au)
    v2 = circular_speed_m_s(r2_au)

    # Semi-major axis of the transfer ellipse
    a_t = (r1 + r2) / 2.0

    # Vis-viva speeds on the transfer ellipse at r1 (periapsis) and r2 (apoapsis)
    v_t_peri = math.sqrt(MU * (2.0 / r1 - 1.0 / a_t))
    v_t_apo  = math.sqrt(MU * (2.0 / r2 - 1.0 / a_t))

    dv1 = abs(v_t_peri - v1)
    dv2 = abs(v2 - v_t_apo)
    return dv1, dv2, dv1 + dv2


def hohmann_transfer_time_hours(r1_au: float, r2_au: float) -> float:
    """
    Flight time for the Hohmann transfer (half the transfer ellipse period) [hours].
    """
    r1 = r1_au * AU
    r2 = r2_au * AU
    a_t = (r1 + r2) / 2.0
    # Full ellipse period; transfer = half
    period_s = 2.0 * math.pi * math.sqrt(a_t ** 3 / MU)
    return (period_s / 2.0) / 3_600.0


# ─────────────────────────────────────────────────────────────────────────────
# Convenience geometry
# ─────────────────────────────────────────────────────────────────────────────

def distance_au(pos1: Tuple[float, float], pos2: Tuple[float, float]) -> float:
    """Euclidean distance between two (x, y) AU positions."""
    dx = pos1[0] - pos2[0]
    dy = pos1[1] - pos2[1]
    return math.sqrt(dx * dx + dy * dy)


def orbital_radius_au(position: Tuple[float, float]) -> float:
    """Distance from origin (star) in AU."""
    return math.sqrt(position[0] ** 2 + position[1] ** 2)


# ─────────────────────────────────────────────────────────────────────────────
# Full transfer estimate (Δv + fuel + feasibility)
# ─────────────────────────────────────────────────────────────────────────────

def estimate_transfer(
    origin_radius_au:   float,
    dest_radius_au:     float,
    ship_dry_mass_kg:   float,
    ship_cargo_mass_kg: float,
    ship_fuel_mass_kg:  float,
    isp_seconds:        float,
    direct_distance_au: float = 0.0,   # actual 3-D distance at departure (AU)
) -> Dict:
    """
    Complete transfer analysis for a given ship configuration.

    Fuel is computed from the Hohmann Δv (correct orbital mechanics).
    Travel time uses the 3-D direct distance / TRANSIT_SPEED_AU_PER_HOUR so
    missions complete in sim-relevant timeframes regardless of transfer orbit.
    If direct_distance_au is 0, a fallback based on |Δr| is used.

    Returns a dict with keys:
        dv1_m_s, dv2_m_s, total_dv_m_s,
        transfer_time_hours,
        fuel_needed_kg, fuel_available_kg,
        fuel_margin_kg, feasible
    """
    r1 = max(origin_radius_au, 0.30)
    r2 = max(dest_radius_au,   0.30)

    dv1, dv2, total_dv = hohmann_delta_v(r1, r2)

    # Travel time: distance-based (more intuitive for logistics scheduling)
    # Minimum of 6 hours to avoid instant deliveries for co-located stations
    if direct_distance_au > 0:
        dist = direct_distance_au
    else:
        dist = abs(r2 - r1) + 0.05    # fallback: |Δr| + small bias
    t_hours = max(6.0, dist / TRANSIT_SPEED_AU_PER_HOUR)

    # Tsiolkovsky: propellant for the complete two-burn sequence
    v_e     = isp_seconds * G0
    m_empty = ship_dry_mass_kg + ship_cargo_mass_kg
    fuel_needed = m_empty * (math.exp(total_dv / v_e) - 1.0)

    margin   = ship_fuel_mass_kg - fuel_needed
    feasible = margin >= 0.0

    return {
        "dv1_m_s":             dv1,
        "dv2_m_s":             dv2,
        "total_dv_m_s":        total_dv,
        "transfer_time_hours": t_hours,
        "fuel_needed_kg":      fuel_needed,
        "fuel_available_kg":   ship_fuel_mass_kg,
        "fuel_margin_kg":      margin,
        "feasible":            feasible,
        "direct_distance_au":  dist,
    }
