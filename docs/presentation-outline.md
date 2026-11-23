# Interim Presentation Outline (Draft 4, 2026-11-23)

**Slot:** ~4–5 minutes inside the 6-person group presentation (**5 main slides + backup slides**).
**Goal:** Present a clean, bulletproof interim story—every number verified from high-`n` data, zero fragile/modeled headline claims, honest caveats, and a clear path to the final SeBS PRs.

> **Changes from Draft 3:** Compressed from 11 slides to 5 for the ~4–5 min subteam slot; removed the fragile `n=2–3` multi-instance spread claim and the synthetic 128 MB Cloud Run/Lambda modeled billing chart; added the explicit 46% stub-call caveat for trace replay; verified AWS `eu-north-1` and GCP `europe-west1` pricing; added slots for today's targeted AWS SDK + `630` + MCP `2026-07-28` run (with clean fallbacks if not completed in time).

---

## Slide 1 — Motivation & Systematic Gap in SeBS (~45 s)

**Title:** MCP tools combine network waiting, heavy SDK startup, and session protocol—a gap in SeBS

- **Problem & Scope:** Cloud providers host MCP servers on serverless (Lambda, Cloud Run, Azure Functions, Workers), but existing MCP benchmarks score LLMs, not infrastructure, and SeBS lacks MCP/agentic workloads. *(Scoped to tool deployment; agent code sandboxes are covered by another SPCL project.)*
- **Census (108 servers, 822 tools across MCP-Bench, MCP-Universe, LiveMCPBench):**
  - **49%** wrap remote REST APIs; **57%** are network-wait-dominated; **30/108** keep state; **37/108** have notable startup cost.
  - Benchmark bias: 100/108 require no API key; 0/108 use a database.
- **27 Real MCP Servers vs. SeBS Catalog (1 vCPU, local):**
  - Real servers: median **42 MB**, **96 deps**, **547 ms CPU-bound init** (even a calculator takes 0.3–0.5 s due to the MCP SDK stack).
  - Existing SeBS catalog (12 benchmarks): median **10 MB**, **114 ms import**, and $\le$22% wait share (except `010.sleep`, `120.uploader`) vs. **96–100% wait** for MCP API/fetch tools.
- **Figures:** `docs/figures/census/classes-by-cost.png` + `docs/figures/real-servers/size-vs-init.png` (side-by-side; `gap-wait.png` in backup or small inset).

---

## Slide 2 — What We Built: Extending SeBS for MCP Tools (~45 s)

**Title:** A dual-path MCP extension for SeBS with census-calibrated tool benchmarks

- **Dual-path MCP layer (AWS, GCP, Azure, local Docker):** Any SeBS benchmark runs as both an MCP tool and a plain FaaS call from the *exact same deployment*, isolating protocol overhead. Supports both **legacy handshake** MCP and **2026-07-28** (stateless, no handshake).
- **Three calibrated tool benchmarks (`600.mcp/`):**
  - `610.api-proxy` (REST API wrapper), `620.fetch-markdown` (fetch + HTML$\to$Markdown CPU), `630.data-analysis` (heavy startup: pandas + dataset load), backed by a deterministic mock upstream.
- **Two variants per tool:**
  - `default` (minimal/no-SDK, 0.03 MB / 1–4 ms import) isolates protocol & platform overhead.
  - `sdk` (`--language-variant sdk`, official `mcp==2.3.0`, **41 MB / 460 ms init**) matches the real-server median (42 MB / 547 ms).
- **Replay driver:** Replays recorded agent call sequences (LiveMCPBench, 95 sessions, 814 calls) with configurable arrival rates and modeled LLM think time.
- **Figure:** `docs/figures/diagrams/wrapper.png`.

---

## Slide 3 — Time Split & Protocol Overhead (~60 s)

**Title:** MCP adds negligible per-call overhead; protocol cost is per-session round trips

- **Warm per-call overhead (same function, `n=200`/mode):**
  - MCP vs. plain is within **$\pm$3 ms on AWS Lambda** and **$\pm$0.8 ms on GCP Cloud Run**—an order of magnitude smaller than the platform/network path (**12–20 ms AWS**, **10–16 ms GCP** in-region).
- **Session setup cost & MCP `2026-07-28` measured on AWS Lambda (`610-sdk`, 1769 MB, WAN ETH $\to$ `eu-north-1`, `n=20` warm / `n=10` cold):**
  - Legacy handshake (`initialize`, `notifications/initialized`, `tools/list` + TLS) costs 3 extra RTTs: **48–52 ms** in-region (**44–47 ms** GCP), rising to **182–262 ms** over WAN.
  - **Dropping the handshake (`2026-07-28`)** cuts a 1-call warm WAN session from **357 ms (4 reqs) $\to$ 239 ms (2 reqs, -33%)** and reduces the **measured CloudWatch Lambda bill by 21%** (`$2.70 -> $2.13 / 1M` sessions; `auto` discovery = 301 ms / `$2.39`). On cold sessions, the **1.26 s SDK Init** still dominates (1,806 ms $\to$ 1,674 ms).
- **Where warm tool time goes (`n=30`/cell):**
  - `610.api-proxy`: **upstream delay + 13–20 ms** across both clouds and memory sizes.
  - `620.fetch-markdown`: shifts to CPU-bound on large pages (1 MB page on AWS: **1.53 s** at 128 MB vs. **0.32 s** at 1769 MB; GCP: **2.05 s** at 0.083 vCPU vs. **0.34 s** at 1 vCPU).
- **Figure:** `docs/figures/interim/protocol-revision-aws.png` (and `docs/figures/aws/e3-time-split.png` in backup/inset).

---

## Slide 4 — Cold Starts: The Realistic MCP Stack Dominates (~60 s)

**Title:** Realistic SDK dependencies turn millisecond cold starts into multi-second stalls

- **Symmetric AWS vs. GCP stack comparison at 1 vCPU (AWS 1769 MB `n=10` vs. GCP 2048 MB boost on `n=6–10`):**
  - `610` (no-SDK, 0.03 MB): **0.72 s AWS** (WAN) vs. **1.73 s GCP**
  - `610`/`620` (**official MCP SDK**, 41 MB): **1.95–2.00 s AWS** (billed `Init` **1.26–1.27 s**) vs. **3.62–3.66 s GCP** (import **2.20–2.25 s**)
  - `630.data-analysis` (**SDK + pandas**, 191 MB): **3.23 s AWS** (`Init` **2.10 s**) vs. **6.39 s GCP** (import 4.6–7.4 s)
  - Across every stack tier, **GCP Cloud Run cold starts are ~2$\times$ AWS Lambda** at 1 vCPU, and adding the official SDK adds **+1.2 s (AWS) to +2.0 s (GCP)**.
- **Two platform-architecture interactions for MCP deployment:**
  - **128 MB memory floor:** `610-sdk` uses **106 MB** and runs cleanly on AWS Lambda (**1.94 s** cold start, 5/5 OK), whereas Cloud Run's Python runtime (`functions-framework` + `gunicorn`) pushes it to **134 MiB $\to$ OOM at 128 MiB**.
  - **AWS Init-burst vs. lazy import:** At 512 MB, `630-sdk` (eager import of SDK + pandas during Lambda's unthrottled `Init` phase: **3.47 s**) is **0.9 s faster** than `630` without the SDK (lazy pandas import inside the throttled handler: **4.36 s**)! Importing MCP dependencies eagerly at startup pays off dramatically on low-memory Lambda.
- **Figure:** `docs/figures/interim/cold-start-by-stack.png`.

---

## Slide 5 — Agent Traffic, Billing Fit & Plan to Final Deliverable (~60 s)

**Title:** Agents pay wall-clock billing for idle waiting; next: symmetric 3-cloud evaluation & SeBS PRs

- **Agent workload pattern (LiveMCPBench trace + E4 replay):**
  - Tool calls are strictly sequential (**2/810** turns parallel $\to$ on the LLM critical path); intra-session gaps are short (modeled p50 1.8 s, p90 9.1 s) and tools are busy only **3–5%** of session wall time $\to$ cold starts depend on inter-session arrival gaps (e.g. past GCP's 15-min idle cliff).
  - *Caveats:* 1 trace, modeled LLM latency, and 46% of trace calls (`tool-router`, `desktop-commander`) mapped to a 50 ms stub.
- **Measured AWS Lambda billing (100% matched CloudWatch `REPORT` lines, `eu-north-1`):**
  - **Predictable:** API tool billed duration = **upstream + 4–7 ms** (p99 $\le$ +12 ms).
  - **Wall-clock mismatch:** **95–100%** of billed time is waiting (CPU < 1 ms) $\to$ **$2.30–$29.14 / 1M calls** at 1 s upstream vs. **$0.31–$0.32** under CPU-time billing (7–91$\times$).
  - **Protocol & init billing:** Init is billed on 319/319 cold starts; legacy handshake is **30% of invocations** and **8.8% of measured Lambda bill** at 512 MB (and on Cloud Run's verified 100 ms billing granularity, each short handshake request consumes a full 100 ms granule).
- **Roadmap for Final Deliverable (~1 month):**
  1. **Symmetric multi-cloud matrix:** AWS Lambda + GCP Cloud Run + Azure Functions (already wired) at matched tiers (`n >= 15`), plus **2–3 real census MCP servers** deployed on cloud to validate `610`–`630`.
  2. **MCP-specific systems studies:** Measured `legacy` vs. `2026-07-28` cost/latency; concurrency > 1 on Cloud Run/Azure for wait-dominated tools; stateful-session routing (30/108 stateful servers).
  3. **Trace realism & SeBS integration:** Filter stub calls, add MCP-Universe/MCP-Bench traces + measured LLM timestamps, and submit clean PRs to `anveba/serverless-benchmarks`.
- **Figure:** `docs/figures/aws/e5-cost.png` (compact).

---

## Backup Slides (for Q&A only)

1. **Gap on Wait-Share & Work Axes:** `docs/figures/local/gap-wait.png`, `docs/figures/local/gap-work.png` (explains why `120.uploader` waits 74–81% but moves 0.5–14 MB and uses 29–165 ms CPU, unlike thin API wrappers).
2. **GCP Methodology & Platform Quirks:** Why measuring true cold starts on Cloud Run gen2 required holding `DEPLOYMENT_ROLLOUT` pre-started instances busy and filtering by system-log `AUTOSCALING` start reason; startup CPU boost effect at fractional vCPU (~10 s off vs. ~1 s on at 0.083 vCPU, no effect at 1 vCPU; `docs/figures/gcp/e2-cold-start-boost.png`).
3. **GCP Idle Eviction Curve:** `docs/figures/idle/idle-gcp-2026-11-22.png` (sharp 15-min cliff: 49/49 warm $\le$15 min, 42/42 cold $\ge$16 min across gen1 and gen2).
4. **SeBS Upstream Bug Fixes Found:** GCP gen1 `enforce_cold_start` infinite hang (`versionId` str vs. int), language variants overwriting default function names, local plain server timing only module import.
5. **Anticipated Tough Questions (1-line answers):**
   - *Why synthetic benchmarks (`610`–`630`) instead of only real servers?* Live third-party APIs have uncontrolled variance, rate limits, and geo-blocks; synthetic tools + mock upstream give reproducible, parameterized SeBS benchmarks calibrated to the 27 real servers, and we will validate against 2–3 deployed real servers next.
   - *Why are 46% of replay calls stubs?* LiveMCPBench includes its own `tool-router` and an out-of-scope `desktop-commander` sandbox; we will report filtered traces + add MCP-Universe/MCP-Bench traces for the final deliverable.
   - *Why not Cloudflare Workers / CPU-billed platform?* SeBS does not have a Workers backend; we used Workers' published pricing analytically on Lambda CPU measurements and will evaluate Azure Flex Consumption / Cloud Run concurrency > 1 inside SeBS next.
   - *How will this integrate into SeBS?* Clean PRs adding `benchmarks/600.mcp/`, the MCP wrapper/SDK variant, and a SeBS-native MCP trigger/experiment interface into the group fork before final submission.
