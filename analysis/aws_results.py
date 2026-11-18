#!/usr/bin/env python3
"""Tables and figures for an AWS Lambda campaign (experiments E1-E5).

    serverless-benchmarks/python-venv/bin/python analysis/aws_results.py results/aws/<campaign> [--figures docs/figures/aws]

Reads the client records written by experiments/aws_campaign.py and the Lambda REPORT
lines (reports.jsonl), writes <campaign>/summary.md with every table, and PNG figures.
Needs pandas and matplotlib (installed in the SeBS virtual environment).
"""

import argparse
import glob
import json
import os

import numpy as np
import pandas as pd
import matplotlib
import matplotlib.ticker

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# Prices used for E5. Lambda: x86, eu-north-1, first 6 billion GB-s (AWS price list published 2026-11-11).
LAMBDA_GB_S = 0.0000166667
LAMBDA_REQUEST = 0.20 / 1e6
# CPU-time billing as in Cloudflare Workers' Standard model (beyond the included monthly quota).
CPU_MS = 0.02 / 1e6
CPU_REQUEST = 0.30 / 1e6

TOOL = {"010": "no-op (010.sleep 0 s)", "110": "dynamic-html (110)", "610": "api-proxy (610)", "620": "fetch-markdown (620)"}
SHORT = {"010": "no-op", "110": "dynamic-html", "610": "api-proxy", "620": "fetch-markdown"}

# Reference palette of the dataviz method, light mode (fixed categorical order).
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": "sans-serif", "font.size": 9, "text.color": INK, "axes.labelcolor": INK2,
    "axes.edgecolor": AXIS, "axes.linewidth": 0.8, "xtick.color": MUTED, "ytick.color": MUTED,
    "xtick.labelcolor": INK2, "ytick.labelcolor": INK2, "axes.titlesize": 10, "axes.titleweight": "bold",
    "axes.titlecolor": INK, "axes.titlelocation": "left", "legend.frameon": False,
    "axes.spines.top": False, "axes.spines.right": False,
})


def q(p):
    return lambda s: float(np.nanpercentile(s, p)) if len(s.dropna()) else np.nan


def ms(us):
    return np.nan if pd.isna(us) else us / 1000


def fmt(x, digits=1):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    return f"{x:,.{digits}f}"


def md_table(df: pd.DataFrame, digits=None) -> str:
    digits = digits or {}
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, row in df.iterrows():
        cells = []
        for c in cols:
            v = row[c]
            if isinstance(v, (float, np.floating)):
                cells.append(fmt(float(v), digits.get(c, 1)))
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


# --- loading -------------------------------------------------------------------------------------

def load(root: str):
    rows = []
    for exp in ("e1", "e1b", "e1wan", "e2", "e3"):
        for path in sorted(glob.glob(os.path.join(root, exp, "*", "*.jsonl"))):
            for seq, line in enumerate(open(path)):
                r = json.loads(line)
                r["file"] = os.path.relpath(path, root)
                r["seq"] = seq
                rows.append(r)
    df = pd.DataFrame(rows)
    if df.empty:
        return df, pd.DataFrame()
    for col in ("request_id", "amzn_request_id", "call", "exec_us", "import_us", "cpu_us", "is_cold", "container_id"):
        if col not in df:
            df[col] = np.nan
    df["rid"] = df["amzn_request_id"].fillna(df["request_id"])
    reports = pd.DataFrame()
    rpath = os.path.join(root, "reports.jsonl")
    if os.path.exists(rpath):
        reports = pd.read_json(rpath, lines=True).drop_duplicates("request_id")
        df = df.merge(reports[["request_id", "duration_ms", "billed_ms", "init_ms", "max_memory_mb"]]
                      .rename(columns={"request_id": "rid"}), on="rid", how="left")
    for col in ("billed_ms", "init_ms", "duration_ms", "max_memory_mb"):
        if col not in df:
            df[col] = np.nan
    df["cold"] = df["is_cold"].eq(True)
    return df, reports


def calls(df):
    return df[df["phase"].isin(["tools/call", "plain"])]


# --- figures ---------------------------------------------------------------------------------------

def style_axis(ax, axis="y"):
    ax.grid(axis=axis, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)


def stacked_bars(ax, positions, segments, colors, horizontal=False, width=0.6):
    """Stacked bars with a 2 px surface-colored gap between segments (edgecolor = surface)."""
    base = np.zeros(len(positions))
    for (label, values), color in zip(segments, colors):
        values = np.nan_to_num(np.asarray(values, dtype=float))
        if horizontal:
            ax.barh(positions, values, left=base, height=width, color=color, label=label,
                    edgecolor=SURFACE, linewidth=1.5)
        else:
            ax.bar(positions, values, bottom=base, width=width, color=color, label=label,
                   edgecolor=SURFACE, linewidth=1.5)
        base += values
    return base


# --- E1: MCP vs plain, warm ------------------------------------------------------------------------

def e1(df, out):
    d = calls(df[(df["exp"] == "e1") & ~df["cold"]]).copy()
    if d.empty:
        return
    d["outside_us"] = d["client_us"] - d["exec_us"]
    g = d.groupby(["mem", "fn", "mode"]).agg(
        n=("client_us", "size"), p50=("client_us", "median"), p90=("client_us", q(90)),
        exec=("exec_us", "median"), outside=("outside_us", "median"), resp=("response_bytes", "median"),
        billed=("billed_ms", "median")).reset_index()
    rows = []
    for (mem, fn), x in g.groupby(["mem", "fn"]):
        m, p = x[x["mode"] == "mcp"].iloc[0], x[x["mode"] == "plain"].iloc[0]
        rows.append({"memory MB": mem, "tool": SHORT[fn], "calls/mode": int(min(m.n, p.n)),
                     "MCP p50 ms": ms(m.p50), "plain p50 ms": ms(p.p50), "MCP − plain p50 ms": ms(m.p50 - p.p50),
                     "MCP p90 ms": ms(m.p90), "plain p90 ms": ms(p.p90),
                     "in function p50 ms (MCP)": ms(m.exec), "outside function p50 ms (MCP / plain)": f"{ms(m.outside):.1f} / {ms(p.outside):.1f}",
                     "response bytes (MCP / plain)": f"{int(m.resp):,} / {int(p.resp):,}"})
    out.append("## E1 · MCP vs plain invocation, warm (client VM in eu-north-1)\n")
    out.append("Cold calls excluded. *Outside function* = client time − time inside the function handler: network, Function URL front end, Lambda routing, protocol.\n")
    out.append(md_table(pd.DataFrame(rows)) + "\n")

    for exp, title in (("e1hs", "VM in eu-north-1"), ("e1wan-hs", "workstation at ETH Zurich")):
        h = df[df["exp"] == exp]
        if h.empty:
            continue
        sess = []
        for f, s in h.groupby("file"):
            ph = s.set_index("phase")
            if not {"initialize", "notifications/initialized", "tools/list", "tools/call"} <= set(ph.index):
                continue
            sess.append({"mem": s["mem"].iloc[0], "connect": ph.loc["initialize", "connect_us"],
                         "initialize": ph.loc["initialize", "client_us"] - ph.loc["initialize", "connect_us"],
                         "notification": ph.loc["notifications/initialized", "client_us"],
                         "tools/list": ph.loc["tools/list", "client_us"],
                         "handshake": ph.loc[["initialize", "notifications/initialized", "tools/list"], "client_us"].sum(),
                         "first call": ph.loc["tools/call", "client_us"],
                         "cold": bool(s["cold"].any())})
        sd = pd.DataFrame(sess)
        if sd.empty:
            continue
        rows = []
        for mem, x in sd.groupby("mem"):
            w = x[~x["cold"]]
            rows.append({"memory MB": mem, "sessions (cold excluded)": f"{len(w)} ({int(x['cold'].sum())})",
                         "TCP+TLS connect": ms(w["connect"].median()), "initialize": ms(w["initialize"].median()),
                         "notifications/initialized": ms(w["notification"].median()),
                         "tools/list": ms(w["tools/list"].median()), "handshake total": ms(w["handshake"].median()),
                         "first tools/call": ms(w["first call"].median())})
        out.append(f"\n**MCP session setup, warm function, client = {title}** (medians, ms; each session opens a new connection)\n")
        out.append(md_table(pd.DataFrame(rows)) + "\n")

    w = calls(df[(df["exp"] == "e1wan") & ~df["cold"]])
    if not w.empty:
        g = w.groupby("mode")["client_us"].agg(["size", "median", q(90)])
        out.append("\n**Workstation at ETH Zurich → eu-north-1, dynamic-html, warm** (ms): " + ", ".join(
            f"{mode}: p50 {ms(r['median']):.1f}, p90 {ms(r.iloc[2]):.1f} (n={int(r['size'])})" for mode, r in g.iterrows()) + "\n")


def e1_figure(df, path):
    """Session setup cost from the two client locations, stacked by request."""
    bars = []
    for exp, label in (("e1hs", "client in eu-north-1"), ("e1wan-hs", "client at ETH Zurich")):
        h = df[(df["exp"] == exp) & (df["mem"] == 128)]
        parts = {"TCP+TLS connect": [], "initialize": [], "notifications/initialized": [], "tools/list": [], "first tools/call": []}
        for f, s in h.groupby("file"):
            if s["cold"].any():
                continue
            ph = s.set_index("phase")
            parts["TCP+TLS connect"].append(ph.loc["initialize", "connect_us"])
            parts["initialize"].append(ph.loc["initialize", "client_us"] - ph.loc["initialize", "connect_us"])
            parts["notifications/initialized"].append(ph.loc["notifications/initialized", "client_us"])
            parts["tools/list"].append(ph.loc["tools/list", "client_us"])
            parts["first tools/call"].append(ph.loc["tools/call", "client_us"])
        if parts["initialize"]:
            bars.append((label, {k: np.median(v) / 1000 for k, v in parts.items()}))
    if not bars:
        return
    fig, ax = plt.subplots(figsize=(7.2, 2.4))
    keys = list(bars[0][1].keys())
    pos = np.arange(len(bars))[::-1]
    totals = stacked_bars(ax, pos, [(k, [b[1][k] for b in bars]) for k in keys], SERIES[:len(keys)], horizontal=True, width=0.5)
    ax.set_yticks(pos, [b[0] for b in bars])
    for p, t, b in zip(pos, totals, bars):
        ax.text(t + 4, p, f"{t:.0f} ms to first result", va="center", color=INK2, fontsize=8)
    ax.set_xlabel("ms (medians, warm 128 MB no-op tool, new connection per session)")
    ax.set_xlim(0, max(totals) * 1.3)
    style_axis(ax, "x")
    ax.set_title("A new MCP session costs 3 round trips before the first tool call")
    ax.legend(ncol=5, loc="upper left", bbox_to_anchor=(0, -0.32), fontsize=8, handlelength=1, columnspacing=1)
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


# --- E2: cold vs warm -------------------------------------------------------------------------------

def e2_sessions(df):
    d = df[df["exp"] == "e2"]
    sessions = []
    for f, s in d.groupby("file"):
        s = s.sort_values("seq")
        mode, fn, mem = s["mode"].iloc[0], s["fn"].iloc[0], s["mem"].iloc[0]
        c = calls(s)
        first = c[c["call"] == 0].iloc[0]
        warm = c[(c["call"] >= 1) & ~c["cold"]]
        rec = {"mem": mem, "fn": fn, "mode": mode, "rep": s["rep"].iloc[0],
               "first_call_us": first["client_us"], "first_exec_us": first["exec_us"],
               "first_import_us": first["import_us"], "first_cold": bool(first["cold"]),
               "warm_us": warm["client_us"].median(), "warm_exec_us": warm["exec_us"].median(),
               "containers": s["container_id"].dropna().nunique(), "cold_events": int(s["cold"].sum())}
        if mode == "mcp":
            ph = s.drop_duplicates("phase").set_index("phase")
            init = ph.loc["initialize"]
            hs = ph.loc[["initialize", "notifications/initialized", "tools/list"], "client_us"].sum()
            rec.update(handshake_us=hs, first_result_us=hs + first["client_us"], init_cold=bool(init["cold"]),
                       platform_init_ms=init["init_ms"], cold_request_billed_ms=init["billed_ms"],
                       cold_request_duration_ms=init["duration_ms"],
                       first_call_new_instance=first["container_id"] != init["container_id"])
        else:
            rec.update(handshake_us=0.0, first_result_us=first["client_us"], init_cold=bool(first["cold"]),
                       platform_init_ms=first["init_ms"], cold_request_billed_ms=first["billed_ms"],
                       cold_request_duration_ms=first["duration_ms"], first_call_new_instance=False)
        sessions.append(rec)
    return pd.DataFrame(sessions)


def e2(df, out):
    s = e2_sessions(df)
    if s.empty:
        return s
    rows = []
    for (mem, fn, mode), x in s.groupby(["mem", "fn", "mode"]):
        rows.append({"memory MB": mem, "tool": SHORT[fn], "mode": mode, "sessions": len(x),
                     "cold first result p50 ms": ms(x["first_result_us"].median()),
                     "warm call p50 ms": ms(x["warm_us"].median()),
                     "cold penalty ms": ms(x["first_result_us"].median() - x["warm_us"].median()),
                     "Lambda init p50 ms": x["platform_init_ms"].median(),
                     "tool import p50 ms": ms(x["first_import_us"].median()),
                     "first call on a 2nd new instance": f"{int(x['first_call_new_instance'].sum())}/{len(x)}" if mode == "mcp" else "–"})
    out.append("\n## E2 · Cold vs warm (forced cold start per session)\n")
    out.append("*Cold first result*: MCP = handshake (initialize, notification, tools/list) + first tools/call; plain = first invocation. "
               "*Lambda init* = Init Duration from the REPORT line of the cold request. *Tool import* = importing the benchmark module inside the first call (SeBS imports it lazily).\n")
    out.append(md_table(pd.DataFrame(rows)) + "\n")

    b = s[s["cold_request_billed_ms"].notna() & s["platform_init_ms"].notna()]
    if not b.empty:
        diff = b["cold_request_billed_ms"] - b["cold_request_duration_ms"]
        out.append(f"\nBilling of the cold request: billed − handler duration p50 {diff.median():.0f} ms vs Init Duration p50 "
                   f"{b['platform_init_ms'].median():.0f} ms (n={len(b)}): "
                   + ("**the init phase is billed**." if abs(diff.median() - b["platform_init_ms"].median()) < 0.25 * b["platform_init_ms"].median()
                      else "the init phase is **not** included in the billed duration.") + "\n")
    return s


def e2_figure(df, s, path):
    if s is None or s.empty:
        return
    mems = sorted(s["mem"].unique())
    fns = [f for f in ("010", "110", "610", "620") if f in set(s["fn"])]
    seg_names = ["Lambda init (platform)", "handshake: network + protocol", "tool import (first call)",
                 "tool execution (first call)", "first call: network + platform"]
    fig, axes = plt.subplots(1, len(fns), figsize=(2.3 * len(fns) + 0.6, 3.3), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, fn in zip(axes, fns):
        positions, labels, segs = [], [], {k: [] for k in seg_names}
        for i, mem in enumerate(mems):
            for j, mode in enumerate(("mcp", "plain")):
                x = s[(s["fn"] == fn) & (s["mem"] == mem) & (s["mode"] == mode) & s["init_cold"]]
                if x.empty:
                    continue
                init = x["platform_init_ms"].median()
                init = 0.0 if pd.isna(init) else init  # no REPORT lines: platform init stays in the other parts
                imp = ms(x["first_import_us"].median())
                exe = ms((x["first_exec_us"] - x["first_import_us"]).median())
                call_net = ms((x["first_call_us"] - x["first_exec_us"]).median())
                if mode == "mcp":
                    hs = ms(x["handshake_us"].median()) - init
                else:
                    hs, call_net = 0.0, call_net - init
                segs[seg_names[0]].append(init)
                segs[seg_names[1]].append(max(hs, 0))
                segs[seg_names[2]].append(imp)
                segs[seg_names[3]].append(max(exe, 0))
                segs[seg_names[4]].append(max(call_net, 0))
                positions.append(i * 2.6 + j)
                labels.append("MCP" if mode == "mcp" else "plain")
        stacked_bars(ax, positions, [(k, segs[k]) for k in seg_names], SERIES[:5], width=0.8)
        ax.set_xticks(positions, labels, fontsize=7.5)
        for i, mem in enumerate(mems):
            ax.text(i * 2.6 + 0.5, -0.13, f"{mem} MB", transform=ax.get_xaxis_transform(), ha="center", color=INK2, fontsize=8)
        ax.set_title(SHORT[fn], fontsize=9.5)
        style_axis(ax)
    axes[0].set_ylabel("ms to first result (medians)")
    fig.suptitle("Where a cold start's time goes", x=0.01, ha="left", fontweight="bold", fontsize=10.5, color=INK)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, ncol=3, loc="lower left", bbox_to_anchor=(0.01, -0.13), fontsize=8, handlelength=1)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


# --- E1b: extra instances under sequential calls -------------------------------------------------

def e1b(df, out):
    d = df[df["exp"] == "e1b"]
    if d.empty:
        return
    runs = []
    for f, s in d.groupby("file"):
        c = calls(s).sort_values("seq")
        first_new = c[c["container_id"] != s.sort_values("seq")["container_id"].dropna().iloc[0]]
        runs.append({"mem": s["mem"].iloc[0], "fn": s["fn"].iloc[0], "interval": s["interval"].iloc[0],
                     "containers": s["container_id"].dropna().nunique(), "cold": int(s["cold"].sum()),
                     "first_extra_call": first_new["call"].min() if not first_new.empty else np.nan})
    r = pd.DataFrame(runs)
    rows = []
    for (mem, interval), x in r.groupby(["mem", "interval"]):
        rows.append({"memory MB": mem, "gap between calls s": interval, "runs": len(x),
                     "instances per run (mean)": x["containers"].mean(), "max": int(x["containers"].max()),
                     "runs with >1 instance": f"{int((x['containers'] > 1).sum())}/{len(x)}",
                     "first call on a new instance (median index)": x["first_extra_call"].median()})
    out.append("\n## E1b · Instances used by one sequential client (handshake + 40 calls after a forced cold start)\n")
    out.append("One client, one request at a time; any instance beyond the first is a cold start the client did not need.\n")
    out.append(md_table(pd.DataFrame(rows), {"instances per run (mean)": 2, "gap between calls s": 2}) + "\n")


# --- E3: time split + E5 billing ------------------------------------------------------------------

def e3_frame(df):
    d = df[(df["exp"] == "e3") & (df["phase"] == "tools/call") & (df["call"] >= 2) & ~df["cold"]].copy()
    if d.empty:
        return d
    d["delay_us"] = d["latency_ms"] * 1000
    d["up_net_us"] = d["m_upstream_wait_us"] - d["delay_us"]
    d["connect_us_up"] = d["m_upstream_connect_us"]
    d["process_us"] = d["m_process_us"]
    d["other_in_us"] = d["exec_us"] - d["m_upstream_wait_us"] - d["m_upstream_connect_us"] - d["m_process_us"]
    d["outside_us"] = d["client_us"] - d["exec_us"]
    d["config"] = d.apply(lambda r: (f"api-proxy, {int(r.latency_ms)} ms upstream" + ("" if r.reuse else ", new connection each call"))
                          if r.fn == "610" else f"fetch-markdown, {int(r['size']) // 1000:,} KB page", axis=1)
    order = {c: i for i, c in enumerate([
        "api-proxy, 50 ms upstream", "api-proxy, 200 ms upstream", "api-proxy, 1000 ms upstream",
        "api-proxy, 200 ms upstream, new connection each call",
        "fetch-markdown, 10 KB page", "fetch-markdown, 200 KB page", "fetch-markdown, 1,000 KB page"])}
    d["order"] = d["config"].map(order)
    return d


def e3(d, out):
    if d.empty:
        return
    g = d.groupby(["mem", "order", "config"]).agg(
        n=("client_us", "size"), client=("client_us", "median"), delay=("delay_us", "median"),
        up_net=("up_net_us", "median"), connect=("connect_us_up", "median"), process=("process_us", "median"),
        other=("other_in_us", "median"), outside=("outside_us", "median")).reset_index().sort_values(["mem", "order"])
    rows = [{"memory MB": r.mem, "configuration": r.config, "calls": r.n, "client p50": ms(r.client),
             "upstream delay (set)": ms(r.delay), "upstream network+HTTP": ms(r.up_net), "upstream connect": ms(r.connect),
             "local processing": ms(r.process), "other in function": ms(r.other), "outside function": ms(r.outside)}
            for r in g.itertuples()]
    out.append("\n## E3 · Where a warm tool call's time goes (medians, ms)\n")
    out.append("Warm calls only (first 2 calls of each run and cold calls dropped). Upstream = mock API on the EC2 VM in the same region.\n")
    out.append(md_table(pd.DataFrame(rows)) + "\n")


def e3_figure(d, path):
    if d.empty:
        return
    mems = sorted(d["mem"].unique())
    configs = d.drop_duplicates("config").sort_values("order")["config"].tolist()
    seg = [("waiting on the upstream (set delay + network + connect)", "wait_us"),
           ("local work in the function", "local_us"),
           ("platform + protocol (outside the function)", "outside_us")]
    fig, axes = plt.subplots(1, len(mems), figsize=(3.4 * len(mems) + 2.4, 3.2), sharey=True, sharex=True)
    axes = np.atleast_1d(axes)
    for ax, mem in zip(axes, mems):
        x = d[d["mem"] == mem]
        x = x.assign(local_us=x["process_us"] + x["other_in_us"].clip(lower=0),
                     wait_us=x["m_upstream_wait_us"] + x["connect_us_up"])
        med = x.groupby("config")[["wait_us", "local_us", "outside_us"]].median()
        med = med.reindex(configs)
        values = [(label, (med[col].clip(lower=0) / 1000).tolist()) for label, col in seg]
        pos = np.arange(len(configs))[::-1]
        totals = stacked_bars(ax, pos, values, SERIES[:3], horizontal=True, width=0.62)
        for p, t in zip(pos, totals):
            ax.text(t + 15, p, f"{t:,.0f}", va="center", fontsize=7.5, color=INK2)
        ax.set_title(f"{mem} MB", fontsize=9.5)
        style_axis(ax, "x")
        ax.set_xlabel("ms (medians)")
    axes[0].set_yticks(np.arange(len(configs))[::-1], configs, fontsize=8)
    for ax in axes:
        ax.set_xlim(0, d.groupby(["mem", "config"])["client_us"].median().max() / 1000 * 1.18)
    fig.suptitle("Warm tool calls: waiting dominates the API tool, processing dominates fetch at low memory",
                 x=0.01, ha="left", fontweight="bold", fontsize=10.5, color=INK)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, ncol=3, loc="lower left", bbox_to_anchor=(0.01, -0.06), fontsize=8, handlelength=1)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def e5(d, df, out):
    b = d[d["billed_ms"].notna()].copy()
    if b.empty:
        out.append("\n## E5 · Billing\n\nNo REPORT lines matched yet (run the `logs` step).\n")
        return pd.DataFrame()
    b["gb_s"] = b["billed_ms"] / 1000 * b["mem"] / 1024
    b["lambda_per_M"] = (b["gb_s"] * LAMBDA_GB_S + LAMBDA_REQUEST) * 1e6
    b["wait_share"] = b["m_upstream_wait_us"] / (b["billed_ms"] * 1000)
    b["cpu_ms"] = b["cpu_us"] / 1000
    b["cpu_per_M"] = (b["cpu_ms"] * CPU_MS + CPU_REQUEST) * 1e6
    b["billed_minus_delay"] = b["billed_ms"] - b["latency_ms"]
    g = b.groupby(["mem", "order", "config"]).agg(
        n=("billed_ms", "size"), billed=("billed_ms", "median"), billed_p99=("billed_ms", q(99)),
        over=("billed_minus_delay", "median"), over_p99=("billed_minus_delay", q(99)),
        wait=("wait_share", "median"), cpu=("cpu_ms", "median"), lam=("lambda_per_M", "mean"),
        cpu_cost=("cpu_per_M", "mean")).reset_index().sort_values(["mem", "order"])
    rows = [{"memory MB": r.mem, "configuration": r.config, "calls": r.n, "billed ms p50": r.billed, "p99": r.billed_p99,
             "billed − upstream delay p50 / p99": f"{r.over:.0f} / {r.over_p99:.0f}",
             "share of billed time waiting on upstream": f"{100 * r.wait:.0f}%", "CPU ms p50": r.cpu,
             "Lambda $ per 1M calls": r.lam, "CPU-time billing $ per 1M calls": r.cpu_cost}
            for r in g.itertuples()]
    out.append("\n## E5 · Billing (warm calls of E3, joined with Lambda REPORT lines)\n")
    out.append(f"Lambda: billed duration × memory at ${LAMBDA_GB_S:.10f}/GB-s + ${LAMBDA_REQUEST * 1e6:.2f} per 1M requests (eu-north-1, x86). "
               f"CPU-time billing: the same calls' measured CPU time at ${CPU_MS * 1e6:.2f} per 1M CPU-ms + ${CPU_REQUEST * 1e6:.2f} per 1M requests "
               "(Cloudflare Workers Standard rates, beyond included quota) — a billing-model comparison on identical work, not a platform comparison.\n")
    out.append(md_table(pd.DataFrame(rows), {"billed ms p50": 0, "p99": 0, "CPU ms p50": 1,
                                             "Lambda $ per 1M calls": 2, "CPU-time billing $ per 1M calls": 2}) + "\n")

    hs = df[(df["exp"] == "e1hs") & df["billed_ms"].notna() & ~df["cold"]]
    if not hs.empty:
        per = hs.groupby(["mem", "phase"])["billed_ms"].median().unstack()
        out.append("\n**Billed duration of the handshake requests (warm, p50 ms):** " + "; ".join(
            f"{mem} MB: " + ", ".join(f"{p} {per.loc[mem, p]:.0f}" for p in per.columns) for mem in per.index) + "\n")
    return b


def e5_figure(b, path):
    if b is None or b.empty:
        return
    mems = sorted(b["mem"].unique())
    configs = b.drop_duplicates("config").sort_values("order")["config"].tolist()
    series = [(f"Lambda, {m} MB", b[b["mem"] == m].groupby("config")["lambda_per_M"].mean().reindex(configs)) for m in mems]
    top = max(mems)
    series.append((f"CPU-time billing (CPU measured at {top} MB)", b[b["mem"] == top].groupby("config")["cpu_per_M"].mean().reindex(configs)))
    fig, ax = plt.subplots(figsize=(8.6, 3.6))
    y = np.arange(len(configs))[::-1]
    offsets = np.linspace(-0.27, 0.27, len(series))
    for (label, vals), off, color in zip(series, offsets, SERIES):
        ax.scatter(vals.values, y + off, s=34, color=color, label=label, zorder=3, edgecolor=SURFACE, linewidth=1.5)
    ax.set_xscale("log")
    ticks = [0.3, 1, 3, 10, 30]
    ax.set_xticks(ticks, [f"${t:g}" if t >= 1 else f"${t:.2f}" for t in ticks])
    ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.set_yticks(y, configs, fontsize=8)
    ax.set_xlabel("$ per 1 million warm tool calls (log scale)")
    style_axis(ax, "x")
    ax.grid(axis="x", which="minor", color=GRID, linewidth=0.3)
    ax.set_title("Cost per million tool calls: wall-clock billing charges for the wait")
    ax.legend(ncol=2, loc="lower left", bbox_to_anchor=(0, -0.42), fontsize=8, handletextpad=0.3)
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


# --- E4: trace replay -------------------------------------------------------------------------------

def e4(root, out):
    files = sorted(glob.glob(os.path.join(root, "e4", "*", "replay-a*.jsonl")))
    if not files:
        return pd.DataFrame()
    rows = []
    for path in files:
        interval = float(os.path.basename(path)[len("replay-a"):-len(".jsonl")])
        recs = pd.read_json(path, lines=True)
        recs["interval"] = interval
        rows.append(recs)
    return pd.concat(rows, ignore_index=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("campaign")
    p.add_argument("--figures", default="docs/figures/aws")
    args = p.parse_args()
    os.makedirs(args.figures, exist_ok=True)
    df, reports = load(args.campaign)
    out = [f"# AWS Lambda campaign `{os.path.basename(os.path.normpath(args.campaign))}` — generated tables\n",
           f"{len(df):,} client records; {len(reports):,} Lambda REPORT lines; "
           f"{int(df['billed_ms'].notna().sum()) if 'billed_ms' in df else 0:,} records matched to a REPORT line.\n"]
    e1(df, out)
    e1_figure(df, os.path.join(args.figures, "e1-session-setup.png"))
    s = e2(df, out)
    e2_figure(df, s, os.path.join(args.figures, "e2-cold-start.png"))
    e1b(df, out)
    d = e3_frame(df)
    e3(d, out)
    e3_figure(d, os.path.join(args.figures, "e3-time-split.png"))
    b = e5(d, df, out)
    e5_figure(b, os.path.join(args.figures, "e5-cost.png"))
    replay = e4(args.campaign, out)
    if not replay.empty:
        replay_tables(replay, reports, out)
        e4_figure(replay, os.path.join(args.figures, "e4-replay-cold-starts.png"))
    with open(os.path.join(args.campaign, "summary.md"), "w") as f:
        f.write("\n".join(out) + "\n")
    print("\n".join(out))


def _replay_sessions(r):
    calls_ = r[r["type"] == "call"]
    starts = (calls_["t_start_ms"] - calls_["think_ms"].fillna(0)).groupby(calls_["session"]).min()
    sess = r[r["type"] == "session"].set_index("session")
    sess["start_ms"] = starts
    sess["end_ms"] = sess["start_ms"] + sess["wall_ms"]
    return sess


def _peak_concurrency(sess):
    events = sorted([(t, 1) for t in sess["start_ms"].dropna()] + [(t, -1) for t in sess["end_ms"].dropna()],
                    key=lambda e: (e[0], e[1]))
    level = peak = 0
    for _, step in events:
        level += step
        peak = max(peak, level)
    return peak


def _cold_breakdown(x):
    """Cold starts of one replay run: each endpoint's first one is its first use after the forced start;
    the rest are extra instances, split by whether the handshake or a tool call hit them."""
    cold = x[x["type"].isin(["init", "call"]) & x["is_cold"].eq(True)].sort_values("ts")
    first_use = cold.groupby("endpoint").head(1).index
    extra = cold.drop(first_use)
    return {"first_use": len(first_use), "extra_handshake": int((extra["type"] == "init").sum()),
            "extra_call": int((extra["type"] == "call").sum())}


def replay_tables(r, reports, out):
    if "amzn_request_id" in r and not reports.empty:
        r = r.merge(reports[["request_id", "billed_ms", "memory_mb"]].rename(columns={"request_id": "amzn_request_id"}),
                    on="amzn_request_id", how="left")
    rows, bill = [], []
    for interval, x in r.groupby("interval"):
        sess = _replay_sessions(x)
        c = x[(x["type"] == "call") & ~x.get("skipped", pd.Series(False, index=x.index)).fillna(False).astype(bool)]
        ok = c[c["error"].isna()] if "error" in c else c
        init = x[x["type"] == "init"]
        cold_calls, cold_inits = int(ok["is_cold"].eq(True).sum()), int(init["is_cold"].eq(True).sum())
        n_sess = len(sess)
        cb = _cold_breakdown(x)
        rows.append({"session arrival interval s": interval, "sessions": n_sess,
                     "peak concurrent sessions": _peak_concurrency(sess), "tool calls": len(ok),
                     "errors": len(c) - len(ok),
                     "cold starts on handshake": cold_inits, "cold starts on tool calls": cold_calls,
                     "first use of a tool": cb["first_use"],
                     "extra instances (handshake / tool call)": f"{cb['extra_handshake']} / {cb['extra_call']}",
                     "instances (all endpoints)": ok.groupby("endpoint")["container_id"].nunique().sum(),
                     "tool call p50 ms": ms(ok["client_us"].median()), "tool call p95 ms": ms(ok["client_us"].quantile(0.95)),
                     "cold tool call p50 ms": ms(ok.loc[ok["is_cold"].eq(True), "client_us"].median()),
                     "tool share of session time p50": f"{100 * (sess['tools_ms'] / sess['wall_ms']).median():.1f}%"})
        if "billed_ms" in x and x["billed_ms"].notna().any():
            mem = x["memory_mb"].dropna().iloc[0]
            inv = x[x["type"].isin(["init", "call"]) & x["amzn_request_id"].notna()]
            hs = inv[inv["type"] == "init"]
            gb_s = inv["billed_ms"].sum() / 1000 * mem / 1024
            bill.append({"session arrival interval s": interval, "invocations": len(inv),
                         "of which handshake": f"{len(hs)} ({100 * len(hs) / max(len(inv), 1):.0f}%)",
                         "billed GB-s": gb_s,
                         "handshake share of billed GB-s": f"{100 * hs['billed_ms'].sum() / max(inv['billed_ms'].sum(), 1):.0f}%",
                         "Lambda $ per 1,000 sessions": 1000 * (gb_s * LAMBDA_GB_S + len(inv) * LAMBDA_REQUEST) / max(n_sess, 1)})
    out.append("\n## E4 · Agent trace replay at three session arrival rates (LiveMCPBench, Claude Sonnet 4 run; modeled LLM time)\n")
    out.append("Each run starts from no warm instances (forced). Sessions connect to all their servers at start (eager handshake).\n")
    out.append("*First use of a tool*: each endpoint's first cold start in the run (the run starts with no warm instances). "
               "*Extra instances*: later cold starts, when overlapping sessions needed another instance.\n")
    out.append(md_table(pd.DataFrame(rows), {"session arrival interval s": 0}) + "\n")
    if bill:
        out.append("\n**Replay billing** (all invocations, matched to REPORT lines)\n")
        out.append(md_table(pd.DataFrame(bill), {"billed GB-s": 1, "Lambda $ per 1,000 sessions": 3, "session arrival interval s": 0}) + "\n")


def e4_figure(r, path):
    rows = []
    for interval, x in r.groupby("interval"):
        sess = _replay_sessions(x)
        rows.append((interval, _cold_breakdown(x), _peak_concurrency(sess), len(sess)))
    rows.sort(key=lambda row: row[0])
    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    pos = np.arange(len(rows))
    totals = stacked_bars(ax, pos, [
        ("first use of each tool (run starts cold)", [row[1]["first_use"] for row in rows]),
        ("extra instance, absorbed by the handshake", [row[1]["extra_handshake"] for row in rows]),
        ("extra instance, hit a tool call", [row[1]["extra_call"] for row in rows])], SERIES[:3], width=0.5)
    for p, t in zip(pos, totals):
        ax.text(p, t + 0.15, f"{t:.0f}", ha="center", color=INK2, fontsize=8)
    ax.set_xticks(pos, [f"a session every {row[0]:g} s\n(peak {row[2]} at once)" for row in rows], fontsize=8)
    ax.set_ylabel(f"cold starts per run of {rows[0][3]} sessions")
    ax.set_ylim(0, max(totals) * 1.25)
    style_axis(ax)
    ax.set_title("Replayed agent sessions: beyond each tool's first use, overlap adds few cold starts")
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.22), fontsize=8, ncol=2)
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
