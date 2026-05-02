"""
Celestial bodies: Star, Planet, SpaceStation.

Positions are 2-D (ecliptic plane), in AU, computed from circular Keplerian
orbital parameters at a given simulation time (hours since epoch).
"""

import math
from dataclasses import dataclass, field
from typing import Optional, Tuple

from config import HOURS_PER_DAY


# ─────────────────────────────────────────────────────────────────────────────
# Base class
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CelestialBody:
    """Any body that occupies a position in the solar system."""
    name:      str
    color:     str
    mass_kg:   float = 0.0
    radius_km: float = 0.0

    def position_at(self, time_hours: float) -> Tuple[float, float]:
        raise NotImplementedError(f"{type(self).__name__}.position_at() not implemented")


# ─────────────────────────────────────────────────────────────────────────────
# Star
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Star(CelestialBody):
    """Central star, fixed at the coordinate origin."""
    luminosity_watts: float = 3.828e26   # solar luminosity

    def position_at(self, time_hours: float) -> Tuple[float, float]:
        return (0.0, 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Planet
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Planet(CelestialBody):
    """
    Planet in a circular prograde orbit around the star.

    Angular velocity  ω = 2π / T  (rad / hour)
    Position          x = r·cos(ωt + φ),  y = r·sin(ωt + φ)
    where φ is a random initial phase set at construction to spread planets.
    """
    orbital_radius_au:   float = 1.0
    orbital_period_days: float = 365.25
    initial_phase_rad:   float = 0.0   # stagger planets across the sky at t=0

    # ── derived helpers ──────────────────────────────────────────────────────

    def angular_speed_rad_per_hour(self) -> float:
        period_hours = self.orbital_period_days * HOURS_PER_DAY
        return (2.0 * math.pi) / period_hours

    def position_at(self, time_hours: float) -> Tuple[float, float]:
        angle = self.angular_speed_rad_per_hour() * time_hours + self.initial_phase_rad
        x = self.orbital_radius_au * math.cos(angle)
        y = self.orbital_radius_au * math.sin(angle)
        return (x, y)


# ─────────────────────────────────────────────────────────────────────────────
# Space Station
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SpaceStation(CelestialBody):
    """
    A crewed station that either co-orbits with a parent planet (with a small
    orbital offset) or maintains its own independent solar orbit (e.g., belt
    mining depot).

    Services: docking, fuel storage, cargo storage.
    """

    # ── orbit definition (one of the two groups must be set) ─────────────────
    parent_planet:        Optional[Planet] = None
    orbital_offset_au:    float = 0.01    # station radius = planet_r + offset

    independent_orbital_radius_au:   Optional[float] = None
    independent_orbital_period_days: Optional[float] = None
    independent_phase_rad:           float = 0.0

    # ── station resources ─────────────────────────────────────────────────────
    fuel_stock_kg:         float = 100_000.0
    max_fuel_stock_kg:     float = 500_000.0
    cargo_storage_kg:      float = 0.0
    max_cargo_storage_kg:  float = 200_000.0
    docking_slots:         int   = 6
    current_docked:        int   = 0

    # ── position ──────────────────────────────────────────────────────────────

    def position_at(self, time_hours: float) -> Tuple[float, float]:
        if self.parent_planet is not None:
            # Co-orbit at planet's angle but slightly further out
            r_planet  = self.parent_planet.orbital_radius_au
            r_station = r_planet + self.orbital_offset_au
            angle = (self.parent_planet.angular_speed_rad_per_hour() * time_hours
                     + self.parent_planet.initial_phase_rad)
            return (r_station * math.cos(angle), r_station * math.sin(angle))

        if self.independent_orbital_radius_au is not None:
            r = self.independent_orbital_radius_au
            omega = (2.0 * math.pi) / (self.independent_orbital_period_days * HOURS_PER_DAY)
            angle = omega * time_hours + self.independent_phase_rad
            return (r * math.cos(angle), r * math.sin(angle))

        return (0.0, 0.0)

    def orbital_radius_at(self, time_hours: float) -> float:
        x, y = self.position_at(time_hours)
        return math.sqrt(x * x + y * y)

    # ── services ─────────────────────────────────────────────────────────────

    def can_dock(self) -> bool:
        return self.current_docked < self.docking_slots

    def refuel_ship(self, ship) -> float:
        """Transfer as much fuel as possible to *ship*. Returns kg transferred."""
        needed      = ship.propulsion.max_fuel_kg - ship.propulsion.fuel_mass_kg
        available   = self.fuel_stock_kg
        transferred = min(needed, available)
        ship.propulsion.fuel_mass_kg += transferred
        self.fuel_stock_kg           -= transferred
        return transferred

    def __repr__(self) -> str:
        return f"<Station '{self.name}' fuel={self.fuel_stock_kg/1000:.0f}t docked={self.current_docked}/{self.docking_slots}>"
