# MCP tools on serverless: a benchmark

Measures what it costs to serve MCP (Model Context Protocol) tools from serverless
functions: protocol overhead, cold starts, time spent waiting on upstream APIs, and how
tool calls interleave with LLM calls in real agent sessions. Built as an extension of
[SeBS](https://github.com/spcl/serverless-benchmarks).

Why this project exists and how the scope was set: [docs/background.md](docs/background.md).

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
