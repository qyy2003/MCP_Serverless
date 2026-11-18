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
| Q1 | How does the time of a tool call split between startup, protocol round trips, network waits and compute? | Measured on AWS Lambda: MCP adds ±3 ms per call and 3 round trips per session; the platform adds 12–20 ms per call; API tools are their upstream's latency + ~18 ms. |
| Q2 | How do tool calls interact with LLM calls: do they overlap? | Answered from a recorded agent run: almost never (2 of 810 turns). Needs more traces to confirm. |
| Q3 | How large is the cold/warm difference, and how often do agent workloads trigger cold starts? | Measured on Lambda: 0.2–1.5 s at 128 MB, 0.2–0.5 s at 1769 MB, dominated by the tool's own import. Replayed sessions arriving ≤ 60 s apart see few cold starts; sparse arrivals are not measured yet. |
| Q4 | Can the bill be predicted in advance, and do current billing models fit this workload? | First answer from Lambda: an API tool's bill is its upstream latency + 4–7 ms, so it is predictable; 95–100% of it pays for waiting, 7–91× what CPU-time billing would charge. |

**The approach.** We extend [SeBS](https://github.com/spcl/serverless-benchmarks), the serverless
benchmark suite from SPCL at ETH Zurich, which already deploys functions to AWS, Azure, GCP and
local Docker and measures time, cold starts and cost. The plan has four steps:

1. Teach SeBS to serve its functions as MCP tools, so the same function can be called through
   MCP and directly, and the difference is the cost of MCP. **Done.**
2. Find out what real MCP tools do, so the benchmark covers realistic workloads. **Done** (the census).
3. Build one benchmark tool per common workload class. **Two of six done.**
4. Run on real platforms: single-tool measurements, then replays of recorded agent sessions
   with the LLM replaced by modeled waiting time. **First AWS Lambda campaign done** (2026-11-18).

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

Everything below runs locally and is tested. The first AWS Lambda campaign ran on 2026-11-18:
four tools, three memory sizes, cold and warm, plus trace replay ([docs/aws-results.md](docs/aws-results.md)).

| Piece | State |
|---|---|
| MCP wrapper for SeBS (any benchmark served as an MCP tool from the same function) | done for AWS Python and the local Python server; runs on AWS Lambda; reports CPU time and import time |
| Timing client (MCP session vs. plain invocation) | done |
| Census of the servers in MCP-Bench, MCP-Universe, LiveMCPBench (108 servers, 822 tools) | done |
| Two tool benchmarks: `610.api-proxy`, `620.fetch-markdown`, plus a mock upstream | done |
| Agent trace (LiveMCPBench, Claude Sonnet 4 run) and replay driver | done; replayed on Lambda at three arrival rates |
| Runs on AWS Lambda | **first campaign done** (eu-north-1; `experiments/aws_campaign.py`, `analysis/aws_results.py`) |
| Runs on SeBS local Docker | not started (needs the run image rebuilt) |
| Browser tool, DB tool, heavy-import tool | not started |
| Node.js wrappers, Azure, GCP, MCP session mode / SSE on the server side | not started |
| SeBS CLI integration (an MCP trigger type) | not started; the client takes a function URL instead |

## Results so far

Four kinds of result exist. Section 4 is the first cloud measurement.

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
  *On Lambda this holds only for Lambda's own init: the tool's import still lands on the first
  `tools/call`, because SeBS imports the benchmark lazily (see section 4).*

### 4. AWS Lambda campaign (2026-11-18, first cloud measurement)

Four tools (no-op, `110.dynamic-html`, `610.api-proxy`, `620.fetch-markdown`) on Lambda in eu-north-1
at 128, 512 and 1769 MB; client and mock upstream on an EC2 VM in the same region; billing from
Lambda's REPORT lines. Full write-up with figures: [docs/aws-results.md](docs/aws-results.md).

| Finding | Number |
|---|---|
| MCP vs plain invocation, warm | within ±3 ms per call; the platform path costs 12–20 ms either way |
| MCP session setup (connect + `initialize` + notification + `tools/list`) | 48–52 ms in-region, 182 ms from ETH Zurich |
| Cold start, time to first result | 0.2–1.5 s at 128 MB, 0.2–0.53 s at 1769 MB |
| ... of which Lambda's init / the tool's import | 67–79 ms at every size / up to 1.1 s at 128 MB, 33–69 ms at 1769 MB |
| API-wrapper call and bill | call = upstream delay + 17–20 ms; billed = upstream delay + 4–7 ms (p99 ≤ +12 ms) |
| Share of the API tool's billed time spent waiting | 95–100%; CPU < 1 ms per call |
| Lambda vs CPU-time billing, API tool at 1 s upstream | $2.30 (128 MB) to $29.14 (1769 MB) vs $0.32 per million calls |
| Init phase billed | yes, on all 319 cold invocations |
| Replay, 20 sessions arriving 1–60 s apart | 4 first-use cold starts + 1–5 more from overlap; tools busy ~3% of session time |
| Handshake share of replay invocations / Lambda bill | 30% / 8.8% |

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
  aws-results.md                  milestone 3: the first AWS Lambda campaign, findings and figures
  aws-tables-2026-11-18.md        every table of that campaign, generated by analysis/aws_results.py
  figures/aws/                    its figures
mcp_bench/                        our Python package (stdlib only)
  client.py                       MCP client and timing driver; `--mode plain` is the non-MCP baseline
  mock_upstream.py                mock REST API and web pages with settable delay and size
  traces.py                       converts recorded agent runs to replay traces
  replay.py                       replays traces against deployed tools
configs/replay.example.json       maps census classes to deployed tools; LLM timing model
configs/sebs-aws.json             SeBS deployment config for AWS (eu-north-1, Function URLs; no keys)
configs/replay.aws.json           the deployed function URLs (git-ignored: they are public endpoints)
experiments/aws_campaign.py       runs experiments E1-E4 on Lambda and fetches billing data (needs boto3)
data/
  server-census/                  one record per server, per benchmark; summary.md is generated
  traces/                         replay trace: 95 sessions, 814 tool calls
analysis/server_census.py         regenerates data/server-census/summary.md
analysis/aws_results.py           tables and figures of an AWS campaign (needs pandas, matplotlib)
serverless-benchmarks/            SeBS submodule, pinned to upstream commit 089e5c6c
patches/serverless-benchmarks.patch   all our changes to SeBS (15 files)
scripts/sebs-patch.sh             apply / export / revert / status of that patch
tests/                            end-to-end tests; fake_lambda.py runs the real AWS wrapper locally
```

Read the docs in this order: `mcp-wrapper.md`, `server-census.md`, `tools-and-replay.md`, `aws-results.md`.

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

## Running on AWS

This is the setup the 2026-11-18 campaign used.

1. **SeBS:** `cd serverless-benchmarks && python3 -m venv python-venv && uv pip install --python python-venv/bin/python -e . matplotlib`
   (an editable install, so `sebs` runs our patched tree). Run `sebs` from inside `serverless-benchmarks/`.
2. **Credentials:** `export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...`. SeBS accepts only an access key and secret
   (no session tokens). The current account's organization policy allows only **eu-north-1**.
3. **Mock upstream:** an EC2 VM in the same region with port 8080 open, running `python3 -m mcp_bench.mock_upstream --port 8080`
   (as a systemd service), and holding a copy of `mcp_bench/`, `configs/` and `data/traces/`. Then `export SEBS_MOCK_UPSTREAM=http://<vm>:8080`.
4. **Deploy:** `sebs benchmark invoke <benchmark> test --config ../configs/sebs-aws.json --deployment aws --trigger http`
   for `010.sleep`, `110.dynamic-html`, `610.api-proxy`, `620.fetch-markdown`. Add `--update-code` after changing the wrapper.
5. **Measure:** `experiments/aws_campaign.py` (see its docstring and the end of `docs/aws-results.md`). It changes memory and
   forces cold starts from the workstation, runs the client on the VM over SSH, and fetches REPORT lines from CloudWatch.

`results/` is git-ignored. Resources the campaign leaves in the account: the four functions and their public URLs,
the S3 bucket `sebs-benchmarks-<id>`, the IAM role `sebs-lambda-role`, the VM, its Elastic IP, security group and key pair.

## After that

In rough priority order; details in the "Next" sections of the docs.

1. Idle-time experiment (call, wait 1–30 min, call): cold starts of sparse agent traffic, which the replay does not reach.
2. Eager-import wrapper variant: import the tool at startup, as real MCP servers do, and re-measure cold starts and billing.
3. Browser tool (Playwright/Chromium as a container image) and a DB tool with connection setup.
4. More traces (MCP-Universe, MCP-Bench), and real timestamps from an instrumented agent run.
   The current LLM times are modeled from token counts, not measured.
5. Other platforms (a CPU-time-billed one to test the billing finding) and languages.

## Caveats on the existing numbers

- The observations in `docs/tools-and-replay.md` (idle gaps, LLM time per turn) come from the
  **modeled** timeline: 400 ms TTFT, 20 000 tok/s prefill, 60 tok/s decode. These are assumptions.
- The census classification is from source code for MCP-Bench, and from configs and tool schemas
  for most of LiveMCPBench. Confidence per benchmark is listed in `docs/server-census.md`.
- The AWS numbers come from one region, one day and one client VM, with 10 cold sessions and 30 warm
  calls per cell; the mock upstream is plain HTTP. Full list in `docs/aws-results.md`.
