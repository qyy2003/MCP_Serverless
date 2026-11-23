#!/usr/bin/env python3
"""Targeted AWS Lambda experiment: SDK/heavy-startup cold starts + MCP 2026-07-28 protocol check.

Designed as a fast, surgical ~20-minute run to complement the 2026-11-18 stdlib AWS campaign
without rerunning E1-E5:

  1. oom      Check whether 610-sdk OOMs at 128 MB on AWS Lambda (like it does at 128 MiB on GCP).
  2. cold     Forced cold starts (default n=10) at 512 MB and 1769 MB (1 vCPU) for:
                - 610-sdk (official MCP SDK 2.3.0, API wrapper)
                - 620-sdk (official MCP SDK 2.3.0, fetch->markdown)
                - 630     (pandas + dataset load, no-SDK shim)
                - 630-sdk (official MCP SDK 2.3.0 + pandas + dataset load)
              Records client latency, server-side init_import_us/init_us/import_us/load_us, and
              joins every invocation to its exact CloudWatch REPORT line (Init Duration, Duration,
              Billed Duration, Max Memory Used).
  3. proto    MCP protocol revision comparison on AWS Lambda (610-sdk at 1769 MB):
              interleaved legacy (handshake) vs modern (2026-07-28, no handshake) vs auto,
              for warm sessions (n=20) and cold sessions (n=10), joined with REPORT billing lines.

Works directly from the workstation (no EC2 VM required: Init Duration, Billed Duration,
Max Memory Used, init_import_us, and WAN handshake savings are exact; set --upstream to any
reachable mock_upstream, or omit --upstream to run handshake-only / dummy-free tests for 610/620
where 010/init is enough -- note: 610/620/630 tool calls need a reachable --upstream URL).

Usage:
    export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...
    serverless-benchmarks/.venv/bin/python experiments/aws_sdk_protocol.py \\
        --upstream http://<reachable-mock-upstream>:8080 \\
        --out results/aws/2026-11-23-sdk-proto \\
        --steps oom,cold,proto,logs
"""

import argparse
import json
import os
import re
import statistics
import sys
import time
import uuid

import boto3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from mcp_bench.client import MCPClient  # noqa: E402

REGION = "eu-north-1"
SEBS_CACHE = os.path.join(ROOT, "serverless-benchmarks", "cache", "aws.json")

REPORT = re.compile(
    r"REPORT RequestId: (?P<request_id>\S+)\s+Duration: (?P<duration_ms>[\d.]+) ms\s+"
    r"Billed Duration: (?P<billed_ms>\d+) ms\s+Memory Size: (?P<memory_mb>\d+) MB\s+"
    r"Max Memory Used: (?P<max_memory_mb>\d+) MB(?:\s+Init Duration: (?P<init_ms>[\d.]+) ms)?"
)


def load_functions(cache_path: str) -> dict:
    """Discover deployed 610/620/630 default & sdk functions from SeBS's AWS cache."""
    data = json.load(open(cache_path))
    urls = data.get("resources", {}).get("function-urls", {})
    found = {}
    for entry in urls.values():
        name = entry["function_name"]
        url = entry["url"]
        parts = name.split("_")
        # SeBS names: sebs_<id>_<code:610>_python_<ver>[_sdk] or similar containing benchmark code & variant
        code = next((p for p in parts if p in ("010", "110", "610", "620", "630")), None)
        if not code:
            continue
        is_sdk = "sdk" in parts or "python-sdk" in name
        key = f"{code}-sdk" if is_sdk else code
        found[key] = {"name": name, "url": url}
    return found


def tool_spec(key: str, upstream: str) -> tuple[str, dict]:
    code = key.split("-")[0]
    if code == "610":
        return "search_products", {"upstream": upstream, "latency_ms": 200, "size": 16384}
    if code == "620":
        return "fetch", {"upstream": upstream, "latency_ms": 200, "size": 200000, "max_length": 5000}
    if code == "630":
        return "summarize_catalog", {
            "upstream": upstream,
            "latency_ms": 200,
            "size": 1 << 20,
            "seed": 1,
            "group_by": "month",
            "min_rating": 0,
            "limit": 12,
        }
    raise ValueError(f"Unsupported key: {key}")


def configure(lam, fn_names: list[str], memory: int | None = None, force_cold: bool = True, timeout: int | None = None):
    for name in fn_names:
        update = {}
        if memory is not None:
            update["MemorySize"] = memory
        if timeout is not None:
            update["Timeout"] = timeout
        if force_cold:
            update["Environment"] = {"Variables": {"cold_start": uuid.uuid4().hex[:8]}}
        for _ in range(60):
            try:
                lam.update_function_configuration(FunctionName=name, **update)
                break
            except lam.exceptions.ResourceConflictException:
                time.sleep(1)
        else:
            raise RuntimeError(f"Timed out updating {name}")
    for name in fn_names:
        lam.get_waiter("function_updated_v2").wait(
            FunctionName=name, WaiterConfig={"Delay": 1, "MaxAttempts": 300}
        )


def run_mcp_session(url: str, tool: str, arguments: dict, protocol: str = "legacy", calls: int = 2) -> list[dict]:
    client = MCPClient(url, protocol=protocol)
    try:
        records = client.connect()
        _, rec = client.list_tools()
        records.append(rec)
        for _ in range(calls):
            _, rec = client.call_tool(tool, arguments)
            records.append(rec)
        return records
    finally:
        client.close()


def append_jsonl(path: str, records: list[dict], meta: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        for pos, r in enumerate(records):
            row = dict(r)
            row.update(meta)
            row["position"] = pos
            f.write(json.dumps(row) + "\n")


def step_oom(lam, fns: dict, upstream: str, out_dir: str):
    key = "610-sdk"
    if key not in fns:
        print(f"[oom] skipped: {key} not found in SeBS cache")
        return
    print(f"[oom] testing {key} at 128 MB (5 attempts)...")
    tool, args = tool_spec(key, upstream)
    out_path = os.path.join(out_dir, "oom-128mb.jsonl")
    for rep in range(5):
        configure(lam, [fns[key]["name"]], memory=128, force_cold=True, timeout=60)
        try:
            recs = run_mcp_session(fns[key]["url"], tool, args, protocol="legacy", calls=1)
            append_jsonl(out_path, recs, {"exp": "oom", "fn": key, "mem": 128, "rep": rep, "ok": True})
            print(f"  rep {rep}: OK (client total {sum(r['client_us'] for r in recs)/1e3:.0f} ms)")
        except Exception as exc:
            append_jsonl(out_path, [{"error": str(exc), "ts": time.time()}],
                         {"exp": "oom", "fn": key, "mem": 128, "rep": rep, "ok": False})
            print(f"  rep {rep}: FAILED -> {exc}")


def step_cold(lam, fns: dict, upstream: str, out_dir: str, memories: list[int], reps: int, targets: list[str]):
    active = [k for k in targets if k in fns]
    if not active:
        print(f"[cold] no target functions found among {targets}; available={sorted(fns)}")
        return
    print(f"[cold] targets={active}, memories={memories}, reps={reps}")
    out_path = os.path.join(out_dir, "cold.jsonl")
    for mem in memories:
        print(f"[cold] memory={mem} MB")
        configure(lam, [fns[k]["name"] for k in active], memory=mem, force_cold=False, timeout=60)
        for rep in range(reps):
            configure(lam, [fns[k]["name"] for k in active], force_cold=True)
            for key in active:
                tool, args = tool_spec(key, upstream)
                try:
                    recs = run_mcp_session(fns[key]["url"], tool, args, protocol="legacy", calls=2)
                    append_jsonl(out_path, recs, {"exp": "cold", "fn": key, "mem": mem, "rep": rep, "protocol": "legacy"})
                    first_res_ms = sum(r["client_us"] for r in recs[:-1]) / 1e3
                    warm_ms = recs[-1]["client_us"] / 1e3
                    init_imp = next((r.get("init_import_us") for r in recs if r.get("init_import_us")), None)
                    print(f"  m{mem} rep {rep+1:02d}/{reps} {key:8s}: first_result={first_res_ms:7.1f} ms  "
                          f"warm={warm_ms:6.1f} ms  init_import={init_imp/1e3 if init_imp else 0:6.1f} ms")
                except Exception as exc:
                    append_jsonl(out_path, [{"error": str(exc), "ts": time.time()}],
                                 {"exp": "cold", "fn": key, "mem": mem, "rep": rep, "ok": False})
                    print(f"  m{mem} rep {rep+1:02d}/{reps} {key:8s}: ERROR {exc}")


def step_proto(lam, fns: dict, upstream: str, out_dir: str, mem: int, warm_reps: int, cold_reps: int):
    key = "610-sdk" if "610-sdk" in fns else ("610" if "610" in fns else None)
    if not key:
        print("[proto] skipped: neither 610-sdk nor 610 found")
        return
    tool, args = tool_spec(key, upstream)
    args = dict(args, latency_ms=50, size=4096)
    protocols = ("legacy", "modern", "auto")
    out_path = os.path.join(out_dir, "proto.jsonl")
    print(f"[proto] fn={key} mem={mem} MB warm={warm_reps} cold={cold_reps} protocols={protocols}")

    configure(lam, [fns[key]["name"]], memory=mem, force_cold=True, timeout=60)
    # Warm-up
    run_mcp_session(fns[key]["url"], tool, args, protocol="legacy", calls=1)

    for rep in range(warm_reps):
        for proto in protocols:
            recs = run_mcp_session(fns[key]["url"], tool, args, protocol=proto, calls=1)
            append_jsonl(out_path, recs, {
                "exp": "proto", "condition": "warm", "fn": key, "mem": mem, "rep": rep, "protocol": proto,
            })
        if (rep + 1) % 5 == 0:
            print(f"  warm {rep+1}/{warm_reps} done")

    for rep in range(cold_reps):
        for proto in protocols:
            configure(lam, [fns[key]["name"]], force_cold=True)
            recs = run_mcp_session(fns[key]["url"], tool, args, protocol=proto, calls=1)
            append_jsonl(out_path, recs, {
                "exp": "proto", "condition": "cold", "fn": key, "mem": mem, "rep": rep, "protocol": proto,
            })
        print(f"  cold {rep+1}/{cold_reps} done")


def step_logs(fns: dict, out_dir: str, start_ms: int):
    logs = boto3.client("logs", region_name=REGION)
    out_path = os.path.join(out_dir, "reports.jsonl")
    print(f"[logs] waiting 15 s for CloudWatch ingestion, then fetching REPORT lines since {start_ms}...")
    time.sleep(15)
    n = 0
    with open(out_path, "w") as f:
        for key, fn in sorted(fns.items()):
            lg = f"/aws/lambda/{fn['name']}"
            kwargs = {"logGroupName": lg, "startTime": start_ms, "filterPattern": '"REPORT RequestId"'}
            try:
                while True:
                    page = logs.filter_log_events(**kwargs)
                    for ev in page["events"]:
                        m = REPORT.search(ev["message"])
                        if not m:
                            continue
                        rec = {k: v for k, v in m.groupdict().items() if v is not None}
                        for k in ("duration_ms", "init_ms"):
                            if k in rec:
                                rec[k] = float(rec[k])
                        for k in ("billed_ms", "memory_mb", "max_memory_mb"):
                            rec[k] = int(rec[k])
                        rec.update(fn=key, timestamp_ms=ev["timestamp"])
                        f.write(json.dumps(rec) + "\n")
                        n += 1
                    if "nextToken" not in page:
                        break
                    kwargs["nextToken"] = page["nextToken"]
            except logs.exceptions.ResourceNotFoundException:
                continue
    print(f"[logs] wrote {n} REPORT lines to {out_path}")


def print_quick_summary(out_dir: str):
    reports = {}
    rep_path = os.path.join(out_dir, "reports.jsonl")
    if os.path.exists(rep_path):
        for line in open(rep_path):
            r = json.loads(line)
            reports[r["request_id"]] = r

    cold_path = os.path.join(out_dir, "cold.jsonl")
    if os.path.exists(cold_path):
        by_sess = {}
        for line in open(cold_path):
            r = json.loads(line)
            if "error" in r:
                continue
            by_sess.setdefault((r["fn"], r["mem"], r["rep"]), []).append(r)
        groups = {}
        for (fn, mem, _), recs in by_sess.items():
            recs.sort(key=lambda x: x["position"])
            first_res = sum(r["client_us"] for r in recs[:-1]) / 1e3
            warm = recs[-1]["client_us"] / 1e3
            inits = [reports[r["amzn_request_id"]].get("init_ms") for r in recs
                     if r.get("amzn_request_id") in reports and "init_ms" in reports[r["amzn_request_id"]]]
            max_mem = max((reports[r["amzn_request_id"]]["max_memory_mb"] for r in recs
                           if r.get("amzn_request_id") in reports), default=0)
            groups.setdefault((fn, mem), []).append((first_res, warm, inits[0] if inits else 0.0, max_mem))
        print("\n=== Cold-start summary ===")
        for (fn, mem), vals in sorted(groups.items()):
            print(f"  {fn:8s} {mem:4d} MB (n={len(vals):2d}): "
                  f"first_result p50={statistics.median(v[0] for v in vals):7.1f} ms | "
                  f"warm p50={statistics.median(v[1] for v in vals):6.1f} ms | "
                  f"Lambda Init p50={statistics.median(v[2] for v in vals):6.1f} ms | "
                  f"max_mem={max(v[3] for v in vals)} MB")

    proto_path = os.path.join(out_dir, "proto.jsonl")
    if os.path.exists(proto_path):
        by_sess = {}
        for line in open(proto_path):
            r = json.loads(line)
            by_sess.setdefault((r["condition"], r["protocol"], r["rep"]), []).append(r)
        groups = {}
        for (cond, proto, _), recs in by_sess.items():
            total_ms = sum(r["client_us"] for r in recs) / 1e3
            billed_ms = sum(reports[r["amzn_request_id"]]["billed_ms"] for r in recs
                            if r.get("amzn_request_id") in reports)
            groups.setdefault((cond, proto), []).append((len(recs), total_ms, billed_ms))
        print("\n=== Protocol revision summary ===")
        for (cond, proto), vals in sorted(groups.items()):
            print(f"  {cond:4s} {proto:7s} (n={len(vals):2d}): reqs={vals[0][0]} | "
                  f"first_result p50={statistics.median(v[1] for v in vals):7.1f} ms | "
                  f"billed_ms p50={statistics.median(v[2] for v in vals):6.1f} ms")


def load_env(path: str = os.path.expanduser("~/.aws-mcpbench.env")):
    if os.environ.get("AWS_ACCESS_KEY_ID") or not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main(argv=None):
    load_env()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--upstream", required=True, help="Reachable mock_upstream URL (http://host:port)")
    p.add_argument("--out", required=True, help="Output directory, e.g. results/aws/2026-11-23-sdk-proto")
    p.add_argument("--cache", default=SEBS_CACHE, help="Path to SeBS aws.json cache")
    p.add_argument("--steps", default="oom,cold,proto,logs", help="Comma-separated: oom,cold,proto,logs,summary")
    p.add_argument("--memories", default="512,1769", help="Memory tiers for cold step")
    p.add_argument("--cold-reps", type=int, default=10)
    p.add_argument("--warm-reps", type=int, default=20)
    p.add_argument("--targets", default="610-sdk,620-sdk,630,630-sdk")
    args = p.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    state_path = os.path.join(args.out, "state.json")
    fns = load_functions(args.cache)
    if os.path.exists(state_path):
        state = json.load(open(state_path))
    else:
        state = {"start_ms": int(time.time() * 1000) - 5000, "functions": fns}
        json.dump(state, open(state_path, "w"), indent=2)

    steps = [s.strip() for s in args.steps.split(",") if s.strip()]
    lam = boto3.client("lambda", region_name=REGION) if any(s in steps for s in ("oom", "cold", "proto")) else None
    memories = [int(m) for m in args.memories.split(",")]
    targets = [t.strip() for t in args.targets.split(",") if t.strip()]

    if "oom" in steps:
        step_oom(lam, fns, args.upstream, args.out)
    if "cold" in steps:
        step_cold(lam, fns, args.upstream, args.out, memories, args.cold_reps, targets)
    if "proto" in steps:
        step_proto(lam, fns, args.upstream, args.out, mem=1769, warm_reps=args.warm_reps, cold_reps=args.cold_reps)
    if "logs" in steps:
        step_logs(fns, args.out, state["start_ms"])
    if "summary" in steps or "logs" in steps:
        print_quick_summary(args.out)


if __name__ == "__main__":
    sys.exit(main())
