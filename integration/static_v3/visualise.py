"""Plots use the validated replay, including all aircraft route boundaries."""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm


def plot_result(scenario, replay, result, path):
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), constrained_layout=True)
    cmap = ListedColormap(["#d4e6b5", "#e74c3c", "#95a5a6"])
    norm = BoundaryNorm([-.5, .5, 1.5, 2.5], cmap.N)
    for ax, grid, title in zip(axes, [scenario.grid, replay["states"][-1]],
                                ["Initial fixed fire", "Validated final state"]):
        ax.imshow(grid, cmap=cmap, norm=norm, interpolation="nearest")
        r, c = scenario.settings.airfield
        ax.plot(c, r, "s", color="navy", label="Airfield")
        for i, (r, c) in enumerate(scenario.settings.water_cells):
            ax.plot(c, r, "^", color="dodgerblue", label="Water" if i == 0 else None)
        ax.set(title=title, xlabel="Column", ylabel="Row")
    for name, route in result["routes"].items():
        axes[1].plot([p["col"] for p in route], [p["row"] for p in route],
                     "-", linewidth=1, alpha=.65, label=name)
    for action in result["actions"]:
        if action["kind"] == "drop":
            axes[1].plot(action["col"], action["row"], "x", color="blue")
    axes[1].legend(fontsize=7)
    fig.suptitle(f"{result['status']} | burn: {result['burn_cell_steps']} cell-steps | "
                 f"travel: {result['flight_distance_m']:.0f} m (Manhattan)")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)
