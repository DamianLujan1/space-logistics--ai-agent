"""
Spacecraft model — integrates propulsion, power, and cargo subsystems.

State machine:
    IDLE  ──► LOADING ──► TRANSIT ──► UNLOADING ──► IDLE
                                 │
                                 ▼
                           LOW_POWER / EMERGENCY
"""

import math
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple

from config import G0, SOLAR_CONSTANT, SIM_TELEMETRY_WINDOW


# ─────────────────────────────────────────────────────────────────────────────
# Ship state machine
# ─────────────────────────────────────────────────────────────────────────────

class ShipState(Enum):
    IDLE      = auto()   # docked, awaiting assignment
    LOADING   = auto()   # taking on cargo at origin station
    TRANSIT   = auto()   # actively traveling to destination
    UNLOADING = auto()   # delivering cargo at destination
    REFUELING = auto()   # replenishing propellant
    LOW_POWER = auto()   # battery critical, non-essential loads shed
    EMERGENCY = auto()   # critical system failure


# ─────────────────────────────────────────────────────────────────────────────
# Propulsion system  (Tsiolkovsky rocket equation)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PropulsionSystem:
    """
    Chemical bipropellant engine.

    Tsiolkovsky: Δv = Isp · g₀ · ln(m₀ / m_f)
    Inverted:    m_fuel = m_dry · (exp(Δv / v_e) − 1)
    """
    isp_seconds:  float   # specific impulse [s]
    max_fuel_kg:  float
    fuel_mass_kg: float   # current propellant load

    @property
    def exhaust_velocity_m_s(self) -> float:
        """Effective exhaust velocity v_e = Isp · g₀  [m/s]."""
        return self.isp_seconds * G0

    def delta_v_available(self, dry_mass_kg: float, cargo_mass_kg: float) -> float:
        """Maximum Δv achievable with current fuel [m/s]."""
        m0 = dry_mass_kg + cargo_mass_kg + self.fuel_mass_kg
        mf = dry_mass_kg + cargo_mass_kg
        if mf <= 0 or self.fuel_mass_kg <= 0:
            return 0.0
        return self.exhaust_velocity_m_s * math.log(m0 / mf)

    def fuel_for_delta_v(self, delta_v: float, dry_mass_kg: float, cargo_mass_kg: float) -> float:
        """Propellant mass required for a given Δv manoeuvre [kg]."""
        m_dry = dry_mass_kg + cargo_mass_kg
        return m_dry * (math.exp(delta_v / self.exhaust_velocity_m_s) - 1.0)

    @property
    def fuel_fraction(self) -> float:
        return self.fuel_mass_kg / self.max_fuel_kg if self.max_fuel_kg else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Power system  (solar + battery)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PowerSystem:
    """
    Solar-electric power plant.

    Generation:   P_solar = S(r) · A · η          [kW]
    where S(r) = 1361 W/m² / r²   (inverse-square from star)
    η = panel conversion efficiency (≈ 28% for III-V space cells)

    Battery integrates the net power balance over each time step.
    When battery < 15 %: enter low-power mode (shed payload + comms).
    """
    solar_panel_area_m2:    float
    panel_efficiency:       float = 0.28
    battery_capacity_kwh:   float = 100.0
    battery_charge_kwh:     float = 100.0   # starts fully charged

    # RTG baseline — constant power regardless of distance (simulates nuclear power
    # plant for outer-system missions; 0.0 for inner-system solar-only ships)
    rtg_power_kw: float = 0.0

    # Per-subsystem steady-state draw [kW]; propulsion only when thrusting
    power_draw_kw: Dict[str, float] = field(default_factory=dict)

    # ── generation ────────────────────────────────────────────────────────────

    def solar_power_kw(self, distance_au: float) -> float:
        """Solar panel output at *distance_au* from the star [kW]."""
        irradiance_w_m2 = SOLAR_CONSTANT / (distance_au ** 2)
        return (irradiance_w_m2 * self.solar_panel_area_m2 * self.panel_efficiency) / 1_000.0

    def total_generation_kw(self, distance_au: float) -> float:
        """Total electrical generation: solar panels + RTG baseline [kW]."""
        return self.solar_power_kw(distance_au) + self.rtg_power_kw

    # ── consumption ───────────────────────────────────────────────────────────

    def total_consumption_kw(self, thrusting: bool = False, low_power: bool = False) -> float:
        """Aggregate power draw with operating-mode adjustments [kW]."""
        total = 0.0
        for name, kw in self.power_draw_kw.items():
            if name == "propulsion" and not thrusting:
                continue
            # Shed payload and comms in low-power mode (10 % residual)
            if low_power and name in ("payload", "comms"):
                total += kw * 0.10
            else:
                total += kw
        return total

    # ── update ────────────────────────────────────────────────────────────────

    def update(self, distance_au: float, thrusting: bool, dt_hours: float) -> float:
        """
        Integrate power balance over *dt_hours*.
        Returns net power [kW]: positive = charging, negative = draining.
        """
        in_low_power = self.battery_fraction < 0.15
        generated = self.total_generation_kw(distance_au)
        consumed  = self.total_consumption_kw(thrusting=thrusting, low_power=in_low_power)
        net_kw    = generated - consumed
        delta_kwh = net_kw * dt_hours

        self.battery_charge_kwh = max(
            0.0,
            min(self.battery_capacity_kwh, self.battery_charge_kwh + delta_kwh)
        )
        return net_kw

    @property
    def battery_fraction(self) -> float:
        return (self.battery_charge_kwh / self.battery_capacity_kwh
                if self.battery_capacity_kwh else 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Cargo hold
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CargoHold:
    """Mass-limited cargo compartment with a line-item manifest."""
    capacity_kg:   float
    current_mass_kg: float = 0.0
    manifest: List[Dict] = field(default_factory=list)   # {name, mass_kg}

    @property
    def free_capacity_kg(self) -> float:
        return self.capacity_kg - self.current_mass_kg

    @property
    def fill_fraction(self) -> float:
        return self.current_mass_kg / self.capacity_kg if self.capacity_kg else 0.0

    def load(self, cargo_name: str, mass_kg: float) -> bool:
        if mass_kg > self.free_capacity_kg:
            return False
        self.manifest.append({"name": cargo_name, "mass_kg": mass_kg})
        self.current_mass_kg += mass_kg
        return True

    def unload_all(self) -> List[Dict]:
        delivered = list(self.manifest)
        self.manifest.clear()
        self.current_mass_kg = 0.0
        return delivered


# ─────────────────────────────────────────────────────────────────────────────
# Spacecraft — top-level model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Spacecraft:
    """
    Full spacecraft model integrating propulsion, power, and cargo.

    Transit model: ship moves along a smooth S-curve interpolation between
    origin and destination orbital positions.  The AI planner deducts fuel
    upfront (departure burn) when a mission is dispatched.
    """

    name:        str
    ship_class:  str
    dry_mass_kg: float
    color:       str
    description: str

    # Subsystems
    propulsion: PropulsionSystem
    power:      PowerSystem
    cargo:      CargoHold

    # State
    state:    ShipState = ShipState.IDLE
    position: Tuple[float, float] = (0.0, 0.0)   # current position [AU]

    # Navigation
    current_station: Optional[object] = None   # SpaceStation (when docked)
    destination:     Optional[object] = None   # SpaceStation (transit target)
    mission:         Optional[object] = None   # active Mission

    # Transit progress  [0 → 1]
    transit_progress:     float = 0.0
    transit_total_hours:  float = 0.0
    transit_elapsed_hours: float = 0.0
    transit_delta_v:      float = 0.0   # [m/s] for this leg

    # Telemetry ring buffers (for plots)
    history_battery:   List[float] = field(default_factory=list)   # [%]
    history_fuel:      List[float] = field(default_factory=list)   # [%]
    history_power:     List[float] = field(default_factory=list)   # [kW generated]
    history_positions: List[Tuple[float, float]] = field(default_factory=list)

    # Lifetime stats
    total_missions_completed:  int   = 0
    total_cargo_delivered_kg:  float = 0.0
    total_distance_traveled_au: float = 0.0
    total_revenue:             float = 0.0

    # ── computed properties ───────────────────────────────────────────────────

    @property
    def total_mass_kg(self) -> float:
        return self.dry_mass_kg + self.propulsion.fuel_mass_kg + self.cargo.current_mass_kg

    def distance_from_star_au(self) -> float:
        return math.sqrt(self.position[0] ** 2 + self.position[1] ** 2)

    # ── telemetry ─────────────────────────────────────────────────────────────

    def record_telemetry(self, time_hours: float):
        """Push current-state snapshot into the ring buffers."""
        dist  = max(self.distance_from_star_au(), 0.1)
        p_gen = self.power.solar_power_kw(dist)

        self.history_battery.append(self.power.battery_fraction * 100.0)
        self.history_fuel.append(self.propulsion.fuel_fraction * 100.0)
        self.history_power.append(p_gen)
        self.history_positions.append(self.position)

        # Trim to sliding window
        limit = SIM_TELEMETRY_WINDOW
        if len(self.history_battery) > limit:
            self.history_battery.pop(0)
            self.history_fuel.pop(0)
            self.history_power.pop(0)
            self.history_positions.pop(0)

    def __repr__(self) -> str:
        return (
            f"<{self.ship_class} '{self.name}' | "
            f"{self.state.name} | "
            f"fuel={self.propulsion.fuel_fraction:.0%} | "
            f"batt={self.power.battery_fraction:.0%} | "
            f"cargo={self.cargo.fill_fraction:.0%}>"
        )
