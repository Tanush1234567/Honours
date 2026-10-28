"""Executed and forecast states are explicitly distinguished in figures."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from PIL import Image
import numpy as np

CMAP = ListedColormap(["#e7e3d7", "#e45635", "#4c98b6"])
NORM = BoundaryNorm([-0.5, 0.5, 1.5, 2.5], CMAP.N)


def plot_window(scenario, replay, result, commit, path, start, backend):
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), constrained_layout=True)
    for ax, state, title in zip(axes, (scenario.grid, replay["states"][commit], replay["states"][-1]),
                               (f"Observed at step {start}", f"Executed through {start + commit}",
                                f"Plan to {start + scenario.settings.horizon_steps} (forecast)")):
        ax.imshow(state, cmap=CMAP, norm=NORM, interpolation="nearest")
        ax.set_title(title)
        ax.set_xlabel("Column")
        ax.set_ylabel("Row")
    for name, route in result["routes"].items():
        axes[1].plot([p["col"] for p in route[:commit + 1]], [p["row"] for p in route[:commit + 1]],
                     ".-", label=name, linewidth=1)
    if result["routes"]:
        axes[1].legend(fontsize=7)
    fig.suptitle(f"{backend} | grey: unburned, red: burning, blue: extinguished", fontsize=10)
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_summary(result, output):
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    history = result["fire_history"]
    for key in ("burning", "extinguished"):
        axes[0].plot([h["step"] for h in history], [h[key] for h in history], label=key)
    axes[0].set_xlabel("Executed step")
    axes[0].set_ylabel("Cells")
    axes[0].legend()
    for name, route in result["routes"].items():
        axes[1].step([p["step"] for p in route], [p["water_l"] for p in route], where="post", label=name)
    axes[1].set_xlabel("Executed step")
    axes[1].set_ylabel("Carried water (L)")
    if result["routes"]:
        axes[1].legend()
    fig.suptitle(f"{result['backend']} | {result['status']}", fontsize=10)
    fig.savefig(output / "summary.png", dpi=140)
    plt.close(fig)
    frames = []
    with np.load(output / "execution.npz") as data:
        for grid in data["fire_states"]:
            rgb = (CMAP(grid)[..., :3] * 255).astype("uint8")
            frame = Image.fromarray(rgb).resize((max(300, grid.shape[1] * 5), max(150, grid.shape[0] * 5)),
                                                resample=Image.Resampling.NEAREST)
            frames.append(frame)
    if frames:
        frames[0].save(output / "simulation.gif", save_all=True, append_images=frames[1:], duration=500, loop=0)
