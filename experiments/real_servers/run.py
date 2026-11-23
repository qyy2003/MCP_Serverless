#!/usr/bin/env python3
"""Measure real MCP servers (configs/real-servers.json), one throwaway container each, one at a time.

    DOCKER_HOST=unix:///var/run/docker.sock python3 experiments/real_servers/run.py [--only name,...] [--runs 7]

Each container installs one server and starts it repeatedly over stdio (probe.py), limited to 1 CPU and 2 GB.
Results: results/real-servers/<name>.json. Servers with a result file are skipped (delete it to redo).
"""
import argparse
import json
import os
import re
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
IMAGE = "mcp-bench-real-servers"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--only")
    p.add_argument("--runs", type=int, default=7)
    p.add_argument("--cpus", default="1")
    a = p.parse_args()
    subprocess.run(["docker", "build", "-q", "-t", IMAGE, HERE], check=True, stdout=subprocess.DEVNULL)
    image_id = subprocess.run(["docker", "image", "inspect", "-f", "{{.Id}}", IMAGE], capture_output=True, text=True).stdout.strip()
    out_dir = os.path.join(ROOT, "results", "real-servers")
    os.makedirs(out_dir, exist_ok=True)
    specs = json.load(open(os.path.join(ROOT, "configs", "real-servers.json")))
    if a.only:
        specs = [s for s in specs if s["name"] in a.only.split(",")]
    for s in specs:
        path = os.path.join(out_dir, re.sub(r"[^A-Za-z0-9._-]", "_", s["name"]) + ".json")
        if os.path.exists(path):
            continue
        t0 = time.time()
        proc = subprocess.run(["docker", "run", "--rm", f"--cpus={a.cpus}", "--memory=2g", IMAGE,
                               "python3", "/probe.py", json.dumps(s), "--runs", str(a.runs)],
                              capture_output=True, text=True, timeout=1800)
        try:
            res = json.loads(proc.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            res = {"spec": s, "error": f"no result (exit {proc.returncode}): {proc.stderr[-800:]}"}
        res.update(image=image_id, cpus=a.cpus, measured=time.strftime("%Y-%m-%dT%H:%M:%S"))
        json.dump(res, open(path, "w"), indent=1)
        ok = [r for r in res.get("runs", []) if "error" not in r]
        print(f"{s['name']:24} {time.time() - t0:5.0f}s  {res.get('installed_mb', 0):7.1f} MB  "
              f"{res.get('n_dependencies', '?'):>4} deps  ok runs {len(ok)}/{len(res.get('runs', []))}  "
              f"tools/list {sorted(r['tools_list_ms'] for r in ok)[len(ok) // 2] if ok else float('nan'):7.0f} ms  "
              f"{res.get('error') or next((r['error'] for r in res.get('runs', []) if 'error' in r), '')[:120]}", flush=True)


if __name__ == "__main__":
    main()
