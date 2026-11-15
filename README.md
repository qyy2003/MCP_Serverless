# MCP tools on serverless: a benchmark

## What this project is about

**The setting.** An AI agent works in a loop: the LLM thinks, calls a *tool* (search the web,
query GitHub, run a calculation), reads the result, and thinks again. The standard protocol
for these tool calls is **MCP** (Model Context Protocol). A tool lives in an *MCP server*,
and the agent talks to it over HTTP.

```
Agent (LLM)  ── tool call ──▶  MCP server on a serverless function  ──▶  GitHub API, web page, computation, ...
     ▲                                      │
     └────────────── result ────────────────┘
        The agent waits here. We want to measure this wait and what it costs.
```

**The problem.** Cloud providers now recommend hosting MCP servers on *serverless* platforms
(AWS Lambda, Cloudflare Workers, Azure Functions, Vercel), where code runs only when a request
arrives and is billed per call. Nobody has measured how well that works:

- Existing MCP benchmarks (MCP-Bench, MCP-Universe, LiveMCPBench) score how well the *LLM* uses
  tools. They say nothing about latency or cost.
- Existing serverless benchmarks, such as SeBS, do not speak MCP and do not model agent workloads.

**The goal.** Build a benchmark that characterizes MCP tool performance on serverless platforms,
and use it to answer four questions:

| | Question | Where we are |
|---|---|---|
| Q1 | How does the time of a tool call split between startup, protocol round trips, network waits and compute? | Tools and client report every part of the split. Measured on localhost only. |
| Q2 | How do tool calls interact with LLM calls: do they overlap? | Answered from a recorded agent run: almost never (2 of 810 turns). Needs more traces to confirm. |
| Q3 | How large is the cold/warm difference, and how often do agent workloads trigger cold starts? | Trace analysis says it depends on session arrival rate. The platform measurement is not done. |
| Q4 | Can the bill be predicted in advance, and do current billing models fit this workload? | Not started. The census shows why it matters: 57% of servers mostly wait on the network, which wall-clock billing charges for. |

**The approach.** We extend [SeBS](https://github.com/spcl/serverless-benchmarks), the serverless
benchmark suite from SPCL at ETH Zurich, which already deploys functions to AWS, Azure, GCP and
local Docker and measures time, cold starts and cost. The plan has four steps:

1. Teach SeBS to serve its functions as MCP tools, so the same function can be called through
   MCP and directly, and the difference is the cost of MCP. **Done.**
2. Find out what real MCP tools do, so the benchmark covers realistic workloads. **Done** (the census).
3. Build one benchmark tool per common workload class. **Two of six done.**
4. Run on real platforms: single-tool measurements, then replays of recorded agent sessions
   with the LLM replaced by modeled waiting time. **Replay driver done; no platform runs yet.**

**Scope.** Serverless deployment of *tools* only. Agent code sandboxes are out of scope; another
SPCL project covers them. The original proposal and the reply that set this scope are in
[docs/background.md](docs/background.md).

**Terms used below**

- **Cold start:** a request that arrives when no instance is running, so the platform boots one first. Slow.
- **Warm:** a request served by an instance that is already running.
- **MCP handshake:** the requests that open a session (`initialize`, `tools/list`) before the first `tools/call`.
- **Upstream:** the remote service a tool calls, such as the GitHub API. We replace it with a mock whose delay and response size we set.
- **Census class:** our category for what a tool does when called (API wrapper, search/fetch, local compute, browser, ...).
- **Trace:** the recorded sequence of LLM turns and tool calls of real agent sessions, which we replay.

## Status

Everything below runs locally and is tested. **Nothing has been run on a real platform yet**:
no AWS Lambda run and no SeBS local-Docker run. That is the next step.

| Piece | State |
|---|---|
| MCP wrapper for SeBS (any benchmark served as an MCP tool from the same function) | done for AWS Python and the local Python server; tested against a fake Function URL only |
| Timing client (MCP session vs. plain invocation) | done |
| Census of the servers in MCP-Bench, MCP-Universe, LiveMCPBench (108 servers, 822 tools) | done |
| Two tool benchmarks: `610.api-proxy`, `620.fetch-markdown`, plus a mock upstream | done |
| Agent trace (LiveMCPBench, Claude Sonnet 4 run) and replay driver | done; only replayed against the fake Lambda and in `--dry-run` |
| Runs on AWS Lambda / SeBS local Docker | **not started** (needs AWS credentials; local needs the run image rebuilt) |
| Browser tool, DB tool, heavy-import tool | not started |
| Node.js wrappers, Azure, GCP, MCP session mode / SSE on the server side | not started |
| SeBS CLI integration (an MCP trigger type) | not started; the client takes a function URL instead |

## Results so far

Three kinds of result exist. None of them is a cloud measurement.

### 1. Census of 108 MCP servers (data, final)

From the server sets of MCP-Bench, MCP-Universe and LiveMCPBench; full write-up in
[docs/server-census.md](docs/server-census.md).

| Finding | Number |
|---|---|
| Servers that wrap a remote REST API | 53 of 108 (49%); 35–59% of task references per benchmark |
| Servers whose time is mostly network wait | 62 of 108 (57%) |
| Light local compute (calculator, time, conversion) | 24 servers; 18–29% of task references |
| Search / fetch | 13 servers; 26–29% of task references in MCP-Bench and MCP-Universe |
| Browser | 3 servers, but 13% of MCP-Universe task references |
| Servers that keep state between calls | 30 (11 in memory, 19 persistent) |
| Servers with notable startup cost | 37 |
| Servers needing an API key / using a database | 8 / 0 |

Consequence: the main workload is a function that waits on the network, which is where
wall-clock billing matters. The benchmarks under-represent authenticated APIs and databases.

### 2. Agent trace analysis (recorded run + modeled LLM time)

From LiveMCPBench's recorded Claude Sonnet 4 run: 95 sessions, 905 LLM turns, 814 tool calls.
The call sequence is real; the timing is modeled (see Caveats). Reproduce with `make dry-run`.

| | p50 | p90 | max |
|---|---|---|---|
| LLM time per turn | 1.7 s | 9.2 s | 51 s |
| LLM time per session | 23 s | 80 s | 181 s |
| Gap between calls to the same tool class | 1.8 s | 9.1 s | 90 s |

- Only 2 of 810 tool-calling turns issue more than one call, so tool calls and LLM generation
  are almost strictly sequential: tool latency is on the agent's critical path.
- Only 2 of 578 same-class gaps exceed a minute, so within a session instances stay warm.
  Cold starts should depend on session arrival rate, not on behavior inside a session.

### 3. Local harness measurements (localhost, sanity check only)

The real AWS wrapper running behind `tests/fake_lambda.py`, client on the same machine.
There is no network, no Lambda runtime and no real cold start here, so these show that the
harness works and how small the protocol cost is in the best case. Re-measured on 2026-11-15.

| Measurement | Result |
|---|---|
| `110.dynamic-html`, MCP `tools/call` vs. plain invocation (median of 200) | 2.07 ms vs. 1.85 ms: about 0.2 ms added per call |
| MCP handshake (`initialize` + `notifications/initialized` + `tools/list`), once per session | about 4.8 ms, of which 1.1 ms is TCP connect |
| `610.api-proxy`, upstream set to 200 ms / 16 KB (median of 30) | 201.5 ms per call; 0.7 ms outside the function |
| `620.fetch-markdown`, upstream set to 300 ms / 200 KB (median of 30) | 319.8 ms per call; about 19 ms beyond the configured delay, mostly HTML → markdown (about 90 ms per MB) |

To reproduce, start `python -m mcp_bench.mock_upstream --port 8080` and
`python tests/fake_lambda.py serverless-benchmarks/benchmarks/<group>/<benchmark> <port>`,
then point `python -m mcp_bench.client --url http://127.0.0.1:<port>/` at it.

Two things found while measuring, worth watching for in cloud runs:

- **Nagle's algorithm with delayed ACK added about 40 ms to every response** until `TCP_NODELAY`
  was set in the client and the test servers. Real MCP clients and hosts can hit the same stall.
- **Cold starts on the handshake were invisible** when only `tools/call` reported `is_cold`.
  The wrapper now reports it on `initialize` and `tools/list` too. With eager initialization the
  handshake takes the cold start and the first tool call looks warm.

## Quick start

Needs Python 3.10+ and git. No packages to install: our code and the tests use only the standard library.

```bash
git clone --recurse-submodules <this repo> && cd MCP_Serverless
make setup      # init the SeBS submodule and apply our patch to it
make test       # 20 tests, about 3 s, no cloud account or Docker
make dry-run    # modeled timeline of the agent trace, calls nothing
```

## Where things are

```
README.md                         this file
Makefile                          setup / test / dry-run / census / patch-export
docs/
  background.md                   original proposal and scope decision
  mcp-wrapper.md                  milestone 1: the wrapper, the SeBS patch workflow, the client
  server-census.md                what the MCP benchmarks exercise; which tool classes to build
  tools-and-replay.md             milestone 2: tool benchmarks, mock upstream, trace replay, first observations
mcp_bench/                        our Python package (stdlib only)
  client.py                       MCP client and timing driver; `--mode plain` is the non-MCP baseline
  mock_upstream.py                mock REST API and web pages with settable delay and size
  traces.py                       converts recorded agent runs to replay traces
  replay.py                       replays traces against deployed tools
configs/replay.example.json       maps census classes to deployed tools; LLM timing model
data/
  server-census/                  one record per server, per benchmark; summary.md is generated
  traces/                         replay trace: 95 sessions, 814 tool calls
analysis/server_census.py         regenerates data/server-census/summary.md
serverless-benchmarks/            SeBS submodule, pinned to upstream commit 089e5c6c
patches/serverless-benchmarks.patch   all our changes to SeBS (15 files)
scripts/sebs-patch.sh             apply / export / revert / status of that patch
tests/                            end-to-end tests; fake_lambda.py runs the real AWS wrapper locally
```

Read the docs in this order: `mcp-wrapper.md`, `server-census.md`, `tools-and-replay.md`.

## The one thing to know: SeBS changes live in a patch

We never commit inside `serverless-benchmarks/`. The submodule stays on the upstream commit
and our changes to it are stored in `patches/serverless-benchmarks.patch`.

```bash
scripts/sebs-patch.sh apply      # after cloning (make setup does this)
# ... edit files under serverless-benchmarks/ ...
scripts/sebs-patch.sh export     # or: make patch-export; then commit the patch file
scripts/sebs-patch.sh status     # applied / not applied / diverged
```

`.gitmodules` sets `ignore = dirty`, so `git status` here will **not** show edits inside the
submodule. If you edit SeBS files and forget `export`, the changes exist only on your disk.

Inside SeBS, our additions are:

- `benchmarks/wrappers/mcp/python/mcp_shim.py`: the MCP server
- `benchmarks/600.mcp/610.api-proxy`, `benchmarks/600.mcp/620.fetch-markdown`: the tool benchmarks
- `mcp.json` in `010.sleep` and `110.dynamic-html`: tool definitions for existing benchmarks
- small edits to the AWS handler, the local server, `configs/systems.json`, `sebs/benchmark.py`

## Next step: the first real run on AWS

These steps are **untested**; they follow the SeBS documentation and how the patch is built.

1. Install SeBS (`serverless-benchmarks/README.md`, `docs/usage.md`) and configure AWS credentials.
2. Start the mock upstream on a small VM in the same region as the functions, reachable from them:
   `python -m mcp_bench.mock_upstream --port 8080`, then `export SEBS_MOCK_UPSTREAM=http://<host>:8080`.
3. Deploy with SeBS, with Function URLs enabled (`use-function-url` in `configs/example.json`):
   `sebs benchmark invoke 610.api-proxy test --config <config> --deployment aws`.
   Same for `620.fetch-markdown`, `110.dynamic-html`, `010.sleep`.
4. Measure MCP against plain invocation on the same URL:
   ```bash
   python -m mcp_bench.client --url <function-url> --arguments '{"sleep": 0.1}' --calls 20 --output results/mcp.jsonl
   python -m mcp_bench.client --url <function-url> --arguments '{"sleep": 0.1}' --calls 20 --mode plain
   ```
5. Copy `configs/replay.example.json`, fill in the four function URLs and the upstream URL, and replay:
   ```bash
   python -m mcp_bench.replay data/traces/livemcpbench-claude-sonnet-4.jsonl \
       --config my-replay.json --sessions 20 --concurrency 4 --output results/replay.jsonl
   ```

`results/` is git-ignored.

Things to check on the first run, because the local tests cannot show them:

- Does a tool call after `initialize` reach the same Lambda instance? The observation that the
  handshake absorbs the cold start depends on it.
- Is `is_cold` reported correctly on Lambda? It relies on a marker file in `/tmp`.
- For the local Docker platform, the run image must be rebuilt (`sebs docker build`) to get the `/mcp` route.

## After that

In rough priority order; details in the "Next" sections of the docs.

1. AWS experiments: MCP vs. plain, cold vs. warm, the time split per tool, replay at several arrival rates.
2. Browser tool (Playwright/Chromium as a container image) and a DB tool with connection setup.
3. More traces (MCP-Universe, MCP-Bench), and real timestamps from an instrumented agent run.
   The current LLM times are modeled from token counts, not measured.
4. Other platforms and languages.

## Caveats on the existing numbers

- The observations in `docs/tools-and-replay.md` (idle gaps, LLM time per turn) come from the
  **modeled** timeline: 400 ms TTFT, 20 000 tok/s prefill, 60 tok/s decode. These are assumptions.
- The census classification is from source code for MCP-Bench, and from configs and tool schemas
  for most of LiveMCPBench. Confidence per benchmark is listed in `docs/server-census.md`.
