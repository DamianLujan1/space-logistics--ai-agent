"""
Space Logistics Simulator — Configuration
Physical constants, simulation parameters, solar system data, ship classes.
"""

# ── Physical Constants ───────────────────────────────────────────────────────
G               = 6.674e-11    # gravitational constant (m³ kg⁻¹ s⁻²)
M_SUN           = 1.989e30     # solar mass (kg)
AU              = 1.496e11     # 1 astronomical unit (m)
SOLAR_CONSTANT  = 1361.0       # solar irradiance at 1 AU (W/m²)
G0              = 9.80665      # standard gravity (m/s²)

# ── Time Scales ──────────────────────────────────────────────────────────────
HOURS_PER_DAY   = 24
DAYS_PER_YEAR   = 365.25
HOURS_PER_YEAR  = HOURS_PER_DAY * DAYS_PER_YEAR

# ── Simulation Parameters ─────────────────────────────────────────────────────
SIM_TIME_STEP_HOURS  = 6       # hours per sim tick
SIM_DURATION_DAYS    = 365     # default run length
SIM_TELEMETRY_WINDOW = 200     # history samples kept per ship

# ── Transit Speed ─────────────────────────────────────────────────────────────
# Ships travel at this cruise speed for scheduling purposes (AU / hour).
# Fuel is still computed from correct Hohmann Δv (Tsiolkovsky equation).
# At 0.002 AU/h ≈ 87 km/s:  Earth↔Mars ~10-50 d, Earth↔Jupiter ~80-120 d.
TRANSIT_SPEED_AU_PER_HOUR = 0.0025

# ── Solar System Bodies ───────────────────────────────────────────────────────
# orbital_radius_au, orbital_period_days, mass_kg, radius_km, color
PLANET_DATA = {
    "Mercury": {
        "orbital_radius_au":   0.387,
        "orbital_period_days": 87.97,
        "mass_kg":             3.285e23,
        "radius_km":           2_439.7,
        "color":               "#b5b5b5",
        "has_stations":        False,
    },
    "Venus": {
        "orbital_radius_au":   0.723,
        "orbital_period_days": 224.70,
        "mass_kg":             4.867e24,
        "radius_km":           6_051.8,
        "color":               "#e8cda0",
        "has_stations":        True,
    },
    "Earth": {
        "orbital_radius_au":   1.000,
        "orbital_period_days": 365.25,
        "mass_kg":             5.972e24,
        "radius_km":           6_371.0,
        "color":               "#4fa3e0",
        "has_stations":        True,
    },
    "Mars": {
        "orbital_radius_au":   1.524,
        "orbital_period_days": 686.97,
        "mass_kg":             6.390e23,
        "radius_km":           3_389.5,
        "color":               "#c1440e",
        "has_stations":        True,
    },
    "Jupiter": {
        "orbital_radius_au":   5.203,
        "orbital_period_days": 4_332.59,
        "mass_kg":             1.898e27,
        "radius_km":           69_911.0,
        "color":               "#c88b3a",
        "has_stations":        True,
    },
    "Saturn": {
        "orbital_radius_au":   9.537,
        "orbital_period_days": 10_759.22,
        "mass_kg":             5.683e26,
        "radius_km":           58_232.0,
        "color":               "#e4d191",
        "has_stations":        False,
    },
}

# ── Space Stations ────────────────────────────────────────────────────────────
# parent_planet → orbits near that planet; else independent solar orbit
STATION_DATA = {
    "Earth Gateway": {
        "parent_planet":    "Earth",
        "orbital_offset_au": 0.008,
        "color":            "#00ff88",
    },
    "Mars Colony Hub": {
        "parent_planet":    "Mars",
        "orbital_offset_au": 0.005,
        "color":            "#ff6644",
    },
    "Venus Orbital Platform": {
        "parent_planet":    "Venus",
        "orbital_offset_au": 0.006,
        "color":            "#ffdd44",
    },
    "Jupiter Gateway": {
        "parent_planet":    "Jupiter",
        "orbital_offset_au": 0.015,
        "color":            "#ff9933",
    },
    "Belt Mining Depot": {
        "orbital_radius_au":    2.700,
        "orbital_period_days":  1_620,
        "color":                "#888888",
    },
    "Lunar Outpost": {
        "parent_planet":    "Earth",
        "orbital_offset_au": 0.003,
        "color":            "#aaaacc",
    },
}

# ── Ship Classes ──────────────────────────────────────────────────────────────
# power_draw_kw represents electrical housekeeping loads (NOT main-engine thrust).
# Chemical rockets consume propellant, not kW.  These loads are: attitude control
# thrusters, avionics, TVC, life support, comms, instruments.
# rtg_power_kw: Radioisotope Thermoelectric Generator baseline (constant; used by
# ships operating beyond ~3 AU where solar becomes insufficient).
SHIP_CLASSES = {
    "Courier": {
        "dry_mass_kg":         5_000,
        "max_fuel_kg":        15_000,
        "cargo_capacity_kg":   3_000,
        "isp_seconds":           320,
        "solar_panel_area_m2":    40,
        "battery_capacity_kwh":   50,
        "rtg_power_kw":            0.5,  # small backup RTG
        "power_draw_kw": {
            "life_support":  0.5,   # basic crew life support
            "propulsion":    2.5,   # ACS + TVC during burn
            "comms":         0.3,
            "payload":       0.4,
        },
        "color":       "#00ffff",
        "description": "Fast light courier for urgent deliveries",
    },
    "Freighter": {
        "dry_mass_kg":        25_000,
        "max_fuel_kg":        80_000,
        "cargo_capacity_kg":  50_000,
        "isp_seconds":           290,
        "solar_panel_area_m2":   200,
        "battery_capacity_kwh":  500,
        "rtg_power_kw":            1.0,
        "power_draw_kw": {
            "life_support":  1.5,
            "propulsion":    4.0,
            "comms":         0.6,
            "payload":       1.2,
        },
        "color":       "#ffaa00",
        "description": "Heavy cargo transport for bulk goods",
    },
    "Science Vessel": {
        "dry_mass_kg":        12_000,
        "max_fuel_kg":        30_000,
        "cargo_capacity_kg":   8_000,
        "isp_seconds":           340,
        "solar_panel_area_m2":   120,
        "battery_capacity_kwh":  200,
        "rtg_power_kw":            1.5,  # larger RTG for science instruments
        "power_draw_kw": {
            "life_support":  1.0,
            "propulsion":    3.0,
            "comms":         1.5,   # high-bandwidth science downlink
            "payload":       4.0,   # active science instruments
        },
        "color":       "#aa44ff",
        "description": "Research vessel with advanced instruments",
    },
    "Tanker": {
        "dry_mass_kg":        15_000,
        "max_fuel_kg":       120_000,
        "cargo_capacity_kg":  80_000,
        "isp_seconds":           310,
        "solar_panel_area_m2":    80,
        "battery_capacity_kwh":  150,
        "rtg_power_kw":            1.2,
        "power_draw_kw": {
            "life_support":  1.2,
            "propulsion":    3.5,
            "comms":         0.4,
            "payload":       0.8,
        },
        "color":       "#ff4488",
        "description": "Bulk fuel and liquid transport",
    },
}

# ── Cargo / Mission Types ─────────────────────────────────────────────────────
# mass_per_unit_kg, value_per_unit (credits), urgency_range (min, max)
CARGO_TYPES = {
    "Food": {
        "mass_per_unit_kg":  100,
        "value_per_unit":    500,
        "urgency_range":     (0.4, 0.75),
    },
    "Medical": {
        "mass_per_unit_kg":   20,
        "value_per_unit":  5_000,
        "urgency_range":     (0.8, 1.0),
    },
    "Equipment": {
        "mass_per_unit_kg":  500,
        "value_per_unit":  2_000,
        "urgency_range":     (0.3, 0.65),
    },
    "Fuel": {
        "mass_per_unit_kg": 1_000,
        "value_per_unit":    800,
        "urgency_range":     (0.4, 0.8),
    },
    "Science Samples": {
        "mass_per_unit_kg":    5,
        "value_per_unit": 10_000,
        "urgency_range":     (0.6, 0.95),
    },
    "Construction Materials": {
        "mass_per_unit_kg": 2_000,
        "value_per_unit":    300,
        "urgency_range":     (0.2, 0.5),
    },
    "Personnel": {
        "mass_per_unit_kg":  200,
        "value_per_unit": 50_000,
        "urgency_range":     (0.7, 1.0),
    },
}

# ── AI Planner Weights ────────────────────────────────────────────────────────
PLANNER_WEIGHTS = {
    "urgency":          3.0,
    "value":            1.0,
    "deadline_penalty": 2.0,
    "fuel_efficiency":  1.5,
    "distance":        -0.5,   # negative → penalise long hauls
}

# ── Stochastic Event Rates (probability per sim step) ─────────────────────────
EVENT_PROBABILITIES = {
    "solar_flare":        0.004,   # reduces panel output
    "equipment_failure":  0.006,   # random ship system hit
    "emergency_mission":  0.018,   # high-urgency mission spawns
    "mission_request":    0.14,    # normal mission request
}
