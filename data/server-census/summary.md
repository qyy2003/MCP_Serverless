108 servers, 822 tools (where known)

## Servers per category

| category | LiveMCPBench | MCP-Bench | MCP-Universe | all |
|---|---|---|---|---|
| api_wrapper | 32 | 16 | 5 | 53 |
| search_fetch | 6 | 5 | 2 | 13 |
| filesystem_git | 3 | 0 | 0 | 3 |
| browser | 2 | 0 | 1 | 3 |
| code_exec | 1 | 0 | 0 | 1 |
| memory_rag | 2 | 0 | 0 | 2 |
| local_compute | 17 | 5 | 2 | 24 |
| local_data | 3 | 1 | 0 | 4 |
| desktop_app | 0 | 0 | 1 | 1 |
| other | 3 | 1 | 0 | 4 |
| **total** | 69 | 28 | 11 | 108 |

## Task references per category

| category | LiveMCPBench | MCP-Bench | MCP-Universe |
|---|---|---|---|
| api_wrapper | 73 (59%) | 92 (54%) | 133 (35%) |
| search_fetch | 5 (4%) | 44 (26%) | 110 (29%) |
| filesystem_git | 2 (2%) | 0 (0%) | 0 (0%) |
| browser | 4 (3%) | 0 (0%) | 49 (13%) |
| local_compute | 36 (29%) | 30 (18%) | 74 (19%) |
| local_data | 3 (2%) | 2 (1%) | 0 (0%) |
| desktop_app | 0 (0%) | 0 (0%) | 19 (5%) |
| other | 0 (0%) | 2 (1%) | 0 (0%) |

## Servers by dominant_cost

| dominant_cost | LiveMCPBench | MCP-Bench | MCP-Universe | all |
|---|---|---|---|---|
| cpu | 10 | 6 | 2 | 18 |
| local_io | 11 | 0 | 0 | 11 |
| mixed | 11 | 4 | 2 | 17 |
| network_wait | 37 | 18 | 7 | 62 |
| **total** | 69 | 28 | 11 | 108 |

## Servers by state

| state | LiveMCPBench | MCP-Bench | MCP-Universe | all |
|---|---|---|---|---|
| persistent | 15 | 2 | 2 | 19 |
| session | 7 | 2 | 2 | 11 |
| stateless | 47 | 24 | 7 | 78 |
| **total** | 69 | 28 | 11 | 108 |

## Servers by needs_api_key

| needs_api_key | LiveMCPBench | MCP-Bench | MCP-Universe | all |
|---|---|---|---|---|
| False | 69 | 24 | 7 | 100 |
| True | 0 | 4 | 4 | 8 |
| **total** | 69 | 28 | 11 | 108 |

## Servers with notable startup cost

| benchmark | server | category | heavy_init |
|---|---|---|---|
| LiveMCPBench | yahoo-finance | api_wrapper | pandas/yfinance deps |
| LiveMCPBench | pdf-reader-mcp | local_compute | pdfjs-dist |
| LiveMCPBench | biomcp | api_wrapper | large Python deps (biomcp-python via uv run --with) |
| LiveMCPBench | image-extractor | local_compute | sharp (native image lib) |
| LiveMCPBench | searxng | local_compute | many doc libs (pdf-lib, mammoth, xlsx, puppeteer possible for docx_to_pdf; unsure) |
| LiveMCPBench | yfmcp | api_wrapper | pandas/yfinance deps |
| LiveMCPBench | okppt | local_compute | python-pptx, SVG rasterization libs |
| LiveMCPBench | kospi-kosdaq | api_wrapper | pandas/pykrx deps |
| LiveMCPBench | mermaid-validator | local_compute | mermaid-cli -> headless chromium (puppeteer) |
| LiveMCPBench | playwright | browser | chromium (playwright browsers) |
| LiveMCPBench | investor | api_wrapper | pandas/yfinance deps |
| LiveMCPBench | ppt | local_compute | python-pptx, Pillow |
| LiveMCPBench | fetch | search_fetch | readabilipy/markdownify (readabilipy may spawn node) |
| LiveMCPBench | sitemap | search_fetch | ultimate-sitemap-parser |
| LiveMCPBench | git | filesystem_git | git binary |
| LiveMCPBench | painter | local_compute | node-canvas (native) likely |
| LiveMCPBench | word-document-server | local_compute | python-docx; convert_to_pdf needs LibreOffice/docx2pdf |
| LiveMCPBench | mindmap | local_compute | markmap-cli via npx (node inside Python server) |
| LiveMCPBench | basic-memory | memory_rag | SQLAlchemy/SQLite, file sync; some versions add embeddings (unsure) |
| LiveMCPBench | docker-mcp | other | docker CLI/socket |
| LiveMCPBench | 12306-mcp | api_wrapper | station list fetched at startup |
| LiveMCPBench | puppeteer | browser | chromium (puppeteer) |
| LiveMCPBench | MetaTagGenie | local_compute | exiftool (exiftool-vendored) |
| LiveMCPBench | arxiv-mcp-server | api_wrapper | PDF-to-markdown deps (pymupdf4llm) |
| LiveMCPBench | chess | local_compute | python-chess |
| LiveMCPBench | excel | local_compute | Go binary distributed via npm (excelize) |
| LiveMCPBench | music-analysis | local_compute | librosa/numpy/scipy/numba (+ yt download libs) |
| MCP-Bench | BioMCP | api_wrapper | moderate: many modules; alphagenome imported lazily only by alphagenome_predictor |
| MCP-Bench | Hugging Face | api_wrapper | huggingface_hub import |
| MCP-Bench | OSINT Intelligence | other | requires system binaries (nmap, dnsrecon, dnstwist, whois, dig) not in Python deps |
| MCP-Bench | Medical Calculator | local_compute | scipy import at startup |
| MCP-Bench | Paper Search | search_fetch | moderate (PyPDF2, bs4/lxml, feedparser, httpx) |
| MCP-Bench | Scientific Computing | local_compute | numpy, sympy, matplotlib |
| MCP-Universe | playwright | browser | chromium |
| MCP-Universe | yfinance | api_wrapper | large deps (pandas, yfinance) |
| MCP-Universe | github | api_wrapper | docker image (ghcr.io/github/github-mcp-server:0.5.0) |
| MCP-Universe | blender | desktop_app | running Blender instance with addon |
