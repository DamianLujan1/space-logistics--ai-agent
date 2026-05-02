"""
Energy system models for spacecraft.

Covers:
  • Solar irradiance as a function of heliocentric distance (inverse-square law)
  • Panel power output with efficiency and degradation factors
  • Per-subsystem power budget tracking
  • Battery state integration
  • Solar event modelling (flares, eclipses)

All power values in kW; energy in kWh; distances in AU.
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from config import SOLAR_CONSTANT


# ─────────────────────────────────────────────────────────────────────────────
# Solar irradiance
# ─────────────────────────────────────────────────────────────────────────────

def solar_irradiance_w_m2(distance_au: float) -> float:
    """
    Solar flux at *distance_au* from the star [W/m²].
    Follows the inverse-square law: S(r) = S₀ / r²
    S₀ = 1361 W/m² at 1 AU (solar constant).
    """
    return SOLAR_CONSTANT / (distance_au ** 2)


def panel_power_kw(
    panel_area_m2:      float,
    efficiency:         float,
    distance_au:        float,
    degradation_factor: float = 1.0,   # 1.0 = new panel, decreases with age
    shadow_factor:      float = 1.0,   # 1.0 = full sun, 0.0 = total eclipse
) -> float:
    """
    Net solar panel output [kW].

    degradation_factor models cumulative radiation damage (typically ≈ 0.97/year).
    shadow_factor captures eclipses or solar flare panel shutdowns.
    """
    irradiance = solar_irradiance_w_m2(distance_au)
    raw_w = irradiance * panel_area_m2 * efficiency
    return (raw_w * degradation_factor * shadow_factor) / 1_000.0


# ─────────────────────────────────────────────────────────────────────────────
# Power budget
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PowerBudget:
    """
    Tracks per-subsystem power allocation.

    Each subsystem has a rated draw (kW) and an on/off switch.
    Subsystems disabled in low-power mode: 'payload', 'comms'.
    """
    subsystems: Dict[str, float] = field(default_factory=dict)   # name → kW
    enabled:    Dict[str, bool]  = field(default_factory=dict)   # name → on/off

    def add_subsystem(self, name: str, power_kw: float, enabled: bool = True):
        self.subsystems[name] = power_kw
        self.enabled[name]    = enabled

    def enable(self, name: str):
        self.enabled[name] = True

    def disable(self, name: str):
        self.enabled[name] = False

    def total_consumption_kw(self) -> float:
        return sum(kw for name, kw in self.subsystems.items()
                   if self.enabled.get(name, True))

    def report(self) -> str:
        lines = ["── Power Budget ───────────────────────────────"]
        for name, kw in sorted(self.subsystems.items()):
            status = "ON " if self.enabled.get(name, True) else "OFF"
            lines.append(f"  [{status}] {name:<22}  {kw:7.2f} kW")
        lines.append(f"  {'TOTAL':<26}  {self.total_consumption_kw():7.2f} kW")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Energy telemetry log
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EnergyLog:
    """
    Rolling time-series log of energy state for a single ship.
    Used by the visualisation dashboard to plot power/battery history.
    """
    MAX_ENTRIES: int = 500

    timestamps:     List[float] = field(default_factory=list)
    generation_kw:  List[float] = field(default_factory=list)
    consumption_kw: List[float] = field(default_factory=list)
    battery_pct:    List[float] = field(default_factory=list)
    distance_au:    List[float] = field(default_factory=list)

    def record(
        self,
        t:       float,
        gen_kw:  float,
        cons_kw: float,
        batt_pct: float,
        dist_au:  float,
    ):
        self.timestamps.append(t)
        self.generation_kw.append(gen_kw)
        self.consumption_kw.append(cons_kw)
        self.battery_pct.append(batt_pct)
        self.distance_au.append(dist_au)

        # Trim to sliding window
        if len(self.timestamps) > self.MAX_ENTRIES:
            self.timestamps.pop(0)
            self.generation_kw.pop(0)
            self.consumption_kw.pop(0)
            self.battery_pct.pop(0)
            self.distance_au.pop(0)


# ─────────────────────────────────────────────────────────────────────────────
# Solar event (flare / eclipse)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SolarEvent:
    """
    Transient disturbance affecting solar panel output.

    intensity = 0.0 → no effect
    intensity = 1.0 → panels produce zero power

    The event ramps up and then ramps down smoothly over its duration,
    avoiding discontinuities in the power curve.
    """
    start_hours:    float
    duration_hours: float
    intensity:      float          # 0 – 1
    event_type:     str = "flare"  # "flare" | "eclipse"

    def is_active(self, time_hours: float) -> bool:
        return self.start_hours <= time_hours <= (self.start_hours + self.duration_hours)

    def shadow_factor(self, time_hours: float) -> float:
        """Returns multiplicative factor on panel output [0, 1]."""
        if not self.is_active(time_hours):
            return 1.0
        elapsed  = time_hours - self.start_hours
        remaining = self.duration_hours - elapsed
        # Smooth hat: ramps from 0 to intensity in first hour, ramps back in last hour
        ramp = min(elapsed, remaining, 1.0)
        return max(0.0, 1.0 - self.intensity * ramp)

    def __repr__(self) -> str:
        return (f"<SolarEvent {self.event_type} "
                f"t={self.start_hours:.0f}h +{self.duration_hours:.1f}h "
                f"intensity={self.intensity:.0%}>")
