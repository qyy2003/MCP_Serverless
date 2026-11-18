#!/usr/bin/env python3
"""AWS Lambda measurement campaign for the MCP tool benchmarks (experiments E1-E4).

Runs on the workstation. Configuration changes (memory size, forced cold starts) are made
from here with boto3; the measurements run on a client VM in the functions' region, over SSH,
so the VM needs no AWS credentials. Needs boto3 and AWS credentials in the environment:

    serverless-benchmarks/python-venv/bin/python experiments/aws_campaign.py \
        --vm ubuntu@<vm> --key ~/.ssh/<key>.pem --upstream http://<vm>:8080 --campaign <id> \
        [--memory 128,512,1769] [--experiments e2,e1b,e1,e3,e4,logs]

Functions and URLs are read from the SeBS cache (serverless-benchmarks/cache/aws.json).
The VM must hold a copy of this repository's mcp_bench/, configs/ and data/traces/ in ~/MCP_Serverless.
Records go to results/aws/<campaign>/<experiment>/m<memory>/ on the VM and are synced back here.

Experiments, per memory size:
  e2   cold vs warm: force a cold start, then one session (handshake + 5 calls) per tool;
       alternating MCP and plain invocation across repetitions
  e1b  extra instances: force a cold start, then 40 sequential calls with a fixed gap
  e1   MCP vs plain, warm: 200 calls per mode, interleaved in chunks of 50; 30 fresh handshakes;
       at the first memory size also from this workstation (wide-area client)
  e3   time split: api-proxy at 50/200/1000 ms upstream delay (+ no connection reuse),
       fetch-markdown at 10 KB / 200 KB / 1 MB pages
Once:
  e4   trace replay at three session arrival intervals (first memory size given)
  logs Lambda REPORT lines (billed duration, init duration, memory used) for the whole campaign
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid

import boto3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGION = "eu-north-1"
SEBS_CACHE = os.path.join(ROOT, "serverless-benchmarks", "cache", "aws.json")
TRACE = "data/traces/livemcpbench-claude-sonnet-4.jsonl"
CODES = ["010", "110", "610", "620"]

REPORT = re.compile(
    r"REPORT RequestId: (?P<request_id>\S+)\s+Duration: (?P<duration_ms>[\d.]+) ms\s+"
    r"Billed Duration: (?P<billed_ms>\d+) ms\s+Memory Size: (?P<memory_mb>\d+) MB\s+"
    r"Max Memory Used: (?P<max_memory_mb>\d+) MB(?:\s+Init Duration: (?P<init_ms>[\d.]+) ms)?"
)


def tools(upstream: str) -> dict:
    return {
        "010": {"tool": "sleep", "args": {"sleep": 0}},
        "110": {"tool": "render_html", "args": {"username": "agent", "random_len": 100}},
        "610": {"tool": "search_products", "args": {"upstream": upstream, "latency_ms": 200, "size": 16384}},
        "620": {"tool": "fetch", "args": {"upstream": upstream, "latency_ms": 200, "size": 200000, "max_length": 5000}},
    }


def functions_from_sebs_cache() -> dict:
    urls = json.load(open(SEBS_CACHE))["resources"]["function-urls"]
    # SeBS names functions sebs_<deployment id>_<benchmark number>_<language>_...
    return {v["function_name"].split("_")[2]: {"name": v["function_name"], "url": v["url"]} for v in urls.values()}


class Campaign:
    def __init__(self, args):
        self.args = args
        self.lam = boto3.client("lambda", region_name=REGION)
        self.fns = functions_from_sebs_cache()
        self.tools = tools(args.upstream)
        self.remote_dir = f"results/aws/{args.campaign}"
        self.local_dir = os.path.join(ROOT, "results", "aws", args.campaign)
        os.makedirs(self.local_dir, exist_ok=True)
        self.log = open(os.path.join(self.local_dir, "campaign.log"), "a")
        self.ssh = ["ssh", "-i", os.path.expanduser(args.key), "-o", "BatchMode=yes",
                    "-o", "ServerAliveInterval=30", "-o", "ControlMaster=auto",
                    "-o", "ControlPath=~/.ssh/cm-mcpbench-%C", "-o", "ControlPersist=600", args.vm]
        state = os.path.join(self.local_dir, "state.json")
        if not os.path.exists(state):
            json.dump({"start_ms": int(time.time() * 1000), "functions": self.fns}, open(state, "w"), indent=2)
        self.state = json.load(open(state))

    def say(self, msg: str):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        self.log.write(line + "\n")
        self.log.flush()

    # --- function configuration -------------------------------------------------------------

    def configure(self, codes, memory=None, force_cold=True):
        """Change memory and/or an environment variable; either makes new requests start fresh instances."""
        names = [self.fns[c]["name"] for c in codes]
        for name in names:
            update = {}
            if memory:
                update["MemorySize"] = memory
            if force_cold:
                update["Environment"] = {"Variables": {"cold_start": uuid.uuid4().hex[:8]}}
            for _ in range(60):
                try:
                    self.lam.update_function_configuration(FunctionName=name, **update)
                    break
                except self.lam.exceptions.ResourceConflictException:
                    time.sleep(1)
            else:
                raise RuntimeError(f"could not update {name}")
        for name in names:
            self.lam.get_waiter("function_updated_v2").wait(
                FunctionName=name, WaiterConfig={"Delay": 1, "MaxAttempts": 300})

    # --- running the client --------------------------------------------------------------------

    def client(self, code, path, meta, mode="mcp", calls=10, interval=0.0, args=None, local=False):
        spec = self.tools[code]
        out = f"{self.remote_dir}/{path}"
        cmd = ["python3", "-m", "mcp_bench.client", "--url", self.fns[code]["url"], "--mode", mode,
               "--calls", str(calls), "--arguments", json.dumps(args or spec["args"]),
               "--meta", json.dumps(dict(meta, fn=code, mode=mode, client="workstation" if local else "vm")),
               "--output", out]
        if mode == "mcp":
            cmd += ["--tool", spec["tool"]]
        if interval:
            cmd += ["--interval", str(interval)]
        if local:
            os.makedirs(os.path.dirname(os.path.join(ROOT, out)), exist_ok=True)
            proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=1800)
        else:
            remote = f"cd MCP_Serverless && mkdir -p {shlex.quote(os.path.dirname(out))} && {shlex.join(cmd)}"
            proc = subprocess.run(self.ssh + [remote], capture_output=True, text=True, timeout=1800)
        if proc.returncode:
            self.say(f"  FAILED {code} {mode} {meta}: {(proc.stderr or proc.stdout)[-400:]!r}")
        return proc.returncode == 0

    def sync(self):
        subprocess.run(["rsync", "-a", "-e", shlex.join(self.ssh[:-1]),
                        f"{self.args.vm}:MCP_Serverless/{self.remote_dir}/", self.local_dir + "/"], check=False)

    # --- experiments ---------------------------------------------------------------------------

    def e2(self, mem, reps=20):
        for rep in range(reps):
            mode = "mcp" if rep % 2 == 0 else "plain"
            self.configure(CODES, force_cold=True)
            for code in CODES:
                self.client(code, f"e2/m{mem}/{code}-{mode}-r{rep:02d}.jsonl",
                            {"exp": "e2", "mem": mem, "rep": rep}, mode=mode, calls=5)
            self.say(f"  e2 m{mem} rep {rep + 1}/{reps} ({mode}) done")

    def e1b(self, mem, reps=2, intervals=(0.0, 0.25, 1.0)):
        for rep in range(reps):
            for interval in intervals:
                self.configure(["010", "110"], force_cold=True)
                for code in ("010", "110"):
                    self.client(code, f"e1b/m{mem}/{code}-i{interval}-r{rep}.jsonl",
                                {"exp": "e1b", "mem": mem, "rep": rep, "interval": interval},
                                calls=40, interval=interval)
            self.say(f"  e1b m{mem} rep {rep + 1}/{reps} done")

    def e1(self, mem, wan=False):
        for code in ("010", "110"):
            self.client(code, f"e1/m{mem}/{code}-warmup.jsonl", {"exp": "warmup", "mem": mem}, calls=3)
            for chunk in range(4):
                modes = ("mcp", "plain") if chunk % 2 == 0 else ("plain", "mcp")
                for mode in modes:
                    self.client(code, f"e1/m{mem}/{code}-{mode}-c{chunk}.jsonl",
                                {"exp": "e1", "mem": mem, "chunk": chunk}, mode=mode, calls=50)
        for i in range(30):
            self.client("010", f"e1/m{mem}/handshake-{i:02d}.jsonl", {"exp": "e1hs", "mem": mem, "i": i}, calls=1)
        self.say(f"  e1 m{mem} (vm) done")
        if wan:
            for chunk in range(4):
                for mode in (("mcp", "plain") if chunk % 2 == 0 else ("plain", "mcp")):
                    self.client("110", f"e1wan/m{mem}/110-{mode}-c{chunk}.jsonl",
                                {"exp": "e1wan", "mem": mem, "chunk": chunk}, mode=mode, calls=50, local=True)
            for i in range(30):
                self.client("010", f"e1wan/m{mem}/handshake-{i:02d}.jsonl",
                            {"exp": "e1wan-hs", "mem": mem, "i": i}, calls=1, local=True)
            self.say(f"  e1 m{mem} (workstation) done")

    def e3(self, mem, calls=32):
        up = self.args.upstream
        grid = [("610", {"latency_ms": lat, "size": 16384}) for lat in (50, 200, 1000)]
        grid.append(("610", {"latency_ms": 200, "size": 16384, "reuse_connection": False}))
        grid += [("620", {"latency_ms": 200, "size": size, "max_length": 5000}) for size in (10_000, 200_000, 1_000_000)]
        for code, params in grid:
            args = dict(upstream=up, seed=1, **params)
            label = f"{code}-l{params['latency_ms']}-s{params['size']}" + ("-noreuse" if params.get("reuse_connection") is False else "")
            meta = {"exp": "e3", "mem": mem, "latency_ms": params["latency_ms"], "size": params["size"],
                    "reuse": params.get("reuse_connection", True)}
            self.client(code, f"e3/m{mem}/{label}.jsonl", meta, calls=calls, args=args)
        self.say(f"  e3 m{mem} done")

    def e4(self, mem, intervals=(1, 10, 60), sessions=20):
        self.configure(CODES, memory=mem, force_cold=True)
        for interval in intervals:
            self.configure(CODES, force_cold=True)
            out = f"{self.remote_dir}/e4/m{mem}/replay-a{interval}"
            remote = (f"cd MCP_Serverless && mkdir -p {shlex.quote(os.path.dirname(out))} && "
                      f"python3 -m mcp_bench.replay {TRACE} --config configs/replay.aws.json "
                      f"--sessions {sessions} --concurrency {sessions} --arrival-interval {interval} "
                      f"--output {out}.jsonl > {out}.summary.json 2> {out}.stderr")
            self.say(f"  e4 m{mem} arrival interval {interval}s: replaying {sessions} sessions")
            proc = subprocess.run(self.ssh + [remote], capture_output=True, text=True, timeout=7200)
            self.say(f"  e4 arrival interval {interval}s done (exit {proc.returncode})")
        self.sync()

    def logs(self):
        """Fetch REPORT lines for every invocation since the campaign started."""
        logs = boto3.client("logs", region_name=REGION)
        out = os.path.join(self.local_dir, "reports.jsonl")
        n = 0
        with open(out, "w") as f:
            for code, fn in self.fns.items():
                kwargs = {"logGroupName": f"/aws/lambda/{fn['name']}", "startTime": self.state["start_ms"],
                          "filterPattern": '"REPORT RequestId"'}
                while True:
                    page = logs.filter_log_events(**kwargs)
                    for event in page["events"]:
                        m = REPORT.search(event["message"])
                        if not m:
                            continue
                        rec = {k: v for k, v in m.groupdict().items() if v is not None}
                        for k in ("duration_ms", "init_ms"):
                            if k in rec:
                                rec[k] = float(rec[k])
                        for k in ("billed_ms", "memory_mb", "max_memory_mb"):
                            rec[k] = int(rec[k])
                        rec.update(fn=code, timestamp_ms=event["timestamp"])
                        f.write(json.dumps(rec) + "\n")
                        n += 1
                    if "nextToken" not in page:
                        break
                    kwargs["nextToken"] = page["nextToken"]
        self.say(f"logs: {n} REPORT lines written to {out}")


def main(argv=None):
    p = argparse.ArgumentParser(description="AWS Lambda measurement campaign (E1-E4) for the MCP tool benchmarks.")
    p.add_argument("--vm", required=True, help="user@host of the client VM")
    p.add_argument("--key", required=True, help="SSH private key for the VM")
    p.add_argument("--upstream", required=True, help="Mock upstream URL as the functions reach it")
    p.add_argument("--campaign", required=True, help="Campaign id (results/aws/<id>/)")
    p.add_argument("--memory", default="128,512,1769", help="Comma-separated memory sizes in MB")
    p.add_argument("--experiments", default="e2,e1b,e1,e3", help="Comma-separated: e2,e1b,e1,e3,e4,logs")
    args = p.parse_args(argv)

    c = Campaign(args)
    memories = [int(m) for m in args.memory.split(",")]
    exps = args.experiments.split(",")
    per_memory = [e for e in ("e2", "e1b", "e1", "e3") if e in exps]
    if per_memory:
        for i, mem in enumerate(memories):
            c.say(f"memory {mem} MB: {', '.join(per_memory)}")
            c.configure(CODES, memory=mem, force_cold=True)
            for exp in per_memory:
                if exp == "e1":
                    c.e1(mem, wan=(i == 0))
                else:
                    getattr(c, exp)(mem)
            c.sync()
    if "e4" in exps:
        c.e4(memories[0])
    if "logs" in exps:
        c.logs()
    c.say("campaign step finished")


if __name__ == "__main__":
    sys.exit(main())
