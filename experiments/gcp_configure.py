#!/usr/bin/env python3
"""Set memory, CPU and startup CPU boost of Cloud Run services (Cloud Run functions gen2) and print the result.

    GOOGLE_APPLICATION_CREDENTIALS=<key> serverless-benchmarks/.venv/bin/python experiments/gcp_configure.py \\
        --memory 512 --cpu 0.333 --boost on <service> [<service> ...]
    ... gcp_configure.py --show <service> ...

Through the Cloud Run API, as experiments/gcp_campaign.py does: a Cloud Functions update (SeBS's path) would
reset CPU and turn the boost back on. Each change is a new revision, which Cloud Run pre-starts instances for.
"""
import argparse
import time

import google.auth
from google.auth.transport.requests import AuthorizedSession

RUN = "https://run.googleapis.com/v2"


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("services", nargs="+")
    p.add_argument("--region", default="europe-west1")
    p.add_argument("--memory", type=int)
    p.add_argument("--cpu")
    p.add_argument("--boost", choices=["on", "off"])
    p.add_argument("--timeout", type=int, help="Request timeout, s")
    p.add_argument("--show", action="store_true")
    a = p.parse_args()
    creds, project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    http = AuthorizedSession(creds)
    base = f"{RUN}/projects/{project}/locations/{a.region}/services"

    def show(name):
        svc = http.get(f"{base}/{name}").json()
        res = svc["template"]["containers"][0]["resources"]
        print(f"{name}: memory {res['limits'].get('memory')}, cpu {res['limits'].get('cpu')}, "
              f"boost {bool(res.get('startupCpuBoost'))}, cpuIdle {res.get('cpuIdle')}, "
              f"concurrency {svc['template'].get('maxInstanceRequestConcurrency')}, timeout {svc['template'].get('timeout')}, "
              f"min instances {svc['template'].get('scaling', {}).get('minInstanceCount', 0)}, "
              f"revision {svc.get('latestReadyRevision', '').split('/')[-1]}")

    if not a.show:
        ops = []
        for name in a.services:
            svc = http.get(f"{base}/{name}").json()
            res = svc["template"]["containers"][0].setdefault("resources", {})
            limits = res.setdefault("limits", {})
            if a.memory:
                limits["memory"] = f"{a.memory}Mi"
            if a.cpu:
                limits["cpu"] = a.cpu
            if a.boost:
                res["startupCpuBoost"] = a.boost == "on"
            if a.timeout:
                svc["template"]["timeout"] = f"{a.timeout}s"
            svc["template"].pop("revision", None)
            r = http.patch(f"{base}/{name}", json=svc)
            r.raise_for_status()
            ops.append((name, r.json()))
        for name, op in ops:
            while not op.get("done"):
                time.sleep(2)
                op = http.get(f"{RUN}/{op['name']}").json()
            if "error" in op:
                raise SystemExit(f"{name}: {op['error']}")
    for name in a.services:
        show(name)


if __name__ == "__main__":
    main()
