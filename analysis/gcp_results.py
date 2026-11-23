#!/usr/bin/env python3
"""Tables and figures for a GCP campaign (Cloud Run functions gen2, concurrency 1): E1-E5 as on AWS.

    serverless-benchmarks/.venv/bin/python analysis/gcp_results.py results/gcp/<campaign> [--figures docs/figures/gcp]

Reads the client records written by experiments/gcp_campaign.py, Cloud Run's request log (requests.jsonl:
instance, latency, status per request, joined by trace_id) and system log (system.jsonl: instance starts with
their reason, startup probes), and configs.jsonl (revision -> tier/boost). Writes <campaign>/summary.md and
PNG figures. Needs pandas and matplotlib (the SeBS venv has both).

Cold-start sessions (e2, e1b) count only if experiments/gcp_session_check.py classifies them as clean: the
first request started a new AUTOSCALING instance itself, and no request was moved or queued behind a hold.

Differences from the AWS analysis that matter when comparing numbers:
- Cloud Run's request-log latency leaves out most of a cold start, so cold-start times come from the client
  and from the system log's startup-probe timestamps, not from the platform's latency.
- `cpu_us` has 10 ms resolution on Cloud Run: per-call CPU medians are meaningless, means over many calls aren't.
- Billing is computed (no per-request billing record exists): request-log latency rounded up to Cloud Run's
  billing granularity, at the prices below.
"""

import argparse
import collections
import glob
import json
import math
import os
import re
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "experiments"))
import gcp_session_check as check  # noqa: E402
from aws_results import (INK, INK2, MUTED, SERIES, SURFACE, _peak_concurrency, _replay_sessions, e3_figure,  # noqa: E402
                         e3_frame, md_table, ms, plt, q, stacked_bars, style_axis)

# Cloud Run request-based billing (CPU allocated only during requests), Tier 1 region (europe-west1).
# NOT VERIFIED against the current price page: the fetch on 2026-11-22 returned no content. These are the list
# prices and the rounding rule as of 2025. Check https://cloud.google.com/run/pricing before quoting $ figures.
RUN_VCPU_S = 0.000024
RUN_GIB_S = 0.0000025
RUN_REQUEST = 0.40 / 1e6
RUN_GRANULARITY_MS = 100
PRICES_VERIFIED = False

TIERS = {"m128c0.083": (128, 0.083), "m512c0.333": (512, 0.333), "m2048c1": (2048, 1.0)}
SHORT = {"010": "no-op", "110": "dynamic-html", "610": "api-proxy", "620": "fetch-markdown",
         "610s": "api-proxy (SDK)", "620s": "fetch-markdown (SDK)"}
FN_ORDER = ["010", "110", "610", "620", "610s", "620s"]
REASON = re.compile(r"Starting new instance\. Reason: (\w+)")


def tier_name(mem, vcpu):
    return f"{int(mem)} MB / {vcpu:g} vCPU"


def billable_ms(latency_ms):
    return np.ceil(latency_ms / RUN_GRANULARITY_MS) * RUN_GRANULARITY_MS


def run_cost_per_million(billable_ms_, mem_mb, vcpu):
    s = billable_ms_ / 1000
    return (s * (vcpu * RUN_VCPU_S + mem_mb / 1024 * RUN_GIB_S) + RUN_REQUEST) * 1e6


# --- loading -------------------------------------------------------------------------------------

class Logs:
    """Cloud Run request and system logs of the campaign."""

    def __init__(self, root):
        self.requests, self.starts, self.kills, self.holds = check.load(root)
        self.probe = {}
        self.start_events = []  # (instance, revision, fn, time, reason)
        for line in open(os.path.join(root, "system.jsonl")):
            e = json.loads(line)
            inst, text = e.get("instance"), e.get("text") or ""
            if not inst:
                continue
            m = REASON.search(text)
            if m:
                self.start_events.append((inst, e.get("revision"), e.get("fn"), check.epoch(e["timestamp"]), m.group(1)))
            elif "STARTUP TCP probe succeeded" in text and inst not in self.probe:
                self.probe[inst] = check.epoch(e["timestamp"])
        self.configs = {}
        cpath = os.path.join(root, "configs.jsonl")
        for line in open(cpath) if os.path.exists(cpath) else []:
            c = json.loads(line)
            self.configs[c["revision"]] = c

    def request_frame(self):
        return pd.DataFrame([{"trace_id": k, "req_instance": r["instance"], "req_revision": r.get("revision"),
                              "req_status": r.get("status"), "req_latency_ms": (r.get("latency_s") or np.nan) * 1000,
                              "req_t": r["t"]} for k, r in self.requests.items()])


def load(root, logs):
    rows = []
    for exp in ("e1", "e1b", "e1wan", "e2", "e3"):
        for path in sorted(glob.glob(os.path.join(root, exp, "**", "*.jsonl"), recursive=True)):
            for seq, line in enumerate(open(path)):
                r = json.loads(line)
                r["file"] = os.path.relpath(path, root)
                r["seq"] = seq
                rows.append(r)
    df = pd.DataFrame(rows)
    for col in ("call", "exec_us", "import_us", "init_import_us", "cpu_us", "is_cold", "container_id", "trace_id"):
        if col not in df:
            df[col] = np.nan
    df["mem"] = df["memory_mb"]
    df["vcpu"] = df["cpu"].astype(float)
    df["cold"] = df["is_cold"].eq(True)
    df = df.merge(logs.request_frame(), on="trace_id", how="left")
    return df


def clean_sessions(root, logs):
    """path -> classification row from gcp_session_check, for every e2/e1b session."""
    out = {}
    for exp, path, recs in check.sessions(root):
        row = check.classify(recs, logs.requests, logs.starts, logs.kills, logs.holds, (0.5, 3.0))
        row["clean"] = row["class"] == "ok" and not row.get("moved") and not row.get("behind_sleeper")
        out[path] = row
    return out


def calls(df):
    return df[df["phase"].isin(["tools/call", "plain"])]


# --- platform behaviour: instance starts ------------------------------------------------------------

def instance_starts(root, logs, out):
    ev = pd.DataFrame(logs.start_events, columns=["instance", "revision", "fn", "t", "reason"])
    if ev.empty:
        return
    total = ev["reason"].value_counts()
    per_rev = ev[ev["reason"] == "DEPLOYMENT_ROLLOUT"].groupby("revision").size()
    aborted = sum(len(glob.glob(os.path.join(root, "aborted", d, "**", "*.jsonl"), recursive=True))
                  for d in os.listdir(os.path.join(root, "aborted"))) if os.path.isdir(os.path.join(root, "aborted")) else 0
    out.append("## Instance starts (Cloud Run system log, whole campaign incl. aborted attempts)\n")
    out.append("| reason | instance starts |\n|---|---|\n" + "\n".join(f"| {r} | {n:,} |" for r, n in total.items()) + "\n")
    out.append(f"\nRevisions that got rollout instances: {len(per_rev):,}; rollout instances per revision: "
               f"median {per_rev.median():.0f}, p90 {per_rev.quantile(0.9):.0f}, max {per_rev.max()}. "
               "Every deployment of a new revision (which is how SeBS forces a cold start) pre-starts instances "
               "that boot and import the tool before any request arrives.\n")
    if aborted:
        out.append(f"\nSessions moved to `aborted/` (failed attempts and sessions that failed the cold-start check): {aborted} files.\n")


# --- E1: MCP vs plain, warm -------------------------------------------------------------------------

def e1(df, out):
    d = calls(df[(df["exp"] == "e1") & ~df["cold"]]).copy()
    if d.empty:
        return
    d["outside_us"] = d["client_us"] - d["exec_us"]
    d["front_us"] = d["client_us"] - d["req_latency_ms"] * 1000
    d["serving_us"] = d["req_latency_ms"] * 1000 - d["exec_us"]
    g = d.groupby(["mem", "vcpu", "fn", "mode"]).agg(
        n=("client_us", "size"), p50=("client_us", "median"), p90=("client_us", q(90)), exec=("exec_us", "median"),
        outside=("outside_us", "median"), front=("front_us", "median"), serving=("serving_us", "median"),
        resp=("response_bytes", "median"), slow=("client_us", lambda v: (v >= 60000).mean())).reset_index()
    rows = []
    for (mem, vcpu, fn), x in g.groupby(["mem", "vcpu", "fn"]):
        m, p = x[x["mode"] == "mcp"].iloc[0], x[x["mode"] == "plain"].iloc[0]
        rows.append({"tier": tier_name(mem, vcpu), "tool": SHORT[fn], "calls/mode": int(min(m.n, p.n)),
                     "MCP p50 ms": ms(m.p50), "plain p50 ms": ms(p.p50), "MCP − plain p50 ms": ms(m.p50 - p.p50),
                     "MCP p90 ms": ms(m.p90), "plain p90 ms": ms(p.p90),
                     "calls ≥ 60 ms (MCP / plain)": f"{100 * m.slow:.0f}% / {100 * p.slow:.0f}%",
                     "in function p50 ms (MCP)": ms(m.exec),
                     "outside function p50 ms (MCP / plain)": f"{ms(m.outside):.1f} / {ms(p.outside):.1f}",
                     "… client ↔ Google front end (MCP)": ms(m.front), "… Cloud Run serving path (MCP)": ms(m.serving),
                     "response bytes (MCP / plain)": f"{int(m.resp):,} / {int(p.resp):,}"})
    out.append("\n## E1 · MCP vs plain invocation, warm (client VM in europe-west1)\n")
    out.append("Cold calls excluded. *Outside function* = client time − time inside the handler; split with Cloud Run's "
               "request-log latency into the path client ↔ Google front end and the path front end → instance → back. "
               "*Calls ≥ 60 ms*: at 0.083 vCPU warm calls are bimodal (≈11 ms or ≈90 ms), consistent with CPU-quota throttling "
               "in 100 ms periods: a request that exhausts its slice waits for the next period.\n")
    out.append(md_table(pd.DataFrame(rows)) + "\n")
    for exp, title in (("e1hs", "VM in europe-west1"), ("e1wan-hs", "workstation (wide area)")):
        sd = handshake_sessions(df[df["exp"] == exp])
        if sd.empty:
            continue
        rows = []
        for (mem, vcpu), x in sd.groupby(["mem", "vcpu"]):
            w = x[~x["cold"]]
            rows.append({"tier": tier_name(mem, vcpu), "sessions (cold excluded)": f"{len(w)} ({int(x['cold'].sum())})",
                         "TCP+TLS connect": ms(w["connect"].median()), "initialize": ms(w["initialize"].median()),
                         "notifications/initialized": ms(w["notification"].median()),
                         "tools/list": ms(w["tools/list"].median()), "handshake total": ms(w["handshake"].median()),
                         "first tools/call": ms(w["first call"].median())})
        out.append(f"\n**MCP session setup, warm no-op function, client = {title}** (medians, ms; new connection per session)\n")
        out.append(md_table(pd.DataFrame(rows)) + "\n")
    w = calls(df[(df["exp"] == "e1wan") & ~df["cold"]])
    if not w.empty:
        g = w.groupby("mode")["client_us"].agg(["size", "median", q(90)])
        out.append("\n**Workstation → europe-west1, dynamic-html, warm** (ms): " + ", ".join(
            f"{mode}: p50 {ms(r['median']):.1f}, p90 {ms(r.iloc[2]):.1f} (n={int(r['size'])})" for mode, r in g.iterrows()) + "\n")


def handshake_sessions(h):
    sess = []
    for f, s in h.groupby("file"):
        ph = s.drop_duplicates("phase").set_index("phase")
        if not {"initialize", "notifications/initialized", "tools/list", "tools/call"} <= set(ph.index):
            continue
        sess.append({"mem": s["mem"].iloc[0], "vcpu": s["vcpu"].iloc[0], "connect": ph.loc["initialize", "connect_us"],
                     "initialize": ph.loc["initialize", "client_us"] - ph.loc["initialize", "connect_us"],
                     "notification": ph.loc["notifications/initialized", "client_us"],
                     "tools/list": ph.loc["tools/list", "client_us"],
                     "handshake": ph.loc[["initialize", "notifications/initialized", "tools/list"], "client_us"].sum(),
                     "first call": ph.loc["tools/call", "client_us"], "cold": bool(s["cold"].any())})
    return pd.DataFrame(sess)


# --- E2: cold vs warm -------------------------------------------------------------------------------

def e2_sessions(df, sessions, logs):
    d = df[df["exp"] == "e2"]
    rows = []
    for f, s in d.groupby("file"):
        chk = sessions.get(f)
        if not chk or not chk["clean"]:
            continue
        s = s.sort_values("seq")
        first = s.iloc[0]
        c = calls(s)
        call0 = c[c["call"] == 0].iloc[0]
        warm = c[(c["call"] >= 1) & ~c["cold"]]
        req = logs.requests.get(first["trace_id"])
        listen = logs.probe.get(req["instance"]) - req["t"] if req and req["instance"] in logs.probe else np.nan
        if first["mode"] == "mcp":
            hs = s.drop_duplicates("phase").set_index("phase").loc[
                ["initialize", "notifications/initialized", "tools/list"], "client_us"].sum()
        else:
            hs = 0.0
        rows.append({"mem": first["mem"], "vcpu": first["vcpu"], "boost": bool(first["boost"]), "fn": first["fn"],
                     "mode": first["mode"], "rep": first["rep"], "first_request_us": first["client_us"],
                     "first_result_us": hs + call0["client_us"], "warm_us": warm["client_us"].median(),
                     "listen_ms": listen * 1000, "call_import_us": call0["import_us"],
                     "startup_import_us": s["init_import_us"].max(), "instances": s["req_instance"].nunique()})
    return pd.DataFrame(rows)


def e2(s, out):
    if s.empty:
        return
    rows = []
    for (mem, vcpu, boost, fn, mode), x in s.groupby(["mem", "vcpu", "boost", "fn", "mode"]):
        imp = x["startup_import_us"] if fn.endswith("s") else x["call_import_us"]
        rows.append({"tier": tier_name(mem, vcpu), "boost": "on" if boost else "off", "tool": SHORT[fn], "mode": mode,
                     "sessions": len(x), "cold first result p50 ms": ms(x["first_result_us"].median()),
                     "p25–p75 ms": f"{ms(x['first_result_us'].quantile(.25)):,.0f}–{ms(x['first_result_us'].quantile(.75)):,.0f}",
                     "container listening after p50 ms": x["listen_ms"].median(),
                     "warm call p50 ms": ms(x["warm_us"].median()),
                     "cold penalty ms": ms(x["first_result_us"].median() - x["warm_us"].median()),
                     "tool import p50 ms": ms(imp.median()),
                     "sessions on >1 instance": f"{int((x['instances'] > 1).sum())}/{len(x)}"})
    out.append("\n## E2 · Cold vs warm (request-triggered cold start; clean sessions only)\n")
    out.append("*Cold first result*: MCP = handshake + first tools/call; plain = first invocation. "
               "*Container listening after*: request arrival → the instance's startup TCP probe succeeded (system log): "
               "sandbox, Python and functions-framework boot, plus, for the SDK variants, the SDK import (they import at module load). "
               "*Tool import*: stdlib tools import lazily in the first call; SDK variants at instance startup (reported only on the MCP path). "
               "*Sessions on >1 instance*: requests of one session served by different instances (request log); at 0.083 vCPU "
               "without boost, the handshake's later requests can land on further instances that Cloud Run started during the "
               "first one's slow boot, each with its own cold start.\n")
    out.append(md_table(pd.DataFrame(rows), {"container listening after p50 ms": 0}) + "\n")

    # Boost effect, pooled over MCP and plain: the first request carries the cold start either way.
    rows = []
    for fn in [f for f in FN_ORDER if f in set(s["fn"])]:
        row = {"tool": SHORT[fn]}
        for (mem, vcpu) in sorted({(m, v) for m, v in zip(s["mem"], s["vcpu"])}):
            cell = []
            for boost in (False, True):
                x = s[(s["fn"] == fn) & (s["mem"] == mem) & (s["boost"] == boost)]["first_request_us"]
                cell.append(f"{ms(x.median()) / 1000:.2f} s (n={len(x)})" if len(x) else "–")
            row[tier_name(mem, vcpu)] = " / ".join(cell)
        rows.append(row)
    out.append("\n**Startup CPU boost: first response of a cold session, boost off / on** (p50, MCP and plain pooled; "
               "the first request is `initialize` or the first plain call)\n")
    out.append(md_table(pd.DataFrame(rows)) + "\n")


def e2_figure(s, path):
    if s.empty:
        return
    tiers = sorted({(m, v) for m, v in zip(s["mem"], s["vcpu"])})
    fns = [f for f in FN_ORDER if f in set(s["fn"])]
    fig, axes = plt.subplots(1, len(tiers), figsize=(3.0 * len(tiers) + 0.8, 3.4), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, (mem, vcpu) in zip(axes, tiers):
        for j, (boost, color, label) in enumerate(((False, SERIES[1], "startup CPU boost off"),
                                                   (True, SERIES[0], "startup CPU boost on (GCP default)"))):
            for i, fn in enumerate(fns):
                x = s[(s["fn"] == fn) & (s["mem"] == mem) & (s["vcpu"] == vcpu) & (s["boost"] == boost)]["first_request_us"] / 1e6
                if x.empty:
                    if fn.endswith("s") and mem < 256 and j == 0:
                        ax.text(i, 1.0, "does not fit\nin 128 MiB", ha="center", va="center", fontsize=6.5, color=MUTED)
                    continue
                pos = i + (j - 0.5) * 0.3
                ax.vlines(pos, x.quantile(.25), x.quantile(.75), color=color, linewidth=2, alpha=0.5)
                ax.scatter([pos], [x.median()], s=30, color=color, edgecolor=SURFACE, linewidth=1.2, zorder=3,
                           label=label if i == 0 else None)
                ax.text(pos, x.quantile(.75) * 1.12, f"{len(x)}", ha="center", fontsize=6, color=MUTED)
        ax.set_yscale("log")
        ax.set_xticks(range(len(fns)), [SHORT[f] for f in fns], rotation=40, ha="right", fontsize=7.5)
        ax.set_xlim(-0.6, len(fns) - 0.4)
        ax.set_title(tier_name(mem, vcpu), fontsize=9.5)
        style_axis(ax)
    axes[0].set_ylabel("first response of a cold session, s (log)")
    axes[0].set_yticks([0.3, 1, 3, 10, 30], ["0.3", "1", "3", "10", "30"])
    fig.suptitle("GCP cold starts: at fractional vCPU, the startup CPU boost decides between ~1 s and ~10 s",
                 x=0.01, ha="left", fontweight="bold", fontsize=10.5, color=INK)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, ncol=2, loc="lower left", bbox_to_anchor=(0.01, -0.06), fontsize=8)
    fig.text(0.99, -0.05, "dot: median, bar: p25–p75, number: clean sessions", ha="right", fontsize=7, color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


# --- E1b ----------------------------------------------------------------------------------------------

def e1b(df, sessions, out):
    d = df[df["exp"] == "e1b"]
    runs = []
    for f, s in d.groupby("file"):
        if not sessions.get(f, {}).get("clean"):
            continue
        s = s.sort_values("seq")
        insts = s["req_instance"].dropna()
        runs.append({"mem": s["mem"].iloc[0], "vcpu": s["vcpu"].iloc[0], "fn": s["fn"].iloc[0],
                     "interval": s["interval"].iloc[0], "instances": insts.nunique()})
    if not runs:
        return
    r = pd.DataFrame(runs)
    rows = [{"tier": tier_name(mem, vcpu), "gap between calls s": interval, "runs (clean)": len(x),
             "instances per run (mean)": x["instances"].mean(), "max": int(x["instances"].max())}
            for (mem, vcpu, interval), x in r.groupby(["mem", "vcpu", "interval"])]
    out.append("\n## E1b · Instances used by one sequential client (handshake + 40 calls after a cold start)\n")
    out.append("Instances from Cloud Run's request log. Few runs passed the cold-start check, so this is indicative only.\n")
    out.append(md_table(pd.DataFrame(rows), {"instances per run (mean)": 2, "gap between calls s": 2}) + "\n")


# --- E3 + E5 -----------------------------------------------------------------------------------------

def e3(d, out):
    if d.empty:
        return
    g = d.groupby(["mem", "vcpu", "order", "config"]).agg(
        n=("client_us", "size"), client=("client_us", "median"), delay=("delay_us", "median"),
        up_net=("up_net_us", "median"), connect=("connect_us_up", "median"), process=("process_us", "median"),
        other=("other_in_us", "median"), outside=("outside_us", "median"),
        cpu=("cpu_us", "mean")).reset_index().sort_values(["mem", "order"])
    rows = [{"tier": tier_name(r.mem, r.vcpu), "configuration": r.config, "calls": r.n, "client p50": ms(r.client),
             "upstream delay (set)": ms(r.delay), "upstream network+HTTP": ms(r.up_net), "upstream connect": ms(r.connect),
             "local processing": ms(r.process), "other in function": ms(r.other), "outside function": ms(r.outside),
             "CPU ms (mean)": ms(r.cpu)} for r in g.itertuples()]
    out.append("\n## E3 · Where a warm tool call's time goes (medians, ms)\n")
    out.append("Warm calls only (first 2 calls of each run and cold calls dropped). Upstream = mock API on the client VM in the same region. "
               "CPU is a mean: Cloud Run's process CPU clock has 10 ms resolution.\n")
    out.append(md_table(pd.DataFrame(rows)) + "\n")


def e5(d, df, out):
    b = d[d["req_latency_ms"].notna()].copy()
    if b.empty:
        return pd.DataFrame()
    b["billable_ms"] = billable_ms(b["req_latency_ms"])
    b["run_per_M"] = run_cost_per_million(b["billable_ms"], b["mem"], b["vcpu"])
    b["exact_per_M"] = run_cost_per_million(b["req_latency_ms"], b["mem"], b["vcpu"])
    b["wait_share"] = b["m_upstream_wait_us"] / (b["billable_ms"] * 1000)
    g = b.groupby(["mem", "vcpu", "order", "config"]).agg(
        n=("billable_ms", "size"), lat=("req_latency_ms", "median"), billed=("billable_ms", "median"),
        billed_p99=("billable_ms", q(99)), wait=("wait_share", "median"), cost=("run_per_M", "mean"),
        exact=("exact_per_M", "mean")).reset_index().sort_values(["mem", "order"])
    rows = [{"tier": tier_name(r.mem, r.vcpu), "configuration": r.config, "calls": r.n,
             "Cloud Run latency p50 ms": r.lat, "billable ms p50 / p99": f"{r.billed:.0f} / {r.billed_p99:.0f}",
             "share of billable time waiting on upstream": f"{100 * r.wait:.0f}%",
             "$ per 1M calls": r.cost, "… with 1 ms granularity": r.exact,
             "rounding surcharge": f"{100 * (r.cost / r.exact - 1):.0f}%"} for r in g.itertuples()]
    out.append("\n## E5 · Billing (warm calls of E3; computed from Cloud Run's request-log latency)\n")
    out.append(f"Request-based billing: billable time = request latency rounded up to {RUN_GRANULARITY_MS} ms (concurrency 1, so per "
               f"request), × (vCPU × ${RUN_VCPU_S}/vCPU-s + GiB × ${RUN_GIB_S}/GiB-s) + ${RUN_REQUEST * 1e6:.2f} per 1M requests. "
               + ("" if PRICES_VERIFIED else "**Prices and rounding rule not verified against the current price page; check before quoting $.** ")
               + "Request-log latency slightly overestimates the instance's billable time (it includes the front end).\n")
    out.append(md_table(pd.DataFrame(rows), {"Cloud Run latency p50 ms": 1, "$ per 1M calls": 2, "… with 1 ms granularity": 2}) + "\n")

    hs = df[(df["exp"] == "e1hs") & ~df["cold"] & df["req_latency_ms"].notna()]
    if not hs.empty:
        hs = hs.assign(billable=billable_ms(hs["req_latency_ms"]))
        g = hs.groupby(["mem", "vcpu", "phase"]).agg(lat=("req_latency_ms", "median"), bill=("billable", "median")).reset_index()
        rows = []
        for (mem, vcpu), x in g.groupby(["mem", "vcpu"]):
            x = x.set_index("phase")
            hs_phases = [p for p in ("initialize", "notifications/initialized", "tools/list") if p in x.index]
            rows.append({"tier": tier_name(mem, vcpu),
                         **{f"{p} latency / billable ms": f"{x.loc[p, 'lat']:.1f} / {x.loc[p, 'bill']:.0f}" for p in hs_phases},
                         "handshake billable ms": x.loc[hs_phases, "bill"].sum()})
        out.append("\n**Handshake requests (warm, p50):** each is billed as a whole granule.\n")
        out.append(md_table(pd.DataFrame(rows), {"handshake billable ms": 0}) + "\n")
    return b


# --- E4: trace replay ---------------------------------------------------------------------------------

def e4(root, logs, out):
    files = sorted(glob.glob(os.path.join(root, "e4", "*", "replay-a*.jsonl")))
    if not files:
        return
    frames = []
    for path in files:
        r = pd.read_json(path, lines=True)
        r["interval"] = float(os.path.basename(path)[len("replay-a"):-len(".jsonl")])
        frames.append(r)
    r = pd.concat(frames, ignore_index=True).merge(logs.request_frame(), on="trace_id", how="left")
    start = {e[0]: (e[3], e[4]) for e in logs.start_events}
    r["start_reason"] = r["req_instance"].map(lambda i: start.get(i, (np.nan, "unknown"))[1])
    r["start_t"] = r["req_instance"].map(lambda i: start.get(i, (np.nan, None))[0])
    cfg = r["req_revision"].map(lambda rev: logs.configs.get(rev, {}))
    tiers = {(c.get("memory_mb"), c.get("cpu"), c.get("boost")) for c in cfg if c}
    rows, bill = [], []
    for interval, x in r.groupby("interval"):
        sess = _replay_sessions(x)
        inv = x[x["type"].isin(["init", "call"])]
        c = inv[inv["type"] == "call"]
        ok = c[c["error"].isna()] if "error" in c else c
        cold = inv[inv["is_cold"].eq(True)]
        insts = inv.dropna(subset=["req_instance"]).drop_duplicates("req_instance")
        t0 = x["ts"].min()
        waited = cold[cold["start_t"] >= cold["req_t"] - 0.5]  # instance started by this request
        rows.append({"session arrival interval s": interval, "sessions": len(sess),
                     "peak concurrent sessions": _peak_concurrency(sess), "tool calls": len(ok), "errors": len(c) - len(ok),
                     "instances used (4 tools)": len(insts),
                     "… pre-started on deploy (rollout) / request-triggered": f"{int((insts['start_reason'] == 'DEPLOYMENT_ROLLOUT').sum())} / "
                                                                              f"{int((insts['start_reason'] == 'AUTOSCALING').sum())}",
                     "fresh-process requests (handshake / call)": f"{int((cold['type'] == 'init').sum())} / {int((cold['type'] == 'call').sum())}",
                     "… of which waited for the instance to start": len(waited),
                     "tool call p50 ms": ms(ok["client_us"].median()), "tool call p95 ms": ms(ok["client_us"].quantile(.95)),
                     "tool share of session time p50": f"{100 * (sess['tools_ms'] / sess['wall_ms']).median():.1f}%",
                     "earliest instance start − run start s": round(insts["start_t"].min() - t0, 1) if insts["start_t"].notna().any() else np.nan})
        m = inv.dropna(subset=["req_latency_ms"]).copy()
        if not m.empty:
            c0 = [logs.configs.get(rev, {}) for rev in m["req_revision"]]
            m["mem"] = [cc.get("memory_mb", np.nan) for cc in c0]
            m["vcpu"] = [float(cc.get("cpu", "nan")) for cc in c0]
            m["billable"] = billable_ms(m["req_latency_ms"])
            m["cost"] = (m["billable"] / 1000 * (m["vcpu"] * RUN_VCPU_S + m["mem"] / 1024 * RUN_GIB_S) + RUN_REQUEST)
            hs = m[m["type"] == "init"]
            bill.append({"session arrival interval s": interval, "invocations": len(m),
                         "of which handshake": f"{len(hs)} ({100 * len(hs) / len(m):.0f}%)",
                         "billable s": m["billable"].sum() / 1000, "handshake share of billable time": f"{100 * hs['billable'].sum() / m['billable'].sum():.0f}%",
                         "handshake share of cost": f"{100 * hs['cost'].sum() / m['cost'].sum():.0f}%",
                         "$ per 1,000 sessions": 1000 * m["cost"].sum() / max(len(sess), 1)})
    out.append("\n## E4 · Agent trace replay (LiveMCPBench, Claude Sonnet 4 run; modeled LLM time)\n")
    out.append("Configurations seen: " + ", ".join(f"{m} MB / {c} vCPU, boost {'on' if b else 'off'}" for m, c, b in sorted(tiers, key=str))
               + ". No holds: each run starts right after a new revision was deployed, so Cloud Run has pre-started an instance per tool. "
               "*Fresh-process requests*: the wrapper's `is_cold` (first request of the process); *waited*: the instance was started "
               "for this request (start logged at most 0.5 s before it), i.e. a cold start the client sat through.\n")
    out.append(md_table(pd.DataFrame(rows), {"session arrival interval s": 0}) + "\n")
    if bill:
        out.append("\n**Replay billing** (computed, all invocations; prices as in E5)\n")
        out.append(md_table(pd.DataFrame(bill), {"session arrival interval s": 0, "billable s": 1, "$ per 1,000 sessions": 4}) + "\n")


# --- main ----------------------------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("campaign")
    p.add_argument("--figures", default="docs/figures/gcp")
    args = p.parse_args()
    os.makedirs(args.figures, exist_ok=True)
    logs = Logs(args.campaign)
    df = load(args.campaign, logs)
    sessions = clean_sessions(args.campaign, logs)
    n_clean = sum(r["clean"] for r in sessions.values())
    out = [f"# GCP campaign `{os.path.basename(os.path.normpath(args.campaign))}` — generated tables\n",
           "Cloud Run functions (gen2), europe-west1, Python 3.11, concurrency 1, `cpuIdle` (CPU only during requests). "
           "Tiers follow Cloud Functions' default CPU per memory size.\n",
           f"{len(df):,} client records; {len(logs.requests):,} request-log entries; "
           f"{int(df['req_instance'].notna().sum()):,} client records matched to one. "
           f"Cold-start sessions (e2, e1b): {len(sessions)} in the result directories, {n_clean} pass the cold-start check.\n"]
    instance_starts(args.campaign, logs, out)
    e1(df, out)
    s = e2_sessions(df, sessions, logs)
    e2(s, out)
    e2_figure(s, os.path.join(args.figures, "e2-cold-start-boost.png"))
    e1b(df, sessions, out)
    d = e3_frame(df)
    e3(d, out)
    e3_figure(d, os.path.join(args.figures, "e3-time-split.png"))
    e5(d, df, out)
    e4(args.campaign, logs, out)
    with open(os.path.join(args.campaign, "summary.md"), "w") as f:
        f.write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
