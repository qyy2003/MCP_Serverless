"""Figures for the mid-term presentation that no campaign script draws.

The numbers are medians copied from the campaign write-ups, which name the raw data:
  docs/aws-results.md                     AWS Lambda, 2026-11-18 (E1, E2, E5)
  docs/gcp-tables-2026-11-20.md           GCP Cloud Run, 2026-11-20 (branch max/local-sdk-gcp)

Usage: python analysis/midterm_figures.py [out_dir]   (default docs/figures/midterm; needs matplotlib)
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
BLUE, ORANGE, GREEN = "#2a78d6", "#eb6834", "#1baf7a"
BLUE_RAMP = ["#86b6ef", "#2a78d6", "#184f95"]  # ordinal steps 250 / 450 / 600: light = less memory

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": "sans-serif", "font.size": 11, "text.color": INK, "axes.labelcolor": INK2,
    "axes.edgecolor": AXIS, "axes.linewidth": 0.8, "xtick.color": MUTED, "ytick.color": MUTED,
    "xtick.labelcolor": INK2, "ytick.labelcolor": INK2, "axes.titlesize": 12, "axes.titleweight": "bold",
    "axes.titlecolor": INK, "axes.titlelocation": "left", "legend.frameon": False,
    "axes.spines.top": False, "axes.spines.right": False,
})


def _grid(ax, axis="y"):
    ax.grid(axis=axis, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


# E1, warm calls, p50 ms: (tier, tool, MCP tools/call, plain invocation)
AWS_E1 = [("128 MB", "no-op", 19.7, 19.7), ("128 MB", "dynamic-html", 24.4, 22.6),
          ("512 MB", "no-op", 14.3, 11.2), ("512 MB", "dynamic-html", 16.3, 14.7),
          ("1769 MB", "no-op", 12.0, 13.8), ("1769 MB", "dynamic-html", 15.3, 14.3)]
GCP_E1 = [("128 MB", "no-op", 16.2, 16.7), ("128 MB", "dynamic-html", 89.4, 90.2),
          ("512 MB", "no-op", 10.4, 10.7), ("512 MB", "dynamic-html", 12.4, 12.7),
          ("2048 MB", "no-op", 11.1, 10.8), ("2048 MB", "dynamic-html", 13.3, 13.5)]


def mcp_vs_plain(path):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), sharey=True)
    width = 0.38
    for ax, rows, title in [(axes[0], AWS_E1, "AWS Lambda (eu-north-1)"),
                            (axes[1], GCP_E1, "GCP Cloud Run (europe-west1)")]:
        xs = [i + (i // 2) * 0.6 for i in range(len(rows))]  # a gap between memory sizes
        for k, (x, (tier, tool, mcp, plain)) in enumerate(zip(xs, rows)):
            ax.bar(x - width / 2, mcp, width, color=BLUE, edgecolor=SURFACE, linewidth=1.5,
                   label="MCP tools/call" if k == 0 else None)
            ax.bar(x + width / 2, plain, width, color=ORANGE, edgecolor=SURFACE, linewidth=1.5,
                   label="plain invocation" if k == 0 else None)
            ax.text(x, max(mcp, plain) + 2, f"{mcp - plain:+.1f}", ha="center", va="bottom",
                    fontsize=10, color=INK2)
        ax.set_xticks(xs, ["no-op" if tool == "no-op" else "dynamic-\nhtml" for _, tool, _, _ in rows], fontsize=10)
        for i in range(0, len(rows), 2):
            ax.text((xs[i] + xs[i + 1]) / 2, -0.17, rows[i][0], transform=ax.get_xaxis_transform(),
                    ha="center", va="top", fontsize=11, color=INK, fontweight="bold")
        ax.set_title(title, pad=12)
        ax.tick_params(axis="x", length=0)
        _grid(ax)
    axes[1].annotate("CPU-throttled at 0.083 vCPU,\nwith and without MCP", xy=(xs[1] + 0.25, 80), xytext=(xs[3] - 0.2, 72),
                     fontsize=9.5, color=INK2, arrowprops={"arrowstyle": "-", "color": MUTED, "linewidth": 0.8})
    axes[0].set_ylabel("warm call, median (ms)")
    axes[0].set_ylim(0, 100)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, bbox_to_anchor=(0.5, 1.0), fontsize=11.5)
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


# E5, $ per million warm calls of 610.api-proxy, by upstream delay (ms)
DELAYS = [50, 200, 1000]
COST = {"Lambda, 1769 MB": [1.75, 6.10, 29.14], "Lambda, 512 MB": [0.66, 1.92, 8.58],
        "Lambda, 128 MB": [0.32, 0.63, 2.30], "CPU-time billing": [0.31, 0.32, 0.32]}


def billing(path):
    fig, ax = plt.subplots(figsize=(10, 4.4))
    colors = {"Lambda, 1769 MB": BLUE_RAMP[2], "Lambda, 512 MB": BLUE_RAMP[1],
              "Lambda, 128 MB": BLUE_RAMP[0], "CPU-time billing": ORANGE}
    for name, vals in COST.items():
        ax.plot(DELAYS, vals, color=colors[name], linewidth=2.2, marker="o", markersize=8,
                markeredgecolor=SURFACE, markeredgewidth=1.5, label=name, zorder=3)
        ax.text(DELAYS[-1] + 25, vals[-1], f"{name}  ${vals[-1]:.2f}", va="center", fontsize=11, color=INK)
    ax.set_xlim(0, 1380)
    ax.set_ylim(0, 32)
    ax.set_xticks(DELAYS, [f"{d} ms" for d in DELAYS])
    ax.set_yticks(range(0, 31, 5), [f"${v}" for v in range(0, 31, 5)])
    ax.set_xlabel("upstream API latency (the tool waits, using < 1 ms of CPU)")
    ax.set_ylabel("$ per million warm calls")
    _grid(ax)
    ax.spines["bottom"].set_bounds(0, 1000)
    ax.legend(loc="upper left", fontsize=10.5)
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


# E2, no-op (010.sleep), plain invocation: time to first result after a cold start, p50 ms
TIERS = ["~0.08 vCPU\nLambda 128 MB · Cloud Run 128 MB", "~0.3 vCPU\nLambda 512 MB · Cloud Run 512 MB",
         "1 vCPU\nLambda 1769 MB · Cloud Run 2048 MB"]
COLD = {"AWS Lambda": [217, 197, 208], "Cloud Run, startup boost on (default)": [885, 791, 1378],
        "Cloud Run, startup boost off": [9431, 2125, 1538]}


def aws_vs_gcp(path):
    fig, ax = plt.subplots(figsize=(10, 4.4))
    width = 0.26
    for k, ((name, vals), color) in enumerate(zip(COLD.items(), [BLUE, ORANGE, GREEN])):
        xs = [i + (k - 1) * width for i in range(len(TIERS))]
        ax.bar(xs, [v / 1000 for v in vals], width, color=color, edgecolor=SURFACE, linewidth=1.5, label=name)
        for x, v in zip(xs, vals):
            ax.text(x, v / 1000 + 0.12, f"{v / 1000:.1f} s", ha="center", va="bottom", fontsize=10.5, color=INK)
    ax.set_xticks(range(len(TIERS)), TIERS, fontsize=10.5)
    ax.tick_params(axis="x", length=0)
    ax.set_ylim(0, 10.5)
    ax.set_ylabel("cold start of a no-op tool,\ntime to first result (s)")
    _grid(ax)
    ax.legend(loc="upper right", fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/figures/midterm")
    out.mkdir(parents=True, exist_ok=True)
    mcp_vs_plain(out / "mcp-vs-plain.png")
    billing(out / "billing-wait.png")
    aws_vs_gcp(out / "aws-vs-gcp-cold-start.png")
    print("\n".join(str(p) for p in sorted(out.glob("*.png"))))
