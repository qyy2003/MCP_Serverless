"""Check that GCP cold-start sessions (e2, e1b) measured what they should: a request-triggered cold start.

Cloud Run pre-starts an instance per new revision (DEPLOYMENT_ROLLOUT); the campaign holds that instance with
an X-Sebs-Hold-S request so the session's first request has to start a new one (AUTOSCALING). A hold longer
than the function's request timeout is cut off (504): the held instance then counts as free, and its worker
keeps sleeping until gunicorn kills it. This script joins the client records (trace_id) with Cloud Run's
request log (instance per request) and system log (instance starts and their reason) and classifies each
session by where its first request went:

  ok        new AUTOSCALING instance, started by this request (start logged within --trigger-window s of it)
  rollout   an instance pre-started for the revision (DEPLOYMENT_ROLLOUT)
  held      the instance the hold request occupied
  existing  an AUTOSCALING instance that was already running (started by something else)
  unknown   no request-log entry for the first request

It also flags sessions whose first tools/call (or, plain mode, first call) went to a different instance than
the first request ("moved"): the benchmark import then happened elsewhere.

Usage: python experiments/gcp_session_check.py results/gcp/<campaign> [--list bad] [--json out.json]
"""
import argparse
import collections
import datetime as dt
import glob
import json
import os
import re
import sys

REASON = re.compile(r"Starting new instance\. Reason: (\w+)")


def epoch(iso: str) -> float:
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def load(campaign: str):
    requests = {}
    for line in open(os.path.join(campaign, "requests.jsonl")):
        r = json.loads(line)
        if r.get("trace_id"):
            r["t"] = epoch(r["timestamp"])
            requests[r["trace_id"]] = r
    starts = {}  # instance -> (time, reason)
    kills = collections.defaultdict(list)  # instance -> worker kill times
    for line in open(os.path.join(campaign, "system.jsonl")):
        e = json.loads(line)
        text = e.get("text") or ""
        inst = e.get("instance")
        if not inst:
            continue
        m = REASON.search(text)
        if m:
            starts[inst] = (epoch(e["timestamp"]), m.group(1))
        elif "WORKER TIMEOUT" in text:
            kills[inst].append(epoch(e["timestamp"]))
    holds = collections.defaultdict(list)  # fn -> [(ts, trace_id, seconds)]
    hold_file = os.path.join(campaign, "holds.jsonl")
    for line in open(hold_file) if os.path.exists(hold_file) else []:
        h = json.loads(line)
        holds[h["fn"]].append((h["ts"], h["trace_id"], h["seconds"]))
    for v in holds.values():
        v.sort()
    return requests, starts, kills, holds


def sessions(campaign: str):
    for exp in ("e2", "e1b"):
        for path in sorted(glob.glob(os.path.join(campaign, exp, "**", "*.jsonl"), recursive=True)):
            recs = [json.loads(l) for l in open(path)]
            if recs:
                yield exp, os.path.relpath(path, campaign), recs


def classify(recs, requests, starts, kills, holds, window):
    first = recs[0]
    fn = first["fn"]
    out = {"fn": fn, "tier": first.get("tier"), "boost": first.get("boost"), "mode": first.get("mode"),
           "rep": first.get("rep"), "interval": first.get("interval"), "first_ms": round(first["client_us"] / 1000, 1)}
    req = requests.get(first.get("trace_id"))
    # The hold sent for this session: the last one for this function before the session started.
    # (--holds > 1 sends several at once: all of them count.)
    before = [h for h in holds.get(fn, []) if first["ts"] - 600 <= h[0] <= first["ts"]]
    sent = [h for h in before if h[0] >= before[-1][0] - 1] if before else []
    hold_reqs = [q for q in (requests.get(h[1]) for h in sent) if q]
    hold_req = hold_reqs[0] if hold_reqs else None
    out["holds"] = len(sent)
    if hold_req:
        out["hold_cut"] = hold_req.get("status") == 504
        out["hold_s"] = round(hold_req.get("latency_s") or 0, 1)
        out["session_after_hold_s"] = round(first["ts"] - hold_req["t"], 1)
    if req is None:
        out["class"] = "unknown"
        return out
    inst = req["instance"]
    start = starts.get(inst)
    out["first_status"] = req.get("status")
    if any(inst == q["instance"] for q in hold_reqs):
        out["class"] = "held"
    elif start is None:
        out["class"] = "existing"  # started before the log window, or its start entry is missing
    elif start[1] == "DEPLOYMENT_ROLLOUT":
        out["class"] = "rollout"
    elif start[0] >= req["t"] - window[0] and start[0] <= req["t"] + window[1]:
        out["class"] = "ok"
    else:
        out["class"] = "existing"
    if start:
        out["start_minus_request_s"] = round(start[0] - req["t"], 2)
    # Where did the first benchmark call go?
    call = next((r for r in recs if r.get("phase") in ("tools/call", "plain")), None)  # plain: the first request
    call_req = requests.get(call.get("trace_id")) if call else None
    out["moved"] = bool(call_req and call_req["instance"] != inst)
    # Any request of the session queued behind the hold's sleeping worker (after the hold was cut)?
    out["behind_sleeper"] = False
    for h in hold_reqs:
        if h.get("status") != 504:
            continue
        cut = h["t"] + h["latency_s"]
        kill = min([k for k in kills.get(h["instance"], []) if k >= cut] or [cut + 900])
        out["behind_sleeper"] |= any(
            (q := requests.get(r.get("trace_id"))) and q["instance"] == h["instance"] and cut <= q["t"] <= kill
            for r in recs)
    n_inst = {requests[r["trace_id"]]["instance"] for r in recs if r.get("trace_id") in requests}
    out["instances"] = len(n_inst)
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("campaign")
    p.add_argument("--trigger-window", default="0.5,3",
                   help="An instance counts as started by the request if its start is logged within -a..+b s")
    p.add_argument("--list", choices=["bad", "all"], help="Print the sessions (bad: not ok, moved or behind_sleeper)")
    p.add_argument("--json", help="Write the per-session classification here")
    args = p.parse_args(argv)
    window = tuple(float(x) for x in args.trigger_window.split(","))
    requests, starts, kills, holds = load(args.campaign)
    rows = []
    for exp, path, recs in sessions(args.campaign):
        row = dict(classify(recs, requests, starts, kills, holds, window), exp=exp, path=path)
        row["bad"] = row["class"] != "ok" or row.get("moved") or row.get("behind_sleeper")
        rows.append(row)

    table = collections.defaultdict(collections.Counter)
    for r in rows:
        key = (r["exp"], r["tier"], "boost" if r["boost"] else "noboost", r["fn"])
        table[key][r["class"]] += 1
        table[key]["moved"] += bool(r.get("moved"))
        table[key]["sleeper"] += bool(r.get("behind_sleeper"))
        table[key]["n"] += 1
    cols = ["n", "ok", "rollout", "held", "existing", "unknown", "moved", "sleeper"]
    print(f"{'exp':4} {'tier':12} {'boost':8} {'fn':5} " + " ".join(f"{c:>8}" for c in cols))
    for key in sorted(table):
        print(f"{key[0]:4} {key[1]:12} {key[2]:8} {key[3]:5} " + " ".join(f"{table[key][c]:>8}" for c in cols))
    bad = [r for r in rows if r["bad"]]
    print(f"\n{len(rows)} sessions, {len(bad)} not clean")
    if args.list:
        for r in rows if args.list == "all" else bad:
            print(json.dumps(r))
    if args.json:
        json.dump(rows, open(args.json, "w"), indent=1)


if __name__ == "__main__":
    sys.exit(main())
