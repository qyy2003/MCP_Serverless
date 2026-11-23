#!/usr/bin/env python3
"""Real MCP servers vs the SeBS catalog and our tool benchmarks: size, startup, memory.

    serverless-benchmarks/.venv/bin/python analysis/real_servers.py [--figures docs/figures/real-servers]

Reads results/real-servers/*.json (experiments/real_servers/run.py) and docs/figures/local/gap-data.csv (SeBS
benchmarks and our tools, measured by experiments/characterize.py on the same laptop). Writes
results/real-servers/summary.md and figures.

Comparable quantities:
- size: installed server with all dependencies (venv or node_modules) vs SeBS's code directory (code + its
  installed requirements). Neither includes the language runtime.
- startup: time from process start to the tools/list response minus a bare interpreter start (`python3 -c pass`,
  `node -e 0`), i.e. importing and initialising the server, vs SeBS's import time of the benchmark module (cold,
  in-process; for our SDK variant, importing the MCP server and SDK at startup).
Real servers: median of runs 2..N (run 1 follows the install directly). 1 CPU (docker --cpus=1).
"""
import argparse
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from aws_results import INK2, MUTED, SERIES, SURFACE, md_table, plt, style_axis  # noqa: E402


def load_real():
    rows = []
    for path in sorted(glob.glob(os.path.join(ROOT, "results", "real-servers", "*.json"))):
        r = json.load(open(path))
        s = r["spec"]
        ok = [x for x in r.get("runs", []) if "error" not in x]
        later = ok[1:] if len(ok) > 1 else ok
        err = r.get("error") or next((x["error"] for x in r.get("runs", []) if "error" in x), None)
        rows.append({"server": s["name"], "language": s["language"], "category": s["category"],
                     "version": r.get("version"), "installed_mb": r.get("installed_mb"),
                     "dependencies": r.get("n_dependencies"), "ok_runs": f"{len(ok)}/{len(r.get('runs', []))}",
                     "startup_ms": np.median([x["tools_list_ms"] for x in later]) if later else np.nan,
                     "baseline_ms": r.get("baseline_ms"),
                     "first_run_ms": ok[0]["tools_list_ms"] if ok else np.nan,
                     "peak_rss_mb": np.median([x["peak_rss_mb"] for x in later]) if later else np.nan,
                     "cpu_s": np.median([x["cpu_s"] for x in later]) if later else np.nan,
                     "tools": ok[0]["n_tools"] if ok else np.nan, "error": err if not ok else None})
    d = pd.DataFrame(rows)
    d["init_ms"] = d["startup_ms"] - d["baseline_ms"]
    return d


def load_catalog():
    g = pd.read_csv(os.path.join(ROOT, "docs", "figures", "local", "gap-data.csv"))
    g = g.groupby(["benchmark", "variant", "group"]).agg(installed_mb=("package_mb", "median"),
                                                          init_ms=("import_ms", "median")).reset_index()
    return g


def tables(d, cat, out):
    ok = d[d["error"].isna()]
    out.append("# Real MCP servers: size, startup and memory\n")
    out.append(f"{len(d)} servers from LiveMCPBench's server set (installable from PyPI/npm), measured in throwaway containers "
               "(Node 22, Debian's Python 3.11), 1 CPU, 2 GB; latest versions as of the run. *Startup*: process start → tools/list response "
               "over stdio, median of runs 2–7. *Init*: startup minus a bare interpreter start. *Peak RSS*: summed over the process tree.\n")
    cols = ["server", "language", "category", "version", "installed_mb", "dependencies", "startup_ms", "init_ms",
            "peak_rss_mb", "cpu_s", "tools", "ok_runs"]
    out.append(md_table(d.sort_values(["category", "installed_mb"])[cols].fillna("–"),
                        {"installed_mb": 1, "startup_ms": 0, "init_ms": 0, "peak_rss_mb": 0, "cpu_s": 2}) + "\n")
    failed = d[d["error"].notna()]
    if len(failed):
        out.append("\n**Failed:** " + "; ".join(f"{r.server}: {str(r.error)[:200]}" for r in failed.itertuples()) + "\n")

    def q(s):
        return f"{s.median():,.0f} ({s.quantile(.25):,.0f}–{s.quantile(.75):,.0f})"
    rows = []
    for lang, x in [("all", ok)] + list(ok.groupby("language")):
        rows.append({"servers": f"{lang} (n={len(x)})", "installed MB": q(x["installed_mb"]), "dependencies": q(x["dependencies"]),
                     "init ms": q(x["init_ms"]), "peak RSS MB": q(x["peak_rss_mb"]),
                     "fit in 128 MB": f"{int((x['peak_rss_mb'] < 128).sum())}/{len(x)}"})
    sebs = cat[cat["group"] == "SeBS benchmarks"]
    ours = cat[cat["group"] != "SeBS benchmarks"]
    for label, x in (("SeBS benchmarks (n=%d)" % len(sebs), sebs),):
        rows.append({"servers": label, "installed MB": q(x["installed_mb"]), "dependencies": "–",
                     "init ms": q(x["init_ms"]), "peak RSS MB": "–", "fit in 128 MB": "–"})
    for r in ours.itertuples():
        rows.append({"servers": f"ours: {r.benchmark} ({r.variant})", "installed MB": f"{r.installed_mb:,.2f}",
                     "dependencies": "–", "init ms": f"{r.init_ms:,.1f}", "peak RSS MB": "–", "fit in 128 MB": "–"})
    out.append("\n## Summary: median (p25–p75)\n")
    out.append(md_table(pd.DataFrame(rows)) + "\n")


def figure(d, cat, path):
    ok = d[d["error"].isna()]
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    sebs = cat[cat["group"] == "SeBS benchmarks"]
    ax.scatter(sebs["installed_mb"], sebs["init_ms"], s=36, color=SERIES[0], label="SeBS benchmarks", zorder=3,
               edgecolor=SURFACE, linewidth=1.2)
    for r in sebs.itertuples():
        ax.annotate(r.benchmark.split(".")[0], (r.installed_mb, r.init_ms), xytext=(4, 3), textcoords="offset points",
                    fontsize=6.5, color=MUTED)
    for lang, color in (("python", SERIES[2]), ("node", SERIES[3])):
        x = ok[ok["language"] == lang]
        ax.scatter(x["installed_mb"], x["init_ms"], s=34, marker="D", color=color, label=f"real MCP servers, {lang} ({len(x)})",
                   zorder=3, edgecolor=SURFACE, linewidth=1.2)
    labels = {"12306-mcp": (6, -3), "trends-hub": (6, -3), "basic-memory": (6, -10), "music-analysis": (6, 4),
              "yahoo-finance": (-30, 8), "mcp-deepwiki": (-30, 7)}
    for r in ok.itertuples():
        if r.server in labels:
            ax.annotate(r.server, (r.installed_mb, r.init_ms), xytext=labels[r.server], textcoords="offset points",
                        fontsize=6.5, color=INK2)
    for variant, marker, label in (("default", "^", "our MCP tools, without SDK"), ("sdk", "s", "our MCP tools, official SDK")):
        x = cat[(cat["group"] != "SeBS benchmarks") & (cat["variant"] == variant)]
        ax.scatter(x["installed_mb"], x["init_ms"], s=70, marker=marker, facecolor="none" if variant == "sdk" else SERIES[1],
                   edgecolor=SERIES[1], linewidth=1.8, label=label, zorder=5)
        for r in x.itertuples():
            if r.benchmark.startswith("630"):  # the heavy-startup tool (pandas); 610/620 overlap, labelled in the text
                ax.annotate("630" + (" SDK" if variant == "sdk" else ""), (r.installed_mb, r.init_ms),
                            xytext=(-12, 9) if variant == "default" else (9, -4), textcoords="offset points",
                            fontsize=7, color=SERIES[1], weight="bold")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("installed size incl. dependencies, MB (log)")
    ax.set_ylabel("cold import / init time at 1 vCPU, ms (log)")
    style_axis(ax, "both")
    ax.set_title("Real MCP servers start in 0.2–6 s at 1 vCPU; our SDK variants and 630 sit among them,\n"
                 "the stdlib-only 610/620 don't")
    ax.legend(fontsize=7.5, loc="upper left")
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--figures", default=os.path.join(ROOT, "docs", "figures", "real-servers"))
    args = a.parse_args()
    d, cat = load_real(), load_catalog()
    out = []
    tables(d, cat, out)
    os.makedirs(args.figures, exist_ok=True)
    figure(d, cat, os.path.join(args.figures, "size-vs-init.png"))
    with open(os.path.join(ROOT, "results", "real-servers", "summary.md"), "w") as f:
        f.write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
