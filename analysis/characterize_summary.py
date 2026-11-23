"""Tables and figures for the gap comparison: SeBS benchmarks vs MCP tools on the same axes.

    serverless-benchmarks/.venv/bin/python analysis/characterize_summary.py \
        results/local/characterize --figures docs/figures/local --title-suffix "local"

Per configuration (medians over warm calls unless noted):
  exec_ms       function-side execution time
  cpu_ms        CPU time of the function process plus finished child processes
  wait_share    1 - cpu / exec: share of the call not spent computing (waiting on I/O or network)
  net_kb        bytes the function container sent and received, minus the invocation's own HTTP bodies
  cold_ms       client time of a call right after a forced cold start (median of cold samples)
  cold_ratio    (cold_ms - warm client time) / warm exec time: cold penalty relative to the work.
                Unreliable for CPU-heavy configs on a laptop: CPU clock changes between samples
                exceed the penalty, so it can come out negative (220, 311).
  import_ms     time to import the benchmark module on a cold start; for the SDK variant, importing
                its MCP server (and the SDK) at instance startup (init_import_us)
  import_ratio  import_ms / warm exec time: process-level cold cost relative to the work, measured
                directly, so robust against that noise (used for the cold-start figure)
  package_mb    code package size
"""

import argparse
import glob
import json
import os

import numpy as np
import pandas as pd
import matplotlib
import matplotlib.ticker
import matplotlib.transforms

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# Same light-mode reference palette and rcParams as analysis/aws_results.py.
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834"]  # fixed order: SeBS, MCP tools (validated: all checks pass)
# group: (color, marker, filled). The SDK variant is the same tools, so the same hue; hollow tells it apart.
GROUPS = {
    "SeBS benchmarks": (SERIES[0], "o", True),
    "MCP tools, without SDK (ours)": (SERIES[1], "^", True),
    "MCP tools, official SDK (ours)": (SERIES[1], "^", False),
}

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": "sans-serif", "font.size": 9, "text.color": INK, "axes.labelcolor": INK2,
    "axes.edgecolor": AXIS, "axes.linewidth": 0.8, "xtick.color": MUTED, "ytick.color": MUTED,
    "xtick.labelcolor": INK2, "ytick.labelcolor": INK2, "axes.titlesize": 10, "axes.titleweight": "bold",
    "axes.titlecolor": INK, "axes.titlelocation": "left", "legend.frameon": False,
    "axes.spines.top": False, "axes.spines.right": False,
})


def load(run_dir):
    rows = []
    packages = json.load(open(os.path.join(run_dir, "packages.json")))
    for path in sorted(glob.glob(os.path.join(run_dir, "*.jsonl"))):
        df = pd.DataFrame([json.loads(line) for line in open(path)])
        warm, cold = df[df.condition == "warm"], df[df.condition == "cold"]
        cpu = warm.cpu_us + warm.child_cpu_us.fillna(0)
        net = (warm.net_rx + warm.net_tx - warm.request_bytes - warm.response_bytes).clip(lower=0)
        exec_ms = warm.exec_us.median() / 1e3
        warm_client = warm.client_us.median() / 1e3
        cold_ms = cold.client_us.median() / 1e3 if len(cold) else np.nan
        benchmark = df.benchmark.iloc[0]
        variant = df.variant.iloc[0] if "variant" in df else "default"
        if not benchmark.startswith("6"):
            group = "SeBS benchmarks"
        else:
            group = "MCP tools, official SDK (ours)" if variant == "sdk" else "MCP tools, without SDK (ours)"
        # SDK variant: the server is imported at startup, not during the call
        imports = cold.init_import_us if "init_import_us" in cold and cold.init_import_us.notna().any() else cold.import_us
        package_key = benchmark + ("" if variant == "default" else f"@{variant}")
        rows.append({
            "config": df.config.iloc[0],
            "benchmark": benchmark,
            "variant": variant,
            "group": group,
            "exec_ms": exec_ms,
            "cpu_ms": cpu.median() / 1e3,
            "child_cpu_ms": warm.child_cpu_us.median() / 1e3,
            "wait_share": float(np.clip(1 - cpu.median() / warm.exec_us.median(), 0, 1)),
            "net_kb": net.median() / 1e3,
            "response_kb": warm.response_bytes.median() / 1e3,
            "cold_ms": cold_ms,
            "cold_ratio": (cold_ms - warm_client) / exec_ms if exec_ms > 0 else np.nan,
            "import_ms": imports.median() / 1e3 if len(cold) else np.nan,
            "import_ratio": imports.median() / warm.exec_us.median() if len(cold) else np.nan,
            "package_mb": packages.get(package_key, np.nan) / 1e6,
            "n_warm": len(warm), "n_cold": len(cold),
        })
    return pd.DataFrame(rows)


def short(config):
    """Compact point label: '411-small', '610 1000ms/64k', '620 SDK 10kB'."""
    parts = config.split("-")
    number = config.split(".")[0]
    sdk = " SDK" if "@sdk" in config else ""
    if number == "610":
        return f"610{sdk} {parts[-2].replace('lat', '')}ms/{parts[-1]}"
    if number in ("620", "630"):
        return f"{number}{sdk} {parts[-1]}"
    return f"{number}-{parts[-1]}"


def cluster_label(configs):
    """'504-test' + '504-small' -> '504'; different benchmarks joined: '502/503-test'."""
    by_number = {}
    for c in configs:
        label = short(c)
        if label.startswith(("610", "620", "630")):
            by_number.setdefault(label, set())
            continue
        number, size = label.split("-", 1)
        by_number.setdefault(number, set()).add(size)
    sizes = {frozenset(v) for v in by_number.values()}
    if len(by_number) > 1 and len(sizes) == 1 and len(next(iter(sizes))) == 1:
        return "/".join(by_number) + "-" + next(iter(next(iter(sizes))))  # all share one size
    return ", ".join(k if len(v) != 1 else f"{k}-{next(iter(v))}" for k, v in by_number.items())


# Label positions relative to the point, tried in order: right-above, left-above, right-below, left-below.
OFFSETS = [((4, 3), "left"), ((-4, 3), "right"), ((4, -9), "left"), ((-4, -9), "right")]
MERGE_PX = 30  # labels of points closer than this (screen pixels) are merged rather than moved apart
FALLBACK_MERGE_PX = 90  # ...and up to this far when the label fits nowhere else


def annotate(ax, df, x, y, label_all_sebs=True, label_sdk=False):
    """Direct labels: every SeBS point, MCP points only at the extremes of their sweep.

    1. Points of the same benchmark that sit close together share a label ('504' for test+small).
    2. Labels are placed in order; a label that would overlap one already placed moves to another side
       of its point, unless the two points are close, in which case the labels merge ('502/503-test').
    Labels stay inside the axes."""
    extremes = df.config.str.endswith(("lat50-4k", "lat1000-64k", "1000kB", "10kB", "1024k"))
    sdk = df.variant == "sdk"
    wanted = df[(df.group == "SeBS benchmarks") & label_all_sebs | extremes & (~sdk | label_sdk)]
    renderer = ax.figure.canvas.get_renderer()
    axes_box = ax.get_window_extent(renderer)
    to_px = ax.transData.transform
    clusters = []  # [screen xy, data xy, configs]
    for _, r in wanted.iterrows():
        sxy = to_px((r[x], r[y]))
        same = next((c for c in clusters if c[2][0].split("-")[0] == r.config.split("-")[0]
                     and not r.config.startswith("6") and np.hypot(*(c[0] - sxy)) < MERGE_PX), None)
        if same:
            same[2].append(r.config)
            same[0], same[1] = (same[0] + sxy) / 2, (same[1][0], max(same[1][1], r[y]))
        else:
            clusters.append([sxy, (r[x], r[y]), [r.config]])

    def fits(box, placed):
        inside = axes_box.x0 <= box.x0 and box.x1 <= axes_box.x1 and axes_box.y0 <= box.y0 and box.y1 <= axes_box.y1
        return inside and not any(box.overlaps(p[1]) for p in placed)

    while True:
        placed, merge = [], None  # placed: [cluster index, box, text]
        for i, (sxy, xy, configs) in enumerate(clusters):
            candidates = []
            for offset, ha in OFFSETS:
                text = ax.annotate(cluster_label(configs), xy, xytext=offset, textcoords="offset points",
                                   fontsize=7, color=INK2, ha=ha)
                box = text.get_window_extent(renderer).expanded(1.04, 1.15)
                candidates.append((text, box))
                hit = next((p for p in placed if box.overlaps(p[1])), None)
                if hit and np.hypot(*(clusters[hit[0]][0] - sxy)) < MERGE_PX:
                    merge = (hit[0], i)
                    break
                if fits(box, placed):
                    break
            else:  # nowhere free: merge with a nearby label it hits, else keep the first position inside the axes
                inside = [c for c in candidates if fits(c[1], [])] or candidates
                text, box = inside[0]
                hit = next((p for p in placed if box.overlaps(p[1])), None)
                if hit and np.hypot(*(clusters[hit[0]][0] - sxy)) < FALLBACK_MERGE_PX:
                    merge = (hit[0], i)
            for t, _ in candidates:
                if t is not text:
                    t.remove()
            placed.append((i, box, text))
            if merge:
                break
        if merge is None:
            return
        for _, _, t in placed:
            t.remove()
        j, i = merge  # the label already placed (j) takes in the other's points and keeps its position
        clusters[j][2] = clusters[j][2] + clusters[i][2]
        del clusters[i]


def scatter(df, x, y, xlabel, ylabel, title, path, logx=True, logy=False, label_all_sebs=True, label_sdk=False):
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for group, (color, marker, filled) in GROUPS.items():
        g = df[df.group == group]
        if g.empty:
            continue
        if filled:  # surface-colored ring separates overlapping markers
            ax.scatter(g[x], g[y], s=46, color=color, marker=marker, edgecolors=SURFACE, linewidths=1.2,
                       label=group, zorder=3)
        else:
            ax.scatter(g[x], g[y], s=46, facecolors=SURFACE, marker=marker, edgecolors=color, linewidths=1.4,
                       label=group, zorder=4)
    plain = matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}")
    if logx:
        ax.set_xscale("log")
        ax.xaxis.set_major_formatter(plain)
    if logy:
        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(plain)
    if y == "wait_share":  # a share: show the full 0–100% range, not an auto-zoomed band
        ax.set_ylim(0, 1.04)
        ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    fig.canvas.draw()  # fix scales and limits before measuring label boxes
    annotate(ax, df, x, y, label_all_sebs, label_sdk)
    ax.legend(loc="best", fontsize=8)
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("run_dir")
    parser.add_argument("--figures", help="directory for PNG figures")
    parser.add_argument("--title-suffix", default="")
    args = parser.parse_args()

    df = load(args.run_dir).sort_values(["group", "config"])
    suffix = f" ({args.title_suffix})" if args.title_suffix else ""

    cols = ["config", "exec_ms", "cpu_ms", "wait_share", "net_kb", "cold_ms", "cold_ratio", "import_ms", "import_ratio",
            "package_mb"]
    out = df[cols].copy()
    out["wait_share"] = (out.wait_share * 100).map(lambda v: f"{v:.0f}%")
    print(out.to_markdown(index=False, floatfmt=(None, ".1f", ".1f", None, ".1f", ".1f", ".2f", ".1f", ".3f", ".3f")))
    failed = sorted(os.path.basename(p)[:-7] for p in glob.glob(os.path.join(args.run_dir, "*.failed")))
    if failed:
        print("\nFailed configurations: " + ", ".join(failed))

    if args.figures:
        os.makedirs(args.figures, exist_ok=True)
        scatter(df, "exec_ms", "wait_share", "warm execution time (ms, log)", "share of time not computing",
                f"Execution time vs. waiting{suffix}", os.path.join(args.figures, "gap-wait.png"))
        scatter(df.assign(net_kb=df.net_kb.clip(lower=0.1), cpu_ms=df.cpu_ms.clip(lower=0.1)),
                "cpu_ms", "net_kb", "CPU time per call (ms, log)", "network traffic per call (kB, log)",
                f"Work done per call{suffix}", os.path.join(args.figures, "gap-work.png"), logy=True)
        scatter(df, "package_mb", "import_ratio", "code package (MB, log)", "cold import time / warm execution time (log)",
                f"Cold start relative to the work{suffix}", os.path.join(args.figures, "gap-cold.png"), logy=True,
                label_sdk=True)
        df.to_csv(os.path.join(args.figures, "gap-data.csv"), index=False)


if __name__ == "__main__":
    main()
