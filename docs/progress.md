# Progress log

Newest first. Each entry: what was done → what came out of it. Details live in the linked files.

## Status at a glance

| Area | State |
|---|---|
| MCP wrapper, census, 2 tool benchmarks, replay driver | done (before 2026-11-18, see README) |
| Heavy-startup tool benchmark `630.data-analysis` | **built** 2026-11-22 (default + SDK variant, tests, local characterisation); GCP cold starts at 1 and 0.333 vCPU measured: [idle-experiment.md](idle-experiment.md) |
| SeBS local Docker runs | done: warm/cold suite on 4 benchmarks (2026-11-18), [results](results-local.md) |
| AWS Lambda campaign E1–E5 (teammate) | done 2026-11-18: [aws-results.md](aws-results.md) |
| Billing analysis (Q4) | first answer from the AWS campaign (E5) |
| Gap figure (SeBS catalog vs. MCP tools) | **local version done** 2026-11-19: 32 configs, [table](../results/local/characterize-summary.md), figures in `figures/local/gap-*.png`. Final numbers must come from a cloud run |
| Import placement as a switch: lazy / first request / startup | planned. Our earlier eager-import change was taken back out (it's in `git stash`) because it conflicted with the AWS campaign's `import_us` |
| Official-SDK tool variant (realistic dependencies) | **built and tested locally** 2026-11-19: `--language-variant sdk` of 610/620 (`mcp==2.3.0`), measured by `characterize.py`. No cloud run yet |
| MCP 2026-07-28 (no handshake) in shim and client | **done** 2026-11-19: both servers speak both revisions; `--protocol legacy\|modern\|auto`; SDK client conformance tests. Protocol cost experiment: `experiments/protocols.py` |
| Replay fixes (tool-router calls, more traces) | not started |
| Real MCP servers measured (gap argument) | **done** 2026-11-22: [real-servers.md](real-servers.md) |
| Idle-time experiment (cold starts of sparse traffic) | **GCP done** 2026-11-22 (sharp edge at 15 min); AWS by the teammate: [idle-experiment.md](idle-experiment.md) |
| GCP + Azure runs (needed for the presentation) | **MCP routing done** 2026-11-19 (shim + SDK variant, both protocol revisions; tested against local emulations). **GCP:** account `hpc-2026` set up, `010.sleep` smoke test on gen2 passed 2026-11-20 (startup CPU boost caveat below). **GCP campaign E1–E4 done** 2026-11-20, **analysed** 2026-11-22: [gcp-results.md](gcp-results.md). Still needed: Azure account and campaign. SeBS has no Oracle backend, so the third cloud is Azure |

## Log

### 2026-11-23: gen1 forced vs natural cold starts rerun; presentation reframed; figures

**gen1 forced cold starts, rerun from the VM** (`experiments/gcp_forced_cold.py`, `results/idle/gcp1-forced/`,
09:16–09:31 UTC, `010.sleep` gen1 128 MB): forced exactly as SeBS does (config update with a new `cold_start` env var,
wait for ACTIVE with the new version, request at once), probe = `run_plain` as in the idle run. 14/14 cold, 0 errors.
First request 172–353 ms from the VM (n = 10, median 298), 241–396 ms from the workstation (n = 4, median 377),
vs 756–969 ms natural (median 919, n = 6). **Reverses the 2026-11-22 note:** SeBS's forced cold start on gen1
*understates* the natural one ~3×; the earlier 2.1–2.5 s (SeBS `perf-cost`, scratch, no raw records) did not
reproduce from either client, cause unknown. The second call went to another, cold instance in 1 of 14 reps.
**Decision (with the user): the forced-vs-natural comparison is not used or mentioned in the presentation;** two
runs contradict each other, so neither direction is trustworthy.
Client VM started for this (new IP 35.233.108.209) and stopped afterwards.

**Presentation** ([presentation-outline.md](presentation-outline.md), draft 2): results sorted into new and
MCP-specific (A), MCP-motivated but generic (B), and generic platform behaviour / SeBS upkeep (C); kind-C results
only appear as consequences for MCP tools or in backup. SeBS already has `eviction_model` and `perf_cost`, which
cover the idle-time and tier experiments on the platform side. Next phase proposed: stateful MCP sessions on
stateless functions (30 of 108 servers keep state).

**Figures:** census chart (`analysis/census_figure.py` → `figures/census/classes-by-cost.png`) and three diagrams
(`figures/diagrams/{agent-mcp,pipeline,wrapper}.{svg,png}`).

### 2026-11-22 (evening): heavy-startup benchmark 630.data-analysis; idle-time results (GCP)

The real-server measurement showed a class our tools didn't cover: servers that are expensive to start (scientific
stack, data loaded at startup). `600.mcp/630.data-analysis` (tool `summarize_catalog`) imports pandas/numpy, loads a
dataset from the mock upstream on an instance's first call (`load_us`), then answers each call (group by month/tag/stock,
price and rating statistics) from memory. Input sizes set the dataset: 64 KB / 1 MB after 200 ms / 8 MB after 1 s.
Both variants (`default`: SeBS shim + pandas, 150 MB installed; `sdk`: official SDK + pandas, 191 MB). Tests in
`tests/test_mcp_tools.py` and `test_mcp_sdk.py` (need `SEBS_DATA_PYTHON` / `SEBS_SDK_PYTHON` with pandas).

- Local, 1 CPU (`characterize.py --only 630`): import 217 ms (SDK + pandas: 667 ms, vs 450 ms for the SDK alone),
  1 MB dataset load 233 ms (mostly the 200 ms upstream delay), warm calls 10–15 ms and CPU-bound. In the
  real-server figure the SDK variant sits at the real servers' p75 (import only, the load comes on top).
- GCP gen2 deploy (SeBS, 2026-11-22): works in both variants. On the first, pre-started instances at 1 vCPU (boost on),
  importing pandas took **3.7 s** and SDK + pandas **7.3 s**, 17× and 11× the laptop.
- Natural cold starts at 2048 MB / 1 vCPU, boost on, after 17 min idle (6 per variant, `results/idle/gcp-630-2048`):
  time to first result 3.3–6.4 s (SDK: 6.2–9.0 s), vs 1.3–1.7 s for the stdlib 610/620 at that tier.
  Same at 512 MB / 0.333 vCPU (20:10–21:53 UTC, `results/idle/gcp-630-512`): 3.9–7.8 s (SDK 5.4–10.8 s); with the
  boost on, the tier barely matters. 24 of 24 probes cold and request-started, 0 errors.

**Idle-time run, GCP** (14:51–18:32 UTC, 91 probes, 0 errors; [idle-experiment.md](idle-experiment.md#results-gcp-2026-11-22)):
all 49 probes after ≤ 15 min idle warm, all 42 after ≥ 16 min cold, on gen1 and gen2 alike; every gen2 cold probe
started its own instance. gen1 natural cold start ~0.9 s vs SeBS's forced 2.1–2.5 s (contradicted by the 2026-11-23 rerun; not used, see above). Client VM stopped afterwards (2026-11-22 ~22:00 UTC).

Also: the gap figures' group "MCP tools, stdlib (ours)" is now "MCP tools, without SDK (ours)", since 630's default
variant isn't stdlib-only.

### 2026-11-22 (afternoon): real MCP servers measured; SeBS cold starts on GCP checked; idle-time experiment set up

**Real servers** ([real-servers.md](real-servers.md)): 27 servers from LiveMCPBench, each installed and started in a throwaway container at 1 CPU (`experiments/real_servers/`, `analysis/real_servers.py`). Median 42 MB, 96 dependencies, 547 ms to initialise, 87 MB peak memory. Our SDK variant (41 MB, 460 ms) sits at the median, while the stdlib tools understate cold starts by about 100×. Startup is CPU-bound for 26 of 27. 3 of 13 Python servers break with MCP SDK 2.x (they don't pin `mcp<2`).

**SeBS cold starts on GCP** (scratch tests; SeBS `perf-cost` cold, 010.sleep):
- gen1 (SeBS's default) **hangs forever** in `enforce_cold_start`: `is_deployed` compares the v1 API's string `versionId` with an int. Fixed in our patch (upstream PR candidate). After the fix: 8/8 cold, 2.1–2.5 s from the workstation.
- gen2: 5/5 flagged cold. 4 of the 5 were served by instances started 7–11 s before the request (1.1 s each); 1 started its own instance (2.5 s). A natural cold start of the same function after ~1 h idle took 0.95 s from the VM. So the pre-started instances apparently don't hide much of the boot at 1 vCPU. Ground truth: the natural cold starts of the idle run.
- Natural cold starts at 128 MB / 0.083 vCPU without boost (services idle since 11-21): 9.7 s (010) and 8.8 s (110), AUTOSCALING started by the request. Matches the campaign's held sessions (9.4–11.2 s), so E2 is valid.
- Cloud Run's request-log latency included the startup for these natural cold starts but not for the campaign's held sessions. Don't use it for cold starts.

**Idle-time experiment** ([idle-experiment.md](idle-experiment.md)): `experiments/idle_probe.py` (one chain per function, probe → idle t → probe), `analysis/idle_results.py`, `experiments/gcp_logs.py`, `experiments/gcp_configure.py`. GCP tools set to 512 MB / 0.333 vCPU / boost on; 010 gen1 and gen2 as SeBS deploys them. Client VM restarted (new IP 207.175.158.212). Pilot (gaps 1, 3, 30 min) running. AWS: the teammate runs it with the same grid.

### 2026-11-22: GCP campaign analysed

`analysis/gcp_results.py` (tables: [gcp-tables-2026-11-20.md](gcp-tables-2026-11-20.md), figures `figures/gcp/`, write-up [gcp-results.md](gcp-results.md)). Cold sessions are filtered through `gcp_session_check.classify`: 477 of the 487 left after the earlier move-aside pass. No new cloud runs. Main results: cold starts at 0.083 vCPU take ~9–11 s without the startup CPU boost and ~1 s with it; the boost does nothing at 1 vCPU. Even at 1 vCPU, GCP cold starts are 3–5× Lambda's. The SDK import takes 2.2–2.7 s at 1 vCPU. Warm calls at 0.083 vCPU are bimodal (~11 / ~90 ms). Cloud Run's 100 ms billing granularity makes the MCP handshake 23–24% of the replay's cost (Lambda: 8.8%).

Found while analysing: Cloud Run's request-log latency leaves out most of a cold start (use client time + startup-probe timestamps); `cpu_us` has 10 ms resolution on Cloud Run. **To do before presenting:** check Cloud Run prices and the 100 ms rounding rule (the price page couldn't be fetched; the constants in `gcp_results.py` are 2025 list prices).

### 2026-11-20 (night): checking the cold sessions; stopped

`experiments/gcp_session_check.py` joins client records (`trace_id`) with Cloud Run's request and system logs and checks that each e2/e1b session's first request started a new instance itself. 216 of 676 sessions failed (mostly 128 and 512 MB: first request on a pre-started or idle instance, or on the instance whose hold had been cut by the request timeout; `110` has 10 s). Reruns with changed protocols (timeout 300 s, several holds, scale to zero via manual scaling, one hold per started instance) each ran into another Cloud Run behaviour: front-end 500s and spontaneous instance starts after switching scaling modes, and a new revision getting as many rollout instances as the previous one had, so counted holds snowballed until the services hit max instances (429). **Stopped there (user decision).** Clean sessions now: 2048 MB 232/240; 512 MB mostly 12–19 per cell (SDK without boost: 5 and 3); 128 MB mostly 8–18 (`110` without boost: 4, `620` with boost: 3); e1b 2–4 per cell. Use only sessions the check passes and report n per cell; the moved-aside sessions are in `aborted/` (on the VM and locally). Services now have timeout 300 s (SeBS: 10–120 s). The `--zero-first`/`--max-holds` options are untested. Client VM stopped; functions left deployed (idle, scale to zero).

**Campaign complete (20:28):** `results/gcp/2026-11-20/`: e2 at 3 tiers × boost off/on × 20 reps (4 functions at 128 MB, 6 at 512/2048 MB; 760 sessions), e1b, e1 and e3 at all tiers, e1wan at 128 MB, e4 (128 MB, arrival 1/10/60 s, 0 errors), `requests.jsonl` (11,576 entries) and `system.jsonl` (11,377). Not analysed yet; analysis must filter cold-start sessions by the instance start reason and check for holds cut off by the timeout (below).

The full campaign (`results/gcp/2026-11-20/`, started 14:46) finished the 128 MB and 512 MB tiers (e2 with 20 reps per function and boost setting, e1b, e1, e3; e1wan at 128 MB) with no failed sessions. At 2048 MB / 1 vCPU, the second e2 configure failed with `Quota exceeded for total allowable CPU per project per region`. Cloud Run's `cpu_allocation` quota is 20 vCPU in europe-west1 for this project, and it counts every live instance: per e2 rep, each of the 6 functions gets a rollout instance (held) plus 1–2 session instances, and idle instances of older revisions take a while to go away. At 1 vCPU per instance that's above 20.

Rerun of that tier with `--e2-serial` (configure, hold, measure one function at a time; hold 60 s instead of 150 s since it only has to outlast one session) and a quota retry in `configure` (wait 60 s, redeploy from a fresh GET; the first retry re-sent a stale service body and got 409s). Serial alone wasn't enough: after 2 reps, the next deploy hit the quota for 20 min. Instance counts per revision (Cloud Monitoring `container/instance_count`) show why: instances of a replaced revision go away within 1–3 min, but the **current** revision keeps its idle instances ~10–15 min, 2–4 per function (rollout, held, session, a spare), so the five functions not being measured still held ~15–18 vCPU. Fix: `park()` redeploys a function at a small tier (128 MB/0.083 vCPU, SDK variants 512 MB/0.333) right after its session, so only the measured function has 1 vCPU instances; all go back to the tier after e2. The two aborted attempts are kept in `aborted/` on the VM.

**Paused at 17:55** (laptop had to go): 2048 MB e2 noboost reps 0–16 done and complete (102 files on the VM, nothing partial). Still to do for this tier: noboost reps 17–19, all 20 boost reps, e1b, e1, e3; then e4 (128 MB) and logs. Needs a resume option first (skip sessions whose output exists; write to `.part` and rename on success).

**Resumed 18:43** with `--resume` (skips sessions whose output exists; clients write `<out>.part` and rename on success).

**Caveat for the analysis: holds are capped by the function's request timeout.** SeBS deploys `110` with 10 s, `610`/`620` (+ SDK) with 60 s, `010` with 120 s. A longer hold gets a 504 at the timeout, Cloud Run counts the instance as free again, and gunicorn kills the still-sleeping worker later (`WORKER TIMEOUT`, SIGKILL, new worker). In the batched 128/512 MB tiers (hold 150 s, six sessions in a row after the holds), a session that started after its function's timeout may have had its first request routed to the rollout instance or queued behind the sleeping worker; most likely for `110` (10 s, second in line). The analysis has to check per session: first request's instance (request log via `trace_id`) must be an AUTOSCALING start and not the hold's instance. In the serial 2048 MB tier the session starts 3 s after the hold, so this mostly doesn't arise. Fix for later campaigns: raise the services' `timeout` (doesn't affect performance) or clamp each hold below it.

One e2 session failed (2048 MB boost, `110` mcp r00): `initialize` went to the new revision, `tools/list` 6 ms later to the previous one, which had no instances (HTTP 500 after 0 s): a routing glitch right after the traffic switch. It has no output, so a `--resume` pass after the campaign redoes it.

Side finding for the write-up: an idle Cloud Run instance of the serving revision isn't billed for CPU (`cpuIdle`), but it does hold quota, and with concurrency 1 a burst leaves several of them per function for ~15 min. The 128/512 MB tiers ran batched (all 6 configured, then 6 sessions); both ways give request-triggered cold starts, but note the difference when comparing tiers. A quota increase would allow the batched mode at 1 vCPU too.

### 2026-11-20 (afternoon): GCP campaign script, and what a cold start is on Cloud Run

**Infrastructure:** `_Default` log sink re-enabled (it had been disabled, not on purpose): request, stdout/stderr and system logs are kept again. Firewall rule `mcpbench-upstream-8080` (tcp:8080 from anywhere, only to VMs tagged `mcpbench-upstream`); the mock upstream moved from 3389 to 8080. `110.dynamic-html` deployed on GCP.

**Client:** `--trace-header` (replay: `MCP_BENCH_TRACE_HEADER=1`) sends a fresh `X-Cloud-Trace-Context` per request and records it as `trace_id`. Cloud Run logs it as the request's trace: 260/260 client records matched their request-log entry (latency, status, instance, revision), including handshake and 202 responses. GCP's counterpart of `x-amzn-RequestId`.

**`experiments/gcp_campaign.py`:** E1–E4 as on AWS, plus the SDK variants and startup boost off/on in e2. Configuration and cold starts through the Cloud Run API (7 s per revision). Logs: `requests.jsonl`, `system.jsonl` (instance starts with reason, startup probes, memory errors), `configs.jsonl` (revision → tier/boost), `holds.jsonl`.

**Decision, to revisit: tiers follow Cloud Functions' default CPU per memory size**, 128 MB/0.083 vCPU, 512 MB/0.333, 2048 MB/1. That matches Lambda's memory-proportional CPU at the AWS campaign's points (≈0.07 / 0.29 / 1 vCPU). The functions as SeBS deploys them have 1 vCPU at any memory size. All tiers accepted on these services (`cpuIdle: true`, concurrency 1).

**SDK variant needs >128 MiB on GCP:** `Memory limit of 128 MiB exceeded with 134 MiB used` (functions-framework's gunicorn + the SDK; one process locally is 75 MiB), then Cloud Run keeps restarting instances. The campaign skips the SDK variants below 256 MiB. Worth reporting: the realistic stack doesn't fit the smallest tier.

**Cold starts on Cloud Run are not Lambda's:** Cloud Run starts an instance as soon as a revision is deployed (`DEPLOYMENT_ROLLOUT`). In the first dry run (forced cold start = new revision, then a session), 70 of 75 instance starts were rollouts and 41 of 45 first requests landed on them, 3–20 s after they had started and imported the tool: the process was fresh (`is_cold`), but the client didn't wait for it. Example: SDK instances reported 3.3–7.2 s import, while the first request took 79–140 ms. **This invalidates this morning's boost pairs** (`gcp_boost_pairs.py`: "no visible boost effect" on `010`): those first requests also hit rollout-started instances.

Fix: the GCP wrapper answers a request with header `X-Sebs-Hold-S: N` with an N-second sleep (no benchmark call, cold marker untouched). e2/e1b first hold the rollout instance of every function (concurrency 1), so the session's first request has to start a new instance (`AUTOSCALING`). Second dry run (2 reps × 2 boosts × 2 tiers × 6 functions): 37 of 40 sessions started on an AUTOSCALING instance; the analysis must filter by the instance's start reason (system log). 11 of them used more than one instance during the session. e4 (replay) doesn't hold: a pre-started instance per revision is what GCP does after a deployment.

First request-triggered cold starts (2 samples per cell, indicative only): at 128 MB / 0.083 vCPU **without boost, 10–23 s** to the first response for `010` and `610`; with boost 0.7–1.6 s. At 512 MB / 0.333 vCPU: 1–3 s without, 0.8–1.5 s with. SDK variant at 512 MB: import 3.0–3.2 s with boost, 6.0–6.3 s without. So at fractional CPU the boost is what keeps cold starts usable, presumably why Google turns it on by default. The full campaign measures both.

### 2026-11-20: GCP account and deployment choice

GCP project `hpc-2026`; service account key via `GOOGLE_APPLICATION_CREDENTIALS` (never in a config file). Required APIs enabled; the service account has the Cloud Functions, Cloud Run, Storage, Logging and actAs permissions (not Compute/Firestore yet). Config: `configs/sebs-gcp.json`, region `europe-west1`.

**Deployment choice, to revisit:** Cloud Functions **gen2** (`function-gen2`, Cloud Run underneath) with `gcp-concurrency: 1`, so an instance serves one request at a time like Lambda. Open questions for the write-up: gen1 vs gen2 cold starts; whether gen2's default concurrency (80) changes cold-start counts and cost for tools that mostly wait (one instance could absorb many waiting calls, which Lambda can't); Cloud Run's billing model. State the choice in every GCP table.

**Smoke test, 2026-11-20 13:44 (`results/gcp/smoke/`):** `010.sleep` deployed as `function-gen2` in 70 s, served 5/5 plain invocations and two MCP sessions (`--protocol legacy` and `modern`, 5 calls each). Warm `tools/call` from the workstation: 31–54 ms client time, 73–90 µs in the function. Deployed settings, read back from the API: 128 MiB, 1 vCPU, `maxInstanceRequestConcurrency: 1`, max 20 instances, `cpuIdle: true` (CPU only during requests). **Caveat:** `startupCpuBoost` is **on**, although the config says `cpu-boost: false`. SeBS applies `cpu-boost`/`cpu-throttle` only in `container` mode; Cloud Functions v2 doesn't expose it and turns it on by default. So GCP cold starts get extra CPU during startup, which Lambda doesn't. Either set it on the underlying Cloud Run service after each deploy, or report it. **Forcing cold starts and the boost, 2026-11-20 (`experiments/gcp_cold_probe.py`, `gcp_boost_pairs.py`; raw data `results/gcp/smoke/cold-*.jsonl`, `boost-pairs.json`):**

| | update via Cloud Functions API (SeBS's way) | update via the Cloud Run service |
|---|---|---|
| Time until the new revision serves | 31–35 s | 7 s |
| Next request cold, on a new instance | yes (3/3) | yes (11/11) |
| Can turn `startupCpuBoost` off | no | yes |

Any Cloud Functions update (SeBS's cold-start forcing, `--update-code`) switches the boost back **on**. So for a controlled campaign: deploy with SeBS, then force cold starts and set the boost through the Cloud Run API.

`010.sleep`, 5 alternating cold-start pairs, only the boost differs: first request (`initialize`) 99–1426 ms with boost (median 230), 115–1418 ms without (median 175). No visible boost effect for a tool that imports almost nothing; GCP cold starts are bimodal (≈100–250 ms or ≈1–1.4 s) either way. A first single pair (218 vs 1115 ms) had suggested a large effect: noise. Still to test: the SDK variant (≈470 ms CPU-bound import), where the boost should matter if anywhere.

**All four tool functions on GCP, 2026-11-20 afternoon (`results/gcp/smoke/`, VM sessions in `vm/`):**

- **Client VM** `mcpbench-client`: e2-small, europe-west1-b, Debian 12, ephemeral external IP (changes if the VM is stopped; look it up in the console, not kept in the repo), SSH user `mcpbench` with key `~/.ssh/gcp-mcpbench`. `mcp_bench/`, `configs/`, `data/traces/` in `~/mcpbench`. Mock upstream runs as systemd unit `mock-upstream` on **port 3389**: the service account can't create firewall rules, and the default network only lets 22/3389/ICMP in. Move to 8080 once there's a firewall rule.
- **Bug found and fixed: the SDK variant didn't start on GCP.** The GCP wrapper *appends* the shipped packages to `sys.path`, so the runtime's own (functions-framework 3.10.2) older copies win: typing_extensions 4.13.2, starlette 1.3.1, anyio 4.14.2, uvicorn 0.33.0. pydantic-core then fails on `from typing_extensions import Sentinel`, the container never listens, and the deploy fails with a health-check error. Found by rebuilding the runtime's exact package set (read from the function image) in a 3.11 venv. Fix: for SDK packages the wrapper now puts its packages *first* (only `click` is imported before `main.py`, so that's safe); other benchmarks keep SeBS's append. The SDK now reports the shipped versions (`_meta.sebs.sdk_versions`: mcp 2.3.0, starlette 1.10.0, anyio 4.16.0, pydantic 2.14.4). `tests/fake_cloud.py` didn't catch this because it runs with whatever functions-framework is installed locally; it should pin the runtime's set (`gcf-platform-reqs.txt` approach).
- **Smoke sessions from the VM** (in-region; both protocol revisions; 10 warm calls each, p50; no errors):

| | call (client) | exec (function) |
|---|---|---|
| 610 stdlib, 200 ms upstream | 215.4–215.5 ms | 202.6–202.7 ms |
| 610 SDK | 217.4–218.9 ms | 204.3–204.7 ms |
| 620 stdlib, 100 kB page, 100 ms upstream | 124.9–125.6 ms | 112.7–113.0 ms |
| 620 SDK | 128.3–130.7 ms | 115.3–116.8 ms |

  About 12–14 ms per call outside the function in-region (AWS: 12–20 ms). One cold SDK instance reported `init_import_us` = 2.2 s (local: ≈0.47 s), at 128 MiB / 1 vCPU **with** startup boost. One sample, so only a hint; the campaign should measure it properly, with and without boost.
- **Cloud logging is off in this project:** the `_Default` log sink is disabled, so only audit logs are kept: no container stdout/stderr, no Cloud Run request logs. Needed for the campaign (request logs = per-request latency/billing data) and for debugging.

Not tested yet: 610/620

### 2026-11-20 (early): MCP routing for GCP and Azure

The GCP and Azure Python wrappers route MCP like AWS: JSON-RPC bodies to the stdlib shim, or (SDK variant) the raw request with its headers to the SDK bridge, built when the wrapper module loads. The plain path also reports `cpu_us`, `child_cpu_us` and `import_us` now, so all four platforms return the same measurement fields. Both protocol revisions work on both platforms.

Tested against local emulations of each platform's HTTP layer (`tests/fake_cloud.py`): GCP runs the generated `main.py` under Google's functions-framework (gunicorn, as on Cloud Run functions); Azure hands `azure.functions.HttpRequest` objects to `main()` (the Functions host itself isn't emulated). `tests/test_mcp_platforms.py`: shim and SDK variant in every protocol mode, the plain path, and the official SDK client in all three modes against both servers, per platform. 55 tests, all pass.

To check on the first real runs:
- **GCP dependency shadowing:** the platform installs functions-framework, which brings starlette, anyio and uvicorn, ahead of the package's own dependencies on `sys.path`. Current versions satisfy both, but the SDK bridge now reports what it actually loaded (`_meta.sebs.sdk_versions`, first response of an instance).
- **Azure:** the worker loads the function module on its first invocation, so the SDK import lands in the first request (fine for cold-start measurements). A function app may run several workers per instance; `is_cold_worker` tells them apart.
- Nothing has been deployed to GCP or Azure yet (no accounts).

### 2026-11-19 (late night): MCP 2026-07-28, and both tool variants in the gap comparison

**Protocol:** the stdlib shim now also speaks 2026-07-28 (no handshake; `server/discover`; `resultType`/`cacheScope`/`ttlMs`), with handshake-era responses unchanged. `mcp_bench.client --protocol legacy|modern|auto` (auto = the SDK client's default: discover, else handshake). The official SDK client works against both servers in all three modes. Against a server that only speaks the handshake revisions (e.g. functions deployed before today), `auto` pays a failed `server/discover` **plus** the handshake: 4 requests before `tools/list`. Tests: 43, all pass (`tests/test_mcp_protocols.py`, more in `tests/test_mcp_sdk.py`).

**Gap comparison:** `experiments/characterize.py` now calls the MCP tools over MCP (`tools/call`, default `--protocol modern`) in both variants (`default`, `sdk`); SeBS benchmarks as before. The earlier plain-path 6xx results are kept in `results/local/characterize-6xx-plain/`. Local results, warm medians:

| | stdlib | SDK |
|---|---|---|
| Cold import (45 cold samples each) | median 1.0 ms | median 470 ms (409–1017; bimodal, laptop CPU states) |
| Import / warm call | 0.1–2% | 80% (1 s upstream) to 9× (50 ms upstream) |
| CPU per call, 610 | 1.2 ms | 2.9 ms |
| Time outside the measured execution, 610 | 2.3 ms | 3.8 ms |
| Response, 610 | 2.3 kB | 2.8 kB (the SDK pretty-prints the JSON text) |

**Session start per protocol** (`experiments/protocols.py`, local, warm medians, 20 sessions each; time from a new connection to the first tool result):

| | requests | 010.sleep (50 ms) | 610 stdlib (50 ms upstream) | 610 SDK |
|---|---|---|---|---|
| legacy (handshake) | 4 | 56.3 ms | 57.2 ms | 66.3 ms |
| auto (discover) | 3 | 55.0 ms | 56.2 ms | 60.8 ms |
| modern (2026-07-28) | 2 | 53.7 ms | 54.9 ms | 59.1 ms |

Locally an extra request costs 1–3.5 ms (most with the SDK); in the cloud each one is a network round trip, so this is the comparison to repeat there. Local cold sessions don't include the SDK import (SeBS waits for `/alive`), unlike Lambda's init phase.

Wait share and traffic per call are unchanged, so in `gap-wait`/`gap-work` the SDK points sit on the stdlib ones. In `gap-cold` the SDK moves the tools from the bottom left into the middle of the SeBS benchmarks: by cold cost relative to the work, a realistic MCP tool looks like `110.dynamic-html` or `210.thumbnailer`, not like `010.sleep`.

### 2026-11-19 (night): official-SDK variant of the MCP tools

**What:** 610 and 620 as real SDK servers: `MCPServer` + `@mcp.tool()` with typed parameters, calling the unchanged tool logic. Deployed with `--language-variant sdk` (a SeBS overlay variant), so the benchmark, its input and validation stay the same. Details: [mcp-wrapper.md](mcp-wrapper.md#sdk-variant).

**How it runs:** the SDK's own stateless JSON Streamable HTTP app, driven in-process by `mcp_sdk_bridge.py` the way Mangum or Azure's ASGI middleware would. The server is imported at instance startup (Lambda init phase), as real servers do. The bridge has no platform code, so the GCP/Azure ports can reuse it. 12 new tests (`tests/test_mcp_sdk.py`, need `SEBS_SDK_PYTHON`); all 32 pass.

**First local numbers** (620, 200 kB page; laptop, one deployment, so indicative only):

| | stdlib (default) | SDK |
|---|---|---|
| Code package | 27 kB | 41 MB |
| Container memory | 17 MB | 52 MB |
| Import | 1–5 ms, lazily in the first call | 455 ms at startup (`mcp_types` alone ≈250 ms: pydantic models for the whole protocol) |
| Warm `tools/call` exec | ≈228 ms | 226–235 ms |

So the realistic stack changes the cold start by two orders of magnitude, but not the warm call.

**Found on the way:**
- **MCP 2026-07-28 drops the `initialize` handshake on HTTP:** every POST is self-contained (version, client info and capabilities in `_meta`; `Mcp-Method`/`Mcp-Name` headers). SDK 2.x serves both revisions; our shim and client speak only the handshake revisions. Our handshake findings (≈4 ms and 3 round trips per session; the handshake absorbing the cold start) apply to the older revisions only.
- **SeBS bugs fixed:** function names ignored the language variant, so deploying a variant replaced the default function (on AWS it would have overwritten the deployed one). Local also looked for a separate run image per variant.
- **Lambda memory:** both tools are configured with 128 MB. Lambda's CPU share scales with memory, so the 455 ms import may take seconds there; worth a memory sweep.
- **Coverage:** the census is half Python, half Node (50/50); this variant covers the Python half.

### 2026-11-19 (evening): gap comparison, full local run

Run: `experiments/characterize.py`, all 32 configs, 0 failed, 10 warm + 5 cold samples each. Table: `results/local/characterize-summary.md` (git-ignored; regenerate with the command at the top of `analysis/characterize_summary.py`). Figures: `figures/local/gap-wait.png`, `gap-work.png`, `gap-cold.png`, data in `gap-data.csv`.

| Finding | Numbers (local, warm medians) |
|---|---|
| **MCP tools wait; SeBS benchmarks compute.** Only two SeBS benchmarks spend most of a call not computing: `010.sleep` (synthetic) and `120.uploader` (real-internet download). | MCP tools: 96–100% waiting, except `620` at 1 MB (61%: 131 ms CPU for the HTML→Markdown conversion). SeBS: 010 99%, 120 74–81%, all others ≤22%. |
| **Little work per call.** No SeBS benchmark other than the synthetic `010` combines little CPU, little traffic and a long call. | MCP tools: ≤2.6 ms CPU and ≤70 kB per call (except `620` at 200 kB/1 MB). `120` waits as much, but moves 0.5–14 MB and uses 29–165 ms CPU. |
| **Cold import is negligible relative to the call.** | MCP tools: 1–5 ms import, 15–19 kB packages, 0.1–2.6% of a call. SeBS: 0.6 ms (010) to 4.4 s (411, PyTorch), up to ≈120× the warm call. |

Caveats, before these go into the presentation:
- The MCP tools' wait shares and cold ratios reflect the mock latencies we chose (50–1000 ms), not observed tool latencies. Real latency distributions should come from the traces.
- Our tools use only the standard library. Real MCP servers ship the SDK and their dependencies, so the cold-import finding needs the official-SDK variant (open item) before we claim it.
- Laptop CPU clock noise: in `220`, ffmpeg CPU time doubles across identical warm calls (4.9 → 10 s); in `311`, cold calls range from 0.5 to 1.1 s. So `cold_ratio` (cold minus warm client time) came out negative for 220 and 311. The cold figure now plots `import_ratio` (import time / warm exec), which is measured directly. Both columns stay in the table.
- `504.dna-visualisation` really sends 168 MB per call: it uploads its result to object storage.
- The laptop was suspended 18:26–21:37 while `610 lat200-64k` was deploying. Its samples (205–208 ms) match the neighbouring configs, so they're unaffected.
- Figure labels: points whose labels would collide share one (e.g. `504` for test + small). Two small overlaps remain, in the 0% row of `gap-wait` and the bottom-left of `gap-work`.

### 2026-11-19: gap comparison, local pipeline

| Done | Result |
|---|---|
| `child_cpu_us` added to the local server and the AWS handler (additive; `cpu_us`/`import_us` unchanged) | `time.process_time()` misses subprocess CPU, e.g. ffmpeg in `220.video-processing`, which would have looked like pure waiting |
| Local server: `cpu_us`, `import_us` like the AWS handler, plus yesterday's timing fix, re-applied on top of the teammate's patch | Local and AWS records have the same fields |
| `experiments/characterize.py`: 12 SeBS benchmarks × test/small + MCP tool sweeps (610: 50/200/1000 ms × 4/64 KB; 620: 10 KB–1 MB), 10 warm + 5 cold each | Per call: exec, CPU (+children), network bytes (container counters read from the host), import time, cold penalty, package size |
| `analysis/characterize_summary.py`: table + 3 figures (wait share, CPU vs. network bytes, cold ratio vs. package size) | Same palette/style as the AWS figures |
| Smoke test (010, 120, 610) | **`120.uploader` also waits 70–86%**: it downloads from Wikipedia over the real internet. The wait-share axis alone won't separate SeBS from MCP tools, so the gap must be argued on several axes together |

Excluded: `020`/`030`/`040`, which are network/clock measurement tools needing a counterpart server, not application workloads.

### 2026-11-18: first SeBS local runs

**Setup**
- Native Docker daemon, not Docker Desktop. SeBS on Linux calls container bridge IPs, which Desktop's VM hides. Tested: unreachable under Desktop, reachable natively.
- SeBS installed in `serverless-benchmarks/.venv`. Local run image rebuilt with our patch. Object storage via `sebs storage start object`.
- Mock upstream bound to the Docker bridge: `python -m mcp_bench.mock_upstream --host 172.17.0.1 --port 8080`.
- New: `configs/sebs-local.json` (experiment config), `mcp_bench/local_suite.py` (warm/cold driver), `analysis/local_summary.py` (tables with bootstrap 95% CIs).

**Fixes to SeBS (in `patches/serverless-benchmarks.patch`)**

| Done | Result |
|---|---|
| Local server, plain route: `end` timestamp moved after the function call | Upstream bug: `begin`/`end` timed only the module import. Local plain-mode exec times were meaningless before. Worth an upstream PR. |
| MCP wrappers (local + AWS): import the tool on the first request of any kind | Before, the cold import cost landed on the first `tools/call`, which reported `is_cold=false`. Real MCP servers load tools at startup. Smoke data with lazy import kept in `results/local/smoke-lazy-import`. **Taken back out on 2026-11-19** (conflicts with the AWS campaign's `import_us`); to return as a switch. `results/local/run1` was measured *with* it. |

**Measurements**

| Done | Result |
|---|---|
| `610.api-proxy` (200 ms upstream, 16 KB), 100 warm calls MCP vs. plain | Median 204.06 vs. 204.05 ms. Time outside the function 2.01 vs. 1.87 ms, so MCP adds ≈0.13 ms per call. Handshake ≈10 ms per session (`initialize` 7.0 ms incl. connect). |
| Same | MCP response is ≈2× the plain one (2,176 vs. 1,033 B): the result is sent both as JSON text and as `structuredContent`, as the MCP spec recommends. |
| `110.dynamic-html` smoke run, lazy import (2 samples) | Cold `initialize` 2.8 ms; the ≈22 ms jinja2 import fell on the first `tools/call`, which was flagged warm. Led to the import fix above. |
| **Full suite** (`010.sleep`, `110.dynamic-html`, `610.api-proxy`, `620.fetch-markdown`): 20 warm sessions × 5 calls + 15 cold samples per mode. Full tables: [results-local.md](results-local.md) | See the findings below. |

**Findings from the full suite** (local, medians, 95% CIs in [results-local.md](results-local.md)):

1. **Per-call MCP overhead is small and grows with the response size.** It's 0.09–0.17 ms for responses of 0.2–11 KB, and 0.52 ms for `110.dynamic-html`'s 73 KB response. MCP responses are ≈2× plain for every tool (text + `structuredContent`).
2. **The handshake costs ≈4 ms warm (3 requests) once per session.** On local that's mostly HTTP server overhead; on a real network it becomes 3 round trips.
3. **With eager import, the handshake absorbs the process-level cold start.** For `110.dynamic-html`: cold handshake 21.2 ms vs. 3.7 ms warm; first-call exec 5.3 ms (MCP) vs. 22.3 ms (plain). Time to first result, cold: MCP 28.2 ms vs. plain 24.2 ms. So MCP's added cold cost is the handshake round trips, nothing more.
4. **Process-level cold starts on local are small:** ≈1–2 ms for the stdlib tools, ≈7 ms for `620`, ≈18 ms for jinja2. Local can't show sandbox boot or network RTT, so the magnitudes that matter need AWS. Local confirms the mechanisms and that the harness works.

## Open issues / notes

- **GCP startup CPU boost (caveat for every GCP cold-start number):** Cloud Functions gen2 deploys with `startupCpuBoost: true`, whatever SeBS's `cpu-boost` says (SeBS applies `cpu-boost`/`cpu-throttle` only in `container` mode). GCP instances get extra CPU while starting, Lambda's don't, so GCP cold starts (above all the SDK import) look faster than without boost. Switching it off works through the Cloud Run API, but every Cloud Functions update switches it back on (tested 2026-11-20). That test measured first requests to rollout-started instances, so it said nothing about the boost (see 2026-11-20 afternoon); with request-triggered cold starts the boost matters a lot at fractional CPU. The campaign measures e2 with and without.
- To reproduce the local suite: native Docker; `sebs storage start object configs/storage.json --output-json ../results/local/storage.json` (from `serverless-benchmarks/`); mock upstream as above; then `python -m mcp_bench.local_suite --storage results/local/storage.json --upstream http://172.17.0.1:8080 --out results/local/<run>`.

- Local cold starts start after the container is up (SeBS waits for the server), so container creation time is not included. Only the process-level cold start is measured.
- The RustFS object store is published on `0.0.0.0:9011` (SeBS default), so it's reachable from the LAN while running.
- Trace: 283 of 814 calls are LiveMCPBench's own `tool-router.route`; 91 are `desktop-commander` (code exec, out of scope). Both replay as a 50 ms sleep stub.
