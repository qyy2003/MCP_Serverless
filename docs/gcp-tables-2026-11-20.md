# GCP campaign `2026-11-20` — generated tables

Cloud Run functions (gen2), europe-west1, Python 3.11, concurrency 1, `cpuIdle` (CPU only during requests). Tiers follow Cloud Functions' default CPU per memory size.

7,824 client records; 13,242 request-log entries; 7,824 client records matched to one. Cold-start sessions (e2, e1b): 487 in the result directories, 477 pass the cold-start check.

## Instance starts (Cloud Run system log, whole campaign incl. aborted attempts)

| reason | instance starts |
|---|---|
| DEPLOYMENT_ROLLOUT | 4,526 |
| AUTOSCALING | 1,616 |
| MANUAL_OR_CUSTOMER_MIN_INSTANCE | 3 |


Revisions that got rollout instances: 1,237; rollout instances per revision: median 1, p90 13, max 20. Every deployment of a new revision (which is how SeBS forces a cold start) pre-starts instances that boot and import the tool before any request arrives.


Sessions moved to `aborted/` (failed attempts and sessions that failed the cold-start check): 238 files.


## E1 · MCP vs plain invocation, warm (client VM in europe-west1)

Cold calls excluded. *Outside function* = client time − time inside the handler; split with Cloud Run's request-log latency into the path client ↔ Google front end and the path front end → instance → back. *Calls ≥ 60 ms*: at 0.083 vCPU warm calls are bimodal (≈11 ms or ≈90 ms), consistent with CPU-quota throttling in 100 ms periods: a request that exhausts its slice waits for the next period.

| tier | tool | calls/mode | MCP p50 ms | plain p50 ms | MCP − plain p50 ms | MCP p90 ms | plain p90 ms | calls ≥ 60 ms (MCP / plain) | in function p50 ms (MCP) | outside function p50 ms (MCP / plain) | … client ↔ Google front end (MCP) | … Cloud Run serving path (MCP) | response bytes (MCP / plain) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 128 MB / 0.083 vCPU | no-op | 200 | 16.2 | 16.7 | -0.5 | 89.3 | 89.7 | 46% / 45% | 0.1 | 15.1 / 16.0 | 9.1 | 4.7 | 452 / 305 |
| 128 MB / 0.083 vCPU | dynamic-html | 200 | 89.4 | 90.2 | -0.8 | 99.9 | 100.6 | 68% / 69% | 1.9 | 10.5 / 10.7 | 7.2 | 2.6 | 8,995 / 4,451 |
| 512 MB / 0.333 vCPU | no-op | 200 | 10.4 | 10.7 | -0.3 | 13.9 | 15.0 | 0% / 0% | 0.1 | 10.3 / 10.6 | 8.0 | 2.2 | 452 / 305 |
| 512 MB / 0.333 vCPU | dynamic-html | 200 | 12.4 | 12.7 | -0.3 | 33.1 | 35.7 | 0% / 0% | 1.8 | 10.3 / 10.5 | 7.6 | 2.6 | 8,993 / 4,450 |
| 2048 MB / 1 vCPU | no-op | 200 | 11.1 | 10.8 | 0.4 | 17.0 | 15.1 | 0% / 0% | 0.1 | 11.1 / 10.7 | 8.0 | 2.9 | 452 / 305 |
| 2048 MB / 1 vCPU | dynamic-html | 200 | 13.3 | 13.5 | -0.1 | 17.3 | 20.0 | 0% / 0% | 1.9 | 11.2 / 11.2 | 7.8 | 3.0 | 8,994 / 4,450 |


**MCP session setup, warm no-op function, client = VM in europe-west1** (medians, ms; new connection per session)

| tier | sessions (cold excluded) | TCP+TLS connect | initialize | notifications/initialized | tools/list | handshake total | first tools/call |
|---|---|---|---|---|---|---|---|
| 128 MB / 0.083 vCPU | 29 (1) | 9.1 | 13.4 | 11.3 | 13.7 | 106.7 | 24.9 |
| 512 MB / 0.333 vCPU | 30 (0) | 9.7 | 11.5 | 10.6 | 12.6 | 46.9 | 11.2 |
| 2048 MB / 1 vCPU | 30 (0) | 9.0 | 11.1 | 11.2 | 10.9 | 43.6 | 11.8 |


**MCP session setup, warm no-op function, client = workstation (wide area)** (medians, ms; new connection per session)

| tier | sessions (cold excluded) | TCP+TLS connect | initialize | notifications/initialized | tools/list | handshake total | first tools/call |
|---|---|---|---|---|---|---|---|
| 128 MB / 0.083 vCPU | 30 (0) | 44.0 | 39.2 | 83.6 | 61.0 | 262.3 | 57.1 |


**Workstation → europe-west1, dynamic-html, warm** (ms): mcp: p50 72.2, p90 104.8 (n=200), plain: p50 78.8, p90 116.6 (n=200)


## E2 · Cold vs warm (request-triggered cold start; clean sessions only)

*Cold first result*: MCP = handshake + first tools/call; plain = first invocation. *Container listening after*: request arrival → the instance's startup TCP probe succeeded (system log): sandbox, Python and functions-framework boot, plus, for the SDK variants, the SDK import (they import at module load). *Tool import*: stdlib tools import lazily in the first call; SDK variants at instance startup (reported only on the MCP path). *Sessions on >1 instance*: requests of one session served by different instances (request log); at 0.083 vCPU without boost, the handshake's later requests can land on further instances that Cloud Run started during the first one's slow boot, each with its own cold start.

| tier | boost | tool | mode | sessions | cold first result p50 ms | p25–p75 ms | container listening after p50 ms | warm call p50 ms | cold penalty ms | tool import p50 ms | sessions on >1 instance |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 128 MB / 0.083 vCPU | off | no-op | mcp | 9 | 9,783.5 | 9,247–9,981 | 8,751 | 42.2 | 9,741.3 | 10.5 | 0/9 |
| 128 MB / 0.083 vCPU | off | no-op | plain | 9 | 9,431.0 | 9,342–10,209 | 8,722 | 53.4 | 9,377.5 | 8.4 | 5/9 |
| 128 MB / 0.083 vCPU | off | dynamic-html | mcp | 2 | 21,584.1 | 16,811–26,357 | 10,259 | 78.2 | 21,505.9 | 60.7 | 1/2 |
| 128 MB / 0.083 vCPU | off | dynamic-html | plain | 2 | 11,199.4 | 10,627–11,772 | 10,071 | 134.3 | 11,065.2 | 46.5 | 2/2 |
| 128 MB / 0.083 vCPU | off | api-proxy | mcp | 5 | 10,154.0 | 9,141–32,074 | 8,936 | 214.7 | 9,939.3 | 98.7 | 2/5 |
| 128 MB / 0.083 vCPU | off | api-proxy | plain | 8 | 9,560.8 | 9,116–12,705 | 8,573 | 222.7 | 9,338.1 | 88.3 | 5/8 |
| 128 MB / 0.083 vCPU | off | fetch-markdown | mcp | 3 | 19,825.1 | 16,258–19,989 | 9,199 | 700.3 | 19,124.8 | 161.4 | 2/3 |
| 128 MB / 0.083 vCPU | off | fetch-markdown | plain | 5 | 9,245.8 | 8,535–9,273 | 7,858 | 595.0 | 8,650.8 | 187.2 | 4/5 |
| 128 MB / 0.083 vCPU | on | no-op | mcp | 4 | 869.2 | 790–1,017 | 705 | 10.5 | 858.7 | 8.4 | 0/4 |
| 128 MB / 0.083 vCPU | on | no-op | plain | 4 | 885.2 | 814–1,022 | 754 | 10.7 | 874.5 | 7.2 | 0/4 |
| 128 MB / 0.083 vCPU | on | dynamic-html | mcp | 4 | 1,124.6 | 1,003–1,259 | 978 | 13.4 | 1,111.2 | 7.0 | 0/4 |
| 128 MB / 0.083 vCPU | on | dynamic-html | plain | 6 | 977.2 | 880–1,003 | 879 | 14.1 | 963.1 | 9.0 | 0/6 |
| 128 MB / 0.083 vCPU | on | api-proxy | mcp | 4 | 1,049.6 | 1,008–1,200 | 662 | 215.1 | 834.5 | 10.5 | 0/4 |
| 128 MB / 0.083 vCPU | on | api-proxy | plain | 7 | 1,088.5 | 1,034–1,289 | 772 | 216.8 | 871.7 | 7.7 | 1/7 |
| 128 MB / 0.083 vCPU | on | fetch-markdown | mcp | 1 | 1,192.0 | 1,192–1,192 | 798 | 248.4 | 943.5 | 22.3 | 0/1 |
| 128 MB / 0.083 vCPU | on | fetch-markdown | plain | 2 | 1,488.8 | 1,280–1,698 | 1,102 | 372.8 | 1,116.0 | 39.7 | 1/2 |
| 512 MB / 0.333 vCPU | off | no-op | mcp | 7 | 2,097.0 | 1,975–2,495 | 1,817 | 10.9 | 2,086.1 | 8.8 | 0/7 |
| 512 MB / 0.333 vCPU | off | no-op | plain | 10 | 2,124.7 | 1,921–2,483 | 1,967 | 12.5 | 2,112.2 | 8.0 | 2/10 |
| 512 MB / 0.333 vCPU | off | dynamic-html | mcp | 9 | 2,359.9 | 1,977–2,964 | 2,089 | 13.7 | 2,346.2 | 9.5 | 0/9 |
| 512 MB / 0.333 vCPU | off | dynamic-html | plain | 7 | 2,384.6 | 2,181–2,851 | 2,165 | 15.8 | 2,368.9 | 7.8 | 0/7 |
| 512 MB / 0.333 vCPU | off | api-proxy | mcp | 7 | 2,456.3 | 2,405–2,540 | 2,016 | 215.0 | 2,241.3 | 9.0 | 1/7 |
| 512 MB / 0.333 vCPU | off | api-proxy | plain | 6 | 2,174.0 | 2,011–2,424 | 1,793 | 215.7 | 1,958.3 | 7.2 | 2/6 |
| 512 MB / 0.333 vCPU | off | api-proxy (SDK) | mcp | 1 | 9,832.4 | 9,832–9,832 | 9,302 | 216.9 | 9,615.5 | 6,715.6 | 0/1 |
| 512 MB / 0.333 vCPU | off | api-proxy (SDK) | plain | 4 | 8,665.4 | 8,570–8,960 | 8,227 | 217.0 | 8,448.4 | – | 3/4 |
| 512 MB / 0.333 vCPU | off | fetch-markdown | mcp | 4 | 2,515.4 | 2,430–2,601 | 2,002 | 269.2 | 2,246.2 | 44.7 | 0/4 |
| 512 MB / 0.333 vCPU | off | fetch-markdown | plain | 8 | 2,828.3 | 2,477–3,226 | 2,301 | 243.2 | 2,585.0 | 32.9 | 3/8 |
| 512 MB / 0.333 vCPU | off | fetch-markdown (SDK) | plain | 3 | 9,326.4 | 9,082–10,207 | 8,796 | 276.2 | 9,050.3 | – | 3/3 |
| 512 MB / 0.333 vCPU | on | no-op | mcp | 9 | 944.3 | 820–1,024 | 794 | 10.2 | 934.1 | 6.8 | 0/9 |
| 512 MB / 0.333 vCPU | on | no-op | plain | 8 | 791.1 | 749–899 | 659 | 12.0 | 779.0 | 8.1 | 0/8 |
| 512 MB / 0.333 vCPU | on | dynamic-html | mcp | 9 | 1,352.9 | 1,048–1,479 | 1,168 | 15.1 | 1,337.8 | 8.7 | 0/9 |
| 512 MB / 0.333 vCPU | on | dynamic-html | plain | 10 | 1,382.7 | 884–1,645 | 1,258 | 13.8 | 1,368.9 | 8.3 | 1/10 |
| 512 MB / 0.333 vCPU | on | api-proxy | mcp | 9 | 1,202.1 | 1,120–1,297 | 843 | 215.5 | 986.6 | 8.5 | 0/9 |
| 512 MB / 0.333 vCPU | on | api-proxy | plain | 8 | 1,135.2 | 1,090–1,297 | 836 | 216.1 | 919.1 | 6.7 | 3/8 |
| 512 MB / 0.333 vCPU | on | api-proxy (SDK) | mcp | 8 | 3,375.7 | 3,238–3,656 | 2,987 | 219.6 | 3,156.2 | 2,090.4 | 0/8 |
| 512 MB / 0.333 vCPU | on | api-proxy (SDK) | plain | 5 | 4,630.3 | 3,098–5,287 | 4,325 | 216.8 | 4,413.6 | – | 2/5 |
| 512 MB / 0.333 vCPU | on | fetch-markdown | mcp | 9 | 1,200.3 | 1,103–1,326 | 757 | 243.0 | 957.3 | 19.0 | 0/9 |
| 512 MB / 0.333 vCPU | on | fetch-markdown | plain | 5 | 1,177.9 | 1,132–1,242 | 827 | 242.2 | 935.7 | 19.3 | 1/5 |
| 512 MB / 0.333 vCPU | on | fetch-markdown (SDK) | mcp | 3 | 4,571.9 | 3,720–4,950 | 4,174 | 248.7 | 4,323.2 | 3,020.8 | 1/3 |
| 512 MB / 0.333 vCPU | on | fetch-markdown (SDK) | plain | 6 | 5,429.7 | 3,890–5,764 | 5,065 | 245.2 | 5,184.5 | – | 6/6 |
| 2048 MB / 1 vCPU | off | no-op | mcp | 10 | 1,489.9 | 1,286–1,737 | 1,340 | 11.6 | 1,478.3 | 9.4 | 0/10 |
| 2048 MB / 1 vCPU | off | no-op | plain | 10 | 1,537.6 | 1,203–1,601 | 1,404 | 13.1 | 1,524.5 | 9.8 | 0/10 |
| 2048 MB / 1 vCPU | off | dynamic-html | mcp | 10 | 1,348.0 | 1,214–1,742 | 1,161 | 15.3 | 1,332.7 | 9.3 | 1/10 |
| 2048 MB / 1 vCPU | off | dynamic-html | plain | 10 | 1,374.4 | 1,300–1,491 | 1,228 | 15.2 | 1,359.2 | 10.0 | 0/10 |
| 2048 MB / 1 vCPU | off | api-proxy | mcp | 10 | 1,489.0 | 1,392–1,675 | 1,061 | 215.5 | 1,273.5 | 8.8 | 0/10 |
| 2048 MB / 1 vCPU | off | api-proxy | plain | 10 | 1,407.8 | 1,316–1,530 | 1,095 | 217.2 | 1,190.6 | 8.6 | 0/10 |
| 2048 MB / 1 vCPU | off | api-proxy (SDK) | mcp | 9 | 3,801.6 | 3,635–4,709 | 3,383 | 219.3 | 3,582.3 | 2,316.2 | 0/9 |
| 2048 MB / 1 vCPU | off | api-proxy (SDK) | plain | 10 | 3,485.3 | 3,272–5,439 | 3,161 | 215.5 | 3,269.7 | – | 0/10 |
| 2048 MB / 1 vCPU | off | fetch-markdown | mcp | 9 | 1,714.5 | 1,524–1,883 | 1,244 | 245.9 | 1,468.6 | 23.1 | 0/9 |
| 2048 MB / 1 vCPU | off | fetch-markdown | plain | 10 | 1,646.5 | 1,555–1,854 | 1,260 | 243.9 | 1,402.6 | 21.1 | 0/10 |
| 2048 MB / 1 vCPU | off | fetch-markdown (SDK) | mcp | 7 | 4,264.6 | 3,777–6,251 | 3,861 | 251.4 | 4,013.3 | 2,699.8 | 0/7 |
| 2048 MB / 1 vCPU | off | fetch-markdown (SDK) | plain | 10 | 4,520.9 | 3,603–5,287 | 4,138 | 239.7 | 4,281.2 | – | 1/10 |
| 2048 MB / 1 vCPU | on | no-op | mcp | 10 | 1,255.7 | 1,141–1,344 | 1,089 | 11.5 | 1,244.1 | 7.8 | 0/10 |
| 2048 MB / 1 vCPU | on | no-op | plain | 10 | 1,377.8 | 1,240–1,552 | 1,239 | 12.7 | 1,365.0 | 8.5 | 0/10 |
| 2048 MB / 1 vCPU | on | dynamic-html | mcp | 9 | 1,408.3 | 1,318–1,454 | 1,227 | 14.8 | 1,393.5 | 10.4 | 0/9 |
| 2048 MB / 1 vCPU | on | dynamic-html | plain | 10 | 1,257.6 | 1,203–1,414 | 1,145 | 13.7 | 1,243.9 | 11.3 | 1/10 |
| 2048 MB / 1 vCPU | on | api-proxy | mcp | 9 | 1,730.6 | 1,655–1,844 | 1,323 | 216.5 | 1,514.1 | 8.6 | 0/9 |
| 2048 MB / 1 vCPU | on | api-proxy | plain | 10 | 1,450.0 | 1,336–1,576 | 1,110 | 216.6 | 1,233.4 | 9.2 | 1/10 |
| 2048 MB / 1 vCPU | on | api-proxy (SDK) | mcp | 10 | 3,619.4 | 3,479–4,878 | 3,271 | 219.9 | 3,399.5 | 2,202.3 | 1/10 |
| 2048 MB / 1 vCPU | on | api-proxy (SDK) | plain | 10 | 4,431.7 | 3,523–6,150 | 4,127 | 215.9 | 4,215.9 | – | 2/10 |
| 2048 MB / 1 vCPU | on | fetch-markdown | mcp | 10 | 1,456.5 | 1,390–1,706 | 1,044 | 240.8 | 1,215.6 | 21.8 | 0/10 |
| 2048 MB / 1 vCPU | on | fetch-markdown | plain | 10 | 1,495.9 | 1,421–1,657 | 1,112 | 244.5 | 1,251.4 | 19.7 | 0/10 |
| 2048 MB / 1 vCPU | on | fetch-markdown (SDK) | mcp | 10 | 3,664.7 | 3,431–3,824 | 3,267 | 247.3 | 3,417.4 | 2,249.2 | 0/10 |
| 2048 MB / 1 vCPU | on | fetch-markdown (SDK) | plain | 9 | 4,019.2 | 3,672–5,605 | 3,680 | 244.3 | 3,774.9 | – | 1/9 |


**Startup CPU boost: first response of a cold session, boost off / on** (p50, MCP and plain pooled; the first request is `initialize` or the first plain call)

| tool | 128 MB / 0.083 vCPU | 512 MB / 0.333 vCPU | 2048 MB / 1 vCPU |
|---|---|---|---|
| no-op | 9.51 s (n=18) / 0.86 s (n=8) | 2.05 s (n=17) / 0.82 s (n=17) | 1.53 s (n=20) / 1.26 s (n=20) |
| dynamic-html | 11.04 s (n=4) / 1.00 s (n=10) | 2.34 s (n=16) / 1.35 s (n=19) | 1.35 s (n=20) / 1.29 s (n=19) |
| api-proxy | 9.61 s (n=13) / 1.06 s (n=11) | 2.20 s (n=13) / 1.07 s (n=17) | 1.34 s (n=20) / 1.45 s (n=19) |
| fetch-markdown | 9.26 s (n=8) / 1.07 s (n=3) | 2.47 s (n=12) / 1.07 s (n=14) | 1.55 s (n=19) / 1.43 s (n=20) |
| api-proxy (SDK) | – / – | 8.71 s (n=5) / 3.13 s (n=13) | 3.50 s (n=19) / 3.61 s (n=20) |
| fetch-markdown (SDK) | – / – | 9.33 s (n=3) / 5.04 s (n=9) | 4.20 s (n=17) / 3.55 s (n=19) |


## E1b · Instances used by one sequential client (handshake + 40 calls after a cold start)

Instances from Cloud Run's request log. Few runs passed the cold-start check, so this is indicative only.

| tier | gap between calls s | runs (clean) | instances per run (mean) | max |
|---|---|---|---|---|
| 128 MB / 0.083 vCPU | 0.00 | 4 | 1.00 | 1 |
| 128 MB / 0.083 vCPU | 0.25 | 1 | 4.00 | 4 |
| 128 MB / 0.083 vCPU | 1.00 | 1 | 1.00 | 1 |
| 512 MB / 0.333 vCPU | 0.00 | 2 | 1.00 | 1 |
| 512 MB / 0.333 vCPU | 0.25 | 1 | 1.00 | 1 |
| 512 MB / 0.333 vCPU | 1.00 | 2 | 1.50 | 2 |
| 2048 MB / 1 vCPU | 0.00 | 3 | 1.00 | 1 |
| 2048 MB / 1 vCPU | 0.25 | 1 | 1.00 | 1 |


## E3 · Where a warm tool call's time goes (medians, ms)

Warm calls only (first 2 calls of each run and cold calls dropped). Upstream = mock API on the client VM in the same region. CPU is a mean: Cloud Run's process CPU clock has 10 ms resolution.

| tier | configuration | calls | client p50 | upstream delay (set) | upstream network+HTTP | upstream connect | local processing | other in function | outside function | CPU ms (mean) |
|---|---|---|---|---|---|---|---|---|---|---|
| 128 MB / 0.083 vCPU | api-proxy, 50 ms upstream | 30 | 65.8 | 50.0 | 3.0 | 0.0 | 0.3 | 0.1 | 11.8 | 2.7 |
| 128 MB / 0.083 vCPU | api-proxy, 200 ms upstream | 30 | 222.1 | 200.0 | 3.8 | 0.0 | 0.3 | 0.1 | 15.6 | 3.7 |
| 128 MB / 0.083 vCPU | api-proxy, 1000 ms upstream | 30 | 1,082.9 | 1,000.0 | 3.7 | 0.0 | 0.3 | 0.1 | 76.2 | 2.0 |
| 128 MB / 0.083 vCPU | api-proxy, 200 ms upstream, new connection each call | 30 | 227.1 | 200.0 | 3.7 | 1.5 | 0.3 | 0.2 | 17.3 | 2.3 |
| 128 MB / 0.083 vCPU | fetch-markdown, 10 KB page | 30 | 220.9 | 200.0 | 2.4 | 0.0 | 1.7 | 0.1 | 11.1 | 9.3 |
| 128 MB / 0.083 vCPU | fetch-markdown, 200 KB page | 30 | 502.1 | 200.0 | 7.7 | 0.0 | 279.2 | 0.2 | 12.3 | 234.7 |
| 128 MB / 0.083 vCPU | fetch-markdown, 1,000 KB page | 30 | 2,049.1 | 200.0 | 187.4 | 0.0 | 1,603.5 | 0.6 | 14.7 | 1,291.0 |
| 512 MB / 0.333 vCPU | api-proxy, 50 ms upstream | 30 | 63.5 | 50.0 | 2.5 | 0.0 | 0.2 | 0.1 | 10.7 | 1.3 |
| 512 MB / 0.333 vCPU | api-proxy, 200 ms upstream | 30 | 214.9 | 200.0 | 3.0 | 0.0 | 0.2 | 0.1 | 11.4 | 1.3 |
| 512 MB / 0.333 vCPU | api-proxy, 1000 ms upstream | 30 | 1,014.3 | 1,000.0 | 3.0 | 0.0 | 0.2 | 0.1 | 11.1 | 0.3 |
| 512 MB / 0.333 vCPU | api-proxy, 200 ms upstream, new connection each call | 30 | 215.0 | 200.0 | 3.2 | 1.1 | 0.2 | 0.2 | 10.2 | 1.7 |
| 512 MB / 0.333 vCPU | fetch-markdown, 10 KB page | 30 | 219.4 | 200.0 | 2.8 | 0.0 | 1.9 | 0.1 | 13.8 | 2.3 |
| 512 MB / 0.333 vCPU | fetch-markdown, 200 KB page | 30 | 242.3 | 200.0 | 5.7 | 0.0 | 22.6 | 0.2 | 12.4 | 26.0 |
| 512 MB / 0.333 vCPU | fetch-markdown, 1,000 KB page | 30 | 580.4 | 200.0 | 15.3 | 0.0 | 351.3 | 0.5 | 11.6 | 289.0 |
| 2048 MB / 1 vCPU | api-proxy, 50 ms upstream | 30 | 64.5 | 50.0 | 2.6 | 0.0 | 0.3 | 0.1 | 11.5 | 1.3 |
| 2048 MB / 1 vCPU | api-proxy, 200 ms upstream | 30 | 214.9 | 200.0 | 3.1 | 0.0 | 0.3 | 0.1 | 11.2 | 0.7 |
| 2048 MB / 1 vCPU | api-proxy, 1000 ms upstream | 29 | 1,016.7 | 1,000.0 | 3.5 | 0.0 | 0.3 | 0.1 | 12.9 | 0.3 |
| 2048 MB / 1 vCPU | api-proxy, 200 ms upstream, new connection each call | 30 | 216.7 | 200.0 | 3.1 | 1.2 | 0.3 | 0.2 | 11.8 | 1.3 |
| 2048 MB / 1 vCPU | fetch-markdown, 10 KB page | 30 | 214.5 | 200.0 | 2.3 | 0.0 | 1.2 | 0.1 | 10.6 | 2.0 |
| 2048 MB / 1 vCPU | fetch-markdown, 200 KB page | 30 | 239.4 | 200.0 | 5.4 | 0.0 | 21.9 | 0.2 | 11.5 | 22.7 |
| 2048 MB / 1 vCPU | fetch-markdown, 1,000 KB page | 30 | 343.6 | 200.0 | 12.2 | 0.0 | 111.9 | 0.6 | 10.8 | 116.0 |


## E5 · Billing (warm calls of E3; computed from Cloud Run's request-log latency)

Request-based billing: billable time = request latency rounded up to 100 ms (concurrency 1, so per request), × (vCPU × $2.4e-05/vCPU-s + GiB × $2.5e-06/GiB-s) + $0.40 per 1M requests. **Prices and rounding rule not verified against the current price page; check before quoting $.** Request-log latency slightly overestimates the instance's billable time (it includes the front end).

| tier | configuration | calls | Cloud Run latency p50 ms | billable ms p50 / p99 | share of billable time waiting on upstream | $ per 1M calls | … with 1 ms granularity | rounding surcharge |
|---|---|---|---|---|---|---|---|---|
| 128 MB / 0.083 vCPU | api-proxy, 50 ms upstream | 30 | 57.2 | 100 / 300 | 53% | 0.70 | 0.60 | 16% |
| 128 MB / 0.083 vCPU | api-proxy, 200 ms upstream | 30 | 211.9 | 300 / 300 | 68% | 1.09 | 0.94 | 16% |
| 128 MB / 0.083 vCPU | api-proxy, 1000 ms upstream | 30 | 1,075.8 | 1100 / 1300 | 91% | 3.03 | 2.88 | 5% |
| 128 MB / 0.083 vCPU | api-proxy, 200 ms upstream, new connection each call | 30 | 216.7 | 300 / 471 | 68% | 1.14 | 0.99 | 15% |
| 128 MB / 0.083 vCPU | fetch-markdown, 10 KB page | 30 | 210.3 | 300 / 471 | 67% | 1.11 | 0.94 | 18% |
| 128 MB / 0.083 vCPU | fetch-markdown, 200 KB page | 30 | 493.8 | 500 / 871 | 41% | 1.71 | 1.65 | 4% |
| 128 MB / 0.083 vCPU | fetch-markdown, 1,000 KB page | 30 | 2,039.5 | 2050 / 2642 | 18% | 5.22 | 5.15 | 1% |
| 512 MB / 0.333 vCPU | api-proxy, 50 ms upstream | 30 | 56.1 | 100 / 100 | 52% | 1.32 | 0.92 | 44% |
| 512 MB / 0.333 vCPU | api-proxy, 200 ms upstream | 30 | 207.1 | 300 / 300 | 68% | 3.17 | 2.32 | 37% |
| 512 MB / 0.333 vCPU | api-proxy, 1000 ms upstream | 30 | 1,007.0 | 1100 / 1100 | 91% | 10.57 | 9.73 | 9% |
| 512 MB / 0.333 vCPU | api-proxy, 200 ms upstream, new connection each call | 30 | 207.6 | 300 / 300 | 68% | 3.17 | 2.32 | 37% |
| 512 MB / 0.333 vCPU | fetch-markdown, 10 KB page | 30 | 210.2 | 300 / 300 | 68% | 3.17 | 2.35 | 35% |
| 512 MB / 0.333 vCPU | fetch-markdown, 200 KB page | 30 | 233.7 | 300 / 371 | 69% | 3.20 | 2.60 | 23% |
| 512 MB / 0.333 vCPU | fetch-markdown, 1,000 KB page | 30 | 572.0 | 600 / 700 | 36% | 5.88 | 5.47 | 8% |
| 2048 MB / 1 vCPU | api-proxy, 50 ms upstream | 30 | 56.7 | 100 / 100 | 53% | 3.30 | 2.06 | 60% |
| 2048 MB / 1 vCPU | api-proxy, 200 ms upstream | 30 | 207.3 | 300 / 300 | 68% | 9.10 | 6.42 | 42% |
| 2048 MB / 1 vCPU | api-proxy, 1000 ms upstream | 29 | 1,008.5 | 1100 / 1100 | 91% | 32.30 | 29.65 | 9% |
| 2048 MB / 1 vCPU | api-proxy, 200 ms upstream, new connection each call | 30 | 208.8 | 300 / 300 | 68% | 9.10 | 6.47 | 41% |
| 2048 MB / 1 vCPU | fetch-markdown, 10 KB page | 30 | 207.1 | 300 / 300 | 67% | 9.10 | 6.41 | 42% |
| 2048 MB / 1 vCPU | fetch-markdown, 200 KB page | 30 | 230.8 | 300 / 300 | 68% | 9.10 | 7.11 | 28% |
| 2048 MB / 1 vCPU | fetch-markdown, 1,000 KB page | 30 | 335.0 | 400 / 400 | 53% | 12.00 | 10.09 | 19% |


**Handshake requests (warm, p50):** each is billed as a whole granule.

| tier | initialize latency / billable ms | notifications/initialized latency / billable ms | tools/list latency / billable ms | handshake billable ms |
|---|---|---|---|---|
| 128 MB / 0.083 vCPU | 4.5 / 100 | 3.5 / 100 | 6.4 / 100 | 300 |
| 512 MB / 0.333 vCPU | 2.4 / 100 | 2.2 / 100 | 2.3 / 100 | 300 |
| 2048 MB / 1 vCPU | 3.3 / 100 | 3.0 / 100 | 2.9 / 100 | 300 |


## E4 · Agent trace replay (LiveMCPBench, Claude Sonnet 4 run; modeled LLM time)

Configurations seen: 128 MB / 0.083 vCPU, boost on. No holds: each run starts right after a new revision was deployed, so Cloud Run has pre-started an instance per tool. *Fresh-process requests*: the wrapper's `is_cold` (first request of the process); *waited*: the instance was started for this request (start logged at most 0.5 s before it), i.e. a cold start the client sat through.

| session arrival interval s | sessions | peak concurrent sessions | tool calls | errors | instances used (4 tools) | … pre-started on deploy (rollout) / request-triggered | fresh-process requests (handshake / call) | … of which waited for the instance to start | tool call p50 ms | tool call p95 ms | tool share of session time p50 | earliest instance start − run start s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 20 | 18 | 214 | 0 | 15 | 7 / 8 | 8 / 2 | 3 | 114.0 | 666.6 | 4.6% | -7.6 |
| 10 | 20 | 7 | 214 | 0 | 5 | 3 / 2 | 4 / 1 | 0 | 123.2 | 654.3 | 4.3% | -6.8 |
| 60 | 20 | 2 | 214 | 0 | 4 | 3 / 1 | 4 / 0 | 0 | 154.2 | 636.3 | 4.9% | -8.3 |


**Replay billing** (computed, all invocations; prices as in E5)

| session arrival interval s | invocations | of which handshake | billable s | handshake share of billable time | handshake share of cost | $ per 1,000 sessions |
|---|---|---|---|---|---|---|
| 1 | 304 | 90 (30%) | 58.9 | 18% | 23% | 0.0129 |
| 10 | 304 | 90 (30%) | 61.9 | 20% | 24% | 0.0132 |
| 60 | 304 | 90 (30%) | 64.0 | 18% | 23% | 0.0135 |

