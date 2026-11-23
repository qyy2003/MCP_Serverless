# Presentation outline (draft, 2026-11-22)

One slide per heading; ~15 slides, about 20 minutes. Each slide: the message (one sentence, usable as the slide
title), the evidence, the figure, and its status: ✅ exists, ⏳ running or pending, ❌ missing.

The thread through the talk, for the supervisor's criteria: **systematic** (census → tool classes → benchmarks),
**a gap shown with data** (slides 4–5), **new benchmarks** (slide 6), **performance patterns on real platforms**
(slides 7–12), **documented failures** (slide 12), **contribution back to SeBS** (slide 13).

## Open decisions before building slides

1. **Third cloud (Azure).** MCP routing exists for Azure but nothing has been deployed. Options: a minimal Azure run
   (warm calls + idle-time + billing, ~1 day incl. account setup), or present two clouds and list Azure as future work.
   Two clouds measured carefully is a defensible scope; ask the supervisor if unsure.
2. **Talk length and split between the two of us.** Natural split: census/gap/benchmarks/AWS (teammate),
   GCP/cold starts/idle/SeBS method (us), or by research question.
3. ~~Heavy-startup benchmark (630)~~ **built 2026-11-22** (`630.data-analysis`, pandas); GCP cold starts measuring.

---

## 1. Title

MCP tools on serverless: a SeBS extension for agent tool workloads. Names, course, supervisor.

## 2. Agents call tools, and providers want those tools on serverless

- Agent loop: LLM → tool call (MCP) → result → LLM. The agent waits for every tool call.
- AWS (Lambda, AgentCore Gateway), Cloudflare (`createMcpHandler`), Vercel (`mcp-handler`), Azure (Functions MCP extension)
  all recommend serverless for MCP servers.
- Nobody measures the infrastructure: MCP-Bench, MCP-Universe and LiveMCPBench score the LLM; SeBS doesn't speak MCP.
- Questions: Q1 where does a tool call's time go; Q2 does it overlap with LLM time; Q3 how large and how frequent are
  cold starts; Q4 does billing fit this workload.
- Figure: the agent ↔ MCP server ↔ upstream diagram from the README (redraw). ❌ needs drawing.

## 3. Approach: extend SeBS, measure on real clouds

- Same function served over MCP and as a plain invocation → the difference is MCP's cost.
- Pipeline: census of real servers → tool classes → benchmarks → AWS + GCP campaigns → agent-trace replay → real-server check.
- Figure: pipeline diagram. ❌ needs drawing.

## 4. What MCP tools actually do (census of 108 servers, 822 tools)

- 49% wrap a remote API; 57% spend most of their time waiting on the network.
- Search/fetch 26–29% of task references (MCP-Bench, MCP-Universe); browsers 13% in MCP-Universe.
- 30 keep state between calls; 37 have notable startup cost; 100 of 108 need no API key, none uses a database
  (benchmark bias: real deployments are the opposite).
- → tool classes to benchmark: API wrapper, fetch→markdown, light compute, browser, DB, heavy startup.
- Source: [server-census.md](server-census.md). Figure: class shares bar chart. ❌ (data in `data/server-census/summary.md`).

## 5. The gap: SeBS's benchmarks don't look like MCP tools

- **They wait:** MCP tools spend 96–100% of a call waiting; SeBS benchmarks ≤ 22% (except `010.sleep` and `120.uploader`).
  Caveat on the slide: our tools' wait share comes from the mock latency we set.
- **Real servers are heavy to start:** 27 real servers, median 42 MB installed, 96 dependencies, 547 ms to initialise at
  1 vCPU, CPU-bound in 26 of 27. SeBS's benchmarks: median 10 MB, 114 ms.
- Our SDK variant (41 MB, 460 ms) sits at the real servers' median; a stdlib mock (0.03 MB, 1 ms) would understate cold
  starts ~100×. → why our benchmarks ship the official SDK. 630 (pandas) covers the heavy end the census predicted.
- Figures: `figures/real-servers/size-vs-init.png` ✅, `figures/local/gap-wait.png` ✅ (local; fine as a characterisation).
- Source: [real-servers.md](real-servers.md).

## 6. New benchmarks in SeBS

- MCP wrapper: any SeBS benchmark served as an MCP tool from the same function (AWS, GCP, Azure, local); both MCP
  protocol revisions (handshake and 2026-07-28).
- `610.api-proxy` (REST API wrapper) and `620.fetch-markdown` (fetch a page, convert to markdown): mock upstream with set
  latency and size; stdlib and official-SDK variants; SeBS input sizes and validation.
- `630.data-analysis` (heavy startup): pandas/numpy import plus a dataset loaded once per instance, then cheap
  calls from memory; 150 MB installed (191 MB with the SDK). Startup cost set by the input size (64 KB–8 MB dataset).
  Locally at 1 CPU: +0.45 s cold (SDK +0.9 s), warm calls 10–15 ms. ✅ built, tested, deployed on GCP.
- Agent-trace replay driver (LiveMCPBench, 95 sessions, 814 calls) and idle-time driver.
- Figure: wrapper/variants diagram. ❌

## 7. Q1: MCP costs almost nothing per call; the platform and the handshake do

- MCP vs plain, warm: within ±3 ms (AWS), ±0.8 ms (GCP).
- Platform path outside the function: 12–20 ms (Lambda), 10–16 ms (Cloud Run), in-region.
- A new session costs 3 round trips before the first call: 44–52 ms in-region, 182–262 ms over a WAN.
- API tool: call = upstream latency + 13–20 ms on both clouds (on GCP at ≥ 0.333 vCPU; at 0.083 vCPU up to +83 ms).
- Figures: `figures/aws/e1-session-setup.png` ✅, `figures/gcp/e3-time-split.png` ✅ (or the AWS one). Consider one
  combined AWS+GCP figure ❌ (needs the AWS raw data from the teammate).

## 8. Q2: tool calls are on the agent's critical path

- In the recorded agent run, 2 of 810 tool-calling turns issue more than one call: tool and LLM time don't overlap.
- Tools are busy 3–5% of a session's wall time (replay, both clouds).
- Caveat: one trace; LLM time modeled from token counts.
- Short slide, or merge into slide 10.

## 9. Q3a: cold starts — how large

- Lambda: 0.25–0.53 s at 1769 MB, up to 1.5 s at 128 MB; the tool's import scales with memory (CPU share).
- GCP: 1.3–1.7 s at 1 vCPU (3–5× Lambda). At 0.083 vCPU the **startup CPU boost** decides: ~10 s without, ~1 s with.
- Realistic stack (official SDK): 3.5–4.2 s at 1 vCPU on GCP, and doesn't fit 128 MiB.
- Heavy startup (630), natural cold starts on GCP, boost on: median 5.0–6.8 s to the first result (range 3.3–10.8 s)
  at both 1 and 0.333 vCPU, nearly all importing pandas (0.22 s on a laptop). With the boost, the tier barely
  matters. ✅ ([idle-experiment.md](idle-experiment.md))
- Startup is CPU-bound (slide 5), so small function sizes multiply it.
- Figures: `figures/gcp/e2-cold-start-boost.png` ✅, `figures/aws/e2-cold-start.png` ✅.
- ❌ AWS run of the SDK variant (the teammate; one E2 run at 3 memory sizes).

## 10. Q3b: cold starts — how often

- Within a session: replay shows few extra cold starts (tools busy 3–5%; 18 concurrent sessions → 8 Lambda instances).
- Between sessions (GCP): a step, not a curve. ≤ 15 min idle: 49/49 warm; ≥ 16 min: 42/42 cold, each on an instance
  its own request started. A tool called less often than every 15 min pays a cold start every time
  (~1 s light, 3–6 s with the SDK at 0.333 vCPU).
- Figures: `figures/aws/e4-replay-cold-starts.png` ✅; `figures/idle/idle-gcp-2026-11-22.png` ✅; AWS curve ⏳ (teammate).

## 11. Q4: billing charges for the wait, and Cloud Run's granularity charges for the handshake

- 95–100% of an API tool's billed time is waiting; CPU-time billing would be 7–91× cheaper (Lambda, 128–1769 MB).
- Cloud Run rounds each request up to 100 ms: +16–60% for 50–200 ms calls; each 2–6 ms handshake request is billed
  100 ms → handshake 23–24% of the replay's cost on GCP vs 8.8% on Lambda.
- → MCP 2026-07-28 (no handshake) is a cost question on per-request-rounded platforms.
- Figure: `figures/aws/e5-cost.png` ✅; a GCP counterpart ❌.
- ⏳ verify Cloud Run prices and the 100 ms rule on the price page before the talk.

## 12. Pathologies: what breaks, and why

- 0.083 vCPU on Cloud Run: warm calls bimodal, ~11 ms or ~90 ms (consistent with CPU-quota throttling in 100 ms periods).
- Slow boots spawn more instances; one sequential client's requests spread across them, each with its own cold start.
- Lambda 128 MB: back-to-back calls start a second instance.
- The realistic SDK stack doesn't fit 128 MiB on GCP.
- Servers that fetch data at startup (12306: ~6 s) pay it on every cold start.
- 3 of 13 real Python servers no longer start as configured (MCP SDK 2.x broke them).
- Source: [gcp-results.md](gcp-results.md), [aws-results.md](aws-results.md), [real-servers.md](real-servers.md).

## 13. What this means for SeBS itself

- "Cold start" isn't one event across platforms: Cloud Run pre-starts instances on every deployment (SeBS's way of
  forcing a cold start); checked against natural cold starts after idling.
- Bugs found and fixed: GCP gen1 cold-start experiments hang (version-type mismatch); local server timed only the
  import, not the call; language variants overwrote the default function. Upstream PRs ⏳.
- gen1: SeBS's forced cold start (2.1–2.5 s) overstates the natural one (median 0.92 s, 6 probes) ~2.5×; gen2 forced ≈ natural. ✅

## 14. Limitations

- One region and one day per cloud; one client VM; few clean cold sessions at the smallest GCP tier.
- Mock upstream (plain HTTP, no TLS); one agent trace with modeled LLM time.
- Real-server startup measured on a laptop at 1 CPU.
- Cloud Run billing computed from published prices, not billing records.
- Concurrency 1 on GCP (Lambda-like); GCP's default (80) not measured.

## 15. Contributions and future work

- Contributions: MCP serving layer for SeBS on 3 platforms; tool benchmarks with realistic and minimal variants;
  census + real-server data that place them; cross-cloud measurements of time split, cold starts, billing;
  replay and idle-time drivers; SeBS fixes.
- Future: browser and DB tools; concurrency > 1 for waiting tools; Azure (if not done); more traces with measured
  LLM time; an MCP trigger type in SeBS's CLI.

---

## To do for the slides, by priority

1. ✅ Idle-time results, GCP; ⏳ AWS (teammate) → slide 10.
2. ❌ AWS raw data from the teammate → combined AWS+GCP figures (slides 7, 9) and the SDK variant on AWS (slide 9).
3. ⏳ Price-page check (slide 11).
4. ❌ Diagrams: agent/MCP/upstream (2), pipeline (3), wrapper (6); census bar chart (4).
5. Decisions 1–3 above.
