"""Plot the held-out ablation curve and the prequential rolling accuracy."""

from __future__ import annotations

from pathlib import Path


def plot_curve(
    series: dict[str, list[dict]],
    baselines: dict[str, dict],
    path: Path,
    prequential: list[dict] | None = None,
    window: int = 100,
    frozen_online: list[dict] | None = None,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from repocortex.learn.replay import rolling_mean

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 2, figsize=(11.2, 8.0))
    styles = {
        "learning off": ("#7f8c8d", "--"),
        "reweight": ("#b9770e", "-"),
        "+shortcuts": ("#1e8449", "-"),
        "+gap": ("#6c3483", "-"),
        "full": ("#1b4f72", "-"),
    }
    holdout_panels = (
        (axes[0, 0], "function_acc@10", "held-out function Acc@10"),
        (axes[0, 1], "mrr", "held-out MRR"),
    )
    collected = []
    for name, curve in series.items():
        for row in curve:
            collected.append(row.get("function_acc@10"))
            collected.append(row.get("mrr"))
    for name in ("bm25", "dense"):
        for key in ("function_acc@10", "mrr"):
            value = baselines.get(name, {}).get(key)
            if value is not None:
                collected.append(value)
    finite = [value for value in collected if isinstance(value, (int, float))]
    ymin = max(0.0, (min(finite) - 0.05) if finite else 0.0)
    ymax = min(1.0, (max(finite) + 0.05) if finite else 1.0)
    if ymax - ymin < 0.2:
        mid = (ymin + ymax) / 2
        ymin = max(0.0, mid - 0.1)
        ymax = min(1.0, mid + 0.1)

    for ax, key, ylabel in holdout_panels:
        for name, curve in series.items():
            if not curve:
                continue
            color, linestyle = styles.get(name, ("#1b4f72", "-"))
            steps = [row["step"] for row in curve]
            values = [row[key] for row in curve]
            ax.plot(steps, values, color=color, linestyle=linestyle, linewidth=2, label=name)
            if name == "full" and curve and isinstance(curve[0].get("ci"), dict):
                lo = [row.get("ci", {}).get(key, {}).get("lo") for row in curve]
                hi = [row.get("ci", {}).get(key, {}).get("hi") for row in curve]
                if all(isinstance(item, (int, float)) for item in lo + hi):
                    ax.fill_between(steps, lo, hi, color=color, alpha=0.15, linewidth=0)
        steps = []
        for curve in series.values():
            if curve:
                steps = [row["step"] for row in curve]
                break
        if steps:
            for name, color in (("bm25", "#1a5276"), ("dense", "#922b21"), ("frozen", "#7f8c8d")):
                value = baselines.get(name, {}).get(key)
                if value is None:
                    continue
                # learning off is already the frozen series, so skip a second copy of that line
                if name == "frozen" and "learning off" in series:
                    continue
                ax.plot(steps, [value] * len(steps), linestyle=":", color=color, linewidth=1.5, label=name)
        ax.set_xlabel("train issues replayed")
        ax.set_ylabel(ylabel)
        ax.set_ylim(ymin, ymax)
        ax.grid(True, axis="y", alpha=0.3)
        ax.legend(frameon=False, fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=4)
    _plot_online(
        axes[1, 0], prequential or [], frozen_online or [], "function_acc@10",
        "expanding-window Acc@10", window, rolling_mean,
    )
    _plot_online(
        axes[1, 1], prequential or [], frozen_online or [], "mrr",
        "expanding-window MRR", window, rolling_mean,
    )
    fig.suptitle("RepoCortex learning curve")
    fig.tight_layout(rect=(0, 0.02, 1, 0.98), h_pad=2.4)
    fig.savefig(path, dpi=140)
    plt.close(fig)


def _plot_online(ax, rows, frozen_rows, key, ylabel, window, rolling_mean) -> None:
    if not rows:
        ax.set_ylabel(ylabel)
        ax.text(0.5, 0.5, "no prequential scores", ha="center", va="center", transform=ax.transAxes)
        return
    # Expanding mean of the first handful of issues is one outcome, not a trend.
    start = min(len(rows) - 1, 19)
    values = [float(row[key]) for row in rows]
    cumulative = rolling_mean(values, len(values))
    rolled = rolling_mean(values, window)
    indexes = [row["index"] for row in rows]
    ax.plot(indexes[start:], cumulative[start:], color="#1b4f72", linewidth=2.2, label="expanding mean")
    ax.plot(indexes[start:], rolled[start:], color="#1b4f72", linewidth=1, alpha=0.45, label=f"rolling {window}")
    if frozen_rows:
        frozen_values = [float(row[key]) for row in frozen_rows]
        frozen_cum = rolling_mean(frozen_values, len(frozen_values))
        frozen_x = [row["index"] for row in frozen_rows]
        offset = min(start, len(frozen_rows) - 1)
        ax.plot(
            frozen_x[offset:], frozen_cum[offset:], color="#7f8c8d", linewidth=1.6,
            linestyle="--", label="frozen expanding mean",
        )
        band = cumulative[start:] + frozen_cum[offset:]
    else:
        band = cumulative[start:]
    ax.set_xlabel("train issues seen")
    ax.set_ylabel(ylabel)
    low = min(band)
    high = max(band)
    pad = max(0.015, (high - low) * 0.35)
    ax.set_ylim(max(0.0, low - pad), min(1.0, high + pad))
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(frameon=False, fontsize=8)
