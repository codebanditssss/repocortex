"""Plot the held-out curve."""

from __future__ import annotations

from pathlib import Path


def plot_curve(curve: list[dict], baselines: dict[str, dict], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8.2, 4.6))
    steps = [row["step"] for row in curve]
    ax.plot(
        steps,
        [row["function_acc@10"] for row in curve],
        marker="o",
        linewidth=2,
        label="repocortex (reweight)",
    )
    if steps:
        for name, style in (("bm25", "--"), ("dense", "--"), ("frozen", ":")):
            value = baselines.get(name, {}).get("function_acc@10")
            if value is None:
                continue
            ax.plot(steps, [value] * len(steps), linestyle=style, label=name)
    ax.set_xlabel("train issues replayed")
    ax.set_ylabel("held-out function Acc@10")
    ax.set_title("RepoCortex held-out localization")
    ax.set_ylim(0, 1)
    ax.legend(frameon=False)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
