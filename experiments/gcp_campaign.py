#!/usr/bin/env python3
"""GCP (Cloud Run functions, gen2) measurement campaign for the MCP tool benchmarks: E1-E4 as on AWS.

Runs on the workstation. Configuration changes (memory/CPU tier, startup CPU boost, forced cold starts) are
made from here through the Cloud Run Admin API; the measurements run on a client VM in the functions'
region, over SSH, so the VM needs no GCP credentials. Needs google-auth (the SeBS venv has it) and a service
account key in GOOGLE_APPLICATION_CREDENTIALS:

    serverless-benchmarks/.venv/bin/python experiments/gcp_campaign.py \\
        --vm mcpbench@<vm> --key ~/.ssh/gcp-mcpbench --upstream http://<vm>:8080 --campaign <id> \\
        [--tiers 128:0.083,512:0.333,2048:1] [--boost off,on] [--experiments e2,e1b,e1,e3,e4,logs]

Deploy the functions with SeBS first (`--system-variant function-gen2`, config `configs/sebs-gcp.json` with
`gcp-concurrency: 1`): 010.sleep, 110.dynamic-html, 610.api-proxy, 620.fetch-markdown, and the SDK variants
of 610/620 (`--language-variant sdk`). Functions and URLs are read from the SeBS cache.
The VM must hold this repository's mcp_bench/, configs/ and data/traces/ in ~/<vm-dir>.
Records go to results/gcp/<campaign>/<experiment>/<tier>/ on the VM and are synced back here.

Why the Cloud Run API and not SeBS's own update (Cloud Functions API): a new revision is ready in ~7 s
instead of ~33 s, and only the Cloud Run API can switch startup CPU boost off (Cloud Functions gen2
turns it on by default). Consequence: the Cloud Functions view of the functions (memory, CPU) is stale
during the campaign, and any Cloud Functions update (e.g. `sebs ... --update-code`) resets memory, CPU and
the boost. Don't run SeBS against these functions mid-campaign.

Cold starts: Cloud Run starts one instance as soon as a revision is deployed (DEPLOYMENT_ROLLOUT), so after
a forced cold start the next request would find an instance that has already started and imported the tool:
a fresh process, but not a request-triggered cold start as on Lambda (dry run 2026-11-20: 70 of 75 instance
starts were rollouts; 41 of 45 first requests landed on them). So e2 and e1b first *hold* that instance
(a request with X-Sebs-Hold-S, answered by the GCP wrapper with a sleep, concurrency 1) and then measure: the
session's first request has to start a new instance (AUTOSCALING). Hold requests are logged in holds.jsonl by
trace_id, to leave them out of the billing analysis; the request/system logs show per session which instance
it ran on. e4 doesn't hold: a pre-started instance per revision is how GCP behaves after a deployment.

Tiers: memory and CPU are independent on Cloud Run. The default tiers are Cloud Functions' own defaults for
these memory sizes, which match Lambda's memory-proportional CPU at the AWS campaign's points
(128 MB: Lambda ~0.07 vCPU, GCF 0.083; 512 MB: 0.29 vs 0.333; 1769 MB vs 2048 MB: 1 vCPU each).
The SDK variants need more than 128 MiB on GCP (OOM at 134 MiB, functions-framework + SDK) and are skipped
at smaller tiers.

Experiments, per tier:
  e2   cold vs warm: force a cold start, then one session (handshake + 5 calls) per tool, alternating MCP and
       plain invocation across repetitions; repeated for every --boost setting. Includes the SDK variants.
  e1b  extra instances: force a cold start, then 40 sequential calls with a fixed gap
  e1   MCP vs plain, warm: 200 calls per mode, interleaved in chunks of 50; 30 fresh handshakes;
       at the first tier also from this workstation (wide-area client)
  e3   time split: api-proxy at 50/200/1000 ms upstream delay (+ no connection reuse),
       fetch-markdown at 10 KB / 200 KB / 1 MB pages
Once:
  e4   trace replay at three session arrival intervals (first tier)
  logs Cloud Run request logs (latency, status, instance, revision per request; matched to client records by
       trace_id) and system logs (instance starts, startup probes, memory errors) for the whole campaign,
       plus configs.jsonl (which revision had which tier/boost) written as the campaign runs
"""

import argparse
import datetime
import http.client
import secrets
import threading
import json
import os
import shlex
import subprocess
import sys
import time
import uuid
from urllib.parse import urlsplit

import google.auth
from google.auth.transport.requests import AuthorizedSession

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGION = "europe-west1"
SEBS_CACHE = os.path.join(ROOT, "serverless-benchmarks", "cache")
BENCHMARKS = {"010": "010.sleep", "110": "110.dynamic-html", "610": "610.api-proxy", "620": "620.fetch-markdown"}
TRACE = "data/traces/livemcpbench-claude-sonnet-4.jsonl"
CODES = ["010", "110", "610", "620"]
SDK_CODES = ["610s", "620s"]
SDK_MIN_MEMORY_MB = 256
# --e2-serial: where functions wait between their measurements (the SDK variants need >128 MiB)
PARK = {"memory_mb": 128, "cpu": "0.083", "label": "park"}
PARK_SDK = {"memory_mb": 512, "cpu": "0.333", "label": "park"}
RUN = "https://run.googleapis.com/v2"
LOGGING = "https://logging.googleapis.com/v2"


def tools(upstream: str) -> dict:
    t = {
        "010": {"tool": "sleep", "args": {"sleep": 0}},
        "110": {"tool": "render_html", "args": {"username": "agent", "random_len": 100}},
        "610": {"tool": "search_products", "args": {"upstream": upstream, "latency_ms": 200, "size": 16384}},
        "620": {"tool": "fetch", "args": {"upstream": upstream, "latency_ms": 200, "size": 200000, "max_length": 5000}},
    }
    t["610s"], t["620s"] = t["610"], t["620"]
    return t


def functions_from_sebs_cache() -> dict:
    """code -> {name, url}; SDK variants as <code>s. SeBS names them sebs_<id>_<nr>_python[_sdk]_<version>_..."""
    fns = {}
    for code, bench in BENCHMARKS.items():
        path = os.path.join(SEBS_CACHE, bench, "config.json")
        if not os.path.exists(path):
            continue
        for name, fn in json.load(open(path)).get("gcp", {}).get("python", {}).get("functions", {}).items():
            if not name.endswith("_gen2"):
                continue
            key = code + ("s" if "_python_sdk_" in name else "")
            url = next(t["url"] for t in fn["triggers"] if t["type"] == "HTTP")
            fns[key] = {"name": name, "url": url, "service": name.replace("_", "-")}
    return fns


def memory_mb(limit: str) -> int:
    """Cloud Run memory limit ('128Mi', '2Gi', '512M') in MiB."""
    for suffix, factor in (("Gi", 1024), ("Mi", 1), ("G", 1e9 / 2**20), ("M", 1e6 / 2**20)):
        if limit.endswith(suffix):
            return round(float(limit[: -len(suffix)]) * factor)
    return round(int(limit) / 2**20)


def parse_tiers(text: str) -> list:
    tiers = []
    for item in text.split(","):
        mem, cpu = item.split(":")
        tiers.append({"memory_mb": int(mem), "cpu": cpu, "label": f"m{mem}c{cpu}"})
    return tiers


class Campaign:
    def __init__(self, args):
        self.args = args
        creds, self.project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        self.http = AuthorizedSession(creds)
        self.fns = functions_from_sebs_cache()
        missing = [c for c in CODES + SDK_CODES if c not in self.fns]
        if missing:
            raise SystemExit(f"not deployed with SeBS (gen2): {missing}")
        self.tools = tools(args.upstream)
        self.remote_dir = f"results/gcp/{args.campaign}"
        self.local_dir = os.path.join(ROOT, "results", "gcp", args.campaign)
        os.makedirs(self.local_dir, exist_ok=True)
        self.log = open(os.path.join(self.local_dir, "campaign.log"), "a")
        self.configs_log = open(os.path.join(self.local_dir, "configs.jsonl"), "a")
        self.ssh = ["ssh", "-i", os.path.expanduser(args.key), "-o", "BatchMode=yes",
                    "-o", "ServerAliveInterval=30", "-o", "ControlMaster=auto",
                    "-o", "ControlPath=~/.ssh/cm-mcpbench-%C", "-o", "ControlPersist=600", args.vm]
        state = os.path.join(self.local_dir, "state.json")
        if not os.path.exists(state):
            json.dump({"start": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                       "functions": self.fns, "project": self.project, "region": REGION}, open(state, "w"), indent=2)
        self.state = json.load(open(state))
        self.current = {}  # code -> {"memory_mb", "cpu", "boost"}

    def say(self, msg: str):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        self.log.write(line + "\n")
        self.log.flush()

    # --- function configuration (Cloud Run Admin API) ----------------------------------------------

    def _service(self, code) -> str:
        return f"projects/{self.project}/locations/{REGION}/services/{self.fns[code]['service']}"

    def _request(self, method, url, **kw):
        last = None
        for attempt in range(30):
            r = self.http.request(method, url, **kw)
            if r.status_code in (409, 429, 500, 503):
                last = f"{r.status_code} {r.text[:300]}"
                time.sleep(min(2 + attempt, 10))
                continue
            if not r.ok:
                raise RuntimeError(f"{method} {url}: {r.status_code} {r.text[:500]}")
            return r.json()
        raise RuntimeError(f"{method} {url}: gave up after retries, last: {last}")

    def _deploy(self, code, tier, boost, tag):
        """PATCH the service from its current definition (a fresh GET each time, so the etag is current)."""
        svc = self._request("GET", f"{RUN}/{self._service(code)}")
        container = svc["template"]["containers"][0]
        resources = container.setdefault("resources", {})
        if tier:
            resources["limits"] = {"memory": f"{tier['memory_mb']}Mi", "cpu": tier["cpu"]}
        if boost is not None:
            resources["startupCpuBoost"] = boost
        if tag:
            env = [e for e in container.get("env", []) if e["name"] != "cold_start"]
            container["env"] = env + [{"name": "cold_start", "value": tag}]
        svc["template"].pop("revision", None)
        return self._request("PATCH", f"{RUN}/{self._service(code)}", json=svc)

    def configure(self, codes, tier=None, boost=None, force_cold=True):
        """New revision per service: tier and/or boost and/or a fresh env var; new requests go to new instances.

        With --e2-serial, one service at a time (each revision pre-starts an instance, and at 1 vCPU six at once
        can exceed the project's CPU quota)."""
        groups = [[c] for c in codes] if self.args.e2_serial else [codes]
        for group in groups:
            pending = []
            for code in group:
                tag = uuid.uuid4().hex[:8] if force_cold else None
                pending.append((code, self._deploy(code, tier, boost, tag), tag))
            for code, op, tag in pending:
                for attempt in range(20):
                    while not op.get("done"):
                        time.sleep(1)
                        op = self._request("GET", f"{RUN}/{op['name']}")
                    if "error" not in op:
                        break
                    # The project's Cloud Run CPU quota (cpu_allocation, 20 vCPU in europe-west1) counts every
                    # live instance, idle ones of older revisions included: wait for them to wind down, redeploy.
                    if "Quota exceeded" not in str(op["error"].get("message", "")):
                        raise RuntimeError(f"configure {code}: {op['error']}")
                    self.say(f"  configure {code}: CPU quota exceeded, retrying in 60 s")
                    time.sleep(60)
                    op = self._deploy(code, tier, boost, tag)
                else:
                    raise RuntimeError(f"configure {code}: CPU quota still exceeded after 20 attempts")
                svc = self._request("GET", f"{RUN}/{self._service(code)}")
                res = svc["template"]["containers"][0]["resources"]
                cfg = {"memory_mb": memory_mb(res["limits"]["memory"]), "cpu": res["limits"]["cpu"],
                       "boost": bool(res.get("startupCpuBoost"))}
                self.current[code] = cfg
                self.configs_log.write(json.dumps(dict(cfg, ts=round(time.time(), 3), fn=code, cold_tag=tag,
                                                       revision=svc.get("latestReadyRevision", "").split("/")[-1])) + "\n")
        self.configs_log.flush()

    def hold(self, codes, seconds):
        """Occupy each function's idle (rollout-started) instance for `seconds`; returns once all holds are in."""
        holds_log = open(os.path.join(self.local_dir, "holds.jsonl"), "a")

        def send(code, trace_id):
            parts = urlsplit(self.fns[code]["url"])
            conn = http.client.HTTPSConnection(parts.netloc, timeout=seconds + 120)
            try:
                conn.request("POST", parts.path or "/", body=b"{}", headers={
                    "X-Sebs-Hold-S": str(seconds), "Content-Type": "application/json",
                    "X-Cloud-Trace-Context": f"{trace_id}/{secrets.randbits(63) or 1};o=0"})
                conn.getresponse().read()
            except OSError:
                pass
            finally:
                conn.close()

        for code in codes:
            trace_id = secrets.token_hex(16)
            holds_log.write(json.dumps({"ts": round(time.time(), 3), "fn": code, "trace_id": trace_id,
                                        "seconds": seconds}) + "\n")
            threading.Thread(target=send, args=(code, trace_id), daemon=True).start()
        holds_log.close()
        time.sleep(3)  # let the holds reach the instances before the measured requests

    def codes_for(self, codes, tier):
        return [c for c in codes if not (c in SDK_CODES and tier["memory_mb"] < SDK_MIN_MEMORY_MB)]

    # --- running the client --------------------------------------------------------------------

    def load_done(self):
        """--resume: the session outputs that already exist (complete ones only: clients write <out>.part and
        rename it on success), relative to the campaign directory, on the VM and (WAN runs) locally."""
        self.done = set()
        if not self.args.resume:
            return
        proc = subprocess.run(self.ssh + [f"cd {self.args.vm_dir}/{self.remote_dir} 2>/dev/null && "
                                          "find . -name '*.jsonl' -not -path './aborted/*'"],
                              capture_output=True, text=True, check=True)
        self.done = {line[2:] for line in proc.stdout.split()}
        for root, _, files in os.walk(self.local_dir):
            for f in files:
                if f.endswith(".jsonl"):
                    self.done.add(os.path.relpath(os.path.join(root, f), self.local_dir))
        self.say(f"resume: {len(self.done)} outputs exist and are skipped")

    def is_done(self, path) -> bool:
        return path in self.done

    def client(self, code, path, meta, mode="mcp", calls=10, interval=0.0, args=None, local=False, redo=False):
        if self.is_done(path) and not redo:
            return True
        spec = self.tools[code]
        out = f"{self.remote_dir}/{path}"
        meta = dict(meta, fn=code, mode=mode, client="workstation" if local else "vm", **self.current.get(code, {}))
        cmd = ["python3", "-m", "mcp_bench.client", "--url", self.fns[code]["url"], "--mode", mode,
               "--calls", str(calls), "--arguments", json.dumps(args or spec["args"]),
               "--meta", json.dumps(meta), "--output", out + ".part", "--trace-header"]
        if mode == "mcp":
            cmd += ["--tool", spec["tool"]]
        if interval:
            cmd += ["--interval", str(interval)]
        if local:
            os.makedirs(os.path.dirname(os.path.join(ROOT, out)), exist_ok=True)
            proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=1800)
            if proc.returncode == 0:
                os.replace(os.path.join(ROOT, out + ".part"), os.path.join(ROOT, out))
        else:
            remote = (f"cd {self.args.vm_dir} && mkdir -p {shlex.quote(os.path.dirname(out))} && {shlex.join(cmd)} "
                      f"&& mv {shlex.quote(out + '.part')} {shlex.quote(out)}")
            proc = subprocess.run(self.ssh + [remote], capture_output=True, text=True, timeout=1800)
        if proc.returncode:
            self.say(f"  FAILED {code} {mode} {meta}: {(proc.stderr or proc.stdout)[-400:]!r}")
        return proc.returncode == 0

    def sync(self):
        subprocess.run(["rsync", "-a", "-e", shlex.join(self.ssh[:-1]),
                        f"{self.args.vm}:{self.args.vm_dir}/{self.remote_dir}/", self.local_dir + "/"], check=False)

    # --- experiments ---------------------------------------------------------------------------

    def park(self, codes, boost=None):
        """Serial mode: move functions to a small tier between their measurements. Cloud Run keeps idle instances
        of a service's current revision ~15 min, older revisions' ones only 1-3 min; parked, a function's
        1 vCPU instances go away and don't count against the CPU quota while the others are measured."""
        for code in codes:
            self.configure([code], tier=PARK_SDK if code in SDK_CODES else PARK, boost=boost, force_cold=False)

    def e2(self, tier, boosts, reps=20):
        codes = self.codes_for(CODES + SDK_CODES, tier)
        serial = self.args.e2_serial
        for boost in boosts:
            tag = "boost" if boost else "noboost"
            if serial:
                self.park(codes, boost=boost)
            else:
                self.configure(codes, boost=boost, force_cold=False)
            for rep in range(reps):
                mode = "mcp" if rep % 2 == 0 else "plain"
                # Serial: one function at a time (configure at the tier, hold, session, park), so only one
                # function has 1 vCPU instances; needed where all of them together exceed the CPU quota.
                path = lambda code: f"e2/{tier['label']}/{tag}/{code}-{mode}-r{rep:02d}.jsonl"
                for group in ([[c] for c in codes] if serial else [codes]):
                    group = [c for c in group if not self.is_done(path(c))]
                    if not group:
                        continue
                    self.configure(group, tier=tier if serial else None, force_cold=True)
                    self.hold(group, self.args.hold)
                    for code in group:
                        self.client(code, path(code),
                                    {"exp": "e2", "tier": tier["label"], "rep": rep, "serial": serial},
                                    mode=mode, calls=5)
                    if serial:
                        self.park(group)
                self.say(f"  e2 {tier['label']} {tag} rep {rep + 1}/{reps} ({mode}) done")
        self.configure(codes, tier=tier if serial else None, boost=self.args.default_boost, force_cold=False)

    def e1b(self, tier, reps=2, intervals=(0.0, 0.25, 1.0)):
        for rep in range(reps):
            for interval in intervals:
                path = lambda code: f"e1b/{tier['label']}/{code}-i{interval}-r{rep}.jsonl"
                todo = [c for c in ("010", "110") if not self.is_done(path(c))]
                if not todo:
                    continue
                self.configure(todo, force_cold=True)
                self.hold(todo, self.args.hold)
                for code in todo:
                    self.client(code, path(code),
                                {"exp": "e1b", "tier": tier["label"], "rep": rep, "interval": interval},
                                calls=40, interval=interval)
            self.say(f"  e1b {tier['label']} rep {rep + 1}/{reps} done")

    def e1(self, tier, wan=False):
        t = tier["label"]
        for code in ("010", "110"):
            self.client(code, f"e1/{t}/{code}-warmup.jsonl", {"exp": "warmup", "tier": t}, calls=3, redo=True)
            for chunk in range(4):
                modes = ("mcp", "plain") if chunk % 2 == 0 else ("plain", "mcp")
                for mode in modes:
                    self.client(code, f"e1/{t}/{code}-{mode}-c{chunk}.jsonl",
                                {"exp": "e1", "tier": t, "chunk": chunk}, mode=mode, calls=50)
        for i in range(30):
            self.client("010", f"e1/{t}/handshake-{i:02d}.jsonl", {"exp": "e1hs", "tier": t, "i": i}, calls=1)
        self.say(f"  e1 {t} (vm) done")
        if wan:
            for chunk in range(4):
                for mode in (("mcp", "plain") if chunk % 2 == 0 else ("plain", "mcp")):
                    self.client("110", f"e1wan/{t}/110-{mode}-c{chunk}.jsonl",
                                {"exp": "e1wan", "tier": t, "chunk": chunk}, mode=mode, calls=50, local=True)
            for i in range(30):
                self.client("010", f"e1wan/{t}/handshake-{i:02d}.jsonl",
                            {"exp": "e1wan-hs", "tier": t, "i": i}, calls=1, local=True)
            self.say(f"  e1 {t} (workstation) done")

    def e3(self, tier, calls=32):
        up = self.args.upstream
        grid = [("610", {"latency_ms": lat, "size": 16384}) for lat in (50, 200, 1000)]
        grid.append(("610", {"latency_ms": 200, "size": 16384, "reuse_connection": False}))
        grid += [("620", {"latency_ms": 200, "size": size, "max_length": 5000}) for size in (10_000, 200_000, 1_000_000)]
        for code, params in grid:
            args = dict(upstream=up, seed=1, **params)
            label = f"{code}-l{params['latency_ms']}-s{params['size']}" + ("-noreuse" if params.get("reuse_connection") is False else "")
            meta = {"exp": "e3", "tier": tier["label"], "latency_ms": params["latency_ms"], "size": params["size"],
                    "reuse": params.get("reuse_connection", True)}
            self.client(code, f"e3/{tier['label']}/{label}.jsonl", meta, calls=calls, args=args)
        self.say(f"  e3 {tier['label']} done")

    def replay_config(self) -> str:
        cfg = json.load(open(os.path.join(ROOT, "configs", "replay.example.json")))
        cfg.pop("_comment", None)
        urls = {"api_wrapper": "610", "search_fetch": "620", "local_compute": "110", "default": "010"}
        for cls, code in urls.items():
            ep = cfg["endpoints"][cls]
            ep["url"] = self.fns[code]["url"] + "/"
            if "upstream" in ep["arguments"]:
                ep["arguments"]["upstream"] = self.args.upstream
        path = os.path.join(self.local_dir, "replay.gcp.json")
        json.dump(cfg, open(path, "w"), indent=2)
        return path

    def e4(self, tier, intervals=(1, 10, 60), sessions=20):
        cfg = self.replay_config()
        subprocess.run(["rsync", "-a", "-e", shlex.join(self.ssh[:-1]), cfg,
                        f"{self.args.vm}:{self.args.vm_dir}/configs/replay.gcp.json"], check=True)
        self.configure(CODES, tier=tier, force_cold=True)
        for interval in intervals:
            if self.is_done(f"e4/{tier['label']}/replay-a{interval}.jsonl"):
                continue
            self.configure(CODES, force_cold=True)
            out = f"{self.remote_dir}/e4/{tier['label']}/replay-a{interval}"
            remote = (f"cd {self.args.vm_dir} && mkdir -p {shlex.quote(os.path.dirname(out))} && "
                      f"MCP_BENCH_TRACE_HEADER=1 python3 -m mcp_bench.replay {TRACE} --config configs/replay.gcp.json "
                      f"--sessions {sessions} --concurrency {sessions} --arrival-interval {interval} "
                      f"--output {out}.jsonl.part > {out}.summary.json 2> {out}.stderr && mv {out}.jsonl.part {out}.jsonl")
            self.say(f"  e4 {tier['label']} arrival interval {interval}s: replaying {sessions} sessions")
            proc = subprocess.run(self.ssh + [remote], capture_output=True, text=True, timeout=7200)
            self.say(f"  e4 arrival interval {interval}s done (exit {proc.returncode})")
        self.sync()

    def logs(self):
        """Request and system log entries of the campaign's services since it started."""
        services = " OR ".join(f'resource.labels.service_name="{fn["service"]}"' for fn in self.fns.values())
        base = (f'resource.type="cloud_run_revision" AND ({services}) AND timestamp>="{self.state["start"]}"')
        code_of = {fn["service"]: code for code, fn in self.fns.items()}
        for kind, log_filter in (("requests", 'logName:"run.googleapis.com%2Frequests"'),
                                 ("system", 'logName:"run.googleapis.com%2Fvarlog%2Fsystem"')):
            out = os.path.join(self.local_dir, f"{kind}.jsonl")
            n, token = 0, None
            with open(out, "w") as f:
                while True:
                    body = {"resourceNames": [f"projects/{self.project}"], "filter": f"{base} AND {log_filter}",
                            "orderBy": "timestamp asc", "pageSize": 1000}
                    if token:
                        body["pageToken"] = token
                    page = self._request("POST", f"{LOGGING}/entries:list", json=body)
                    for e in page.get("entries", []):
                        labels = e["resource"]["labels"]
                        rec = {"fn": code_of.get(labels["service_name"]), "revision": labels.get("revision_name"),
                               "instance": e.get("labels", {}).get("instanceId"), "timestamp": e["timestamp"],
                               "severity": e.get("severity")}
                        if kind == "requests":
                            h = e.get("httpRequest", {})
                            rec.update(trace_id=e.get("trace", "").split("/")[-1], status=h.get("status"),
                                       latency_s=float(h.get("latency", "0s").rstrip("s") or 0),
                                       request_bytes=int(h.get("requestSize", 0)), response_bytes=int(h.get("responseSize", 0)))
                        else:
                            rec["text"] = e.get("textPayload") or json.dumps(e.get("jsonPayload"))
                        f.write(json.dumps(rec) + "\n")
                        n += 1
                    token = page.get("nextPageToken")
                    if not token:
                        break
                    time.sleep(1.1)  # entries:list allows 60 requests per minute
            self.say(f"logs: {n} {kind} entries written to {out}")


def main(argv=None):
    p = argparse.ArgumentParser(description="GCP Cloud Run functions campaign (E1-E4) for the MCP tool benchmarks.")
    p.add_argument("--vm", required=True, help="user@host of the client VM")
    p.add_argument("--key", required=True, help="SSH private key for the VM")
    p.add_argument("--vm-dir", default="mcpbench", help="Directory on the VM holding mcp_bench/, configs/, data/")
    p.add_argument("--upstream", required=True, help="Mock upstream URL as the functions reach it")
    p.add_argument("--campaign", required=True, help="Campaign id (results/gcp/<id>/)")
    p.add_argument("--tiers", default="128:0.083,512:0.333,2048:1", help="memory_MB:vCPU,... (see docstring)")
    p.add_argument("--boost", default="off,on", help="Startup CPU boost settings for e2 (off,on)")
    p.add_argument("--experiments", default="e2,e1b,e1,e3", help="Comma-separated: e2,e1b,e1,e3,e4,logs")
    p.add_argument("--reps", type=int, default=20, help="e2 repetitions per boost setting")
    p.add_argument("--hold", type=int, default=150,
                   help="Seconds to hold the rollout-started instance before e2/e1b sessions (must outlast them)")
    p.add_argument("--e2-serial", action="store_true",
                   help="Configure (and in e2 hold and measure) one function at a time: stays under the CPU quota at 1 vCPU")
    p.add_argument("--resume", action="store_true",
                   help="Skip sessions whose output already exists (VM, and locally for WAN runs)")
    p.add_argument("--skip-wan", action="store_true", help="Don't repeat e1's workstation (WAN) run at the first tier")
    args = p.parse_args(argv)
    boosts = [b.strip() == "on" for b in args.boost.split(",")]
    args.default_boost = True  # the platform default; it matters only for experiments other than e2 (warm ones)

    c = Campaign(args)
    c.load_done()
    tiers = parse_tiers(args.tiers)
    exps = args.experiments.split(",")
    per_tier = [e for e in ("e2", "e1b", "e1", "e3") if e in exps]
    if per_tier:
        for i, tier in enumerate(tiers):
            c.say(f"tier {tier['label']}: {', '.join(per_tier)}")
            c.configure(c.codes_for(CODES + SDK_CODES, tier), tier=tier, boost=args.default_boost, force_cold=True)
            for exp in per_tier:
                if exp == "e2":
                    c.e2(tier, boosts, reps=args.reps)
                elif exp == "e1":
                    c.e1(tier, wan=(i == 0 and not args.skip_wan))
                else:
                    getattr(c, exp)(tier)
            c.sync()
    if "e4" in exps:
        c.e4(tiers[0])
    if "logs" in exps:
        c.logs()
    c.say("campaign step finished")


if __name__ == "__main__":
    sys.exit(main())
