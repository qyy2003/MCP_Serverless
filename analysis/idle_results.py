#!/usr/bin/env python3
"""Tables and a figure for an idle-time run (experiments/idle_probe.py): cold-start probability vs idle time.

    serverless-benchmarks/.venv/bin/python analysis/idle_results.py results/idle/<run> [--figures docs/figures/idle]

Per probe: idle time before it, whether its first request ran in a fresh process (`is_cold`), whether it was
served by the same instance as the previous probe, and the first request's latency. If the run directory holds
Cloud Run logs (requests.jsonl, system.jsonl from experiments/gcp_logs.py), each probe's first request is also
joined to its instance and to how that instance was started: by this request (AUTOSCALING, started at most
`WINDOW` s before it), before it (pre-started or left over), or for a deployment (DEPLOYMENT_ROLLOUT).
"""
import argparse
import glob
import json
import os
import re
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "experiments"))
from aws_results import INK, MUTED, SERIES, SURFACE, md_table, plt, style_axis  # noqa: E402
from gcp_session_check import epoch  # noqa: E402

REASON = re.compile(r"Starting new instance\. Reason: (\w+)")
WINDOW = 1.0  # s: an instance started at most this long before a request counts as started by it


def load_probes(run):
    rows = []
    for path in sorted(glob.glob(os.path.join(run, "*.jsonl"))):
        if os.path.basename(path) in ("requests.jsonl", "system.jsonl"):
            continue
        recs = pd.read_json(path, lines=True)
        if recs.empty:
            continue
        for (target, probe), x in recs.groupby(["target", "probe"]):
            first = x.iloc[0]
            call = x[x["phase"].isin(["tools/call", "plain"])]
            rows.append({"target": target, "probe": probe, "idle_s": first.get("idle_s"),
                         "planned_gap_s": first.get("planned_gap_s"), "resumed": bool(first.get("resumed")),
                         "ts": first["ts"], "error": first.get("error") if first["phase"] == "error" else None,
                         "cold": bool(first.get("is_cold")) if first["phase"] != "error" else None,
                         "container": first.get("container_id"), "first_ms": first["client_us"] / 1000,
                         "session_ms": (x["client_us"].sum()) / 1000,
                         "call_ms": call["client_us"].iloc[0] / 1000 if len(call) else np.nan,
                         "trace_id": first.get("trace_id")})
    p = pd.DataFrame(rows).sort_values(["target", "probe"])
    p["prev_container"] = p.groupby("target")["container"].shift()
    p["same_instance"] = p["container"] == p["prev_container"]
    return p


def join_logs(p, run):
    rpath, spath = os.path.join(run, "requests.jsonl"), os.path.join(run, "system.jsonl")
    if not (os.path.exists(rpath) and os.path.exists(spath)):
        return p
    req = {}
    for line in open(rpath):
        r = json.loads(line)
        if r.get("trace_id"):
            req[r["trace_id"]] = (r["instance"], epoch(r["timestamp"]))
    starts = {}
    for line in open(spath):
        e = json.loads(line)
        m = REASON.search(e.get("text") or "")
        if m and e.get("instance"):
            starts[e["instance"]] = (epoch(e["timestamp"]), m.group(1))

    def how(trace):
        if trace not in req:
            return "no log entry"
        inst, t = req[trace]
        if inst not in starts:
            return "running before the logs start"
        st, reason = starts[inst]
        if reason == "AUTOSCALING" and st >= t - WINDOW:
            return "started by this request"
        if reason == "DEPLOYMENT_ROLLOUT":
            return "pre-started for a deployment"
        return f"started earlier ({reason})"
    p["instance_start"] = p["trace_id"].map(how)
    return p


def tables(p, out):
    m = p[(p["probe"] > 0) & ~p["resumed"] & p["error"].isna()].copy()
    m["gap_min"] = (m["planned_gap_s"] / 60).round(1)
    out.append("## Cold-start probability vs idle time\n")
    out.append("Probe 0 of each chain and the first probe after a restart are left out (their idle time isn't the planned one). "
               "*Cold*: the probe's first request ran in a fresh process.\n")
    g = m.groupby("gap_min").agg(probes=("cold", "size"), cold=("cold", "sum"),
                                 first_ms_warm=("first_ms", lambda s: s[~m.loc[s.index, "cold"]].median()),
                                 first_ms_cold=("first_ms", lambda s: s[m.loc[s.index, "cold"]].median())).reset_index()
    g["P(cold)"] = g["cold"] / g["probes"]
    g["probes"], g["cold"] = g["probes"].astype(int).astype(str), g["cold"].astype(int).astype(str)
    out.append(md_table(g.rename(columns={"gap_min": "idle min", "first_ms_warm": "first request p50 ms (warm)",
                                          "first_ms_cold": "first request p50 ms (cold)"}),
                        {"P(cold)": 2, "idle min": 1, "first request p50 ms (warm)": 0, "first request p50 ms (cold)": 0}) + "\n")
    piv = m.pivot_table(index="target", columns="gap_min", values="cold", aggfunc=lambda s: "".join("C" if v else "w" for v in s))
    out.append("\n**Per target** (C = cold, w = warm, per probe at that idle time)\n")
    piv.columns = [f"{c:g} min" for c in piv.columns]
    out.append(md_table(piv.reset_index().fillna("")) + "\n")
    cold = m[m["cold"]]
    if len(cold):
        out.append("\n**Cold probes** (first request ms; how the instance was started, if logs are present)\n")
        cols = ["target", "gap_min", "idle_s", "first_ms", "session_ms"] + (["instance_start"] if "instance_start" in m else [])
        out.append(md_table(cold[cols].sort_values(["target", "gap_min"]), {"gap_min": 1, "idle_s": 0, "first_ms": 0, "session_ms": 0}) + "\n")
    if "instance_start" in m:
        out.append("\n**How the instance serving each probe was started** (all probes)\n")
        out.append(md_table(m.groupby(["cold", "instance_start"]).size().rename("probes").reset_index()) + "\n")
    errors = p[p["error"].notna()]
    if len(errors):
        out.append(f"\n**Errors:** {len(errors)} probes failed: " + "; ".join(f"{r.target} #{r.probe}: {r.error}" for r in errors.itertuples()) + "\n")
    return m


PLATFORMS = (("gcp1", "GCP gen1"), ("gcp2", "GCP gen2"), ("aws", "AWS Lambda"), ("azure", "Azure"))


def platform(target):
    return next((label for prefix, label in PLATFORMS if target.startswith(prefix)), target.split("-")[0])


def figure(m, path, title):
    if m.empty:
        return
    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    m = m.assign(platform=[platform(t) for t in m["target"]])
    # Platforms often coincide exactly: draw later ones as larger hollow markers so both stay visible.
    for i, (plat, x) in enumerate(m.groupby("platform", sort=False)):
        g = x.groupby("gap_min")["cold"].agg(["mean", "size"])
        hollow = i > 0
        ax.plot(g.index, g["mean"], marker="o", markersize=9 if hollow else 5, color=SERIES[i % len(SERIES)],
                markerfacecolor="none" if hollow else SERIES[i % len(SERIES)],
                markeredgecolor=SERIES[i % len(SERIES)] if hollow else SURFACE,
                linestyle="--" if hollow else "-", linewidth=1.5, zorder=3 - i,
                label=f"{plat} ({len(x['target'].unique())} function{'s' * (len(x['target'].unique()) > 1)}, "
                      f"{int(g['size'].sum())} probes)")
    ax.set_xlabel("idle time before the request, min")
    ax.set_ylabel("share of cold starts")
    ax.set_ylim(-0.05, 1.05)
    style_axis(ax)
    ax.set_title(title)
    ax.legend(loc="center right", fontsize=8)
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def main():
    a = argparse.ArgumentParser()
    a.add_argument("run")
    a.add_argument("--figures")
    a.add_argument("--title", default="Cold-start probability vs idle time")
    args = a.parse_args()
    p = join_logs(load_probes(args.run), args.run)
    out = [f"# Idle-time run `{os.path.basename(os.path.normpath(args.run))}`\n"]
    m = tables(p, out)
    if args.figures:
        os.makedirs(args.figures, exist_ok=True)
        figure(m, os.path.join(args.figures, f"idle-{os.path.basename(os.path.normpath(args.run))}.png"),
               args.title)
    with open(os.path.join(args.run, "summary.md"), "w") as f:
        f.write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
