"""Summarize a `mcp_bench.local_suite` run as markdown tables.

    python analysis/local_summary.py results/local/run1

All values are medians in ms with a bootstrap 95% confidence interval of the median.
"Outside" is client time minus the function's own execution time: network, HTTP server
and protocol. "First result" is the time from the first byte sent to the first tool
result: handshake plus first call for MCP, the first call for plain.
"""

import glob
import json
import os
import random
import statistics
import sys

random.seed(0)


def ci(values, reps=2000):
    """Median and bootstrap 95% CI of the median."""
    if not values:
        return None
    meds = sorted(statistics.median(random.choices(values, k=len(values))) for _ in range(reps))
    return statistics.median(values), meds[int(0.025 * reps)], meds[int(0.975 * reps)]


def fmt(stat):
    if stat is None:
        return "–"
    m, lo, hi = stat
    return f"{m:.2f} [{lo:.2f}, {hi:.2f}]"


def ms(us):
    return us / 1000


def sessions(records, mode, condition):
    out = {}
    for r in records:
        if r["mode"] == mode and r["condition"] == condition:
            out.setdefault(r["sample"], []).append(r)
    return [sorted(s, key=lambda r: r["position"]) for s in out.values()]


def handshake(session):
    return sum(r["client_us"] for r in session if r["phase"] not in ("tools/call", "plain"))


def calls(session):
    return [r for r in session if r["phase"] in ("tools/call", "plain")]


def summarize(path):
    records = [json.loads(line) for line in open(path)]
    name = records[0]["benchmark"]
    row = {"benchmark": name}
    for mode in ("mcp", "plain"):
        warm = sessions(records, mode, "warm")
        cold = sessions(records, mode, "cold")
        warm_calls = [c for s in warm for c in calls(s)]
        row[f"{mode}_warm_call"] = ci([ms(c["client_us"]) for c in warm_calls])
        row[f"{mode}_warm_exec"] = ci([ms(c["exec_us"]) for c in warm_calls])
        row[f"{mode}_warm_outside"] = ci([ms(c["client_us"] - c["exec_us"]) for c in warm_calls])
        row[f"{mode}_bytes"] = statistics.median(c["response_bytes"] for c in warm_calls)
        row[f"{mode}_warm_first"] = ci([ms(handshake(s) + calls(s)[0]["client_us"]) for s in warm])
        row[f"{mode}_cold_first"] = ci([ms(handshake(s) + calls(s)[0]["client_us"]) for s in cold])
        row[f"{mode}_cold_first_exec"] = ci([ms(calls(s)[0]["exec_us"]) for s in cold])
        if mode == "mcp":
            row["mcp_warm_handshake"] = ci([ms(handshake(s)) for s in warm])
            row["mcp_cold_handshake"] = ci([ms(handshake(s)) for s in cold])
            row["cold_flag_on"] = sorted({r["phase"] for s in cold for r in s if r.get("is_cold")})
        row[f"{mode}_n"] = (len(warm_calls), len(cold))
    return row


def main(run_dir):
    rows = [summarize(p) for p in sorted(glob.glob(os.path.join(run_dir, "*.jsonl")))]
    params = json.load(open(os.path.join(run_dir, "params.json")))
    print(f"Run `{run_dir}` ({params['started']}): {params['warm_sessions']} warm sessions × "
          f"{params['calls']} calls and {params['cold_samples']} cold samples per mode.\n")

    print("**Warm calls** (ms, median [95% CI])\n")
    print("| benchmark | function exec | MCP call | plain call | outside, MCP | outside, plain | response bytes MCP / plain |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['benchmark']} | {fmt(r['mcp_warm_exec'])} | {fmt(r['mcp_warm_call'])} | {fmt(r['plain_warm_call'])} "
              f"| {fmt(r['mcp_warm_outside'])} | {fmt(r['plain_warm_outside'])} | {r['mcp_bytes']:.0f} / {r['plain_bytes']:.0f} |")

    print("\n**Time to first result**, new connection (ms, median [95% CI]). MCP includes the handshake.\n")
    print("| benchmark | MCP handshake warm | MCP handshake cold | MCP warm | MCP cold | plain warm | plain cold | first-call exec cold, MCP / plain | `is_cold` reported on |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['benchmark']} | {fmt(r['mcp_warm_handshake'])} | {fmt(r['mcp_cold_handshake'])} "
              f"| {fmt(r['mcp_warm_first'])} | {fmt(r['mcp_cold_first'])} | {fmt(r['plain_warm_first'])} | {fmt(r['plain_cold_first'])} "
              f"| {r['mcp_cold_first_exec'][0]:.2f} / {r['plain_cold_first_exec'][0]:.2f} | {', '.join(r['cold_flag_on'])} |")


if __name__ == "__main__":
    main(sys.argv[1])
