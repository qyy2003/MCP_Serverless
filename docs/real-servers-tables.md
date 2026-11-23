# Real MCP servers: size, startup and memory

27 servers from LiveMCPBench's server set (installable from PyPI/npm), measured in throwaway containers (Node 22, Debian's Python 3.11), 1 CPU, 2 GB; latest versions as of the run. *Startup*: process start → tools/list response over stdio, median of runs 2–7. *Init*: startup minus a bare interpreter start. *Peak RSS*: summed over the process tree.

| server | language | category | version | installed_mb | dependencies | startup_ms | init_ms | peak_rss_mb | cpu_s | tools | ok_runs |
|---|---|---|---|---|---|---|---|---|---|---|---|
| mcp-server-chart | node | api_wrapper | @antv/mcp-server-chart@0.9.10 | 19.4 | 109 | 694 | 648 | 93 | 0.69 | 27 | 7/7 |
| trends-hub | node | api_wrapper | mcp-trends-hub@1.6.2 | 19.5 | 119 | 3,518 | 3,476 | 85 | 0.55 | 21 | 7/7 |
| hackernews | node | api_wrapper | @devabdultech/hn-mcp-server@1.2.2 | 25.8 | 113 | 447 | 401 | 81 | 0.44 | 9 | 7/7 |
| mcp-simple-arxiv | python | api_wrapper | mcp_simple_arxiv-0.2.3 | 29.4 | 34 | 351 | 332 | 54 | 0.34 | 4 | 7/7 |
| Context7 | node | api_wrapper | @upstash/context7-mcp@4.7.3 | 40.4 | 104 | 851 | 804 | 100 | 0.83 | 2 | 7/7 |
| osm-mcp-server | python | api_wrapper | osm_mcp_server-0.1.1 | 45.4 | 44 | 422 | 406 | 73 | 0.41 | 12 | 7/7 |
| arxiv-mcp-server | python | api_wrapper | arxiv_mcp_server-0.8.2 | 65.7 | 45 | 381 | 370 | 65 | 0.37 | 19 | 7/7 |
| wikipedia | python | api_wrapper | wikipedia_mcp-2.0.1 | 93.9 | 70 | 952 | 941 | 99 | 0.94 | 22 | 7/7 |
| 12306-mcp | node | api_wrapper | 12306-mcp@0.3.10 | 139.1 | 228 | 6,431 | 6,381 | 115 | 2.82 | 8 | 7/7 |
| yahoo-finance | python | api_wrapper | mcp_yahoo_finance-0.2.0 | 249.9 | 47 | 1,092 | 1,082 | 134 | 1.08 | 21 | 7/7 |
| playwright | node | browser | @executeautomation/playwright-mcp-server@1.0.12 | 143.6 | 320 | 1,122 | 1,081 | 111 | 1.12 | 33 | 7/7 |
| filesystem | node | filesystem_git | @modelcontextprotocol/server-filesystem@2025.8.18 | 21.3 | 135 | 397 | 361 | 73 | 0.39 | 14 | 7/7 |
| git | python | filesystem_git | mcp_server_git-2026.11.18 | 41.5 | 32 | 498 | 487 | 69 | 0.48 | 14 | 7/7 |
| image-extractor | node | local_compute | mcp-image-extractor@1.1.0 | 33.3 | 121 | 573 | 547 | 91 | 0.54 | 3 | 7/7 |
| calculator | python | local_compute | mcp_server_calculator-0.2.1 | 38.0 | 30 | 326 | 316 | 53 | 0.32 | 1 | 7/7 |
| time | python | local_compute | mcp_server_time-2026.11.18 | 39.9 | 31 | 494 | 484 | 67 | 0.48 | 3 | 7/7 |
| ppt | python | local_compute | office_powerpoint_mcp_server-2.0.7 | 90.2 | 42 | 572 | 552 | 87 | 0.56 | 37 | 7/7 |
| word-document-server | python | local_compute | office_word_mcp_server-1.1.11 | 108.0 | 72 | 852 | 842 | 98 | 0.84 | 54 | 7/7 |
| searxng (doc-forge) | node | local_compute | @cablate/mcp-doc-forge@0.0.8 | 139.5 | 369 | 1,251 | 1,207 | 140 | 1.25 | 16 | 7/7 |
| music-analysis | python | local_compute | mcp_music_analysis-0.1.41 | 496.4 | 70 | 1,086 | 1,069 | 116 | 1.07 | 8 | 7/7 |
| howtocook-mcp | node | local_data | howtocook-mcp@0.2.2 | 18.6 | 108 | 509 | 464 | 90 | 0.54 | 5 | 7/7 |
| memory | node | memory_rag | @modelcontextprotocol/server-memory@1.0.0 | 16.7 | 96 | 381 | 348 | 73 | 0.36 | 9 | 7/7 |
| basic-memory | python | memory_rag | basic_memory-1.0.0 | 360.3 | 160 | 3,335 | 3,323 | 226 | 3.30 | 12 | 7/7 |
| sequential-thinking | node | other | @modelcontextprotocol/server-sequential-thinking@1.0.0 | 17.3 | 113 | 404 | 371 | 73 | 0.40 | 1 | 7/7 |
| duckduckgo-search | node | search_fetch | duckduckgo-mcp-server@0.1.2 | 15.2 | 26 | 265 | 229 | 68 | 0.25 | 1 | 7/7 |
| fetch | python | search_fetch | mcp_server_fetch-2026.11.11 | 60.7 | 46 | 520 | 510 | 80 | 0.51 | 1 | 7/7 |
| mcp-deepwiki | node | search_fetch | mcp-deepwiki@0.0.10 | 69.8 | 348 | 1,546 | 1,512 | 155 | 1.54 | 1 | 7/7 |


## Summary: median (p25–p75)

| servers | installed MB | dependencies | init ms | peak RSS MB | fit in 128 MB |
|---|---|---|---|---|---|
| all (n=27) | 42 (24–101) | 96 (44–120) | 547 (386–1,075) | 87 (73–106) | 23/27 |
| node (n=14) | 24 (19–62) | 116 (108–205) | 597 (378–1,176) | 90 (75–108) | 12/14 |
| python (n=13) | 66 (42–108) | 45 (34–70) | 510 (406–941) | 80 (67–99) | 11/13 |
| SeBS benchmarks (n=12) | 10 (1–87) | – | 114 (21–157) | – | – |
| ours: 610.api-proxy (default) | 0.03 | – | 0.9 | – | – |
| ours: 610.api-proxy (sdk) | 41.12 | – | 459.9 | – | – |
| ours: 620.fetch-markdown (default) | 0.03 | – | 4.0 | – | – |
| ours: 620.fetch-markdown (sdk) | 41.13 | – | 462.0 | – | – |
| ours: 630.data-analysis (default) | 149.93 | – | 216.9 | – | – |
| ours: 630.data-analysis (sdk) | 191.03 | – | 671.8 | – | – |

