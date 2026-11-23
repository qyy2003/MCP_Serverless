# Presentation outline (draft 3, 2026-11-23)

Interim presentation, ~11 slides plus backup, about 20 minutes. Each slide: the message (one sentence, usable as
the slide title), the evidence, the figure, and its status: ✅ exists, ⏳ running or pending, ❌ missing.
Draft 2 (organised by kinds A/B/C, with a platform-behaviour section) is in git history (`a4cc181`).

## What changed from draft 2, and why

The supervisor's reply asked us to *characterise tool performance on serverless platforms, including the metrics
we mentioned*. The proposal named three metrics: (1) how a tool call's time splits between startup, protocol overhead
and compute, (2) how cold and warm starts differ *in practice*, (3) whether costs are predictable. Draft 3 uses
those three as the questions (our internal Q2, the LLM/tool overlap, becomes a fact about the workload) and drops
the section on platform behaviour.

**The lens.** An MCP tool on serverless differs from a generic function in three traits. Every result slide
says which trait drives it:

| Trait | What it is | Evidence that it's real |
|---|---|---|
| **Protocol** | A tool is used through a session: handshake requests before the first call, several requests per session, optionally session state (`Mcp-Session-Id`) | MCP spec; 30 of 108 census servers keep state |
| **Stack** | Real servers ship the MCP SDK and its dependencies: heavy, CPU-bound startup for little work per call | 27 real servers: median 547 ms init, 96 dependencies |
| **Traffic** | Calls come from an agent: sequential, on its critical path, bursty within a session, sparse between sessions | LiveMCPBench trace: 2 of 810 turns overlap; tools busy 3–5% of a session |

**Rule for every slide:** would this result be different if the function weren't an MCP tool, or the load
weren't an agent? If not, it goes to backup. Platform facts (eviction edge, CPU tiers, startup boost, forced
cold starts) are SeBS's own territory (`perf_cost`, `eviction_model`) and appear at most as one line of context.

## Open decisions

1. **Azure.** MCP routing exists, nothing deployed. Suggestion: two clouds for the interim, Azure as the first
   post-interim campaign, designed from the three questions (slide 10), not as a copy of the AWS/GCP campaigns.
2. **Split of the talk** between the two of us. Natural split: slides 2–5 and 7 (teammate: census, benchmarks,
   AWS, trace) and slides 6, 8–10 (us), or by part.
3. **Real servers on serverless.** The proposal promised "running existing MCP server sets on serverless
   deployments". Suggestion: synthetic tools stay the benchmark, real servers calibrate them (slide 4), and 2–3
   real servers deployed to one cloud as a check after the interim (slide 10). Agree this with the teammate.

---

## 1. Title

MCP tools on serverless: a SeBS extension for agent tool workloads. Names, course, supervisor.

## 2. Agents call tools, providers put those tools on serverless, and nobody measures it

- Agent loop: LLM → tool call (MCP) → result → LLM. The agent waits for every tool call.
- AWS (Lambda, AgentCore Gateway), Cloudflare (`createMcpHandler`), Vercel (`mcp-handler`), Azure (Functions MCP
  extension) all offer serverless hosting for MCP servers.
- MCP-Bench, MCP-Universe and LiveMCPBench score the LLM, not the infrastructure; SeBS doesn't speak MCP and
  has no agent workload.
- **Three questions** (from the proposal, as the supervisor scoped it): where does a tool call's time go; how do
  cold starts play out under agent traffic; is the bill predictable.
- **Three traits** that make an MCP tool different from a generic function: protocol, stack, traffic (table above).
  These are the reason the questions need new benchmarks.
- Figure: `figures/diagrams/agent-mcp.png` ✅ (crop the results row if it gives numbers away too early).

## 3. What MCP tools are: census of 108 servers, 822 tools

- 49% wrap a remote API; 57% spend most of their time waiting on the network. → the wait-dominated regime.
- **30 of 108 keep state between calls** (protocol trait; comes back on slide 10).
- ~8 tools per server on average (822 / 108) → how to package them (one function per server or per tool) is an
  open choice (slide 10).
- 37 have notable startup cost (stack trait).
- Benchmark bias, said plainly: 100 of 108 need no API key, none uses a database.
- Source: [server-census.md](server-census.md). Figure: `figures/census/classes-by-cost.png` ✅.

## 4. The gap: SeBS's benchmarks don't look like MCP tools

- **Stack:** 27 real servers measured: median 42 MB, 96 dependencies, 547 ms to initialise at 1 vCPU, CPU-bound in
  26 of 27. SeBS: median 10 MB, 114 ms. Even a calculator server takes 0.3–0.5 s, because of the SDK stack.
- **Wait:** our MCP tools wait 96–100% of a call; SeBS benchmarks ≤ 22% (except `010.sleep`, `120.uploader`).
  Caveat: our tools' wait share comes from the mock latency we set.
- **Protocol:** no SeBS benchmark is invoked through a session.
- Heavy imports aren't new to SeBS (411 has PyTorch); what's new is that *the typical MCP tool* is wait-dominated,
  heavy to start *and* session-based.
- Figures: `figures/real-servers/size-vs-init.png` ✅, `figures/local/gap-wait.png` ✅.

## 5. What we built: MCP in SeBS, and tools calibrated to the census

- MCP layer: any SeBS benchmark served as an MCP tool from the same function (AWS, GCP, Azure, local), so MCP vs
  plain on the same deployment isolates MCP's cost. Both protocol revisions: with handshake, and 2026-07-28 without.
- `610.api-proxy` (API wrapper), `620.fetch-markdown` (search/fetch), `630.data-analysis` (heavy startup), mock
  upstream with set latency and size.
- Each in a no-SDK and an official-SDK variant. The SDK variant sits at the real servers' median (41 MB, 460 ms),
  so it's the realistic configuration; SDK − no-SDK = what the MCP stack costs.
- Agent-trace replay driver (LiveMCPBench, 95 sessions, 814 calls), LLM time modeled.
- Figure: `figures/diagrams/wrapper.png` ✅.

## 6. Time split: MCP costs nothing per call, the session costs round trips

*Trait: protocol.*

- MCP vs plain, warm, same function: within ±3 ms (AWS), ±0.8 ms (GCP).
- A new session costs 3 round trips before the first call: 44–52 ms in-region, 182–262 ms over a WAN. The
  `notifications/initialized` round trip carries no response; a client that doesn't wait for its 202 saves one.
- An API tool call = upstream latency + 13–20 ms on both clouds: the rest of the time is the upstream's.
- → MCP's cost is per session, so it depends on how often agents open sessions, which the 2026-07-28 revision
  removes (no handshake).
- Figures: `figures/aws/e1-session-setup.png` ✅, `figures/gcp/e3-time-split.png` ✅. Combined AWS+GCP figure ❌
  (needs the AWS raw data).

## 7. Agent traffic: tool calls are on the critical path, and tools are mostly idle

*Trait: traffic.*

- In the recorded run, 2 of 810 tool-calling turns issue more than one call: tool time adds directly to the agent's
  latency.
- Within a session, calls to a tool class are seconds apart (p50 1.8 s, p90 9.1 s): instances stay warm.
- Tools are busy 3–5% of a session's wall time (replay, both clouds). 18 concurrent sessions → 8 Lambda instances,
  15 Cloud Run instances across 4 tools.
- → Cold starts are decided by how often sessions arrive, not by what happens inside one (slide 8).
- Caveat: one trace; LLM time modeled from token counts.
- Figure: `figures/aws/e4-replay-cold-starts.png` ✅.

## 8. Cold starts in practice: the MCP stack sets the cost, the session decides where it lands

*Traits: stack and protocol (traffic from slide 7).*

- **The stack makes it seconds.** On GCP at 1 vCPU, the official SDK variant's cold start is 3.5–4.2 s (import alone
  2.2–2.7 s), the no-SDK tool ~1.3–1.7 s; SDK + pandas (`630`) 7.3 s import. The SDK stack doesn't fit 128 MiB
  (needs 134 MiB). ❌ SDK variant on AWS (teammate).
- **The handshake takes the cold start**, but only the platform's part: on Lambda, init lands on `initialize`, the
  tool's import on the first `tools/call` (SeBS imports lazily). A cold MCP session reaches its first result
  25–75 ms later than a cold plain call.
- **A session can hit several cold instances** (indicative, GCP, n = 2–3): after a cold start, later handshake
  requests went to fresh instances, and the first result came after ~20 s instead of ~10 s. The protocol's
  multi-request session meets the platform's per-request routing.
- **Under replay**, at ≤ 60 s session arrivals few calls see a cold start. One line of context: past the platform's
  idle limit (15 min measured on GCP) every session pays the full cold start; sparse arrivals not replayed yet.
- Figures: `figures/gcp/e2-cold-start-boost.png` ✅ (SDK cells), `figures/aws/e2-cold-start.png` ✅.
  ❌ A figure with no-SDK vs SDK vs SDK+pandas cold start per cloud would carry this slide better.

## 9. Cost: the protocol meets the billing model

*Traits: protocol and stack.*

- **Billing granularity punishes the handshake.** Cloud Run rounds each request up to 100 ms: a handshake request
  does 2–6 ms of work and is billed 100 ms. In the replay, handshake requests are 30% of invocations and 23–24% of
  the GCP bill, vs 8.8% on Lambda (1 ms rounding). → On per-request-rounded platforms the protocol revision
  (2026-07-28, no handshake) is a cost decision, not only a latency one. Our most MCP-specific result.
- **Predictable, but in steps.** An API tool's bill is its upstream latency + a few ms, so it can be predicted from
  the upstream. With 100 ms rounding it moves in steps: a 207 ms call is billed 300 ms.
- One line of context: 95–100% of a waiting tool's billed time is waiting (Lambda; a known serverless critique,
  relevant because 57% of MCP servers are in that regime).
- Figure: GCP vs Lambda cost split of the replay (handshake vs tool calls) ❌, **priority 1**.
- ⏳ Verify Cloud Run prices and the 100 ms rule on the price page before the talk.

## 10. Next: the MCP-specific questions we haven't measured yet

This is the plan to the final presentation. Each item is MCP-specific by the rule above.

| Experiment | Trait | Question | Builds on |
|---|---|---|---|
| **Stateful sessions on stateless functions**: how often a session's requests leave their instance, what that costs (state rebuild, wrong results) | protocol | time, cold | 30 of 108 stateful servers; slide 8's session spread |
| **Protocol revision × billing model on three clouds**: handshake vs 2026-07-28, Lambda / Cloud Run / Azure Flex Consumption | protocol | cost | slide 9; shim and client already speak both revisions |
| **One function per server vs per tool**: shared cold starts vs package size, under replay | stack, traffic | cold, cost | ~8 tools per server |
| **Sparse agent traffic**: replay with session arrivals beyond the idle limit, with the SDK stack | traffic, stack | cold | slides 7–8 |
| **Concurrency > 1 for waiting tools**: one instance absorbing many waiting calls (Cloud Run, Azure) | traffic | cost | 57% wait-dominated |
| **Real servers deployed**: 2–3 census servers on one cloud, compared with our tools | stack | all | proposal; slide 4 |

Also: more traces with measured LLM time; Azure as the third cloud, inside the experiments above.

## 11. Limitations

- One region and one day per cloud; one client VM; few clean cold sessions in some GCP cells.
- Mock upstream (plain HTTP, no TLS); one agent trace with modeled LLM time.
- Real-server startup measured on a laptop at 1 CPU.
- Cloud Run billing computed from published prices, not billing records.
- GCP: gen2, concurrency 1 (Lambda-like), startup CPU boost on (GCP's default).

---

## Backup slides (for questions)

Platform behaviour we measured on the way. Not MCP-specific; SeBS's `perf_cost` and `eviction_model` cover it.

- GCP startup CPU boost: at 0.083 vCPU ~10 s cold start without, ~1 s with; nothing at 1 vCPU.
- GCP cold starts are 3–5× Lambda's at 1 vCPU (no-SDK tools: 1.3–1.7 s vs 0.25–0.53 s).
- Idle-time curve: 49/49 warm ≤ 15 min idle, 42/42 cold ≥ 16 min (GCP, gen1 and gen2).
- 0.083 vCPU on Cloud Run: warm calls bimodal, ~11 ms or ~90 ms (consistent with CPU-quota throttling).
- Cloud Run pre-starts instances on every new revision, so SeBS's redeploy doesn't force a cold start there; why
  the GCP campaign filters sessions by instance start reason.
- Lambda bills its init phase (all 319 cold invocations).
- Memory size as a cost decision: API tool same latency at 128 and 1769 MB, 10× the price; fetch tool needs CPU.
- SeBS fixes: GCP gen1 cold-start hang (`versionId` string vs int); language variants overwrote the default
  function; local server timed only the import. Upstream PRs ⏳.
- Real servers: some fetch data at startup (12306: ~6 s); 3 of 13 Python servers broken by MCP SDK 2.x.

## To do for the slides, by priority

1. ❌ Slide 9 figure (GCP vs Lambda cost split of the replay) + ⏳ price-page check.
2. ❌ Slide 8 figure: cold start by stack (no-SDK / SDK / SDK+pandas), per cloud. Needs the SDK variant on AWS.
3. ❌ AWS raw data from the teammate → combined figure on slide 6.
4. Decisions 1–3 above.
5. ✅ Diagrams and census chart (slides 2–5). SVG sources next to the PNGs
   (render: `rsvg-convert -z 2 x.svg -o x.png`).
