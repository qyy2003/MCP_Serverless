"""Usage: experiments/gcp_cold_probe.py <output dir> <MCP_Serverless dir>   (SeBS venv python)

Probe: forcing cold starts on Cloud Functions gen2, and whether startupCpuBoost can be turned off.

A: env-var update through the Cloud Functions v2 API (SeBS's way)
B: update of the underlying Cloud Run service (env var + startupCpuBoost=False)
C: A again -> does the Cloud Functions update switch the boost back on?
After each step, one MCP session (legacy) checks that the first request lands on a new, cold instance.
"""
import json, os, subprocess, sys, time
import google.auth
from google.auth.transport.requests import AuthorizedSession

OUT = sys.argv[1]
MCP_DIR = sys.argv[2]

creds, PROJECT = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
s = AuthorizedSession(creds)

# 010.sleep as deployed by SeBS (gen2); its name and URL come from the SeBS cache, not from the repo.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gcp_campaign import functions_from_sebs_cache  # noqa: E402
_fn = functions_from_sebs_cache()["010"]
FN = f"projects/{PROJECT}/locations/europe-west1/functions/{_fn['name']}"
URL = _fn["url"]


def ok(r):
    if not r.ok:
        raise RuntimeError(f"{r.status_code}: {r.text[:600]}")
    return r.json()


def wait_op(base, op):
    while not op.get("done"):
        time.sleep(2)
        op = ok(s.get(f"{base}/{op['name']}"))
    if "error" in op:
        raise RuntimeError(op["error"])
    return op


def service_name():
    return ok(s.get(f"https://cloudfunctions.googleapis.com/v2/{FN}"))["serviceConfig"]["service"]


def run_state():
    svc = ok(s.get(f"https://run.googleapis.com/v2/{service_name()}"))
    c = svc["template"]["containers"][0]
    env = {e["name"]: e.get("value") for e in c.get("env", [])}
    return dict(boost=c["resources"].get("startupCpuBoost"), cpuIdle=c["resources"].get("cpuIdle"),
                revision=svc.get("latestReadyRevision", "").split("/")[-1],
                cold_start=env.get("cold_start"), conc=svc["template"].get("maxInstanceRequestConcurrency"))


def via_functions(tag):
    f = ok(s.get(f"https://cloudfunctions.googleapis.com/v2/{FN}"))
    envs = {**f["serviceConfig"].get("environmentVariables", {}), "cold_start": tag}
    t = time.time()
    op = ok(s.patch(f"https://cloudfunctions.googleapis.com/v2/{FN}",
                    params={"updateMask": "serviceConfig.environmentVariables"},
                    json={"serviceConfig": {"environmentVariables": envs}}))
    wait_op("https://cloudfunctions.googleapis.com/v2", op)
    return time.time() - t


def via_run(tag, boost):
    name = service_name()
    svc = ok(s.get(f"https://run.googleapis.com/v2/{name}"))
    c = svc["template"]["containers"][0]
    env = [e for e in c.get("env", []) if e["name"] != "cold_start"] + [{"name": "cold_start", "value": tag}]
    c["env"] = env
    c["resources"]["startupCpuBoost"] = boost
    svc["template"].pop("revision", None)
    t = time.time()
    op = ok(s.patch(f"https://run.googleapis.com/v2/{name}", json=svc))
    wait_op("https://run.googleapis.com/v2", op)
    return time.time() - t


def session(tag):
    out = f"{OUT}/cold-{tag}.jsonl"
    subprocess.run([sys.executable, "-m", "mcp_bench.client", "--url", URL, "--arguments", '{"sleep": 0}',
                    "--calls", "3", "--protocol", "legacy", "--output", out],
                   cwd=MCP_DIR, check=True, capture_output=True)
    recs = [json.loads(l) for l in open(out)]
    first = recs[0]
    call = next(r for r in recs if r.get("exec_us") is not None)
    return dict(first_ms=round(first["client_us"] / 1000, 1), first_cold=first.get("is_cold"),
                first_container=str(first.get("container_id"))[:12],
                call_ms=round(call["client_us"] / 1000, 1), call_cold=call.get("is_cold"))


print("before", run_state(), flush=True)
for step, fn in [("A-functions", lambda: via_functions("cf1")),
                 ("B-run-noboost", lambda: via_run("run1", False)),
                 ("C-functions", lambda: via_functions("cf2"))]:
    dt = fn()
    print(f"{step}: update took {dt:.1f} s;", run_state(), flush=True)
    print(f"{step}: session", session(step), flush=True)
