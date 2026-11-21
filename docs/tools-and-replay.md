# MCP tool benchmarks and agent replay (milestone 2)

Builds on the MCP wrapper (docs/mcp-wrapper.md) and the server census
(docs/server-census.md): two tool benchmarks for the most common workload
classes, a mock upstream they call, and a driver that replays real agent
sessions against deployed tools.

## Pieces

| File | What it is |
|---|---|
| `mcp_bench/mock_upstream.py` | Mock REST API (`/api`) and web pages (`/page`). Each request sets the response delay and size, so upstream behavior is controlled and repeatable. |
| SeBS `600.mcp/610.api-proxy` | **API-wrapper tool** (`search_products`): GET a JSON list from the upstream, filter and sort it, return the top items. Covers the largest census class. |
| SeBS `600.mcp/620.fetch-markdown` | **Fetch tool** (`fetch`): GET an HTML page, strip boilerplate, convert it to markdown, return `max_length` characters with paging, like the reference fetch server. |
| `mcp_bench/traces.py` | Converts recorded agent runs to replay traces. Currently reads LiveMCPBench baseline runs. |
| `data/traces/livemcpbench-claude-sonnet-4.jsonl` | Trace derived from LiveMCPBench's Claude Sonnet 4 baseline run (Apache-2.0): 95 sessions, 905 LLM turns, 814 tool calls, each call mapped to its census class. |
| `mcp_bench/replay.py` | Replays traces against MCP endpoints and reports latency, cold starts by idle gap, and the tool share of session time. `--dry-run` reports only the modeled timeline. |
| `configs/replay.example.json` | Maps census classes to deployed tools and sets the LLM timing model. |

Both tools use only the Python standard library (`http.client`, `html.parser`).
That keeps package size and import time minimal, and makes them testable without installing anything.
Real servers often use httpx/requests and BeautifulSoup/markdownify, which add import time to cold starts.
That can become a SeBS language variant later.

## What the tools measure

Each tool returns SeBS's usual `{"result": ..., "measurement": ...}`; over MCP, it arrives in the tool result's `structuredContent`.

| Field | Meaning |
|---|---|
| `upstream_wait_us` | request sent → full response read. Includes the configured `latency_ms`; the rest is network + HTTP. |
| `upstream_connect_us`, `upstream_new_connection` | TCP (+TLS) setup; 0 / false when a warm instance reuses its kept-alive connection |
| `upstream_bytes` | upstream response size |
| `process_us` | local work: JSON reshaping, or HTML → markdown (about 90 ms per MB of HTML) |

Together with the wrapper's `exec_us` and the client's `connect_us`/`ttfb_us`/`client_us`, a call splits into:
client↔function network and protocol | cold start | upstream connect | upstream wait | local processing.
That is research question 1.

The upstream connection is kept across warm invocations, as a real server's HTTP client would.
A cold start therefore also pays for a new upstream connection.
`reuse_connection: false` disables the reuse, to measure that cost.

## Running

```bash
python -m mcp_bench.mock_upstream --port 8080          # where the functions can reach it
export SEBS_MOCK_UPSTREAM=http://<host>:8080           # read by the benchmarks' input.py
# deploy with SeBS as usual: 600.mcp/610.api-proxy, 600.mcp/620.fetch-markdown, ...
python -m mcp_bench.client --url <function URL> --arguments "$(cat input.json)" --calls 20
```

For AWS, run the mock upstream on a small VM in the same region as the functions, so the configured latency dominates.

### Replaying agent sessions

```bash
# fill in configs/replay.example.json with function URLs and the upstream URL, then:
python -m mcp_bench.replay data/traces/livemcpbench-claude-sonnet-4.jsonl \
    --config my-replay.json --sessions 20 --concurrency 4 --output results/replay.jsonl
```

- **Session behavior:** each session connects to its servers when it starts (like Claude Desktop; `--lazy-init` connects on first use). It then waits the modeled LLM time before each turn and runs that turn's calls in parallel.
- **Arrivals:** `--concurrency` and `--arrival-interval` control how sessions arrive. Arrivals, more than behavior inside a session, decide how often instances go cold (see below).
- **Time scaling:** `--time-scale` scales the modeled LLM time (0 replays back to back).
- **Output records:** one per handshake request, tool call and session. Calls carry the idle gap since that endpoint last finished a call, `is_cold`, `container_id` and all timings.
- **Summary:** errors, cold starts on tool calls and on handshakes, distinct containers, latency per class, cold-start rate per idle-gap bucket, and the tool share of session time.

**LLM time is modeled**, because the recorded run has no timestamps.
Per turn: `ttft_ms + context_tokens / prefill_tokens_per_s + output_tokens / decode_tokens_per_s`.
The defaults are 400 ms, 20 000 tok/s and 60 tok/s at 4 characters per token. They are assumptions; set them in the config.
User think time between sessions is not modeled.

## First observations

**The MCP handshake absorbs the cold start.** With eager initialization, `initialize` is the first request a fresh instance sees.
The wrapper now reports `is_cold` on `initialize` and `tools/list` too; before this change, those cold starts were invisible.
On a real platform this only helps if the later tool call reaches the same instance. That is one of the things to measure on Lambda.

**Within a session, tool instances barely idle** (modeled, `--dry-run` on the LiveMCPBench trace):

| | p50 | p90 | max |
|---|---|---|---|
| LLM time per turn | 1.7 s | 9.2 s | 51 s |
| LLM time per session | 23 s | 80 s | 181 s |
| gap between calls to the same class | 1.8 s | 9.1 s | 90 s |

Only 2 of 578 same-class gaps exceed a minute.
If a platform keeps idle instances for minutes, nearly all calls after the first in a session find a warm instance.
Cold starts then come from session starts and from how often sessions arrive at a tool, and from parallel sessions needing more instances.
That points the cold-start experiment (Q3) at arrival rates rather than at agent behavior.
SeBS's eviction experiment measures the platform's idle-instance lifetime.

**Parallel tool calls are rare:** 2 of 810 tool-calling turns in the recorded run issued more than one call.
So tool calls and LLM generation are almost strictly sequential, and every tool millisecond is on the agent's critical path (Q2).

## Tests

```bash
make setup
python3 -m unittest tests.test_mcp_e2e tests.test_mcp_tools tests.test_replay     # 20 tests
```

The fake Function URL (`tests/fake_lambda.py`) runs the real AWS wrapper.
Each fake instance gets its own `/tmp` (the cold-start marker lives there) and handles one request at a time, as a Lambda instance does.
Both were needed to get correct cold-start counts in the replay.

## Next

- **AWS runs** (needs credentials): MCP vs plain, cold vs warm, and the time split for the three tools. Then trace replay at several arrival rates.
- **Browser tool** (Playwright/Chromium as a container-image function) and a **DB tool** with connection setup.
- **More traces:** MCP-Universe and MCP-Bench runs, and real timestamps from an instrumented agent run, to replace the LLM-time model.
