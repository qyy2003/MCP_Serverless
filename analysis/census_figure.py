#!/usr/bin/env python3
"""Census figure: MCP servers per workload class, each bar split by where a call's time goes.

    serverless-benchmarks/.venv/bin/python analysis/census_figure.py [--out docs/figures/census]

Reads data/server-census/*.json (the same records as analysis/server_census.py) and writes
classes-by-cost.png/.svg. Bars are labeled with the benchmark that covers the class.
"""
import argparse
import collections
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from aws_results import GRID, INK, INK2, MUTED, SERIES, SURFACE, plt  # noqa: E402
from server_census import load  # noqa: E402

LABEL = {
    "api_wrapper": "API wrapper", "local_compute": "Local compute", "search_fetch": "Search / fetch",
    "local_data": "Local data", "filesystem_git": "Filesystem / git", "browser": "Browser",
    "memory_rag": "Memory / RAG", "code_exec": "Code execution", "desktop_app": "Desktop app",
    "database": "Database", "other": "Other",
}
# Fixed categorical order (validated: scripts/validate_palette.js of the dataviz method, light mode, all pass).
COSTS = [("network_wait", "waits on the network", SERIES[0]), ("cpu", "CPU", SERIES[1]),
         ("mixed", "mixed", SERIES[2]), ("local_io", "local I/O", SERIES[3])]
COVERED = {"api_wrapper": "610.api-proxy", "search_fetch": "620.fetch-markdown",
           "local_compute": "630.data-analysis (heavy startup)"}


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--data", default=os.path.join(ROOT, "data", "server-census"))
    p.add_argument("--out", default=os.path.join(ROOT, "docs", "figures", "census"))
    a = p.parse_args()
    records = load(a.data)
    n = len(records)
    by_class = collections.Counter(r["category"] for r in records)
    cost = collections.Counter((r["category"], r.get("dominant_cost")) for r in records)
    classes = sorted((c for c in by_class if c != "other"), key=lambda c: -by_class[c]) + ["other"]
    classes = classes[::-1]  # largest at the top

    fig, ax = plt.subplots(figsize=(7.6, 3.9))
    y = range(len(classes))
    left = [0] * len(classes)
    for key, label, color in COSTS:
        widths = [cost[(c, key)] for c in classes]
        # 2px surface gap between adjacent segments (edge in the surface color).
        ax.barh(y, widths, left=left, height=0.62, color=color, label=label, edgecolor=SURFACE, linewidth=1.5)
        left = [l + w for l, w in zip(left, widths)]
    for i, c in enumerate(classes):
        text = f"{by_class[c]}  ({100 * by_class[c] / n:.0f}%)"
        ax.text(by_class[c] + 0.8, i, text, va="center", fontsize=8.5, color=INK)
        if c in COVERED:
            ax.text(by_class[c] + 9.5, i, f"→ {COVERED[c]}", va="center", fontsize=8.5, color=INK2, weight="bold")
    ax.set_yticks(list(y), [LABEL.get(c, c) for c in classes])
    ax.tick_params(axis="y", length=0)
    ax.set_xlim(0, 84)
    ax.set_xlabel("MCP servers")
    ax.xaxis.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    nw = sum(v for (c, k), v in cost.items() if k == "network_wait")
    ax.set_title(f"What MCP tools do: {n} servers from MCP-Bench, MCP-Universe and LiveMCPBench", pad=20)
    ax.text(0, 1.02, f"{100 * by_class['api_wrapper'] / n:.0f}% wrap a remote API; "
            f"{100 * nw / n:.0f}% spend most of a call waiting on the network",
            transform=ax.transAxes, fontsize=8.5, color=INK2, va="bottom")
    ax.legend(title="most of a call's time", loc="lower right", fontsize=8, title_fontsize=8,
              labelcolor=INK2)
    ax.get_legend().get_title().set_color(MUTED)
    fig.tight_layout()
    os.makedirs(a.out, exist_ok=True)
    for ext in ("png", "svg"):
        fig.savefig(os.path.join(a.out, f"classes-by-cost.{ext}"), dpi=200, bbox_inches="tight")
    print(f"wrote {a.out}/classes-by-cost.png")


if __name__ == "__main__":
    main()
