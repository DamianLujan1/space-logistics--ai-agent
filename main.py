"""
Space Logistics AI Agent Simulator  —  Entry Point
═══════════════════════════════════════════════════

A physics-accurate space logistics simulation featuring:
  • Keplerian orbital mechanics (Hohmann transfers, Tsiolkovsky equation)
  • Solar-electric energy models (inverse-square irradiance, battery SOC)
  • Multi-objective AI mission planner (greedy weighted assignment)
  • Stochastic event generation (missions, solar flares, equipment failures)
  • Matplotlib mission-control dashboard (4-panel, dark theme)

Usage examples
──────────────
  python main.py                         # 365-day run, save dashboard.png
  python main.py --days 180              # 180-day run
  python main.py --days 90 --verbose     # with step-by-step console output
  python main.py --save my_run.png       # custom output path
  python main.py --seed 777              # different stochastic sequence
  python main.py --animate               # live animation (needs display)
  python main.py --steps 500             # run exactly N sim steps
"""

import argparse
import sys
import os

from simulation.engine import SimulationEngine
from visualization.dashboard import Dashboard
from config import SIM_DURATION_DAYS, HOURS_PER_DAY, SIM_TIME_STEP_HOURS


# ─────────────────────────────────────────────────────────────────────────────
# Banner
# ─────────────────────────────────────────────────────────────────────────────

BANNER = r"""
  ╔════════════════════════════════════════════════════════════════╗
  ║         SPACE LOGISTICS AI AGENT SIMULATOR  v1.0              ║
  ║  Orbital Mechanics  ·  Energy Models  ·  Decision AI          ║
  ╚════════════════════════════════════════════════════════════════╝
"""


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="space_logistics",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--days",    type=float, default=SIM_DURATION_DAYS,
                   metavar="N", help="Simulation duration in days (default: %(default)s)")
    p.add_argument("--steps",   type=int,   default=None,
                   metavar="N", help="Run for exactly N steps (overrides --days)")
    p.add_argument("--seed",    type=int,   default=42,
                   metavar="S", help="Random seed (default: %(default)s)")
    p.add_argument("--save",    type=str,   default="space_logistics_dashboard.png",
                   metavar="PATH", help="Output PNG path (default: %(default)s)")
    p.add_argument("--verbose", action="store_true",
                   help="Print per-100-step progress to stdout")
    p.add_argument("--animate", action="store_true",
                   help="Run live animation instead of static render (needs display)")
    p.add_argument("--no-save", action="store_true",
                   help="Skip saving the dashboard image")
    return p.parse_args()


# ─────────────────────────────────────────────────────────────────────────────
# Report helpers
# ─────────────────────────────────────────────────────────────────────────────

def print_summary(engine: SimulationEngine, duration_days: float, n_steps: int):
    s   = engine.stats
    div = "═" * 66

    print(f"\n{div}")
    print("  SIMULATION COMPLETE  —  FINAL REPORT")
    print(div)
    print(f"  Duration         : {duration_days:.1f} days  ({n_steps} steps)")
    print(f"  Fleet size       : {len(engine.ships)} ships")
    print(f"  Stations         : {len(engine.stations)}")
    print(f"  Missions generated:  {s['total_missions_generated']:>5}")
    print(f"  Missions completed:  {s['total_missions_completed']:>5}")
    print(f"  Missions failed  :  {s['total_missions_failed']:>5}")
    success = s["total_missions_completed"] / max(s["total_missions_generated"], 1) * 100
    print(f"  Success rate     :  {success:>5.1f} %")
    print(f"  Total revenue    :  {s['total_revenue']:>15,.0f} cr")
    print(f"  Cargo delivered  :  {s['total_cargo_delivered_kg']:>15,.0f} kg")
    print(f"  Solar flares     :  {s['solar_flares']:>5}")
    print(f"  Equipment events :  {s['equipment_failures']:>5}")
    print()

    # Per-ship breakdown
    print(f"  {'Ship':<14} {'Class':<16} {'Missions':>9} {'Revenue (cr)':>15} {'Cargo (kg)':>12}")
    print("  " + "─" * 68)
    for ship in sorted(engine.ships, key=lambda s: s.total_revenue, reverse=True):
        print(
            f"  {ship.name:<14} {ship.ship_class:<16}"
            f" {ship.total_missions_completed:>9}"
            f" {ship.total_revenue:>15,.0f}"
            f" {ship.total_cargo_delivered_kg:>12,.0f}"
        )
    print(div)


def print_recent_log(engine: SimulationEngine, n: int = 18):
    log = engine.planner.decision_log
    entries = log[-n:] if len(log) > n else log
    print(f"\n  RECENT AI DECISIONS (last {len(entries)} entries)")
    print("  " + "─" * 72)
    for entry in entries:
        print(f"  {entry}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print(BANNER)
    args = parse_args()

    # ── Build engine ──────────────────────────────────────────────────────────
    print(f"  Initialising simulation  (seed={args.seed}) …")
    engine = SimulationEngine(seed=args.seed)
    engine.initialize()
    print(f"  Fleet     : {len(engine.ships)} ships")
    print(f"  Stations  : {len(engine.stations)}")
    print(f"  Planets   : {len(engine.planets)}")
    print(f"  Seed missions : {len(engine.missions)}")
    print()

    # ── Determine run length ──────────────────────────────────────────────────
    if args.steps is not None:
        n_steps       = args.steps
        duration_days = n_steps * SIM_TIME_STEP_HOURS / HOURS_PER_DAY
    else:
        duration_days = args.days
        n_steps       = int(args.days * HOURS_PER_DAY / SIM_TIME_STEP_HOURS)

    # ── Animate or batch run ──────────────────────────────────────────────────
    if args.animate:
        print("  Starting live animation (close window to stop) …")
        dash = Dashboard(figsize=(22, 13))
        dash.animate(engine, steps_per_frame=8, interval_ms=110)
        return

    print(f"  Running {n_steps} steps  ({duration_days:.1f} days)  …")
    if args.verbose:
        print()

    engine.run(duration_days=duration_days, verbose=args.verbose)

    # ── Console summary ───────────────────────────────────────────────────────
    print_summary(engine, duration_days, n_steps)
    print_recent_log(engine)

    # ── Dashboard render ──────────────────────────────────────────────────────
    save_path = None if args.no_save else args.save
    print(f"  Rendering dashboard …")
    dash = Dashboard(figsize=(22, 13))
    dash.render(engine, save_path=save_path)

    if save_path:
        size_kb = os.path.getsize(save_path) / 1_024
        print(f"  Dashboard  → {save_path}  ({size_kb:.0f} KB)")

    print("\n  Done.\n")


if __name__ == "__main__":
    main()
