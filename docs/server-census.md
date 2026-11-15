# MCP server census: what the MCP benchmarks actually exercise

We classified every server used by the three LLM-side MCP benchmarks by its
*infrastructure* workload: where a tool call spends its time, whether it keeps
state between calls, and what it costs to start. The aim is to pick which tool
classes our serverless benchmark has to cover.

- Data: `data/server-census/{mcp-bench,mcp-universe,livemcpbench}.json`, one record per server
- Tables: `data/server-census/summary.md` (regenerate with `python analysis/server_census.py`)
- Sources: Accenture/mcp-bench (`mcp_servers/commands.json`, 28 servers), SalesforceAIResearch/MCP-Universe
  (`mcp/configs/server_list.json`, 11 servers used by benchmark tasks), icip-cas/LiveMCPBench
  (`tools/LiveMCPTool/all_config.json`, 69 servers, 525 tools); shallow clones of their default branches, November 2026.

**108 servers, 822 tools.**

## How it was classified (and how far to trust it)

| Benchmark | Basis | Confidence |
|---|---|---|
| MCP-Bench | server source code (all servers are vendored in the repo) | high |
| MCP-Universe | in-repo source for 5 servers; config + package knowledge for 6 third-party ones (playwright, github, notion, google-maps, fetch, calculator) | medium–high |
| LiveMCPBench | config + cached tool schemas (`tools.json`); no source read | medium |

Task counts: MCP-Bench from each task group's `server_name` (split on `+`, 104 tasks);
MCP-Universe from each task's `mcp_servers` (231 unique tasks); LiveMCPBench by mapping
the tool names in the 95 annotated tasks to servers, counting only tool names unique to one server.
The "share of task references" below counts a multi-server task once per server.
Spot checks against the repos: all matched (e.g. Blender task count, misnamed LiveMCPBench config keys, MCP-Bench's in-memory tensor state).

## Findings

**1. Most MCP tools are thin API wrappers that mostly wait on the network.**
53 of 108 servers (49%) wrap a remote REST API, and 62 (57%) spend most of their time on network waits.
API wrappers account for 35–59% of task references, depending on the benchmark.
On wall-clock-billed platforms (Lambda, Azure Functions), these calls pay for memory while idle.
This is the main workload and the core of the billing question.

| Category | Servers | Share of task references (LiveMCPBench / MCP-Bench / MCP-Universe) |
|---|---|---|
| api_wrapper | 53 | 59% / 54% / 35% |
| local_compute | 24 | 29% / 18% / 19% |
| search_fetch | 13 | 4% / 26% / 29% |
| browser | 3 | 3% / 0% / 13% |
| desktop_app (Blender) | 1 | – / – / 5% |
| filesystem_git, memory_rag, code_exec, local_data, other | 14 | ≤ 2% each |

**2. Search/fetch is the second network class, with large responses.**
Web search and fetch-URL-to-markdown make up 26–29% of task references in MCP-Bench and MCP-Universe.
Responses are pages of text (tens to hundreds of KB), and HTML parsing adds CPU on top of the wait.

**3. Local compute is common but light.**
24 servers (calculator, time, unit conversion, medical formulas, document conversion) and 18–29% of task references.
Most finish in milliseconds, so the MCP round trips and any cold start dominate.
This is where protocol overhead, the thing milestone 1 measures, matters most in relative terms.

**4. Browsers are rare in server count but heavy in practice.**
Only 3 servers (playwright, puppeteer), but 13% of MCP-Universe's task references.
They need Chromium (hundreds of MB, seconds to launch) and keep the open page between calls.
This is the hardest case for serverless and the clearest cold-start story.

**5. 30 of 108 servers keep state between calls.**
11 keep it in memory (session): browser pages, Scientific Computing's tensors, Met Museum's downloaded images, Blender.
19 write state that later calls read (persistent): files, caches, GitHub and Notion objects.
Stateless serverless with no session affinity breaks the session group outright.
The persistent group needs external storage.

**6. 37 servers have a notable startup cost.**
- **Native binaries:** Chromium (also pulled in by mermaid-cli), LibreOffice, exiftool, git, nmap.
- **Large Python stacks:** pandas/yfinance, numpy/scipy/sympy, librosa/numba.
- **Startup work:** downloading data at start (12306 station list, the Huge Icons catalog), installing from git.

Some can't run on a function platform at all: docker-mcp needs a Docker daemon, OSINT needs nmap and raw network access, and Blender needs a running desktop app.

**7. The benchmarks are biased towards keyless public APIs.**
100 of 108 servers need no API key, and **no benchmark uses a database server**.
Real deployments lean the other way: authenticated SaaS (GitHub, Slack, Notion, Jira) and databases (Postgres, BigQuery).
The benchmarks choose keyless services for reproducibility.
An infrastructure benchmark should not copy that bias: it should add an authenticated-API class and a database class.
DB connection setup is a cold-start cost the LLM benchmarks never exercise.

**8. Reproducibility hazards when replaying real servers.**
- **Upstream variance:** live third-party APIs add variance and rate limits.
- **Blocked or region-dependent scraping:** Yahoo, YouTube, Airbnb, 12306 and Chinese trend sites block or behave differently from cloud IPs and regions.
- **Hardcoded keys:** some servers ship API keys in the source.

Replaying traces against the live services won't give stable numbers. We need a mock upstream with controlled latency and payload size.

## What to build, in order

| # | Tool class | Why | Implementation |
|---|---|---|---|
| 1 | **API proxy** with a controllable upstream | largest class; carries the billing question | tool makes an outbound HTTPS call to a mock upstream we run, with configurable latency (e.g. 50 ms–2 s) and response size; real HTTP client, TLS and JSON reshaping |
| 2 | **Fetch → markdown** | second network class; large payloads + parsing CPU | fetch a page from the same mock (sizes 10 KB–1 MB) and convert it to markdown |
| 3 | **Light local compute** | protocol overhead dominates | already covered: `010.sleep`, `110.dynamic-html`; add a calculator/time-style microtool |
| 4 | **Browser session** | heaviest cold start + session state | Playwright/Chromium as a container-image function; navigate, then query the page across calls |
| 5 | **DB query** (not in the benchmarks, but common in real use) | connection setup on cold start; pooling | reuse `130.crud-api`'s NoSQL path; add a Postgres variant |
| 6 | **Heavy-import compute** | import-time cold start | numpy/scipy tool (like Scientific Computing / Medical Calculator) |

Out of scope for functions: Docker-, desktop-app- and raw-network-dependent servers (docker-mcp, Blender, OSINT).

For the trace-replay experiment, take inter-arrival gaps and call sequences from MCP-Universe and MCP-Bench tasks.
Map each real server to one of the classes above by its category, and parameterize the mock upstream from that class.
