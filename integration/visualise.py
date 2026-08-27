# =============================================================================
# visualise.py
# Plotting utilities for the rolling-horizon simulation.
#
# Three outputs per iteration:
#   1. Grid snapshot  — fire state map with aircraft positions and drop locations
#   2. Time-series summary saved at the end — burning cells vs iteration
#   3. Route plot per aircraft (optional, can be expensive for large grids)
# =============================================================================

import os
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')   # non-interactive backend (runs on servers / HPC)
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import ListedColormap, BoundaryNorm

from config.config import (
    GRID_ROWS, GRID_COLS, CELL_SIZE_M,
    STATE_UNBURNED, STATE_BURNING, STATE_EXTINGUISHED,
    AIRFIELD_CELL, WATER_CELLS,
    OUTPUT_DIR,
)

# Colour map for the 3-state grid
_CMAP  = ListedColormap(['#d4e6b5', '#e74c3c', '#95a5a6'])   # green / red / grey
_NORM  = BoundaryNorm([-0.5, 0.5, 1.5, 2.5], _CMAP.N)
_STATE_LABELS = {0: 'Unburned', 1: 'Burning', 2: 'Extinguished'}


# ---------------------------------------------------------------------------
# 1. Per-iteration grid snapshot
# ---------------------------------------------------------------------------
def plot_iteration(
    iteration: int,
    grid_before: np.ndarray,
    grid_after: np.ndarray,
    drop_schedule: list,
    routes: dict,
    wind: dict,
    output_dir: str = OUTPUT_DIR,
) -> None:
    """
    Save a two-panel figure:
      Left  — fire state BEFORE the optimiser ran (as seen by Gurobi)
      Right — fire state AFTER drops were applied  (fed to next FARSITE run)

    Aircraft positions at each timestep are plotted as light trajectories.
    Drop locations are marked with a blue cross.
    """
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    for ax, grid, title in zip(
        axes,
        [grid_before, grid_after],
        [f'Iter {iteration}: Before drops', f'Iter {iteration}: After drops']
    ):
        ax.imshow(grid, cmap=_CMAP, norm=_NORM,
                  extent=[0, GRID_COLS, GRID_ROWS, 0])
        ax.set_title(title, fontsize=11)
        ax.set_xlabel('Column')
        ax.set_ylabel('Row')

        # Fixed landmarks
        ax.plot(AIRFIELD_CELL[1] + 0.5, AIRFIELD_CELL[0] + 0.5,
                's', color='navy', markersize=10, label='Airfield')
        for (wr, wc) in WATER_CELLS:
            ax.plot(wc + 0.5, wr + 0.5,
                    '^', color='dodgerblue', markersize=9, label='Water')

    # Overlay drop locations on the RIGHT panel
    ax_right = axes[1]
    for (ac_id, ac_type, abs_t, r, c) in drop_schedule:
        colour = 'blue' if ac_type == 'tanker' else 'purple'
        ax_right.plot(c + 0.5, r + 0.5, 'x', color=colour,
                      markersize=8, markeredgewidth=2)

    # Overlay routes on RIGHT panel (one colour per aircraft)
    colours = plt.cm.tab10.colors
    for idx, (ac_id, steps) in enumerate(routes.items()):
        if not steps:
            continue
        col = colours[idx % len(colours)]
        rows_t = [s[1] + 0.5 for s in steps]
        cols_t = [s[2] + 0.5 for s in steps]
        ax_right.plot(cols_t, rows_t, '-', color=col, alpha=0.4, linewidth=1)
        ax_right.plot(cols_t[0], rows_t[0], 'o', color=col, markersize=5,
                      label=ac_id)

    # Legend and wind annotation
    legend_patches = [
        mpatches.Patch(color='#d4e6b5', label='Unburned'),
        mpatches.Patch(color='#e74c3c', label='Burning'),
        mpatches.Patch(color='#95a5a6', label='Extinguished'),
        mpatches.Patch(color='navy',    label='Airfield'),
        mpatches.Patch(color='dodgerblue', label='Water'),
        mpatches.Patch(color='blue',    label='Tanker drop'),
        mpatches.Patch(color='purple',  label='Scooper drop'),
    ]
    axes[1].legend(handles=legend_patches, loc='upper right',
                   fontsize=7, framealpha=0.8)

    wind_str = (f"Wind: {wind['speed_kph']:.1f} km/h "
                f"@ {wind['dir_deg']:.0f}°")
    fig.suptitle(wind_str, fontsize=10, y=1.01)

    out_path = os.path.join(output_dir, f'iter_{iteration:03d}_grid.png')
    os.makedirs(output_dir, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close(fig)


# ---------------------------------------------------------------------------
# 2. Summary time-series plot (called after the full run finishes)
# ---------------------------------------------------------------------------
def plot_summary(log_dir: str, output_dir: str = OUTPUT_DIR) -> None:
    """
    Load all iter_NNN.json log files and produce:
      - Burning cells vs iteration (before and after drops)
      - Number of drops per iteration
      - Optimiser gap per iteration
    """
    records = []
    for fname in sorted(os.listdir(log_dir)):
        if fname.startswith('iter_') and fname.endswith('.json'):
            with open(os.path.join(log_dir, fname)) as f:
                records.append(json.load(f))

    if not records:
        return

    iters         = [r['iteration']                     for r in records]
    burn_before   = [r['stats_before']['burning']        for r in records]
    burn_after    = [r['stats_after']['burning']         for r in records]
    ext_after     = [r['stats_after']['extinguished']    for r in records]
    n_drops       = [r['n_drops']                        for r in records]
    gaps          = [r['opt_gap'] if r['opt_gap'] is not None else np.nan
                     for r in records]

    fig, axes = plt.subplots(3, 1, figsize=(10, 10), sharex=True)

    # Panel 1: fire spread
    axes[0].plot(iters, burn_before,  'r-o', label='Burning (before drops)', linewidth=2)
    axes[0].plot(iters, burn_after,   'r--s', label='Burning (after drops)')
    axes[0].plot(iters, ext_after,    'grey', linestyle='--', label='Extinguished')
    axes[0].set_ylabel('Number of cells')
    axes[0].set_title('Fire state evolution')
    axes[0].legend(fontsize=8)
    axes[0].grid(True, alpha=0.3)

    # Panel 2: drops per iteration
    axes[1].bar(iters, n_drops, color='steelblue', alpha=0.8)
    axes[1].set_ylabel('Water drops')
    axes[1].set_title('Drops per iteration')
    axes[1].grid(True, alpha=0.3, axis='y')

    # Panel 3: optimiser gap
    axes[2].plot(iters, [g * 100 if not np.isnan(g) else np.nan for g in gaps],
                 'g-^', linewidth=2)
    axes[2].axhline(y=0, color='k', linewidth=0.5)
    axes[2].set_ylabel('MIP gap [%]')
    axes[2].set_xlabel('Iteration')
    axes[2].set_title('Gurobi optimality gap')
    axes[2].grid(True, alpha=0.3)

    fig.tight_layout()
    out = os.path.join(output_dir, 'summary.png')
    fig.savefig(out, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"[visualise] Summary saved → {out}")


# ---------------------------------------------------------------------------
# 3. Animate all grid snapshots into a GIF (optional, requires Pillow)
# ---------------------------------------------------------------------------
def animate_run(output_dir: str = OUTPUT_DIR, fps: int = 2) -> None:
    """
    Stitch all iter_NNN_grid.png files into a single animated GIF.
    Requires Pillow: pip install Pillow
    """
    try:
        from PIL import Image
    except ImportError:
        print("[visualise] Pillow not installed — skipping animation.")
        return

    frames = []
    for fname in sorted(os.listdir(output_dir)):
        if fname.endswith('_grid.png'):
            frames.append(Image.open(os.path.join(output_dir, fname)))

    if not frames:
        return

    gif_path = os.path.join(output_dir, 'simulation.gif')
    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=int(1000 / fps),
        loop=0,
    )
    print(f"[visualise] Animation saved → {gif_path}")
