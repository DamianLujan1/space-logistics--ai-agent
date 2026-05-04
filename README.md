# Space Logistics AI Agent Simulator

A physics-accurate Python simulator of an interplanetary cargo network managed
by an AI planning agent.  Ships haul cargo between space stations across the
solar system while managing fuel budgets, solar power, and mission deadlines.

---

## What it does

| Layer | What's modelled |
|---|---|
| **Orbital mechanics** | Hohmann transfer Δv (vis-viva equation), Tsiolkovsky rocket equation for fuel mass |
| **Energy system** | Solar irradiance falls off as 1/r², 28 % panel efficiency, RTG baseline power, per-subsystem power budget, battery state-of-charge |
| **AI planner** | Greedy weighted-utility assignment — scores every (ship, mission) pair on urgency, value density, fuel efficiency, and deadline proximity; dispatches the globally best collision-free set each tick |
| **Simulation engine** | 6-hour time steps, ship state machines (IDLE → TRANSIT → LOW\_POWER → …), stochastic event generation (missions, solar flares, equipment failures) |
| **Visualization** | 4-panel dark matplotlib dashboard: solar-system map with orbital trails and transit arrows, fleet fuel/battery bars, energy telemetry chart, scrolling AI decision log |

### Ships
| Class | Role |
|---|---|
| Courier | Fast, light — urgent medical / personnel runs |
| Freighter | Heavy bulk cargo |
| Science Vessel | Instruments + high-bandwidth comms |
| Tanker | Fuel and liquid bulk |

### Solar system
6 planets (Mercury → Saturn) + 6 space stations:
Earth Gateway, Lunar Outpost, Mars Colony Hub, Venus Orbital Platform,
Jupiter Gateway, Belt Mining Depot.

---

## How to run

### 1 — Install dependencies

```bash
pip install -r requirements.txt
```

### 2 — Quick start (365-day run, saves `space_logistics_dashboard.png`)

```bash
python main.py
```

### 3 — Common options

```bash
# Choose duration
python main.py --days 90

# Print step-by-step progress
python main.py --days 180 --verbose

# Different random seed (changes planet phases, mission RNG)
python main.py --seed 1234

# Save dashboard to a custom path
python main.py --save my_run.png

# Run exactly N simulation steps
python main.py --steps 200

# Live animated window (requires a display / desktop)
python main.py --animate
```

### 4 — Full option reference

```
python main.py --help

  --days   N     Simulation duration in days           (default: 365)
  --steps  N     Run exactly N steps (overrides --days)
  --seed   S     Random seed for reproducibility       (default: 42)
  --save   PATH  Output PNG path                       (default: space_logistics_dashboard.png)
  --verbose      Print progress every 100 steps
  --animate      Live animation (needs display)
  --no-save      Skip saving the dashboard image
```

### 5 — Example: compare two seeds

```bash
python main.py --days 180 --seed 42   --save run_42.png
python main.py --days 180 --seed 999  --save run_999.png
```

---

## Project layout

```
space-logistics--ai-agent/
├── config.py               Physical constants, planet data, ship classes, cargo types
├── main.py                 CLI entry point
├── requirements.txt
├── models/
│   ├── celestial.py        Star, Planet (Keplerian orbits), SpaceStation
│   ├── spacecraft.py       PropulsionSystem, PowerSystem, CargoHold, Spacecraft
│   └── mission.py          CargoItem, Mission (reward / penalty / deadline)
├── physics/
│   ├── orbital.py          Hohmann Δv, Tsiolkovsky fuel, cruise-speed transit time
│   └── energy.py           Solar irradiance model, PowerBudget, SolarEvent
├── agent/
│   └── planner.py          AI mission planner (greedy weighted-utility)
├── simulation/
│   └── engine.py           Time-stepped sim loop, event system, world builder
└── visualization/
    └── dashboard.py        4-panel matplotlib dashboard
```

---

## What to look for in the output

- **DISPATCH** lines — AI assigns a ship to a mission with Δv, ETA, and score
- **DELIVERY ON TIME / LATE** — mission outcome and credit reward
- **ALERT / LOW POWER** — outer-system ship battery depleted (e.g. Jupiter Gateway)
- **RECOVERY** — ship recharges and resumes transit
- **SOLAR FLARE** — X-class event reduces panel output on outer-system ships
- **EMERGENCY** — high-urgency medical/personnel mission spawns with tight deadline

---

## Extending the simulator

| Want to… | Where to edit |
|---|---|
| Add a new planet or station | `config.py` → `PLANET_DATA` / `STATION_DATA` |
| Add a new ship class | `config.py` → `SHIP_CLASSES` |
| Add a new cargo type | `config.py` → `CARGO_TYPES` |
| Tune AI scoring weights | `config.py` → `PLANNER_WEIGHTS` |
| Change transit speed | `config.py` → `TRANSIT_SPEED_AU_PER_HOUR` |
| Improve the AI (e.g. lookahead, LP) | `agent/planner.py` |
| Add new physics events | `simulation/engine.py` → `_generate_events()` |
| Customise the dashboard layout | `visualization/dashboard.py` |
