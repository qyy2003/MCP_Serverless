#!/usr/bin/env python3
"""Generate interim presentation tables and cross-cloud figures from the AWS SDK/protocol run + GCP data.

    serverless-benchmarks/.venv/bin/python analysis/interim_figures.py \
        results/aws/2026-11-23-sdk-proto \
        --figures docs/figures/interim \
        --table docs/aws-sdk-proto-2026-11-23.md
"""

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from aws_results import (  # noqa: E402
    AXIS, GRID, INK, INK2, LAMBDA_GB_S, LAMBDA_REQUEST, MUTED, SERIES, SURFACE, md_table, plt,
)

# Verified clean GCP Cloud Run gen2 (boost on, MCP mode) E2 medians & IQRs from docs/gcp-tables-2026-11-20.md
# Format: (fn_key, tier_label) -> dict(n, p50, p25, p75, import_p50)  [all ms]
GCP_E2_BOOST_ON = {
    ("610", "512"): {"n": 9, "p50": 1202.1, "p25": 1120.0, "p75": 1297.0, "import_p50": 8.5},
    ("610-sdk", "512"): {"n": 8, "p50": 3375.7, "p25": 3238.0, "p75": 3656.0, "import_p50": 2090.4},
    ("620-sdk", "512"): {"n": 3, "p50": 4571.9, "p25": 3720.0, "p75": 4950.0, "import_p50": 3020.8},
    ("610", "1vcpu"): {"n": 9, "p50": 1730.6, "p25": 1655.0, "p75": 1844.0, "import_p50": 8.6},
    ("610-sdk", "1vcpu"): {"n": 10, "p50": 3619.4, "p25": 3479.0, "p75": 4878.0, "import_p50": 2202.3},
    ("620-sdk", "1vcpu"): {"n": 10, "p50": 3664.7, "p25": 3431.0, "p75": 3824.0, "import_p50": 2249.2},
}

STACK_ORDER = ["610", "610-sdk", "620-sdk", "630", "630-sdk"]
STACK_LABELS = {
    "610": "610 api-proxy\n(no-SDK, 0.03 MB)",
    "610-sdk": "610 api-proxy\n(MCP SDK, 41 MB)",
    "620-sdk": "620 fetch-md\n(MCP SDK, 41 MB)",
    "630": "630 data-analysis\n(pandas, 150 MB)",
    "630-sdk": "630 data-analysis\n(SDK+pandas, 191 MB)",
}


def load_gcp_630() -> dict:
    """Compute natural cold-start p50/p25/p75 for GCP 630/630-sdk from results/idle/gcp-630-*."""
    out = {}
    for tier_label, subdir in (("512", "gcp-630-512"), ("1vcpu", "gcp-630-2048")):
        for key, fname in (("630", "gcp2-630.jsonl"), ("630-sdk", "gcp2-630s.jsonl")):
            path = os.path.join(ROOT, "results", "idle", subdir, fname)
            if not os.path.exists(path):
                continue
            by_probe = {}
            for line in open(path):
                r = json.loads(line)
                if r.get("probe", 0) == 0:
                    continue
                by_probe.setdefault(r["probe"], []).append(r)
            first_results, imports = [], []
            for recs in by_probe.values():
                # Handshake + first tools/call (call == 0)
                first_call_seen = False
                tot_us = 0
                imp_us = 0
                for r in recs:
                    if r.get("phase") == "tools/call":
                        if r.get("call", 0) == 0:
                            tot_us += r["client_us"]
                            first_call_seen = True
                            imp_us = max(imp_us, r.get("import_us") or 0, r.get("init_import_us") or 0)
                            break
                    else:
                        tot_us += r["client_us"]
                        imp_us = max(imp_us, r.get("init_import_us") or 0)
                if first_call_seen:
                    first_results.append(tot_us / 1e3)
                    imports.append(imp_us / 1e3)
            if first_results:
                out[(key, tier_label)] = {
                    "n": len(first_results),
                    "p50": float(np.median(first_results)),
                    "p25": float(np.percentile(first_results, 25)),
                    "p75": float(np.percentile(first_results, 75)),
                    "import_p50": float(np.median(imports)),
                }
    return out


def load_reports(run_dir: str) -> dict:
    path = os.path.join(run_dir, "reports.jsonl")
    reps = {}
    if os.path.exists(path):
        for line in open(path):
            r = json.loads(line)
            reps[r["request_id"]] = r
    return reps


def summarize_oom(run_dir: str, reports: dict) -> pd.DataFrame:
    path = os.path.join(run_dir, "oom-128mb.jsonl")
    if not os.path.exists(path):
        return pd.DataFrame()
    by_rep = {}
    for line in open(path):
        r = json.loads(line)
        by_rep.setdefault(r["rep"], []).append(r)
    rows = []
    for rep, recs in sorted(by_rep.items()):
        if any("error" in r for r in recs):
            rows.append({"rep": rep, "status": "FAILED", "first_result_ms": np.nan, "init_ms": np.nan,
                         "init_import_ms": np.nan, "billed_ms": np.nan, "max_memory_mb": np.nan})
            continue
        recs.sort(key=lambda x: x["position"])
        first_ms = sum(r["client_us"] for r in recs) / 1e3
        rep_objs = [reports[r["amzn_request_id"]] for r in recs if r.get("amzn_request_id") in reports]
        init_ms = next((o["init_ms"] for o in rep_objs if "init_ms" in o), np.nan)
        billed_ms = sum(o["billed_ms"] for o in rep_objs) if rep_objs else np.nan
        max_mem = max((o["max_memory_mb"] for o in rep_objs), default=np.nan)
        init_imp = next((r["init_import_us"] / 1e3 for r in recs if r.get("init_import_us")), np.nan)
        rows.append({"rep": rep, "status": "OK", "first_result_ms": first_ms, "init_ms": init_ms,
                     "init_import_ms": init_imp, "billed_ms": billed_ms, "max_memory_mb": max_mem})
    return pd.DataFrame(rows)


def summarize_cold(run_dir: str, reports: dict) -> tuple[pd.DataFrame, dict]:
    path = os.path.join(run_dir, "cold.jsonl")
    if not os.path.exists(path):
        return pd.DataFrame(), {}
    by_sess = {}
    for line in open(path):
        r = json.loads(line)
        if "error" in r:
            continue
        by_sess.setdefault((r["fn"], r["mem"], r["rep"]), []).append(r)

    per_sess = []
    for (fn, mem, rep), recs in sorted(by_sess.items()):
        recs.sort(key=lambda x: x["position"])
        # Handshake + first tools/call = recs[:-1]; recs[-1] is second (warm) tools/call
        cold_recs = recs[:-1]
        warm_rec = recs[-1]
        first_ms = sum(r["client_us"] for r in cold_recs) / 1e3
        warm_ms = warm_rec["client_us"] / 1e3
        rep_objs = [reports[r["amzn_request_id"]] for r in cold_recs if r.get("amzn_request_id") in reports]
        init_ms = next((o["init_ms"] for o in rep_objs if "init_ms" in o), np.nan)
        billed_ms = sum(o["billed_ms"] for o in rep_objs) if rep_objs else np.nan
        max_mem = max((o["max_memory_mb"] for o in rep_objs), default=np.nan)
        imp_ms = max(
            [r.get("init_import_us", 0) or 0 for r in cold_recs]
            + [r.get("import_us", 0) or 0 for r in cold_recs]
        ) / 1e3
        load_ms = max((r.get("m_load_us", 0) or 0 for r in cold_recs), default=0) / 1e3
        per_sess.append({
            "fn": fn, "mem": mem, "rep": rep, "first_ms": first_ms, "warm_ms": warm_ms,
            "init_ms": init_ms, "import_ms": imp_ms, "load_ms": load_ms,
            "billed_ms": billed_ms, "max_mem": max_mem,
        })
    df = pd.DataFrame(per_sess)
    rows = []
    aws_stats = {}
    for mem in sorted(df["mem"].unique()):
        tier_label = "512" if mem == 512 else "1vcpu"
        for fn in STACK_ORDER:
            sub = df[(df["fn"] == fn) & (df["mem"] == mem)]
            if sub.empty:
                continue
            p50 = float(sub["first_ms"].median())
            p25 = float(sub["first_ms"].quantile(0.25))
            p75 = float(sub["first_ms"].quantile(0.75))
            aws_stats[(fn, tier_label)] = {
                "n": len(sub), "p50": p50, "p25": p25, "p75": p75,
                "init_p50": float(sub["init_ms"].median()),
                "import_p50": float(sub["import_ms"].median()),
                "max_mem": int(sub["max_mem"].max()) if sub["max_mem"].notna().any() else 0,
            }
            rows.append({
                "memory MB": mem,
                "tool": fn,
                "n": len(sub),
                "first result p50 ms": p50,
                "p25–p75 ms": f"{p25:,.0f}–{p75:,.0f}",
                "warm call p50 ms": float(sub["warm_ms"].median()),
                "Lambda Init p50 ms": float(sub["init_ms"].median()),
                "import p50 ms": float(sub["import_ms"].median()),
                "dataset load p50 ms": float(sub["load_ms"].median()),
                "billed session p50 ms": float(sub["billed_ms"].median()),
                "max mem MB": int(sub["max_mem"].max()) if sub["max_mem"].notna().any() else 0,
            })
    return pd.DataFrame(rows), aws_stats


def summarize_proto(run_dir: str, reports: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    path = os.path.join(run_dir, "proto.jsonl")
    if not os.path.exists(path):
        return pd.DataFrame(), pd.DataFrame()
    by_sess = {}
    for line in open(path):
        r = json.loads(line)
        by_sess.setdefault((r["condition"], r["protocol"], r["mem"], r["rep"]), []).append(r)

    per_sess = []
    for (cond, proto, mem, rep), recs in sorted(by_sess.items()):
        recs.sort(key=lambda x: x["position"])
        total_ms = sum(r["client_us"] for r in recs) / 1e3
        rep_objs = [reports[r["amzn_request_id"]] for r in recs if r.get("amzn_request_id") in reports]
        billed_ms = sum(o["billed_ms"] for o in rep_objs) if len(rep_objs) == len(recs) else np.nan
        init_ms = sum(o.get("init_ms", 0.0) for o in rep_objs) if rep_objs else np.nan
        cost_1m = (
            (billed_ms / 1000.0 * (mem / 1024.0) * LAMBDA_GB_S + len(recs) * LAMBDA_REQUEST) * 1e6
            if not np.isnan(billed_ms) else np.nan
        )
        per_sess.append({
            "condition": cond, "protocol": proto, "mem": mem, "rep": rep,
            "reqs": len(recs), "total_ms": total_ms, "billed_ms": billed_ms,
            "init_ms": init_ms, "cost_per_1m_sessions": cost_1m,
        })
    raw = pd.DataFrame(per_sess)
    rows = []
    for cond in ("warm", "cold"):
        for proto in ("legacy", "auto", "modern"):
            sub = raw[(raw["condition"] == cond) & (raw["protocol"] == proto)]
            if sub.empty:
                continue
            rows.append({
                "condition": cond,
                "protocol": proto,
                "n": len(sub),
                "requests": int(sub["reqs"].median()),
                "first result p50 ms": float(sub["total_ms"].median()),
                "p25–p75 ms": f"{sub['total_ms'].quantile(0.25):,.0f}–{sub['total_ms'].quantile(0.75):,.0f}",
                "billed p50 ms": float(sub["billed_ms"].median()),
                "Lambda Init p50 ms": float(sub["init_ms"].median()),
                "$ per 1M sessions": float(sub["cost_per_1m_sessions"].median()),
            })
    return pd.DataFrame(rows), raw


def plot_cold_by_stack(aws_stats: dict, gcp_stats: dict, out_path: str):
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.3), sharey=True)
    panels = [
        ("1vcpu", "1 vCPU  (AWS 1769 MB  vs.  GCP 2048 MB, boost on)"),
        ("512", "512 MB  (AWS ~0.29 vCPU  vs.  GCP 0.333 vCPU, boost on)"),
    ]
    y = np.arange(len(STACK_ORDER))
    h = 0.36
    c_aws, c_gcp = SERIES[0], SERIES[1]

    for ax, (tier, title) in zip(axes, panels):
        aws_vals, aws_lo, aws_hi = [], [], []
        gcp_vals, gcp_lo, gcp_hi = [], [], []
        for fn in STACK_ORDER:
            a = aws_stats.get((fn, tier))
            g = gcp_stats.get((fn, tier))
            aws_vals.append(a["p50"] / 1000.0 if a else np.nan)
            aws_lo.append((a["p50"] - a["p25"]) / 1000.0 if a else 0.0)
            aws_hi.append((a["p75"] - a["p50"]) / 1000.0 if a else 0.0)
            gcp_vals.append(g["p50"] / 1000.0 if g else np.nan)
            gcp_lo.append((g["p50"] - g["p25"]) / 1000.0 if g else 0.0)
            gcp_hi.append((g["p75"] - g["p50"]) / 1000.0 if g else 0.0)

        ax.barh(y - h / 2, aws_vals, height=h, color=c_aws, label="AWS Lambda (eu-north-1)", zorder=3)
        ax.errorbar(aws_vals, y - h / 2, xerr=[aws_lo, aws_hi], fmt="none", ecolor=INK, elinewidth=1.0, capsize=2.5, zorder=4)
        ax.barh(y + h / 2, gcp_vals, height=h, color=c_gcp, label="GCP Cloud Run gen2 (europe-west1)", zorder=3)
        ax.errorbar(gcp_vals, y + h / 2, xerr=[gcp_lo, gcp_hi], fmt="none", ecolor=INK, elinewidth=1.0, capsize=2.5, zorder=4)

        xmax = max([v for v in aws_vals + gcp_vals if not np.isnan(v)] + [1.0])
        for i, (av, gv) in enumerate(zip(aws_vals, gcp_vals)):
            if not np.isnan(av):
                ax.text(av + aws_hi[i] + xmax * 0.015, y[i] - h / 2, f"{av:.2f} s", va="center", fontsize=8, color=INK)
            if not np.isnan(gv):
                ax.text(gv + gcp_hi[i] + xmax * 0.015, y[i] + h / 2, f"{gv:.2f} s", va="center", fontsize=8, color=INK)

        ax.set_xlim(0, xmax * 1.24)
        ax.set_xlabel("Cold time to first tool result (seconds, median & IQR)")
        ax.set_title(title, fontsize=9.5, pad=8)
        ax.xaxis.grid(True, color=GRID, linewidth=0.7, zorder=0)
        ax.set_axisbelow(True)

    axes[0].invert_yaxis()
    axes[0].set_yticks(y)
    axes[0].set_yticklabels([STACK_LABELS[k] for k in STACK_ORDER], fontsize=8.5)
    axes[1].legend(loc="upper right", fontsize=8.5)
    # Highlight the AWS Init-burst inversion at 512 MB (eager SDK+pandas faster than lazy pandas)
    axes[1].annotate(
        "Eager Init burst\nbeats lazy handler\nimport (-0.9 s)",
        xy=(4.55, 3.82), xytext=(5.9, 1.4),
        fontsize=7.5, color=SERIES[0], fontweight="bold", ha="left", va="center",
        bbox=dict(boxstyle="round,pad=0.3", facecolor=SURFACE, edgecolor=SERIES[0], lw=0.8),
        arrowprops=dict(arrowstyle="->", color=SERIES[0], lw=1.1, connectionstyle="arc3,rad=-0.18"),
    )
    fig.suptitle("Cold start by MCP software stack: AWS Lambda vs. GCP Cloud Run", x=0.02, ha="left",
                 fontsize=11, fontweight="bold", color=INK)
    fig.text(
        0.02, 0.01,
        "AWS: n=10 forced cold starts (WAN client, 200 ms upstream); GCP: 610/620 n=3–10 (E2), 630 n=6 (natural cold after 17 min idle).\n"
        "128 MB floor: 610-sdk OOMs on GCP Cloud Run (134 MiB) but runs cleanly on AWS Lambda (106 MB max, 1.94 s median).",
        fontsize=7.5, color=MUTED,
    )
    fig.tight_layout(rect=[0, 0.06, 1, 0.94])
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.savefig(out_path, dpi=220)
    plt.close(fig)


def plot_protocol_aws(proto_raw: pd.DataFrame, out_path: str):
    if proto_raw.empty:
        return
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 4.0))
    protos = ["legacy", "auto", "modern"]
    labels = ["Legacy\n(4 reqs)", "Auto\n(3 reqs)", "2026-07-28\n(2 reqs)"]
    colors = [SERIES[1], SERIES[3], SERIES[2]]

    # Panel 1: Warm & Cold latency
    ax = axes[0]
    x = np.arange(len(protos))
    w = 0.36
    warm_med = [proto_raw[(proto_raw["condition"] == "warm") & (proto_raw["protocol"] == p)]["total_ms"].median() for p in protos]
    cold_med = [proto_raw[(proto_raw["condition"] == "cold") & (proto_raw["protocol"] == p)]["total_ms"].median() for p in protos]
    ax.bar(x - w / 2, warm_med, width=w, color=SERIES[0], label="Warm session (n=20)", zorder=3)
    ax.bar(x + w / 2, cold_med, width=w, color=SERIES[1], label="Cold session (n=10)", zorder=3)
    for i, (wm, cm) in enumerate(zip(warm_med, cold_med)):
        tag = f"{wm:.0f} ms\n(-33%)" if i == 2 else f"{wm:.0f} ms"
        ax.text(x[i] - w / 2, wm + max(cold_med) * 0.02, tag, ha="center", va="bottom", fontsize=8,
                fontweight="bold" if i == 2 else "normal", color=SERIES[0] if i == 2 else INK)
        ax.text(x[i] + w / 2, cm + max(cold_med) * 0.02, f"{cm:.0f} ms", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Time to first tool result (ms, median)")
    ax.set_title("Session startup latency (WAN, 610-sdk)", fontsize=9.5, pad=8)
    ax.set_ylim(0, max(cold_med) * 1.32)
    ax.yaxis.grid(True, color=GRID, linewidth=0.7, zorder=0)
    ax.legend(loc="upper center", ncol=2, fontsize=8)

    # Panel 2: Measured CloudWatch billing (warm sessions)
    ax = axes[1]
    warm_cost = [proto_raw[(proto_raw["condition"] == "warm") & (proto_raw["protocol"] == p)]["cost_per_1m_sessions"].median() for p in protos]
    warm_reqs = [proto_raw[(proto_raw["condition"] == "warm") & (proto_raw["protocol"] == p)]["reqs"].median() for p in protos]
    ax.bar(x, warm_cost, width=0.5, color=colors, zorder=3)
    for i, (cost, reqs) in enumerate(zip(warm_cost, warm_reqs)):
        pct = (1.0 - cost / warm_cost[0]) * 100.0
        extra = f"\n(-{pct:.0f}%)" if i > 0 else ""
        ax.text(x[i], cost + max(warm_cost) * 0.025, f"${cost:.2f}{extra}", ha="center", va="bottom",
                fontsize=8.5, fontweight="bold" if i == 2 else "normal",
                color=SERIES[2] if i == 2 else INK)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Measured Lambda cost ($ / 1M warm sessions)")
    ax.set_title("Measured Lambda bill (1-call warm session)", fontsize=9.5, pad=8)
    ax.set_ylim(0, max(warm_cost) * 1.28)
    ax.yaxis.grid(True, color=GRID, linewidth=0.7, zorder=0)

    fig.suptitle("MCP protocol revision on AWS Lambda: dropping the handshake (2026-07-28)",
                 x=0.02, ha="left", fontsize=11, fontweight="bold", color=INK)
    fig.text(0.02, 0.01,
             "610.api-proxy (official SDK, 1769 MB, 50 ms upstream), WAN client ETH Zurich -> eu-north-1.\n"
             "Costs computed directly from matched CloudWatch REPORT lines (eu-north-1 x86 rates); cold sessions add ~1.26 s billed Init.",
             fontsize=7.5, color=MUTED)
    fig.tight_layout(rect=[0, 0.06, 1, 0.93])
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.savefig(out_path, dpi=220)
    plt.close(fig)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("run_dir", help="Path to results/aws/2026-11-23-sdk-proto")
    p.add_argument("--figures", default=os.path.join(ROOT, "docs", "figures", "interim"))
    p.add_argument("--table", default=os.path.join(ROOT, "docs", "aws-sdk-proto-2026-11-23.md"))
    args = p.parse_args(argv)

    reports = load_reports(args.run_dir)
    oom_df = summarize_oom(args.run_dir, reports)
    cold_df, aws_stats = summarize_cold(args.run_dir, reports)
    proto_df, proto_raw = summarize_proto(args.run_dir, reports)

    gcp_stats = dict(GCP_E2_BOOST_ON)
    gcp_stats.update(load_gcp_630())

    lines = [
        "# AWS Lambda SDK, Heavy-Startup (`630`) & MCP `2026-07-28` Measurements (2026-11-23)",
        "",
        f"Source: `{os.path.relpath(args.run_dir, ROOT)}/`, matched against {len(reports)} CloudWatch `REPORT` lines (`eu-north-1`, Python 3.11, x86_64).",
        "",
        "## 1. 128 MB Memory Check (`610-sdk`)",
        "",
        md_table(oom_df, {"first_result_ms": 1, "init_ms": 1, "init_import_ms": 1, "billed_ms": 0, "max_memory_mb": 0})
        if not oom_df.empty else "_No data._",
        "",
        "## 2. Cold Starts by Software Stack (512 MB & 1769 MB / 1 vCPU)",
        "",
        md_table(cold_df, {"first result p50 ms": 1, "warm call p50 ms": 1, "Lambda Init p50 ms": 1,
                           "import p50 ms": 1, "dataset load p50 ms": 1, "billed session p50 ms": 0})
        if not cold_df.empty else "_No data._",
        "",
        "## 3. MCP Protocol Revision (`610-sdk`, 1769 MB, 50 ms upstream, WAN ETH -> eu-north-1)",
        "",
        md_table(proto_df, {"first result p50 ms": 1, "billed p50 ms": 0, "Lambda Init p50 ms": 1, "$ per 1M sessions": 2})
        if not proto_df.empty else "_No data._",
        "",
    ]
    os.makedirs(os.path.dirname(args.table), exist_ok=True)
    open(args.table, "w").write("\n".join(lines))
    print(f"Wrote {args.table}")

    plot_cold_by_stack(aws_stats, gcp_stats, os.path.join(args.figures, "cold-start-by-stack.png"))
    print(f"Wrote {os.path.join(args.figures, 'cold-start-by-stack.png')}")
    plot_protocol_aws(proto_raw, os.path.join(args.figures, "protocol-revision-aws.png"))
    print(f"Wrote {os.path.join(args.figures, 'protocol-revision-aws.png')}")


if __name__ == "__main__":
    sys.exit(main())
