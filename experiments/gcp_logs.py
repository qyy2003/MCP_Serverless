#!/usr/bin/env python3
"""Fetch Cloud Run request and system logs for some services into requests.jsonl / system.jsonl.

Same record format as experiments/gcp_campaign.py's `logs` step, so gcp_session_check.py and
analysis/gcp_results.py can read the output.

    GOOGLE_APPLICATION_CREDENTIALS=<key> serverless-benchmarks/.venv/bin/python experiments/gcp_logs.py \\
        --since 2026-11-22T10:00:00Z --out <dir> --service <code>=<service> [--service ...]
"""
import argparse
import json
import os
import time

import google.auth
from google.auth.transport.requests import AuthorizedSession

LOGGING = "https://logging.googleapis.com/v2"
KINDS = (("requests", 'logName:"run.googleapis.com%2Frequests"'),
         ("system", 'logName:"run.googleapis.com%2Fvarlog%2Fsystem"'))


def fetch(services: dict, since: str, out_dir: str, until: str = None, say=print) -> dict:
    """services: code -> Cloud Run service name. Returns {kind: entries written}."""
    creds, project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    http = AuthorizedSession(creds)
    names = " OR ".join(f'resource.labels.service_name="{s}"' for s in services.values())
    base = f'resource.type="cloud_run_revision" AND ({names}) AND timestamp>="{since}"'
    if until:
        base += f' AND timestamp<="{until}"'
    code_of = {s: c for c, s in services.items()}
    os.makedirs(out_dir, exist_ok=True)
    counts = {}
    for kind, log_filter in KINDS:
        n, token = 0, None
        with open(os.path.join(out_dir, f"{kind}.jsonl"), "w") as f:
            while True:
                body = {"resourceNames": [f"projects/{project}"], "filter": f"{base} AND {log_filter}",
                        "orderBy": "timestamp asc", "pageSize": 1000}
                if token:
                    body["pageToken"] = token
                for attempt in range(5):
                    r = http.post(f"{LOGGING}/entries:list", json=body)
                    if r.status_code != 429:
                        break
                    time.sleep(10 * (attempt + 1))
                r.raise_for_status()
                page = r.json()
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
        counts[kind] = n
        say(f"logs: {n} {kind} entries")
    return counts


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--since", required=True)
    p.add_argument("--until")
    p.add_argument("--out", required=True)
    p.add_argument("--service", action="append", required=True, help="<code>=<Cloud Run service name>")
    a = p.parse_args()
    fetch(dict(s.split("=", 1) for s in a.service), a.since, a.out, a.until)


if __name__ == "__main__":
    main()
