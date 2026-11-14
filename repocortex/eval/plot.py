"""Plot the held-out curve."""

from __future__ import annotations

from pathlib import Path


def plot_curve(curve: list[dict], baselines: dict[str, dict], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(10.6, 4.4))
    steps = [row["step"] for row in curve]
    panels = (
        ("function_acc@10", "held-out function Acc@10"),
        ("mrr", "held-out MRR"),
    )
    for ax, (key, ylabel) in zip(axes, panels):
        ax.plot(
            steps,
            [row[key] for row in curve],
            marker="o",
            linewidth=2,
            label="repocortex",
        )
        if steps:
            for name, style in (("bm25", "--"), ("dense", "--"), ("frozen", ":")):
                value = baselines.get(name, {}).get(key)
                if value is None:
                    continue
                ax.plot(steps, [value] * len(steps), linestyle=style, label=name)
        ax.set_xlabel("train issues replayed")
        ax.set_ylabel(ylabel)
        ax.set_ylim(0.15, 0.7)
        ax.legend(frameon=False)
        ax.grid(True, axis="y", alpha=0.3)
    fig.suptitle("RepoCortex held-out localization")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
