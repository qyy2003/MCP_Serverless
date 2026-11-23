#!/usr/bin/env python3
"""Forced cold starts on Cloud Functions gen1, the way SeBS forces them, probed from the VM or the workstation.

Checks whether SeBS's forced cold start (2.1-2.5 s for gen1 010.sleep, measured from the workstation) is really
slower than the natural one after idling (median 0.92 s, measured from the VM by idle_probe.py), or whether the
client location explains it. Each rep:

1. Update the function's configuration as SeBS's `CloudFunctionGen1Strategy.update_config` does (same body and
   update mask; a new `cold_start` value in the environment), which creates a new version.
2. Wait until the function is ACTIVE with that version (SeBS's `enforce_cold_start` with our versionId fix).
3. Probe it at once with the same request as idle_probe.py (`run_plain`, 2 calls, new connection), from the VM
   (over a kept-open SSH connection) or from this machine, in a shuffled order.

    GOOGLE_APPLICATION_CREDENTIALS=<key> serverless-benchmarks/.venv/bin/python experiments/gcp_forced_cold.py \\
        --function sebs_2c58abb2_010_python_3_11_x64_gen1 --vm mcpbench@<ip> --out results/idle/gcp1-forced \\
        --reps-vm 10 --reps-local 4

Output: <out>/forced.jsonl, the client's per-request records plus rep, client ("vm"/"local"), version and the
deploy timestamps (t_patch, t_active, t_probe). Resume: rerun the same command; finished reps are kept.
"""
import argparse
import json
import os
import random
import subprocess
import sys
import time

import google.auth
from google.auth.transport.requests import AuthorizedSession

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from mcp_bench.client import run_plain  # noqa: E402

API = "https://cloudfunctions.googleapis.com/v1"
ARGS = {"sleep": 0}
CALLS = 2


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def force(http, name):
    """SeBS's gen1 update_config: same body and mask, merged environment with a new cold_start value."""
    f = http.get(f"{API}/{name}").json()
    envs = dict(f.get("environmentVariables", {}), cold_start=str(int(time.time())))
    body = {"availableMemoryMb": f["availableMemoryMb"], "timeout": f["timeout"],
            "minInstances": f.get("minInstances", 0), "maxInstances": f.get("maxInstances", 0),
            "environmentVariables": envs}
    mask = "availableMemoryMb,timeout,environmentVariables,minInstances,maxInstances"
    t_patch = time.time()
    r = http.patch(f"{API}/{name}", params={"updateMask": mask}, json=body)
    r.raise_for_status()
    version = int(r.json()["metadata"]["versionId"])
    deadline = time.time() + 600
    while time.time() < deadline:
        time.sleep(1)
        r = http.get(f"{API}/{name}")
        if r.status_code in (429, 503):
            continue
        s = r.json()
        if s.get("status") == "ACTIVE" and int(s["versionId"]) == version:
            return version, t_patch, time.time()
    raise RuntimeError(f"version {version} not ACTIVE after 600 s")


def probe_vm(ssh, vm_dir, url):
    code = ("import json; from mcp_bench.client import run_plain; "
            f"print(json.dumps(run_plain({url!r}, {ARGS!r}, {CALLS}, False)))")
    p = subprocess.run(ssh + [f"cd {vm_dir} && python3 -c {json.dumps(code)}"],
                       capture_output=True, text=True, timeout=300)
    if p.returncode:
        raise RuntimeError(p.stderr.strip()[-500:])
    return json.loads(p.stdout.strip().splitlines()[-1])


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--function", required=True)
    p.add_argument("--region", default="europe-west1")
    p.add_argument("--vm", required=True, help="user@host of the client VM")
    p.add_argument("--key", default="~/.ssh/gcp-mcpbench")
    p.add_argument("--vm-dir", default="~/mcpbench")
    p.add_argument("--out", required=True)
    p.add_argument("--reps-vm", type=int, default=10)
    p.add_argument("--reps-local", type=int, default=4)
    p.add_argument("--pause", type=float, default=20.0, help="Seconds between reps")
    p.add_argument("--seed", default="1")
    a = p.parse_args()

    creds, project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    http = AuthorizedSession(creds)
    name = f"projects/{project}/locations/{a.region}/functions/{a.function}"
    url = http.get(f"{API}/{name}").json()["httpsTrigger"]["url"]
    ssh = ["ssh", "-i", os.path.expanduser(a.key), "-o", "BatchMode=yes", "-o", "ServerAliveInterval=30",
           "-o", "ControlMaster=auto", "-o", "ControlPath=~/.ssh/cm-mcpbench-%C", "-o", "ControlPersist=600", a.vm]

    plan = ["vm"] * a.reps_vm + ["local"] * a.reps_local
    random.Random(a.seed).shuffle(plan)
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "forced.jsonl")
    done = set()
    if os.path.exists(path):
        done = {json.loads(line)["rep"] for line in open(path)}
    say(f"{a.function}: {len(plan)} reps ({a.reps_vm} vm, {a.reps_local} local), {len(done)} done; url {url}")

    for rep, client in enumerate(plan):
        if rep in done:
            continue
        if client == "vm":
            subprocess.run(ssh + ["true"], check=True, timeout=60)  # keep the control connection open
        version, t_patch, t_active = force(http, name)
        t_probe = time.time()
        try:
            records = probe_vm(ssh, a.vm_dir, url) if client == "vm" else run_plain(url, ARGS, CALLS, False)
            error = None
        except Exception as e:
            records, error = [], f"{type(e).__name__}: {e}"
        meta = {"rep": rep, "client": client, "version": version, "t_patch": t_patch, "t_active": t_active,
                "t_probe": t_probe, "function": a.function}
        if error or not records:
            records = [{"phase": "error", "error": error or "no records", "ts": t_probe, "client_us": 0}]
        with open(path, "a") as f:
            for r in records:
                f.write(json.dumps(dict(r, **meta)) + "\n")
        first = records[0]
        say(f"rep {rep:2} {client:5} v{version} deploy {t_active - t_patch:5.1f}s  cold={first.get('is_cold')} "
            f"first {first.get('client_us', 0) / 1e3:7.0f} ms  {error or ''}")
        time.sleep(a.pause)
    say("done")


if __name__ == "__main__":
    main()
