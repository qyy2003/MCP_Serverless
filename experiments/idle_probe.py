#!/usr/bin/env python3
"""Idle-time experiment: how likely is a cold start after a function sat idle for t minutes?

One chain per target function, all chains in parallel (a function's instances only see its own chain): probe,
stay idle for t, probe again, with t taken from a shuffled schedule. A probe is what an agent does when it
comes back to a tool: a new connection and an MCP session (handshake, plus `calls` tool calls), or plain
invocations for targets in mode "plain". The idle time is measured from the end of the previous probe.

Needs only the targets' URLs, so it runs unchanged against AWS, GCP and Azure (stdlib only, like mcp_bench).
Cold = the wrapper's `is_cold` on the probe's first request (a fresh process). On GCP, join with Cloud Run's
logs afterwards (`--trace-header` is always on; experiments/gcp_logs.py) to see how each instance was started.

    python3 experiments/idle_probe.py --targets targets.json --out results/idle/<run> \\
        --gaps 1,3,30 [--reps 1] [--seed 1] [--first-gap 0]

targets.json: [{"name": "gcp-610", "url": "https://...", "mode": "mcp", "calls": 0, "arguments": {}}, ...]

Output per target: <out>/<name>.jsonl, the client's per-request records plus probe, planned_gap_s, idle_s,
target. Resume: rerun the same command; finished probes are kept, the chain continues with the next planned
gap, and its first probe after the restart is marked `resumed` (its idle time isn't the planned one).
"""
import argparse
import json
import os
import random
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mcp_bench.client import Connection, run_mcp, run_plain  # noqa: E402

lock = threading.Lock()


def say(msg):
    with lock:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def schedule(gaps_min, reps, seed, name):
    """Planned idle times (s) for one target: every gap `reps` times, shuffled per target."""
    plan = [g * 60 for g in gaps_min for _ in range(reps)]
    random.Random(f"{seed}-{name}").shuffle(plan)
    return plan


def probe(t):
    if t.get("mode", "mcp") == "mcp":
        # A new client per probe = a new connection per session, kept for the session's requests.
        return run_mcp(t["url"], t.get("arguments", {}), t.get("calls", 0), False, t.get("tool"), 0.0,
                       t.get("protocol", "legacy"))
    return run_plain(t["url"], t.get("arguments", {}), max(t.get("calls", 1), 1), False)


def chain(t, plan, out_dir, first_gap):
    path = os.path.join(out_dir, f"{t['name']}.jsonl")
    done = {}
    if os.path.exists(path):
        for line in open(path):
            r = json.loads(line)
            done.setdefault(r["probe"], []).append(r)
    steps = [first_gap] + plan  # probe 0 starts the chain (its idle time is unknown)
    last_end = None
    if done:
        last = max(done)
        last_end = max(r["ts"] + r["client_us"] / 1e6 for r in done[last])
    resumed = bool(done)
    for i, gap in enumerate(steps):
        if i in done:
            continue
        if last_end is not None and not resumed:
            time.sleep(max(0.0, last_end + gap - time.time()))
        start = time.time()
        try:
            records = probe(t)
            error = None
        except Exception as e:  # keep the chain alive; record the failure
            records, error = [], f"{type(e).__name__}: {e}"
        idle = start - last_end if last_end is not None else None
        meta = {"target": t["name"], "probe": i, "planned_gap_s": gap if i else None,
                "idle_s": round(idle, 1) if idle is not None else None, "resumed": resumed}
        if error or not records:
            records = [{"phase": "error", "error": error or "no records", "ts": start, "client_us": 0}]
        with open(path, "a") as f:
            for r in records:
                f.write(json.dumps(dict(r, **meta)) + "\n")
        first = records[0]
        say(f"{t['name']:14} probe {i:2}/{len(steps) - 1} idle {meta['idle_s'] or 0:7.1f}s "
            f"cold={first.get('is_cold')} {first.get('client_us', 0) / 1e3:8.0f} ms  {error or ''}")
        last_end = max(r["ts"] + r["client_us"] / 1e6 for r in records)
        resumed = False
    say(f"{t['name']}: chain done")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--targets", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--gaps", required=True, help="Idle times in minutes, comma-separated")
    p.add_argument("--reps", type=int, default=1)
    p.add_argument("--seed", default="1")
    p.add_argument("--first-gap", type=float, default=0.0, help="Unused placeholder for probe 0")
    p.add_argument("--only", help="Comma-separated target names to run")
    a = p.parse_args()
    targets = json.load(open(a.targets))
    if a.only:
        targets = [t for t in targets if t["name"] in a.only.split(",")]
    gaps = [float(g) for g in a.gaps.split(",")]
    os.makedirs(a.out, exist_ok=True)
    Connection.send_trace = True
    plans = {t["name"]: schedule(gaps, a.reps, a.seed, t["name"]) for t in targets}
    json.dump({"targets": targets, "gaps_min": gaps, "reps": a.reps, "seed": a.seed, "plans_s": plans,
               "started": time.time()}, open(os.path.join(a.out, "plan.json"), "w"), indent=1)
    total = max(sum(v) for v in plans.values()) / 3600
    say(f"{len(targets)} chains, {len(gaps) * a.reps} idle periods each, about {total:.1f} h")
    threads = [threading.Thread(target=chain, args=(t, plans[t["name"]], a.out, a.first_gap)) for t in targets]
    for th in threads:
        th.start()
    for th in threads:
        th.join()


if __name__ == "__main__":
    main()
