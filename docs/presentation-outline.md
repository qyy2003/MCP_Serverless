# Presentation outline (draft 2, 2026-11-23)

One slide per heading; ~13 slides plus backup, about 20 minutes. Each slide: the message (one sentence, usable as
the slide title), the evidence, the figure, and its status: ✅ exists, ⏳ running or pending, ❌ missing.

## Framing: what is new, and what only follows from it

Not everything we measured is new or specific to MCP. SeBS already has `perf_cost` (cold vs warm, memory sweeps,
cost), `eviction_model` (cold starts vs idle time) and a heavy-dependency benchmark (`411.image-recognition`).
Three kinds of result:

| Kind | What | Where in the talk |
|---|---|---|
| **A. New and specific to MCP or agents** | MCP layer for SeBS; session/handshake cost; handshake × per-request billing granularity and the 2026-07-28 revision; census and gap; real-server startup; agent-trace replay (critical path, sparse use) | the core: slides 4–9 |
| **B. Motivated by MCP, generic as functions** | 610/620/630 are a proxy, a fetch-and-convert and a heavy import; "billing pays for waiting"; dependency size → cold start | as what our benchmarks reproduce, with the census as the reason (slides 6, 10–11) |
| **C. Generic platform behaviour / SeBS upkeep** | cold start vs tier, Lambda vs GCP; idle eviction edge; GCP startup CPU boost; 0.083 vCPU throttling; Lambda bills init; gen1 hang; Cloud Run pre-starting instances | only as consequences for MCP tools (slide 10), the SeBS slide (12), or backup |

**Rule for every slide:** a kind-C number appears only as "what this means for an MCP tool", e.g. "a tool used
less often than every 15 min pays a 3–6 s cold start on every call with a realistic MCP stack", never as a platform
fact on its own. The story is a chain: MCP tools have the traits the supervisor named (short, bursty, I/O-heavy,
large dependencies; slides 4–5, 9) → our benchmarks reproduce them (6) → what the platforms do to such workloads
(7–8, 10–11).

## Open decisions

1. **Azure.** MCP routing exists, nothing deployed. Suggestion: two clouds measured carefully for the interim,
   Azure as next step, unless the supervisor insists.
2. **Split of the talk.** Natural split: motivation/census/gap/benchmarks/AWS (teammate), session cost/billing/
   cold starts/next phase (us), or by part.

---

## 1. Title

MCP tools on serverless: a SeBS extension for agent tool workloads. Names, course, supervisor.

## 2. Agents call tools, and providers want those tools on serverless

- Agent loop: LLM → tool call (MCP) → result → LLM. The agent waits for every tool call.
- AWS (Lambda, AgentCore Gateway), Cloudflare (`createMcpHandler`), Vercel (`mcp-handler`), Azure (Functions MCP
  extension) all recommend serverless for MCP servers.
- Nobody measures the infrastructure: MCP-Bench, MCP-Universe and LiveMCPBench score the LLM; SeBS doesn't speak MCP.
- Questions: Q1 where does a tool call's time go; Q2 does it overlap with LLM time; Q3 how large and how frequent are
  cold starts; Q4 does billing fit this workload.
- Figure: `figures/diagrams/agent-mcp.png` ✅. Its bottom row previews the results; crop it here and reuse the
  full figure as the summary slide if the numbers come too early.

## 3. Approach: find out what MCP tools are, then extend SeBS to measure them

- Census of real servers → tool classes → benchmarks → AWS + GCP → agent-trace replay; real-server check feeds back.
- Same function served over MCP and as a plain invocation → the difference is MCP's cost.
- Figure: `figures/diagrams/pipeline.png` ✅.

### Part I: what MCP tools are (kind A)

## 4. What MCP tools actually do (census of 108 servers, 822 tools)

- 49% wrap a remote API; 57% spend most of their time waiting on the network.
- Search/fetch 26–29% of task references (MCP-Bench, MCP-Universe); browsers 13% in MCP-Universe.
- **30 of 108 keep state between calls** (persistent or per session): set up here, comes back on slide 13.
- 37 have notable startup cost; 100 of 108 need no API key, none uses a database (benchmark bias: real deployments
  are the opposite).
- Source: [server-census.md](server-census.md). Figure: `figures/census/classes-by-cost.png` ✅.

## 5. The gap: SeBS's benchmarks don't look like MCP tools

- **They wait:** MCP tools spend 96–100% of a call waiting; SeBS benchmarks ≤ 22% (except `010.sleep` and `120.uploader`).
  Caveat on the slide: our tools' wait share comes from the mock latency we set.
- **Real servers are heavy to start:** 27 real servers, median 42 MB installed, 96 dependencies, 547 ms to initialise at
  1 vCPU, CPU-bound in 26 of 27. SeBS's benchmarks: median 10 MB, 114 ms.
- A stdlib mock (0.03 MB, 1 ms) would understate cold starts ~100×; our SDK variant (41 MB, 460 ms) sits at the median.
- Say it plainly: heavy imports aren't new to SeBS (411 has PyTorch); what's new is that *the typical MCP tool* is
  wait-dominated *and* heavy to start, a combination no SeBS benchmark has.
- Figures: `figures/real-servers/size-vs-init.png` ✅, `figures/local/gap-wait.png` ✅ (local; fine as a characterisation).

### Part II: what we built (kind A + B)

## 6. MCP in SeBS, and benchmarks that reproduce the census classes

- MCP layer: any SeBS benchmark served as an MCP tool from the same function (AWS, GCP, Azure, local); both MCP
  revisions (with handshake, and 2026-07-28 without). New in SeBS.
- `610.api-proxy` (API wrapper, 49%), `620.fetch-markdown` (search/fetch), `630.data-analysis` (heavy startup:
  pandas + a dataset loaded once per instance). Mock upstream with set latency and size; SeBS input sizes and validation.
- Each with a no-SDK and an official-SDK variant: SDK − shim = what a realistic MCP stack costs.
- Honest about kind B: as functions these are simple; their value is that the census says they are the common case.
- Drivers: agent-trace replay (LiveMCPBench, 95 sessions, 814 calls), idle-time probes.
- Figure: `figures/diagrams/wrapper.png` ✅.

### Part III: what is specific to MCP on serverless (kind A)

## 7. Q1: MCP costs nothing per call; the session does

- MCP vs plain, warm: within ±3 ms (AWS), ±0.8 ms (GCP).
- A new session costs 3 round trips before the first call: 44–52 ms in-region, 182–262 ms over a WAN.
- Platform path outside the function 10–20 ms on both clouds; API tool call = upstream latency + 13–20 ms.
- Figures: `figures/aws/e1-session-setup.png` ✅; `figures/gcp/e3-time-split.png` ✅. A combined AWS+GCP figure ❌
  (needs the AWS raw data from the teammate).

## 8. Q4a: on per-request-rounded billing, the handshake is a quarter of the bill

- Cloud Run rounds each request up to 100 ms: each 2–6 ms handshake request is billed 100 ms → handshake 23–24% of the
  replay's cost on GCP vs 8.8% on Lambda (1 ms rounding).
- → MCP 2026-07-28 (no handshake) is a cost question, not only a latency one, on per-request-rounded platforms.
- Our most MCP-specific result: protocol design × billing granularity. Give it its own slide.
- Figure: GCP vs Lambda cost split of the replay ❌.
- ⏳ verify Cloud Run prices and the 100 ms rule on the price page before the talk.

## 9. Q2 + agent traffic: tool calls are on the critical path, and tools are mostly idle

- In the recorded agent run, 2 of 810 tool-calling turns issue more than one call: tool and LLM time don't overlap.
- Tools are busy 3–5% of a session's wall time (replay, both clouds); 18 concurrent sessions → 8 Lambda instances across 4 tools.
- So agent traffic is sparse and bursty per tool: this is what makes cold starts (slide 10) matter.
- Caveat: one trace; LLM time modeled from token counts.
- Figure: `figures/aws/e4-replay-cold-starts.png` ✅.

### Part IV: what the platforms do to these traits (kind C, framed for MCP)

## 10. Q3: a realistic MCP tool used sparsely pays a multi-second cold start on every call

- Size: light tool 0.25–1.5 s (Lambda), ~1 s (GCP, boost on); **official SDK 3.5–4.2 s, pandas 5–7 s on GCP**; the SDK
  stack doesn't fit 128 MiB on GCP. Startup is CPU-bound (slide 5), so small tiers multiply it.
- Rate: on GCP, ≤ 15 min idle always warm, ≥ 16 min always cold. With slide 9's sparse use, a tool called less often
  than every 15 min pays the full cold start each time.
- Say where it comes from: the eviction edge and tier scaling are platform behaviour SeBS can already measure
  (`eviction_model`, `perf_cost`); what's ours is the MCP stack's size and the agent's call pattern.
- Figures: `figures/gcp/e2-cold-start-boost.png` ✅, `figures/idle/idle-gcp-2026-11-22.png` ✅,
  `figures/aws/e2-cold-start.png` ✅. ❌ SDK variant on AWS (teammate; one E2 run at 3 memory sizes); ⏳ AWS idle curve (teammate).

## 11. Q4b: wall-clock billing charges MCP tools for waiting

- 95–100% of an API tool's billed time is waiting; CPU-time billing would be 7–91× cheaper (Lambda, 128–1769 MB).
- Memory size is a cost decision per tool: same latency at 128 MB and 1769 MB, 10× the price (API tool); the fetch
  tool needs CPU (1 MB page: 1.5 s at 128 MB vs 0.3 s).
- Known critique of serverless (kind B); new is that the census puts 57% of MCP tools in this regime.
- Open: concurrency > 1 (Cloud Run's default 80) would let one instance absorb many waiting calls; not measured.
- Figure: `figures/aws/e5-cost.png` ✅.

## 12. Back to SeBS: what we fixed and what we contribute

- Contributed: MCP layer, 3 tool benchmarks with SDK variants, replay and idle drivers.
- Fixed: GCP gen1 cold-start experiments hang forever (`versionId` string vs int); language variants overwrote the
  default function; local server timed only the import, not the call. Upstream PRs ⏳.
## 13. Next phase: the MCP-specific problems serverless hasn't been measured on

- **Stateful sessions on stateless functions.** 30 of 108 servers keep state between calls (`Mcp-Session-Id`,
  memory, browser). Serverless doesn't route a session's calls to one instance, and we already see it break up:
  on GCP, one sequential client's requests spread over several instances after a cold start (plain 26 of 80 sessions,
  MCP 2 of 75 at 512 MB). Measure how often affinity breaks and what it costs (state rebuild, wrong answers).
- **One function per server or per tool.** A server exposes ~8 tools on average (822 tools, 108 servers; counts not known for all): packing shares cold starts but grows the
  package; splitting does the opposite.
- **Concurrency > 1 for waiting tools** (slide 11).
- Azure, if not done by the interim; more traces with measured LLM time; browser and DB tools.

## 14. Limitations

- One region and one day per cloud; one client VM; few clean cold sessions at the smallest GCP tier.
- Mock upstream (plain HTTP, no TLS); one agent trace with modeled LLM time.
- Real-server startup measured on a laptop at 1 CPU.
- Cloud Run billing computed from published prices, not billing records.
- Concurrency 1 on GCP (Lambda-like), gen2 with the startup CPU boost on (GCP's default).

---

## Backup slides (kind C detail, for questions)

- GCP startup CPU boost: at 0.083 vCPU ~10 s without, ~1 s with; nothing at 1 vCPU. Figure `figures/gcp/e2-cold-start-boost.png`.
- 0.083 vCPU on Cloud Run: warm calls bimodal, ~11 ms or ~90 ms (CPU-quota throttling in 100 ms periods).
- Lambda bills its init phase (billed = handler + init, all 319 cold invocations).
- Idle-time curve in detail: 49/49 warm ≤ 15 min, 42/42 cold ≥ 16 min, gen1 and gen2.
- Cloud Run pre-starts instances on every new revision; why the GCP campaign filters sessions by instance start reason.
- Servers that fetch data at startup (12306: ~6 s); 3 of 13 real Python servers broken by MCP SDK 2.x.

## To do for the slides, by priority

1. ❌ AWS raw data, AWS idle run, SDK variant on AWS (teammate) → slides 7, 10.
2. ❌ Slide 8 figure (GCP vs Lambda cost split of the replay) + ⏳ price-page check. Slide 8 carries the most
   MCP-specific result, so this comes before polish elsewhere.
3. ✅ Diagrams and census chart (slides 2, 3, 4, 6). SVG sources next to the PNGs
   (render: `rsvg-convert -z 2 x.svg -o x.png`).
4. Decisions 1–2 above.
