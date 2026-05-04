"""
AI Mission Planner — decision-making brain of the logistics network.

Architecture
────────────
The planner implements a *greedy priority-weighted assignment* algorithm:

1.  Each simulation tick, collect idle ships and pending missions.
2.  Score every (ship, mission) pair with a multi-objective utility function:

        U = w_urgency  · urgency  · deadline_factor
          + w_value    · value    / orbital_distance
          + w_fuel_eff · (1 − fuel_fraction_used)
          − w_distance · orbital_distance

3.  Sort candidates by U descending; greedily assign (each ship/mission once).
4.  Dispatch: deduct departure-burn fuel, update ship/mission state.
5.  Run emergency monitor: catch critical battery, fuel, or overdue events.

Extensions possible: lookahead planning, LP/ILP for global optimum, RL policy.
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from models.mission import Mission, MissionStatus
from models.spacecraft import Spacecraft, ShipState
from physics.orbital import estimate_transfer, orbital_radius_au, distance_au
from config import PLANNER_WEIGHTS


# ─────────────────────────────────────────────────────────────────────────────
# Scored candidate pairing
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Assignment:
    """A scored (ship, mission) pairing ready for dispatch."""
    score:         float
    ship:          Spacecraft
    mission:       Mission
    transfer_info: dict       # from physics.orbital.estimate_transfer()

    def __lt__(self, other: "Assignment") -> bool:
        return self.score > other.score   # higher score = better


# ─────────────────────────────────────────────────────────────────────────────
# Planner
# ─────────────────────────────────────────────────────────────────────────────

class MissionPlanner:
    """
    Greedy multi-objective logistics planner.

    Call .tick(ships, missions, time_hours) once per simulation step.
    Read .decision_log for a human-readable record of all AI decisions.
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = weights or dict(PLANNER_WEIGHTS)
        self.decision_log: List[str] = []   # bounded ring-buffer of log entries
        self.total_assignments = 0
        self.total_revenue     = 0.0

    # ── Logging ───────────────────────────────────────────────────────────────

    def log(self, msg: str, time_hours: float = 0.0):
        day   = time_hours / 24.0
        entry = f"[Day {day:7.2f}]  {msg}"
        self.decision_log.append(entry)
        if len(self.decision_log) > 400:
            self.decision_log.pop(0)

    # ── Scoring ───────────────────────────────────────────────────────────────

    def _score(
        self,
        ship:          Spacecraft,
        mission:       Mission,
        time_hours:    float,
    ) -> Optional[Assignment]:
        """
        Score a (ship, mission) pair.  Returns None if infeasible.

        Feasibility gates:
          • Ship must be IDLE and docked
          • Mission cargo must fit in the ship's hold
          • Ship must have enough fuel for the Hohmann transfer
        """
        # State gates
        if ship.state is not ShipState.IDLE:
            return None
        if ship.current_station is None:
            return None

        # Skip if ship is already docked at the mission destination — no journey needed
        if ship.current_station is mission.destination:
            return None

        # Capacity gate
        if mission.total_cargo_mass_kg > ship.cargo.free_capacity_kg:
            return None
        if mission.total_cargo_mass_kg > ship.cargo.capacity_kg:
            return None

        # Orbital radii and 3-D positions
        ship_pos = ship.position
        dest_pos = mission.destination.position_at(time_hours)
        origin_r = orbital_radius_au(ship_pos)
        dest_r   = orbital_radius_au(dest_pos)
        direct_d = distance_au(ship_pos, dest_pos)

        # Physics feasibility + travel time
        info = estimate_transfer(
            origin_radius_au   = max(origin_r, 0.30),
            dest_radius_au     = max(dest_r,   0.30),
            ship_dry_mass_kg   = ship.dry_mass_kg,
            ship_cargo_mass_kg = mission.total_cargo_mass_kg,
            ship_fuel_mass_kg  = ship.propulsion.fuel_mass_kg,
            isp_seconds        = ship.propulsion.isp_seconds,
            direct_distance_au = direct_d,
        )
        if not info["feasible"]:
            return None

        w = self.weights

        # ── Urgency factor ────────────────────────────────────────────────────
        # Urgency rises if the transfer time itself almost fills the remaining window
        time_left    = mission.time_until_deadline(time_hours)
        transfer_t   = info["transfer_time_hours"]

        if time_left < transfer_t:
            # Already unreachable on time — still assign but discounted
            deadline_factor = 0.25
        elif time_left < transfer_t * 1.5:
            deadline_factor = 2.0   # very close to deadline
        elif time_left < transfer_t * 3.0:
            deadline_factor = 1.3
        else:
            deadline_factor = 1.0

        urgency_score = mission.urgency * deadline_factor * w["urgency"]

        # ── Value-density score ────────────────────────────────────────────────
        orbital_dist = abs(dest_r - origin_r) + 0.001
        value_score  = (mission.total_value_credits / orbital_dist) * w["value"] * 1e-4

        # ── Fuel-efficiency score ─────────────────────────────────────────────
        fuel_fraction_used = info["fuel_needed_kg"] / max(ship.propulsion.fuel_mass_kg, 1.0)
        fuel_score         = (1.0 - min(fuel_fraction_used, 1.0)) * w["fuel_efficiency"]

        # ── Distance penalty ──────────────────────────────────────────────────
        dist_penalty = orbital_dist * abs(w["distance"])

        total_score = urgency_score + value_score + fuel_score - dist_penalty

        return Assignment(
            score         = total_score,
            ship          = ship,
            mission       = mission,
            transfer_info = info,
        )

    # ── Assignment ────────────────────────────────────────────────────────────

    def make_assignments(
        self,
        ships:      List[Spacecraft],
        missions:   List[Mission],
        time_hours: float,
    ) -> List[Assignment]:
        """
        Score all feasible (ship, mission) pairs and return a collision-free
        greedy selection (each ship and mission used at most once).
        """
        pending   = [m for m in missions  if m.status == MissionStatus.PENDING]
        idle      = [s for s in ships     if s.state  == ShipState.IDLE]

        if not pending or not idle:
            return []

        # Score all pairs
        candidates: List[Assignment] = []
        for ship in idle:
            for mission in pending:
                a = self._score(ship, mission, time_hours)
                if a is not None:
                    candidates.append(a)

        candidates.sort()   # Assignment.__lt__ → descending score

        # Greedy selection
        used_ships:    Set[str] = set()
        used_missions: Set[str] = set()
        selected:      List[Assignment] = []

        for a in candidates:
            sid = a.ship.name
            mid = a.mission.mission_id
            if sid in used_ships or mid in used_missions:
                continue
            selected.append(a)
            used_ships.add(sid)
            used_missions.add(mid)

        return selected

    def dispatch(self, assignments: List[Assignment], time_hours: float):
        """
        Execute a list of assignments:
        • Load cargo onto the ship
        • Deduct departure-burn fuel (Tsiolkovsky, immediate)
        • Set ship + mission state to TRANSIT / IN_TRANSIT
        """
        for a in assignments:
            ship    = a.ship
            mission = a.mission
            info    = a.transfer_info

            # Mission state
            mission.status            = MissionStatus.IN_TRANSIT
            mission.assigned_ship     = ship
            mission.assigned_at_hours = time_hours

            # Load cargo
            for item in mission.cargo_items:
                ship.cargo.load(item.cargo_type.value, item.mass_kg)

            # Ship navigation
            ship.state                 = ShipState.TRANSIT
            ship.mission               = mission
            ship.destination           = mission.destination
            ship.transit_total_hours   = info["transfer_time_hours"]
            ship.transit_elapsed_hours = 0.0
            ship.transit_progress      = 0.0
            ship.transit_delta_v       = info["total_dv_m_s"]

            # Deduct fuel for both burns upfront (simplified: no mid-journey accounting)
            ship.propulsion.fuel_mass_kg = max(
                0.0, ship.propulsion.fuel_mass_kg - info["fuel_needed_kg"]
            )

            self.total_assignments += 1

            eta_days = info["transfer_time_hours"] / 24.0
            self.log(
                f"DISPATCH  {ship.name:<12} [{ship.ship_class}] "
                f"→ {mission.name}  |  "
                f"dest={mission.destination.name}  "
                f"cargo={mission.total_cargo_mass_kg:,.0f} kg  "
                f"Δv={info['total_dv_m_s']:,.0f} m/s  "
                f"ETA={eta_days:.1f} d  "
                f"score={a.score:.3f}",
                time_hours,
            )

    # ── Emergency Monitor ─────────────────────────────────────────────────────

    def handle_emergencies(self, ships: List[Spacecraft], time_hours: float):
        """
        Scan fleet for critical conditions and apply corrective actions.

        Conditions handled:
        • Battery < 10 % → enter LOW_POWER mode
        • Battery > 35 % while LOW_POWER → recover to previous state
        • Fuel < 5 % during transit → warning log
        """
        for ship in ships:
            batt = ship.power.battery_fraction
            fuel = ship.propulsion.fuel_fraction

            # Enter low-power mode
            if batt < 0.10 and ship.state not in (ShipState.LOW_POWER, ShipState.EMERGENCY):
                ship.state = ShipState.LOW_POWER
                self.log(
                    f"ALERT     {ship.name}  battery CRITICAL {batt:.0%} — LOW POWER mode",
                    time_hours,
                )

            # Recover from low-power
            elif ship.state == ShipState.LOW_POWER and batt > 0.35:
                ship.state = ShipState.TRANSIT if ship.mission else ShipState.IDLE
                self.log(
                    f"RECOVERY  {ship.name}  battery restored {batt:.0%} — resuming {ship.state.name}",
                    time_hours,
                )

            # Fuel warning during transit
            if ship.state == ShipState.TRANSIT and fuel < 0.05:
                self.log(
                    f"WARNING   {ship.name}  fuel CRITICAL {ship.propulsion.fuel_mass_kg:,.0f} kg "
                    f"({fuel:.0%}) — in transit to "
                    f"{ship.destination.name if ship.destination else '?'}",
                    time_hours,
                )

    # ── Main tick ─────────────────────────────────────────────────────────────

    def tick(
        self,
        ships:      List[Spacecraft],
        missions:   List[Mission],
        time_hours: float,
    ) -> List[Assignment]:
        """
        One AI decision cycle.  Call once per simulation step.

        Returns the list of new assignments dispatched this tick.
        """
        self.handle_emergencies(ships, time_hours)

        assignments = self.make_assignments(ships, missions, time_hours)
        if assignments:
            self.dispatch(assignments, time_hours)

        return assignments
