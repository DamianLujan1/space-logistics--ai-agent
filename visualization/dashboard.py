"""
Mission-control dashboard — four-panel matplotlib layout.

Panel layout
────────────
  ┌──────────────────────────┬──────────────────┐
  │  Solar System Map        │  Fleet Status    │
  │  • planet orbits (rings) │  • ship bars     │
  │  • station positions     │  • fuel / batt   │
  │  • ship positions+trails │  • mission info  │
  │  • transit arrows        │  • global stats  │
  ├──────────────────────────┼──────────────────┤
  │  Energy & Fuel Telemetry │  Mission Log     │
  │  • battery % history     │  • scrolling AI  │
  │  • fuel % history        │    decision log  │
  │  (per ship, color-coded) │  • mission counts│
  └──────────────────────────┴──────────────────┘

Usage:
    from simulation.engine import SimulationEngine
    from visualization.dashboard import Dashboard

    engine = SimulationEngine()
    engine.initialize()
    engine.run(duration_days=90)

    dash = Dashboard()
    dash.render(engine, save_path="dashboard.png")
"""

import math
import textwrap
from typing import Optional

import matplotlib
matplotlib.use("Agg")    # headless rendering; change to "TkAgg" for live window
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, FancyArrow

from models.spacecraft import Spacecraft, ShipState
from models.mission import MissionStatus
from simulation.engine import SimulationEngine


# ── Colour palette ────────────────────────────────────────────────────────────
BG      = "#080818"
PANEL   = "#0d0d24"
GRID    = "#1a1a3c"
FG      = "#c8d0e8"
ACCENT  = "#3a88ff"
GOOD    = "#34e89e"
WARN    = "#ffaa00"
CRIT    = "#ff4455"
DIM     = "#606080"

# Map ShipState → colour for icons and status bars
STATE_COLOR = {
    ShipState.IDLE:      GOOD,
    ShipState.LOADING:   WARN,
    ShipState.TRANSIT:   ACCENT,
    ShipState.UNLOADING: "#ff88aa",
    ShipState.REFUELING: "#88bbff",
    ShipState.LOW_POWER: "#ff8800",
    ShipState.EMERGENCY: CRIT,
}


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard class
# ─────────────────────────────────────────────────────────────────────────────

class Dashboard:
    """
    Renders (or animates) a complete mission-control snapshot of the simulation.

    Methods
    -------
    render(engine, save_path=None)
        Draw all four panels; save to file or show interactively.
    animate(engine, steps_per_frame=10, interval_ms=120)
        Live animation using matplotlib FuncAnimation (requires a display).
    """

    def __init__(self, figsize=(22, 13)):
        self.fig = plt.figure(figsize=figsize, facecolor=BG)
        self.fig.suptitle(
            "◈  SPACE LOGISTICS COMMAND  —  MISSION CONTROL  ◈",
            color=FG, fontsize=15, fontweight="bold",
            fontfamily="monospace", y=0.985,
        )

        gs = gridspec.GridSpec(
            2, 3, figure=self.fig,
            left=0.04, right=0.98,
            top=0.95, bottom=0.05,
            wspace=0.32, hspace=0.42,
        )

        # Panels
        self.ax_solar  = self.fig.add_subplot(gs[0, :2])   # solar system map
        self.ax_status = self.fig.add_subplot(gs[0, 2])    # fleet status
        self.ax_energy = self.fig.add_subplot(gs[1, :2])   # energy telemetry
        self.ax_log    = self.fig.add_subplot(gs[1, 2])    # mission log

        for ax in (self.ax_solar, self.ax_status, self.ax_energy, self.ax_log):
            ax.set_facecolor(PANEL)
            for spine in ax.spines.values():
                spine.set_color(GRID)

    # ─────────────────────────────────────────────────────────────────────────
    # Panel 1: Solar system map
    # ─────────────────────────────────────────────────────────────────────────

    def _draw_solar_system(self, engine: SimulationEngine):
        ax = self.ax_solar
        ax.clear()
        ax.set_facecolor(PANEL)
        ax.set_aspect("equal")

        t   = engine.current_time_hours
        day = t / 24.0

        ax.set_title(
            f"SOLAR SYSTEM  ▸  Day {day:.1f}",
            color=FG, fontfamily="monospace", fontsize=10, pad=6,
        )

        # ── Orbit rings ──
        for planet in engine.planets:
            r      = planet.orbital_radius_au
            circle = Circle((0, 0), r, fill=False, color=GRID,
                            linewidth=0.6, linestyle="--", alpha=0.5)
            ax.add_patch(circle)

        # ── Star ──
        ax.scatter([0], [0], s=350, color="#ffee44", zorder=6,
                   edgecolors="#ffff99", linewidths=0.8, marker="*")
        ax.text(0, 0.04, "Sol", color="#ffee88", fontsize=6.5,
                ha="center", va="bottom", fontfamily="monospace", zorder=7)

        # ── Planets ──
        for planet in engine.planets:
            px, py = planet.position_at(t)
            size   = max(18.0, min(100.0, planet.radius_km / 900.0))
            ax.scatter([px], [py], s=size, color=planet.color, zorder=5, alpha=0.92)
            ax.text(px, py + planet.orbital_radius_au * 0.04,
                    planet.name[:3].upper(),
                    color=planet.color, fontsize=5.5, ha="center", va="bottom",
                    fontfamily="monospace", zorder=6)

        # ── Stations ──
        for station in engine.stations:
            sx, sy = station.position_at(t)
            ax.scatter([sx], [sy], s=45, color=station.color,
                       marker="D", zorder=5, alpha=0.88, edgecolors="#ffffff20",
                       linewidths=0.4)
            ax.text(sx + 0.03, sy, station.name[:10],
                    color=station.color, fontsize=4.8, ha="left", va="center",
                    fontfamily="monospace", zorder=6, alpha=0.9)

        # ── Ships ──
        for ship in engine.ships:
            sx, sy      = ship.position
            state_color = STATE_COLOR.get(ship.state, FG)

            # Position trail (last 50 points)
            if len(ship.history_positions) > 2:
                pts = ship.history_positions[-50:]
                n   = len(pts)
                for i in range(1, n):
                    alpha = (i / n) * 0.45
                    ax.plot(
                        [pts[i-1][0], pts[i][0]],
                        [pts[i-1][1], pts[i][1]],
                        color=ship.color, alpha=alpha, linewidth=0.9, zorder=3,
                    )

            # Ship icon (triangle)
            ax.scatter([sx], [sy], s=70, color=state_color, marker="^",
                       zorder=7, edgecolors=ship.color, linewidths=1.0)

            # Label
            ax.text(sx - 0.03, sy, ship.name[:7],
                    color=ship.color, fontsize=5.0, ha="right", va="center",
                    fontfamily="monospace", zorder=8,
                    bbox=dict(boxstyle="round,pad=0.15", fc=BG, ec="none", alpha=0.5))

            # Transit arrow to destination
            if ship.state == ShipState.TRANSIT and ship.destination is not None:
                dx, dy = ship.destination.position_at(t)
                ax.annotate(
                    "", xy=(dx, dy), xytext=(sx, sy),
                    arrowprops=dict(
                        arrowstyle="->",
                        color=ship.color,
                        lw=0.75,
                        alpha=0.45,
                        connectionstyle="arc3,rad=0.18",
                    ),
                    zorder=4,
                )

        # ── State legend ──
        active_states = set(s.state for s in engine.ships)
        legend_elems  = [
            Line2D([0], [0], marker="^", color="none",
                   markerfacecolor=STATE_COLOR[st], markersize=7,
                   label=st.name)
            for st in STATE_COLOR
            if st in active_states
        ]
        if legend_elems:
            ax.legend(
                handles=legend_elems, loc="lower left", fontsize=5.5,
                framealpha=0.4, facecolor=BG, edgecolor=GRID,
                labelcolor=FG,
            )

        # Auto-scale
        max_r  = max((p.orbital_radius_au for p in engine.planets), default=2.0)
        margin = max_r * 0.12
        ax.set_xlim(-max_r - margin, max_r + margin)
        ax.set_ylim(-max_r - margin, max_r + margin)
        ax.tick_params(colors=DIM, labelsize=5.5)
        ax.set_xlabel("X (AU)", color=DIM, fontsize=7, fontfamily="monospace")
        ax.set_ylabel("Y (AU)", color=DIM, fontsize=7, fontfamily="monospace")
        ax.grid(True, color=GRID, linewidth=0.3, alpha=0.6)

    # ─────────────────────────────────────────────────────────────────────────
    # Panel 2: Fleet status
    # ─────────────────────────────────────────────────────────────────────────

    def _draw_fleet_status(self, engine: SimulationEngine):
        ax = self.ax_status
        ax.clear()
        ax.set_facecolor(PANEL)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.set_title("FLEET STATUS", color=FG, fontfamily="monospace",
                     fontsize=10, pad=6)

        n          = len(engine.ships)
        row_h      = 0.90 / max(n, 1)
        top_y      = 0.97

        for i, ship in enumerate(engine.ships):
            y0          = top_y - i * row_h
            state_color = STATE_COLOR.get(ship.state, FG)

            # Ship name
            ax.text(0.03, y0, f"◈  {ship.name}",
                    color=ship.color, fontsize=8.5, fontweight="bold",
                    fontfamily="monospace", transform=ax.transAxes, va="top")

            # Class + state
            ax.text(0.03, y0 - 0.022,
                    f"   {ship.ship_class:<16}  {ship.state.name}",
                    color=state_color, fontsize=6, fontfamily="monospace",
                    transform=ax.transAxes, va="top")

            bar_y = y0 - 0.048

            # Fuel bar
            fuel = ship.propulsion.fuel_fraction
            self._bar(ax, 0.03, bar_y, 0.44, 0.014,
                      fuel, GOOD if fuel > 0.25 else CRIT,
                      label="FUEL", pct=fuel)

            # Battery bar
            batt = ship.power.battery_fraction
            self._bar(ax, 0.53, bar_y, 0.44, 0.014,
                      batt, GOOD if batt > 0.20 else WARN,
                      label="PWR", pct=batt)

            # Mission line
            if ship.mission:
                dest = ship.mission.destination.name[:13] if ship.mission.destination else "?"
                pct  = ship.transit_progress
                ax.text(0.03, bar_y - 0.018,
                        f"   ► {dest}  [{pct:.0%}]",
                        color=ACCENT, fontsize=5.2, fontfamily="monospace",
                        transform=ax.transAxes, va="top")

            # Separator
            sep_y = bar_y - 0.030
            ax.axhline(sep_y, color=GRID, linewidth=0.5, alpha=0.6,
                       xmin=0.02, xmax=0.98)

        # ── Global summary (bottom) ──
        s = engine.stats
        bot = 0.10
        ax.text(0.03, bot,
                f"Completed  : {s['total_missions_completed']:>5}",
                color=GOOD, fontsize=6.5, fontfamily="monospace",
                transform=ax.transAxes)
        ax.text(0.03, bot - 0.030,
                f"Failed     : {s['total_missions_failed']:>5}",
                color=CRIT, fontsize=6.5, fontfamily="monospace",
                transform=ax.transAxes)
        ax.text(0.03, bot - 0.060,
                f"Revenue    : {s['total_revenue']:>12,.0f} cr",
                color=GOOD, fontsize=6.5, fontfamily="monospace",
                transform=ax.transAxes)
        ax.text(0.03, bot - 0.090,
                f"Cargo deliv: {s['total_cargo_delivered_kg']:>10,.0f} kg",
                color=FG, fontsize=6.5, fontfamily="monospace",
                transform=ax.transAxes)

    def _bar(self, ax, x, y, w, h, fraction, color, label="", pct=0.0):
        """Draw a labelled horizontal progress bar in axes-fraction coordinates."""
        # Background track
        ax.add_patch(mpatches.FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0",
            facecolor=GRID, edgecolor=DIM, linewidth=0.3,
            transform=ax.transAxes,
        ))
        # Fill
        fill_w = max(0.001, w * min(fraction, 1.0))
        ax.add_patch(mpatches.FancyBboxPatch(
            (x, y), fill_w, h,
            boxstyle="round,pad=0",
            facecolor=color, edgecolor="none", alpha=0.85,
            transform=ax.transAxes,
        ))
        # Labels
        ax.text(x - 0.01, y + h / 2, label,
                color=DIM, fontsize=4, fontfamily="monospace",
                ha="right", va="center", transform=ax.transAxes)
        ax.text(x + w + 0.01, y + h / 2, f"{pct:.0%}",
                color=color, fontsize=4, fontfamily="monospace",
                ha="left", va="center", transform=ax.transAxes)

    # ─────────────────────────────────────────────────────────────────────────
    # Panel 3: Energy telemetry
    # ─────────────────────────────────────────────────────────────────────────

    def _draw_energy(self, engine: SimulationEngine):
        ax = self.ax_energy
        ax.clear()
        ax.set_facecolor(PANEL)

        ax.set_title(
            "FLEET ENERGY & FUEL TELEMETRY  (solid=battery %  dashed=fuel %)",
            color=FG, fontfamily="monospace", fontsize=9.5, pad=6,
        )

        ax2 = ax.twinx()
        ax2.set_facecolor(PANEL)

        plotted = False
        for ship in engine.ships:
            if not ship.history_battery:
                continue
            plotted = True
            steps_b = list(range(len(ship.history_battery)))
            steps_f = list(range(len(ship.history_fuel)))

            # Battery % — solid
            ax.plot(steps_b, ship.history_battery,
                    color=ship.color, linewidth=1.3, alpha=0.85)

            # Fuel % — dashed (on twin axis so scales don't interfere)
            if ship.history_fuel:
                ax2.plot(steps_f, ship.history_fuel,
                         color=ship.color, linewidth=0.9, alpha=0.50,
                         linestyle="--")

        # Threshold guides
        ax.axhline(15, color=CRIT, linewidth=0.6, linestyle=":", alpha=0.7)
        ax.axhline(35, color=WARN, linewidth=0.6, linestyle=":", alpha=0.5)
        ax.text(2, 16.5, "⚠ BATTERY CRITICAL", color=CRIT,
                fontsize=5.5, fontfamily="monospace")
        ax.text(2, 36.5, "LOW POWER THRESHOLD", color=WARN,
                fontsize=5.5, fontfamily="monospace")

        ax.set_ylabel("Battery %", color=GOOD, fontsize=7.5, fontfamily="monospace")
        ax2.set_ylabel("Fuel %", color=WARN, fontsize=7.5, fontfamily="monospace")
        ax.set_xlabel("Simulation Steps", color=DIM, fontsize=7, fontfamily="monospace")
        ax.set_ylim(0, 108)
        ax2.set_ylim(0, 108)
        ax.tick_params(colors=DIM, labelsize=6)
        ax2.tick_params(colors=DIM, labelsize=6)
        ax.grid(True, color=GRID, linewidth=0.35, alpha=0.55)

        for spine in ax2.spines.values():
            spine.set_color(GRID)

        if plotted:
            legend_elems = [
                Line2D([0], [0], color=s.color, lw=1.3,
                       label=f"{s.name} ({s.ship_class})")
                for s in engine.ships if s.history_battery
            ]
            ax.legend(
                handles=legend_elems, fontsize=5.5, loc="lower right",
                framealpha=0.35, facecolor=BG, edgecolor=GRID,
                labelcolor=FG, ncol=2,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Panel 4: Mission log
    # ─────────────────────────────────────────────────────────────────────────

    def _draw_log(self, engine: SimulationEngine):
        ax = self.ax_log
        ax.clear()
        ax.set_facecolor(PANEL)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.set_title("MISSION CONTROL LOG", color=FG,
                     fontfamily="monospace", fontsize=10, pad=6)

        # ── Mission counts sidebar ──
        missions = engine.missions
        cnt = {
            "PENDING":    sum(1 for m in missions if m.status == MissionStatus.PENDING),
            "IN TRANSIT": sum(1 for m in missions if m.status == MissionStatus.IN_TRANSIT),
            "DELIVERED":  sum(1 for m in missions if m.status == MissionStatus.DELIVERED),
            "FAILED":     sum(1 for m in missions if m.status == MissionStatus.FAILED),
        }
        cnt_colors = {"PENDING": WARN, "IN TRANSIT": ACCENT,
                      "DELIVERED": GOOD, "FAILED": CRIT}
        for j, (label, n) in enumerate(cnt.items()):
            x = 0.03 + j * 0.245
            ax.text(x, 0.97, label, color=cnt_colors[label],
                    fontsize=5, fontfamily="monospace", transform=ax.transAxes,
                    ha="left", va="top")
            ax.text(x, 0.955, str(n), color=cnt_colors[label],
                    fontsize=9, fontweight="bold", fontfamily="monospace",
                    transform=ax.transAxes, ha="left", va="top")

        ax.axhline(0.935, color=GRID, linewidth=0.6, alpha=0.7,
                   xmin=0.01, xmax=0.99)

        # ── Scrolling log ──
        log     = engine.planner.decision_log
        visible = log[-28:] if len(log) > 28 else log
        n_vis   = len(visible)

        log_top = 0.920
        line_h  = (log_top - 0.01) / max(n_vis, 1)

        for i, entry in enumerate(reversed(visible)):
            y = log_top - i * line_h

            # Colour-code by keyword
            if any(k in entry for k in ("DISPATCH", "DELIVERY")):
                color = GOOD
            elif any(k in entry for k in ("ALERT", "WARNING", "FAILED")):
                color = CRIT
            elif "EMERGENCY" in entry:
                color = WARN
            elif any(k in entry for k in ("RECOVERY", "SOLAR FLARE", "EQUIPMENT")):
                color = ACCENT
            elif "MISSION   " in entry or "INITIALIZED" in entry:
                color = DIM
            else:
                color = FG

            # Wrap long lines
            short = entry if len(entry) <= 54 else entry[:51] + "…"
            ax.text(0.02, y, short, color=color, fontsize=4.8,
                    fontfamily="monospace", transform=ax.transAxes,
                    va="top", clip_on=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Footer
    # ─────────────────────────────────────────────────────────────────────────

    def _draw_footer(self, engine: SimulationEngine):
        s   = engine.stats
        day = engine.current_time_hours / 24.0
        text = (
            f"  Day {day:7.1f}  ▸  "
            f"Generated: {s['total_missions_generated']}  "
            f"Completed: {s['total_missions_completed']}  "
            f"Failed: {s['total_missions_failed']}  "
            f"Revenue: {s['total_revenue']:,.0f} cr  "
            f"Cargo: {s['total_cargo_delivered_kg']:,.0f} kg  "
            f"Flares: {s['solar_flares']}  "
            f"Steps: {s['steps_completed']}"
        )
        self.fig.text(0.01, 0.012, text, color=ACCENT,
                      fontsize=6.5, fontfamily="monospace", alpha=0.85)

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def render(self, engine: SimulationEngine, save_path: Optional[str] = None):
        """
        Render a full dashboard snapshot.

        Parameters
        ----------
        engine    : SimulationEngine — source of all state
        save_path : str or None — path for PNG output; None → plt.show()
        """
        self._draw_solar_system(engine)
        self._draw_fleet_status(engine)
        self._draw_energy(engine)
        self._draw_log(engine)
        self._draw_footer(engine)

        if save_path:
            self.fig.savefig(save_path, dpi=150, bbox_inches="tight",
                             facecolor=BG, edgecolor="none")
            print(f"[Dashboard] Saved → {save_path}")
        else:
            plt.tight_layout(rect=[0, 0.025, 1, 0.98])
            plt.show()

        return self.fig

    def animate(
        self,
        engine: SimulationEngine,
        steps_per_frame: int = 10,
        interval_ms:     int = 120,
    ):
        """
        Live animated dashboard.  Requires a display (non-Agg backend).
        Each animation frame advances the sim by *steps_per_frame* steps.
        """
        import matplotlib.animation as animation
        matplotlib.use("TkAgg")

        def _frame(_):
            for _ in range(steps_per_frame):
                engine.step()
            self._draw_solar_system(engine)
            self._draw_fleet_status(engine)
            self._draw_energy(engine)
            self._draw_log(engine)
            self._draw_footer(engine)
            day = engine.current_time_hours / 24.0
            self.fig.suptitle(
                f"◈  SPACE LOGISTICS COMMAND  —  Day {day:.1f}  ◈",
                color=FG, fontsize=15, fontweight="bold",
                fontfamily="monospace", y=0.985,
            )
            return []

        ani = animation.FuncAnimation(
            self.fig, _frame,
            interval=interval_ms,
            blit=False,
            cache_frame_data=False,
        )
        plt.show()
        return ani
