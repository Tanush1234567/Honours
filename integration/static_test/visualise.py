# =============================================================================
# visualise.py  (static_test — single-shot version, no rolling loop)
# Produces:
#   1. Two-panel grid snapshot (before / after drops)
#   2. Summary text printed to console
# =============================================================================

import os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import ListedColormap, BoundaryNorm

from config.config import (
    GRID_ROWS, GRID_COLS, CELL_SIZE_M,
    STATE_UNBURNED, STATE_BURNING, STATE_EXTINGUISHED,
    AIRFIELD_CELL, WATER_CELLS,
    OUTPUT_DIR,
)

_CMAP  = ListedColormap(['#d4e6b5', '#e74c3c', '#95a5a6'])
_NORM  = BoundaryNorm([-0.5, 0.5, 1.5, 2.5], _CMAP.N)


def plot_result(
    grid_before: np.ndarray,
    grid_after: np.ndarray,
    drop_schedule: list,
    routes: dict,
    output_dir: str = OUTPUT_DIR,
) -> None:
    """
    Save a two-panel figure:
      Left  — fire state as read from the ignition shapefile (input to Gurobi)
      Right — fire state after drops applied (updated landscape)
    """
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    for ax, grid, title in zip(
        axes,
        [grid_before, grid_after],
        ['Before drops (MILP input)', 'After drops (updated landscape)']
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

    # Overlay drops on right panel
    ax_right = axes[1]
    for (ac_id, ac_type, abs_t, r, c) in drop_schedule:
        colour = 'blue' if ac_type == 'tanker' else 'purple'
        ax_right.plot(c + 0.5, r + 0.5, 'x', color=colour,
                      markersize=8, markeredgewidth=2)

    # Overlay routes on right panel
    colours = plt.cm.tab10.colors
    for idx, (ac_id, steps) in enumerate(routes.items()):
        if not steps:
            continue
        col = colours[idx % len(colours)]
        rows_t = [s[1] + 0.5 for s in steps]
        cols_t = [s[2] + 0.5 for s in steps]
        ax_right.plot(cols_t, rows_t, '-', color=col, alpha=0.5, linewidth=1)
        ax_right.plot(cols_t[0], rows_t[0], 'o', color=col, markersize=5,
                      label=ac_id)

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

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, 'static_result.png')
    fig.tight_layout()
    fig.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close(fig)
    print(f"[visualise] Plot saved → {out_path}")
