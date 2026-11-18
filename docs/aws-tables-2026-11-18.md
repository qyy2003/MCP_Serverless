# AWS Lambda campaign `2026-11-18` — generated tables

7,243 client records; 8,155 Lambda REPORT lines; 7,243 records matched to a REPORT line.

## E1 · MCP vs plain invocation, warm (client VM in eu-north-1)

Cold calls excluded. *Outside function* = client time − time inside the function handler: network, Function URL front end, Lambda routing, protocol.

| memory MB | tool | calls/mode | MCP p50 ms | plain p50 ms | MCP − plain p50 ms | MCP p90 ms | plain p90 ms | in function p50 ms (MCP) | outside function p50 ms (MCP / plain) | response bytes (MCP / plain) |
|---|---|---|---|---|---|---|---|---|---|---|
| 128 | no-op | 199 | 19.7 | 19.7 | -0.1 | 20.6 | 20.5 | 0.1 | 19.4 / 19.6 | 418 / 271 |
| 128 | dynamic-html | 199 | 24.4 | 22.6 | 1.8 | 40.2 | 40.1 | 9.3 | 15.5 / 14.8 | 8,960 / 4,417 |
| 512 | no-op | 200 | 14.3 | 11.2 | 3.1 | 18.2 | 15.6 | 0.1 | 14.2 / 11.2 | 418 / 271 |
| 512 | dynamic-html | 200 | 16.3 | 14.7 | 1.6 | 19.6 | 19.6 | 1.4 | 14.9 / 13.3 | 8,962 / 4,417 |
| 1769 | no-op | 200 | 12.0 | 13.8 | -1.7 | 16.0 | 18.3 | 0.1 | 12.0 / 13.7 | 418 / 271 |
| 1769 | dynamic-html | 200 | 15.3 | 14.3 | 1.0 | 18.7 | 18.7 | 1.3 | 14.0 / 13.0 | 8,961 / 4,416 |


**MCP session setup, warm function, client = VM in eu-north-1** (medians, ms; each session opens a new connection)

| memory MB | sessions (cold excluded) | TCP+TLS connect | initialize | notifications/initialized | tools/list | handshake total | first tools/call |
|---|---|---|---|---|---|---|---|
| 128 | 30 (0) | 6.7 | 13.5 | 14.1 | 17.1 | 52.0 | 19.9 |
| 512 | 30 (0) | 7.0 | 14.2 | 13.9 | 13.0 | 48.6 | 13.0 |
| 1769 | 30 (0) | 5.4 | 14.5 | 13.9 | 13.3 | 47.6 | 14.1 |


**MCP session setup, warm function, client = workstation at ETH Zurich** (medians, ms; each session opens a new connection)

| memory MB | sessions (cold excluded) | TCP+TLS connect | initialize | notifications/initialized | tools/list | handshake total | first tools/call |
|---|---|---|---|---|---|---|---|
| 128 | 30 (0) | 60.4 | 40.2 | 40.6 | 40.3 | 182.1 | 40.3 |


**Workstation at ETH Zurich → eu-north-1, dynamic-html, warm** (ms): mcp: p50 59.5, p90 60.3 (n=200), plain: p50 59.2, p90 60.3 (n=200)


## E2 · Cold vs warm (forced cold start per session)

*Cold first result*: MCP = handshake (initialize, notification, tools/list) + first tools/call; plain = first invocation. *Lambda init* = Init Duration from the REPORT line of the cold request. *Tool import* = importing the benchmark module inside the first call (SeBS imports it lazily).

| memory MB | tool | mode | sessions | cold first result p50 ms | warm call p50 ms | cold penalty ms | Lambda init p50 ms | tool import p50 ms | first call on a 2nd new instance |
|---|---|---|---|---|---|---|---|---|---|
| 128 | no-op | mcp | 10 | 273.9 | 19.2 | 254.6 | 77.6 | 0.4 | 0/10 |
| 128 | no-op | plain | 10 | 216.5 | 19.8 | 196.7 | 71.8 | 0.4 | – |
| 128 | dynamic-html | mcp | 10 | 1,402.4 | 39.7 | 1,362.7 | 79.2 | 1,056.3 | 0/10 |
| 128 | dynamic-html | plain | 10 | 1,372.0 | 39.9 | 1,332.1 | 79.4 | 1,091.4 | – |
| 128 | api-proxy | mcp | 10 | 1,073.5 | 220.3 | 853.2 | 76.7 | 537.2 | 0/10 |
| 128 | api-proxy | plain | 10 | 1,046.4 | 220.2 | 826.2 | 74.6 | 580.9 | – |
| 128 | fetch-markdown | mcp | 10 | 1,516.9 | 539.5 | 977.4 | 76.5 | 614.3 | 0/10 |
| 128 | fetch-markdown | plain | 10 | 1,492.6 | 538.9 | 953.7 | 71.9 | 623.1 | – |
| 512 | no-op | mcp | 10 | 271.5 | 14.9 | 256.6 | 73.0 | 0.4 | 0/10 |
| 512 | no-op | plain | 10 | 197.1 | 14.2 | 182.9 | 67.0 | 0.2 | – |
| 512 | dynamic-html | mcp | 10 | 483.8 | 16.9 | 466.8 | 77.7 | 221.3 | 0/10 |
| 512 | dynamic-html | plain | 10 | 435.5 | 17.1 | 418.3 | 78.5 | 227.0 | – |
| 512 | api-proxy | mcp | 10 | 562.9 | 218.3 | 344.7 | 77.8 | 104.0 | 0/10 |
| 512 | api-proxy | plain | 10 | 510.5 | 219.8 | 290.6 | 67.4 | 101.0 | – |
| 512 | fetch-markdown | mcp | 10 | 649.6 | 280.5 | 369.1 | 75.7 | 117.8 | 0/10 |
| 512 | fetch-markdown | plain | 10 | 623.7 | 280.9 | 342.8 | 78.5 | 126.2 | – |
| 1769 | no-op | mcp | 10 | 253.6 | 14.7 | 238.9 | 71.0 | 0.4 | 0/10 |
| 1769 | no-op | plain | 10 | 207.8 | 16.8 | 191.0 | 74.9 | 0.3 | – |
| 1769 | dynamic-html | mcp | 10 | 331.1 | 17.3 | 313.9 | 74.9 | 66.3 | 0/10 |
| 1769 | dynamic-html | plain | 10 | 272.2 | 17.6 | 254.6 | 66.7 | 69.1 | – |
| 1769 | api-proxy | mcp | 10 | 495.0 | 218.5 | 276.5 | 77.4 | 35.1 | 0/10 |
| 1769 | api-proxy | plain | 10 | 455.7 | 223.1 | 232.6 | 75.3 | 33.0 | – |
| 1769 | fetch-markdown | mcp | 10 | 526.7 | 240.1 | 286.5 | 76.2 | 42.1 | 0/10 |
| 1769 | fetch-markdown | plain | 10 | 484.4 | 240.7 | 243.7 | 77.5 | 41.3 | – |


Billing of the cold request: billed − handler duration p50 77 ms vs Init Duration p50 77 ms (n=240): **the init phase is billed**.


## E1b · Instances used by one sequential client (handshake + 40 calls after a forced cold start)

One client, one request at a time; any instance beyond the first is a cold start the client did not need.

| memory MB | gap between calls s | runs | instances per run (mean) | max | runs with >1 instance | first call on a new instance (median index) |
|---|---|---|---|---|---|---|
| 128 | 0.00 | 4 | 2.00 | 2 | 4/4 | 16.0 |
| 128 | 0.25 | 4 | 1.00 | 1 | 0/4 | – |
| 128 | 1.00 | 4 | 1.00 | 1 | 0/4 | – |
| 512 | 0.00 | 4 | 1.00 | 1 | 0/4 | – |
| 512 | 0.25 | 4 | 1.00 | 1 | 0/4 | – |
| 512 | 1.00 | 4 | 1.00 | 1 | 0/4 | – |
| 1769 | 0.00 | 4 | 1.00 | 1 | 0/4 | – |
| 1769 | 0.25 | 4 | 1.00 | 1 | 0/4 | – |
| 1769 | 1.00 | 4 | 1.00 | 1 | 0/4 | – |


## E3 · Where a warm tool call's time goes (medians, ms)

Warm calls only (first 2 calls of each run and cold calls dropped). Upstream = mock API on the EC2 VM in the same region.

| memory MB | configuration | calls | client p50 | upstream delay (set) | upstream network+HTTP | upstream connect | local processing | other in function | outside function |
|---|---|---|---|---|---|---|---|---|---|
| 128 | api-proxy, 50 ms upstream | 30 | 67.4 | 50.0 | 2.2 | 0.0 | 0.2 | 0.1 | 14.8 |
| 128 | api-proxy, 200 ms upstream | 30 | 220.0 | 200.0 | 3.3 | 0.0 | 0.2 | 0.1 | 16.3 |
| 128 | api-proxy, 1000 ms upstream | 30 | 1,019.4 | 1,000.0 | 3.2 | 0.0 | 0.2 | 0.1 | 15.7 |
| 128 | api-proxy, 200 ms upstream, new connection each call | 30 | 220.7 | 200.0 | 3.4 | 1.4 | 0.2 | 0.1 | 15.4 |
| 128 | fetch-markdown, 10 KB page | 29 | 217.4 | 200.0 | 2.1 | 0.0 | 1.2 | 0.1 | 13.6 |
| 128 | fetch-markdown, 200 KB page | 30 | 459.9 | 200.0 | 4.3 | 0.0 | 178.9 | 56.5 | 16.4 |
| 128 | fetch-markdown, 1,000 KB page | 30 | 1,526.4 | 200.0 | 9.6 | 0.0 | 1,266.3 | 37.7 | 16.1 |
| 512 | api-proxy, 50 ms upstream | 30 | 67.6 | 50.0 | 2.3 | 0.0 | 0.2 | 0.1 | 15.1 |
| 512 | api-proxy, 200 ms upstream | 30 | 218.6 | 200.0 | 3.6 | 0.0 | 0.2 | 0.1 | 14.7 |
| 512 | api-proxy, 1000 ms upstream | 30 | 1,019.2 | 1,000.0 | 3.5 | 0.0 | 0.2 | 0.1 | 15.5 |
| 512 | api-proxy, 200 ms upstream, new connection each call | 30 | 221.5 | 200.0 | 3.5 | 1.4 | 0.2 | 0.1 | 16.2 |
| 512 | fetch-markdown, 10 KB page | 30 | 218.0 | 200.0 | 1.3 | 0.0 | 1.1 | 0.1 | 15.4 |
| 512 | fetch-markdown, 200 KB page | 30 | 261.7 | 200.0 | 1.6 | 0.0 | 47.5 | 0.2 | 12.9 |
| 512 | fetch-markdown, 1,000 KB page | 30 | 559.9 | 200.0 | 3.4 | 0.0 | 338.7 | 0.6 | 14.8 |
| 1769 | api-proxy, 50 ms upstream | 30 | 67.3 | 50.0 | 1.9 | 0.0 | 0.1 | 0.1 | 15.1 |
| 1769 | api-proxy, 200 ms upstream | 30 | 219.0 | 200.0 | 2.9 | 0.0 | 0.2 | 0.1 | 15.6 |
| 1769 | api-proxy, 1000 ms upstream | 30 | 1,017.0 | 1,000.0 | 2.8 | 0.0 | 0.2 | 0.1 | 14.0 |
| 1769 | api-proxy, 200 ms upstream, new connection each call | 30 | 214.4 | 200.0 | 3.0 | 1.2 | 0.2 | 0.2 | 9.9 |
| 1769 | fetch-markdown, 10 KB page | 30 | 219.2 | 200.0 | 2.1 | 0.0 | 0.9 | 0.1 | 16.1 |
| 1769 | fetch-markdown, 200 KB page | 29 | 237.1 | 200.0 | 3.2 | 0.0 | 18.7 | 0.1 | 14.6 |
| 1769 | fetch-markdown, 1,000 KB page | 30 | 318.1 | 200.0 | 5.2 | 0.0 | 96.9 | 0.4 | 15.9 |


## E5 · Billing (warm calls of E3, joined with Lambda REPORT lines)

Lambda: billed duration × memory at $0.0000166667/GB-s + $0.20 per 1M requests (eu-north-1, x86). CPU-time billing: the same calls' measured CPU time at $0.02 per 1M CPU-ms + $0.30 per 1M requests (Cloudflare Workers Standard rates, beyond included quota) — a billing-model comparison on identical work, not a platform comparison.

| memory MB | configuration | calls | billed ms p50 | p99 | billed − upstream delay p50 / p99 | share of billed time waiting on upstream | CPU ms p50 | Lambda $ per 1M calls | CPU-time billing $ per 1M calls |
|---|---|---|---|---|---|---|---|---|---|
| 128 | api-proxy, 50 ms upstream | 30 | 55 | 62 | 5 / 12 | 95% | 0.7 | 0.32 | 0.32 |
| 128 | api-proxy, 200 ms upstream | 30 | 206 | 212 | 6 / 12 | 99% | 0.8 | 0.63 | 0.32 |
| 128 | api-proxy, 1000 ms upstream | 30 | 1,006 | 1,009 | 6 / 9 | 100% | 0.8 | 2.30 | 0.32 |
| 128 | api-proxy, 200 ms upstream, new connection each call | 30 | 207 | 212 | 7 / 12 | 98% | 1.0 | 0.63 | 0.32 |
| 128 | fetch-markdown, 10 KB page | 29 | 208 | 229 | 8 / 29 | 97% | 1.7 | 0.64 | 0.33 |
| 128 | fetch-markdown, 200 KB page | 30 | 451 | 509 | 251 / 309 | 45% | 15.7 | 1.16 | 0.64 |
| 128 | fetch-markdown, 1,000 KB page | 30 | 1,528 | 1,812 | 1328 / 1612 | 14% | 80.0 | 3.56 | 2.16 |
| 512 | api-proxy, 50 ms upstream | 30 | 55 | 55 | 5 / 5 | 95% | 0.7 | 0.66 | 0.32 |
| 512 | api-proxy, 200 ms upstream | 30 | 206 | 207 | 6 / 7 | 99% | 0.8 | 1.92 | 0.32 |
| 512 | api-proxy, 1000 ms upstream | 30 | 1,006 | 1,008 | 6 / 8 | 100% | 0.8 | 8.58 | 0.32 |
| 512 | api-proxy, 200 ms upstream, new connection each call | 30 | 207 | 208 | 7 / 8 | 98% | 1.0 | 1.93 | 0.32 |
| 512 | fetch-markdown, 10 KB page | 30 | 205 | 205 | 5 / 5 | 98% | 1.7 | 1.91 | 0.33 |
| 512 | fetch-markdown, 200 KB page | 30 | 254 | 273 | 54 / 73 | 79% | 20.3 | 2.36 | 0.70 |
| 512 | fetch-markdown, 1,000 KB page | 30 | 548 | 567 | 348 / 367 | 37% | 103.8 | 4.77 | 2.38 |
| 1769 | api-proxy, 50 ms upstream | 30 | 54 | 55 | 4 / 5 | 96% | 0.5 | 1.75 | 0.31 |
| 1769 | api-proxy, 200 ms upstream | 30 | 205 | 206 | 5 / 6 | 99% | 0.7 | 6.10 | 0.31 |
| 1769 | api-proxy, 1000 ms upstream | 30 | 1,005 | 1,005 | 5 / 5 | 100% | 0.7 | 29.14 | 0.31 |
| 1769 | api-proxy, 200 ms upstream, new connection each call | 30 | 206 | 208 | 6 / 8 | 98% | 0.9 | 6.15 | 0.32 |
| 1769 | fetch-markdown, 10 KB page | 30 | 205 | 206 | 5 / 6 | 99% | 1.4 | 6.10 | 0.33 |
| 1769 | fetch-markdown, 200 KB page | 29 | 225 | 230 | 25 / 30 | 90% | 19.3 | 6.67 | 0.65 |
| 1769 | fetch-markdown, 1,000 KB page | 30 | 305 | 306 | 105 / 106 | 67% | 98.4 | 8.98 | 2.27 |


**Billed duration of the handshake requests (warm, p50 ms):** 128 MB: initialize 2, notifications/initialized 2, tools/call 2, tools/list 2; 512 MB: initialize 2, notifications/initialized 2, tools/call 2, tools/list 2; 1769 MB: initialize 2, notifications/initialized 1, tools/call 2, tools/list 1


## E4 · Agent trace replay at three session arrival rates (LiveMCPBench, Claude Sonnet 4 run; modeled LLM time)

Each run starts from no warm instances (forced). Sessions connect to all their servers at start (eager handshake).

*First use of a tool*: each endpoint's first cold start in the run (the run starts with no warm instances). *Extra instances*: later cold starts, when overlapping sessions needed another instance.

| session arrival interval s | sessions | peak concurrent sessions | tool calls | errors | cold starts on handshake | cold starts on tool calls | first use of a tool | extra instances (handshake / tool call) | instances (all endpoints) | tool call p50 ms | tool call p95 ms | cold tool call p50 ms | tool share of session time p50 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 20 | 18 | 214 | 0 | 5 | 4 | 4 | 1 / 4 | 8 | 65.6 | 381.8 | 397.4 | 3.1% |
| 10 | 20 | 7 | 214 | 0 | 4 | 1 | 4 | 0 / 1 | 6 | 67.0 | 366.8 | 508.4 | 2.7% |
| 60 | 20 | 2 | 214 | 0 | 6 | 0 | 4 | 2 / 0 | 6 | 67.3 | 384.2 | – | 2.7% |


**Replay billing** (all invocations, matched to REPORT lines)

| session arrival interval s | invocations | of which handshake | billed GB-s | handshake share of billed GB-s | Lambda $ per 1,000 sessions |
|---|---|---|---|---|---|
| 1 | 304 | 90 (30%) | 11.9 | 2% | 0.013 |
| 10 | 304 | 90 (30%) | 11.6 | 2% | 0.013 |
| 60 | 304 | 90 (30%) | 11.9 | 3% | 0.013 |

