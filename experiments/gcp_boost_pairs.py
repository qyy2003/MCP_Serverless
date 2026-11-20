"""Usage: experiments/gcp_boost_pairs.py <output dir> <MCP_Serverless dir> experiments/gcp_cold_probe.py

NOTE: superseded. These first requests hit instances Cloud Run had pre-started for the new revision, so the
result says nothing about the boost (docs/progress.md, 2026-11-20 afternoon). gcp_campaign.py e2 does it right.

5 alternating cold-start pairs via the Cloud Run API: startupCpuBoost on vs off; only the boost differs."""
import sys, json
src = open(sys.argv[3]).read().split('print("before"')[0]
ns = {"__name__": "lib"}; sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
exec(compile(src, "probe", "exec"), ns)
rows = []
for i in range(5):
    for boost in (True, False):
        tag = f"pair{i}-{'boost' if boost else 'noboost'}"
        ns["via_run"](tag, boost)
        st = ns["run_state"](); r = ns["session"](tag)
        assert st["cold_start"] == tag and bool(st["boost"]) == boost and r["first_cold"]
        rows.append(dict(boost=boost, **r)); print(tag, r, flush=True)
for b in (True, False):
    xs = sorted(r["first_ms"] for r in rows if r["boost"] == b)
    print("boost" if b else "noboost", "first-request ms:", xs, "median", xs[len(xs)//2])
json.dump(rows, open(f"{sys.argv[1]}/boost-pairs.json", "w"), indent=1)
