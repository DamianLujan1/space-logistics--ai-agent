"""
Simulation engine — orchestrates the space logistics world.

Each call to .step() advances time by SIM_TIME_STEP_HOURS and:

  1.  Update ship positions (transit interpolation + orbital drift)
  2.  Update power systems (solar generation vs. consumption)
  3.  Record per-ship telemetry
  4.  Check for mission arrivals (transit_progress ≥ 1.0)
  5.  Check for overdue pending missions (→ FAILED)
  6.  Run AI planner tick (assignments + emergency response)
  7.  Stochastic event generation (missions, solar flares)
  8.  Advance clock

The engine is pure Python; the dashboard is a separate visualisation layer.
"""

import math
import random
import heapq
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Tuple

from models.celestial import Planet, SpaceStation, Star
from models.spacecraft import Spacecraft, ShipState, PropulsionSystem, PowerSystem, CargoHold
from models.mission import Mission, MissionStatus, CargoItem, CargoType
from physics.orbital import orbital_radius_au
from agent.planner import MissionPlanner
from config import (
    PLANET_DATA, STATION_DATA, SHIP_CLASSES, CARGO_TYPES,
    EVENT_PROBABILITIES, SIM_TIME_STEP_HOURS, HOURS_PER_DAY,
)


# ─────────────────────────────────────────────────────────────────────────────
# Event system
# ─────────────────────────────────────────────────────────────────────────────

class EventType(Enum):
    MISSION_REQUEST   = auto()
    MISSION_DELIVERED = auto()
    MISSION_FAILED    = auto()
    SOLAR_FLARE       = auto()
    EQUIPMENT_FAILURE = auto()
    SHIP_ARRIVAL      = auto()
    STATUS_REPORT     = auto()


@dataclass
class SimEvent:
    """A scheduled simulation event (stored in a min-heap by time)."""
    time_hours: float
    event_type: EventType
    data: Dict[str, Any] = field(default_factory=dict)

    def __lt__(self, other: "SimEvent") -> bool:
        return self.time_hours < other.time_hours


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────

class SimulationEngine:
    """
    Master state-holder and time-stepper for the space logistics simulation.

    Attributes
    ----------
    current_time_hours : float
        Simulation clock in hours since epoch.
    star, planets, stations : world objects
    ships : List[Spacecraft]
    missions : List[Mission]
    planner : MissionPlanner
    stats : Dict[str, ...]
        Running counters — missions generated / completed / failed, revenue, etc.
    """

    def __init__(
        self,
        time_step_hours: float = SIM_TIME_STEP_HOURS,
        seed:            int   = 42,
    ):
        self.time_step_hours    = time_step_hours
        self.current_time_hours = 0.0
        self.rng                = random.Random(seed)
        self.event_queue: List[SimEvent] = []

        self.star:     Optional[Star]          = None
        self.planets:  List[Planet]            = []
        self.stations: List[SpaceStation]      = []
        self.ships:    List[Spacecraft]        = []
        self.missions: List[Mission]           = []

        self.planner = MissionPlanner()

        self.stats: Dict[str, Any] = {
            "total_missions_generated":  0,
            "total_missions_completed":  0,
            "total_missions_failed":     0,
            "total_revenue":             0.0,
            "total_cargo_delivered_kg":  0.0,
            "solar_flares":              0,
            "equipment_failures":        0,
            "steps_completed":           0,
        }

    # ── World construction ────────────────────────────────────────────────────

    def build_solar_system(self):
        """Populate planets and stations from config data."""
        self.star = Star(
            name="Sol",
            color="#ffff00",
            mass_kg=1.989e30,
            luminosity_watts=3.828e26,
        )

        planet_by_name: Dict[str, Planet] = {}

        for name, data in PLANET_DATA.items():
            planet = Planet(
                name                = name,
                color               = data["color"],
                mass_kg             = data["mass_kg"],
                radius_km           = data["radius_km"],
                orbital_radius_au   = data["orbital_radius_au"],
                orbital_period_days = data["orbital_period_days"],
                initial_phase_rad   = self.rng.uniform(0, 2 * math.pi),
            )
            self.planets.append(planet)
            planet_by_name[name] = planet

        for name, data in STATION_DATA.items():
            if "parent_planet" in data:
                parent  = planet_by_name.get(data["parent_planet"])
                station = SpaceStation(
                    name               = name,
                    color              = data["color"],
                    parent_planet      = parent,
                    orbital_offset_au  = data.get("orbital_offset_au", 0.0),
                    independent_phase_rad = self.rng.uniform(0, 2 * math.pi),
                )
            else:
                station = SpaceStation(
                    name                             = name,
                    color                            = data["color"],
                    independent_orbital_radius_au    = data["orbital_radius_au"],
                    independent_orbital_period_days  = data["orbital_period_days"],
                    independent_phase_rad            = self.rng.uniform(0, 2 * math.pi),
                )
            self.stations.append(station)

    def build_fleet(self, fleet_config: Optional[List[Dict]] = None):
        """Assemble the initial fleet. Uses default roster if none supplied."""
        if fleet_config is None:
            fleet_config = [
                {"name": "Hermes",    "class": "Courier"},
                {"name": "Prometheus","class": "Freighter"},
                {"name": "Athena",    "class": "Science Vessel"},
                {"name": "Kronos",    "class": "Tanker"},
                {"name": "Ares",      "class": "Courier"},
                {"name": "Poseidon",  "class": "Freighter"},
            ]

        for i, cfg in enumerate(fleet_config):
            cls_name = cfg["class"]
            spec     = SHIP_CLASSES[cls_name]

            # Assign to a station round-robin
            station   = self.stations[i % len(self.stations)]
            start_pos = station.position_at(0.0)

            ship = Spacecraft(
                name        = cfg["name"],
                ship_class  = cls_name,
                dry_mass_kg = spec["dry_mass_kg"],
                color       = spec["color"],
                description = spec["description"],
                propulsion  = PropulsionSystem(
                    isp_seconds  = spec["isp_seconds"],
                    max_fuel_kg  = spec["max_fuel_kg"],
                    fuel_mass_kg = spec["max_fuel_kg"] * self.rng.uniform(0.72, 1.0),
                ),
                power = PowerSystem(
                    solar_panel_area_m2  = spec["solar_panel_area_m2"],
                    battery_capacity_kwh = spec["battery_capacity_kwh"],
                    battery_charge_kwh   = spec["battery_capacity_kwh"],
                    rtg_power_kw         = spec.get("rtg_power_kw", 0.0),
                    power_draw_kw        = dict(spec["power_draw_kw"]),
                ),
                cargo           = CargoHold(capacity_kg=spec["cargo_capacity_kg"]),
                state           = ShipState.IDLE,
                position        = start_pos,
                current_station = station,
            )
            self.ships.append(ship)

    # ── Mission generation ────────────────────────────────────────────────────

    def generate_mission(self, emergency: bool = False) -> Optional[Mission]:
        """
        Spawn a new random logistics mission between two distinct stations.

        Emergency missions: high urgency, tight deadline, premium reward.
        """
        if len(self.stations) < 2:
            return None

        origin, dest = self.rng.sample(self.stations, 2)

        # Pick cargo type
        if emergency:
            cargo_type = self.rng.choice([CargoType.MEDICAL, CargoType.PERSONNEL])
        else:
            cargo_type = self.rng.choice(list(CargoType))

        spec = CARGO_TYPES[cargo_type.value]
        quantity = self.rng.randint(1, 8)

        umin, umax = spec["urgency_range"]
        if emergency:
            umin = max(umin, 0.80)
        urgency = self.rng.uniform(umin, umax)

        cargo_item = CargoItem.generate(cargo_type, quantity, urgency_override=urgency)

        # Estimate transit time for deadline (uses same cruise-speed model as planner)
        from physics.orbital import distance_au as dist_au_fn
        from config import TRANSIT_SPEED_AU_PER_HOUR
        origin_pos = origin.position_at(self.current_time_hours)
        dest_pos   = dest.position_at(self.current_time_hours)
        direct_d   = dist_au_fn(origin_pos, dest_pos)
        base_t_h   = max(6.0, direct_d / TRANSIT_SPEED_AU_PER_HOUR)

        deadline_mult = self.rng.uniform(1.2, 2.0) if emergency else self.rng.uniform(2.0, 5.5)
        deadline      = self.current_time_hours + base_t_h * deadline_mult

        value = cargo_item.value_credits
        mission = Mission(
            name          = f"{'[EMG] ' if emergency else ''}{cargo_type.value} → {dest.name[:12]}",
            origin        = origin,
            destination   = dest,
            cargo_items   = [cargo_item],
            created_at_hours    = self.current_time_hours,
            deadline_hours      = deadline,
            base_reward_credits = value * self.rng.uniform(0.85, 1.20),
            early_bonus_credits = value * 0.10,
            late_penalty_per_hour = value * 0.005,
        )

        self.missions.append(mission)
        self.stats["total_missions_generated"] += 1

        self.planner.log(
            f"{'EMERGENCY ' if emergency else 'MISSION   '}"
            f"{mission.mission_id}  {mission.name}  "
            f"cargo={cargo_item.mass_kg:,.0f} kg  "
            f"value={value:,.0f} cr  "
            f"urgency={urgency:.2f}  "
            f"deadline=+{(deadline - self.current_time_hours)/HOURS_PER_DAY:.1f} d",
            self.current_time_hours,
        )
        return mission

    # ── Time step ─────────────────────────────────────────────────────────────

    def step(self):
        """Advance the simulation by one time step."""
        dt = self.time_step_hours

        self._update_ships(dt)
        self._check_arrivals()
        self._check_deadlines()
        self.planner.tick(self.ships, self.missions, self.current_time_hours)
        self._generate_events()

        self.current_time_hours += dt
        self.stats["steps_completed"] += 1

    # ── Internal update helpers ────────────────────────────────────────────────

    def _update_ships(self, dt: float):
        for ship in self.ships:
            # Compute new position
            new_pos = self._interpolated_position(ship)
            ship.position = new_pos

            # Power system update
            dist_au  = max(orbital_radius_au(new_pos), 0.10)
            thrusting = (ship.state == ShipState.TRANSIT)
            ship.power.update(dist_au, thrusting, dt)

            # Telemetry snapshot
            ship.record_telemetry(self.current_time_hours)

            # Advance transit progress — even in LOW_POWER (coasting, no active thrust)
            if ship.state in (ShipState.TRANSIT, ShipState.LOW_POWER) and ship.mission:
                ship.transit_elapsed_hours += dt
                ship.transit_progress = min(
                    1.0,
                    ship.transit_elapsed_hours / max(ship.transit_total_hours, 1.0),
                )

    def _interpolated_position(self, ship: Spacecraft) -> Tuple[float, float]:
        """
        Return the ship's current position in AU.

        IDLE / docked → follow the station.
        TRANSIT       → smooth S-curve between station positions.
        """
        t = self.current_time_hours

        if ship.state in (ShipState.IDLE, ShipState.LOADING,
                          ShipState.UNLOADING, ShipState.REFUELING):
            return ship.current_station.position_at(t) if ship.current_station else ship.position

        if ship.state in (ShipState.TRANSIT, ShipState.LOW_POWER) and ship.destination is not None:
            p = ship.transit_progress
            # Smooth step: 3p² − 2p³  (zero 1st-derivative at endpoints)
            p_smooth = p * p * (3.0 - 2.0 * p)

            origin_pos = (
                ship.current_station.position_at(t)
                if ship.current_station else ship.position
            )
            dest_pos = ship.destination.position_at(t)

            x = origin_pos[0] + p_smooth * (dest_pos[0] - origin_pos[0])
            y = origin_pos[1] + p_smooth * (dest_pos[1] - origin_pos[1])
            return (x, y)

        # LOW_POWER / EMERGENCY: stay put
        return ship.position

    def _check_arrivals(self):
        """Detect ships that have completed their transit."""
        for ship in self.ships:
            if ship.state == ShipState.TRANSIT and ship.transit_progress >= 1.0:
                self._complete_delivery(ship)

    def _complete_delivery(self, ship: Spacecraft):
        mission = ship.mission
        if mission is None:
            ship.state = ShipState.IDLE
            return

        # Deliver cargo
        delivered           = ship.cargo.unload_all()
        mission.status      = MissionStatus.DELIVERED
        mission.completed_at_hours = self.current_time_hours

        reward = mission.compute_reward(self.current_time_hours)
        on_time = self.current_time_hours <= mission.deadline_hours

        # Update ship stats
        ship.total_revenue            += reward
        ship.total_missions_completed += 1
        ship.total_cargo_delivered_kg += mission.total_cargo_mass_kg

        # Update global stats
        self.stats["total_missions_completed"] += 1
        self.stats["total_revenue"]            += reward
        self.stats["total_cargo_delivered_kg"] += mission.total_cargo_mass_kg
        self.planner.total_revenue             += reward

        # Dock ship at destination
        ship.current_station  = mission.destination
        ship.state            = ShipState.IDLE
        ship.mission          = None
        ship.destination      = None
        ship.transit_progress = 0.0

        self.planner.log(
            f"DELIVERY  {ship.name:<12}  '{mission.name}'  "
            f"reward={reward:,.0f} cr  "
            f"{'ON TIME' if on_time else 'LATE   '}  "
            f"cargo={mission.total_cargo_mass_kg:,.0f} kg",
            self.current_time_hours,
        )

        self._push_event(SimEvent(
            time_hours = self.current_time_hours,
            event_type = EventType.MISSION_DELIVERED,
            data       = {"ship": ship.name, "mission": mission.name, "reward": reward},
        ))

    def _check_deadlines(self):
        """Mark expired pending missions as FAILED."""
        for mission in self.missions:
            if (mission.status == MissionStatus.PENDING
                    and mission.is_overdue(self.current_time_hours)):
                mission.status = MissionStatus.FAILED
                self.stats["total_missions_failed"] += 1
                self.planner.log(
                    f"FAILED    mission '{mission.name}' expired unassigned",
                    self.current_time_hours,
                )

    def _generate_events(self):
        """Stochastic generation of missions and solar events each tick."""
        if self.rng.random() < EVENT_PROBABILITIES["mission_request"]:
            self.generate_mission(emergency=False)

        if self.rng.random() < EVENT_PROBABILITIES["emergency_mission"]:
            self.generate_mission(emergency=True)

        if self.rng.random() < EVENT_PROBABILITIES["solar_flare"]:
            self.stats["solar_flares"] += 1
            self.planner.log(
                "SOLAR FLARE  X-class flare detected — outer-system ships may "
                "experience panel output reduction for the next 2–6 hours",
                self.current_time_hours,
            )
            # Apply temporary power reduction to ships in the outer system
            for ship in self.ships:
                if ship.distance_from_star_au() > 3.0:
                    ship.power.battery_charge_kwh = max(
                        0.0,
                        ship.power.battery_charge_kwh - ship.power.battery_capacity_kwh * 0.08
                    )

        if self.rng.random() < EVENT_PROBABILITIES["equipment_failure"]:
            affected = self.rng.choice(self.ships)
            self.stats["equipment_failures"] += 1
            # Drain battery to simulate power spike / reset
            affected.power.battery_charge_kwh = max(
                0.0,
                affected.power.battery_charge_kwh - affected.power.battery_capacity_kwh * 0.15,
            )
            self.planner.log(
                f"EQUIPMENT  {affected.name}  minor system failure — "
                f"battery drained to {affected.power.battery_fraction:.0%}",
                self.current_time_hours,
            )

    def _push_event(self, event: SimEvent):
        heapq.heappush(self.event_queue, event)

    # ── Initialization & run ──────────────────────────────────────────────────

    def initialize(self):
        """Build world, assemble fleet, seed initial missions."""
        self.build_solar_system()
        self.build_fleet()

        # Seed with enough missions to keep all ships busy from the start
        for _ in range(max(8, len(self.ships) + 2)):
            self.generate_mission()

        self.planner.log(
            f"=== SIMULATION INITIALIZED ===  "
            f"ships={len(self.ships)}  "
            f"stations={len(self.stations)}  "
            f"planets={len(self.planets)}  "
            f"seed_missions={len(self.missions)}",
            0.0,
        )

    def run(self, duration_days: float, verbose: bool = False) -> Dict:
        """
        Step the simulation for *duration_days* and return the final stats dict.
        Prints a progress line every 100 steps when *verbose* is True.
        """
        n_steps = int(duration_days * HOURS_PER_DAY / self.time_step_hours)

        for i in range(n_steps):
            self.step()
            if verbose and i % 100 == 0:
                day  = self.current_time_hours / HOURS_PER_DAY
                comp = self.stats["total_missions_completed"]
                rev  = self.stats["total_revenue"]
                print(f"  Day {day:7.1f}  |  completed={comp:4d}  |  revenue={rev:>14,.0f} cr")

        return dict(self.stats)
