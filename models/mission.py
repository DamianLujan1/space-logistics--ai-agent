"""
Mission and cargo data models.

A Mission encodes a full logistics job:
  pickup cargo at *origin* station → deliver to *destination* station
  before *deadline_hours* to maximise reward.

Reward structure:
  final_reward = base_reward
               + early_bonus  (if delivered before deadline)
               − late_penalty × hours_late  (if overdue, floor 0)
"""

import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional

from config import CARGO_TYPES


# ─────────────────────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────────────────────

class MissionStatus(Enum):
    PENDING    = auto()   # unassigned, awaiting a ship
    ASSIGNED   = auto()   # ship assigned but not yet loaded  (unused — we go direct to IN_TRANSIT)
    IN_TRANSIT = auto()   # cargo aboard, ship en route
    DELIVERED  = auto()   # cargo safely received
    FAILED     = auto()   # deadline passed before assignment/delivery
    CANCELLED  = auto()   # manually cancelled


class CargoType(Enum):
    FOOD                  = "Food"
    MEDICAL               = "Medical"
    EQUIPMENT             = "Equipment"
    FUEL                  = "Fuel"
    SCIENCE_SAMPLES       = "Science Samples"
    CONSTRUCTION_MATERIALS = "Construction Materials"
    PERSONNEL             = "Personnel"


# ─────────────────────────────────────────────────────────────────────────────
# Cargo item
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CargoItem:
    """One line item in a mission's cargo manifest."""
    cargo_type:     CargoType
    quantity:       int
    mass_kg:        float
    value_credits:  float
    urgency:        float   # 0.0 (routine) → 1.0 (life-critical)

    @classmethod
    def generate(cls, cargo_type: CargoType, quantity: int = 1,
                 urgency_override: Optional[float] = None) -> "CargoItem":
        """Construct from config spec; optionally force urgency."""
        spec = CARGO_TYPES[cargo_type.value]
        urgency = urgency_override if urgency_override is not None else (
            (spec["urgency_range"][0] + spec["urgency_range"][1]) / 2.0
        )
        return cls(
            cargo_type    = cargo_type,
            quantity      = quantity,
            mass_kg       = spec["mass_per_unit_kg"] * quantity,
            value_credits = spec["value_per_unit"]   * quantity,
            urgency       = urgency,
        )

    def __repr__(self) -> str:
        return (f"<Cargo {self.cargo_type.value} ×{self.quantity} "
                f"({self.mass_kg:.0f} kg, {self.value_credits:,.0f} cr, "
                f"urgency={self.urgency:.2f})>")


# ─────────────────────────────────────────────────────────────────────────────
# Mission
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Mission:
    """
    A logistics task: move *cargo_items* from *origin* to *destination*.

    The planner scores missions by (urgency, value, proximity, fuel cost) and
    assigns the highest-scoring idle ship.  Once dispatched, cargo is loaded
    immediately and the ship enters TRANSIT state.
    """

    # Identity
    mission_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8].upper())
    name:       str = "Unnamed Mission"
    status:     MissionStatus = MissionStatus.PENDING

    # Logistics
    origin:      Optional[object] = None   # SpaceStation
    destination: Optional[object] = None   # SpaceStation
    cargo_items: List[CargoItem]  = field(default_factory=list)

    # Timing (hours from simulation epoch)
    created_at_hours:   float = 0.0
    deadline_hours:     float = float("inf")
    assigned_at_hours:  Optional[float] = None
    completed_at_hours: Optional[float] = None

    # Economics
    base_reward_credits:    float = 0.0
    early_bonus_credits:    float = 0.0
    late_penalty_per_hour:  float = 0.0

    # Assignment
    assigned_ship: Optional[object] = None   # Spacecraft

    # ── computed properties ───────────────────────────────────────────────────

    @property
    def total_cargo_mass_kg(self) -> float:
        return sum(i.mass_kg for i in self.cargo_items)

    @property
    def total_value_credits(self) -> float:
        return sum(i.value_credits for i in self.cargo_items)

    @property
    def urgency(self) -> float:
        """Peak urgency across all cargo items."""
        return max((i.urgency for i in self.cargo_items), default=0.0)

    def time_until_deadline(self, current_time_hours: float) -> float:
        return self.deadline_hours - current_time_hours

    def is_overdue(self, current_time_hours: float) -> bool:
        return current_time_hours > self.deadline_hours

    # ── reward computation ────────────────────────────────────────────────────

    def compute_reward(self, delivered_at_hours: float) -> float:
        if delivered_at_hours <= self.deadline_hours:
            hours_early = self.deadline_hours - delivered_at_hours
            bonus = min(self.early_bonus_credits, hours_early * 10.0)
            return self.base_reward_credits + bonus
        hours_late = delivered_at_hours - self.deadline_hours
        return max(0.0, self.base_reward_credits - hours_late * self.late_penalty_per_hour)

    def __repr__(self) -> str:
        o = self.origin.name      if self.origin      else "?"
        d = self.destination.name if self.destination else "?"
        return (f"<Mission[{self.mission_id}] '{self.name}' "
                f"{o}→{d} {self.total_cargo_mass_kg:.0f} kg "
                f"urgency={self.urgency:.2f} [{self.status.name}]>")
