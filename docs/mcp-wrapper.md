# MCP wrapper for SeBS (milestone 1)

Goal: serve any SeBS benchmark as an MCP tool, from the *same* deployed function
that SeBS already invokes, so we can measure what MCP adds on serverless
(protocol round trips, handshake, cold starts) against a plain invocation.

## Layout

The files of this milestone; the README has the full repository map.

```
serverless-benchmarks/            SeBS submodule (fork anveba/serverless-benchmarks), pinned commit (never committed to)
patches/serverless-benchmarks.patch   all our changes to SeBS
scripts/sebs-patch.sh             apply / export / revert / status of the patch
mcp_bench/client.py               MCP client + timing driver (stdlib only)
tests/fake_lambda.py              runs the real AWS wrapper behind a fake Function URL
tests/test_mcp_e2e.py             end-to-end tests
```

## Working on the SeBS changes

```bash
git submodule update --init
scripts/sebs-patch.sh apply      # patch the submodule's working tree
# ... edit files in serverless-benchmarks/ ...
scripts/sebs-patch.sh export     # write them back to patches/serverless-benchmarks.patch
git add patches/ && git commit
```

`.gitmodules` sets `ignore = dirty`, so the patched submodule tree does not show
up as a change in this repository; only the patch file does.

## What the patch changes in SeBS

| File | Change |
|---|---|
| `benchmarks/wrappers/mcp/python/mcp_shim.py` | New. Stateless MCP Streamable HTTP server (JSON responses, no SSE, no session): `initialize`, `ping`, `tools/list`, `tools/call`. Standard library only, so package size and import time are unchanged. SeBS timings go back in the tool result's `_meta.sebs`. |
| `benchmarks/wrappers/aws/python/handler.py` | A JSON-RPC body is routed to the shim, anything else follows the existing path. Cold-start detection moved into `cold_test()`. In the MCP path every request (including `initialize`) counts towards warming the container. Both paths report `cpu_us` (process CPU time of the call) and `import_us` (time to import the benchmark module, which happens on an instance's first call). |
| `dockerfiles/local/python/server.py` | New `POST /mcp` route next to `POST /`. **The local run image must be rebuilt** to pick this up (`sebs docker build`). |
| `configs/systems.json` | Ships the shim and the SDK bridge with Python packages on all four platforms (`../../mcp/python/...`). |
| `sebs/benchmark.py` | Copies the benchmark's `mcp.json` into the package, and hashes it and the shim so edits invalidate the SeBS build cache. |
| `benchmarks/*/mcp.json` | Tool definition (name, description, inputSchema) for `010.sleep` and `110.dynamic-html`. Arguments are the benchmark's normal input. |
| `benchmarks/wrappers/mcp/python/mcp_sdk_bridge.py` | New. Serves the `sdk` variant of a benchmark through the official MCP Python SDK: the SDK's stateless JSON Streamable HTTP app, driven in-process like an ASGI adapter (Mangum, Azure's AsgiMiddleware). Imports the benchmark's `mcp_server` at instance startup and adds SeBS timings to `_meta.sebs` through SDK server middleware. Standard library only; only imported for SDK packages. |
| `benchmarks/600.mcp/6x0.*/python/sdk/` | The `sdk` language variant (overlay): `mcp_server.py` registers the unchanged tool logic on `MCPServer` with a typed signature; `requirements.txt` pins `mcp==2.3.0`. |
| AWS `handler.py`, local `server.py` (SDK) | If the package has `function/mcp_server.py`, build the SDK bridge at startup (Lambda init phase) and hand JSON-RPC requests to it with their headers. Other packages are unchanged and never import the bridge. |
| `benchmarks/wrappers/{gcp,azure}/python/handler.py` | The same MCP routing as AWS: JSON-RPC to the shim, or with the headers to the SDK bridge (built at module load: GCP instance startup, Azure first load in a worker). The plain path also reports `cpu_us`, `child_cpu_us`, `import_us`, as on AWS and local. Azure adds `is_cold_worker` to `_meta.sebs`. Endpoints: the function's HTTP trigger URL (Azure: `https://<app>.azurewebsites.net/api/handler`). |
| `sebs/faas/function.py`, `sebs/benchmark.py`, `sebs/{aws,gcp,azure,local}/*.py` | `sdk` Python variant. Function names include a non-default variant (`python-sdk`), so variants don't overwrite each other; default names are unchanged. Local uses the default run image for `sdk` (it is a code variant, not a runtime). |

## Measuring

```bash
# MCP session: initialize, notifications/initialized, tools/list, then N tools/call
python -m mcp_bench.client --url <function-url> --arguments '{"sleep": 0.1}' --calls 20 --output mcp.jsonl
# Baseline: the same input posted as SeBS's HTTP trigger does
python -m mcp_bench.client --url <function-url> --mode plain --arguments '{"sleep": 0.1}' --calls 20
```

On AWS both modes use the same Function URL. On local, MCP uses `http://<container>:9000/mcp` and plain uses `/`.
`--fresh-connection` opens a new TCP/TLS connection per request, like a client that does not keep connections alive.

Per request the driver records `connect_us`, `ttfb_us`, `client_us`, a timestamp, the Lambda request ID
(`amzn_request_id`, for matching billing records) and, for tool calls, the function-side `exec_us`, `cpu_us`,
`import_us`, `is_cold`, `container_id` and the tool's own measurements (`m_*`). `--interval` spaces the calls;
`--meta` adds labels to every record.

## SDK variant

```bash
sebs local start 620.fetch-markdown small out.json ... --language-variant sdk   # or: sebs deploy ... --language-variant sdk
SEBS_SDK_PYTHON=<python with mcp==2.3.0> python3 -m unittest tests.test_mcp_sdk
```

Extra fields in `_meta.sebs` of SDK responses: `init_import_us` (importing `mcp_server`, and with it the SDK,
at startup) and `init_us` (that plus building and starting the app). `import_us` is 0: nothing is imported
during calls. `exec_us` of a tool call covers the call through the SDK: argument validation, the tool
(a sync tool runs in the SDK's worker thread), and result conversion.

## Protocol revisions

Both servers (shim and SDK variant) speak both eras of MCP:

| | Handshake era (≤ 2025-11-25) | 2026-07-28 |
|---|---|---|
| Session start | `initialize` + `notifications/initialized` | none; a client may probe `server/discover` once |
| Per request | `MCP-Protocol-Version` header | version, client info and capabilities in `params._meta`; `Mcp-Method` (and `Mcp-Name` for `tools/call`) headers |
| Results | as before | add `resultType`; `tools/list` and `server/discover` add `cacheScope`/`ttlMs` (we send `private`/0 like the SDK) |

The shim answers handshake-era requests exactly as before, so earlier measurements stay comparable. It recognises a
2026-07-28 request by the version in `params._meta` and does not check the mirrored headers (the wrappers pass it
only the body). `mcp_bench.client --protocol legacy|modern|auto` picks the revision; `auto` is the SDK client's
default (discover, and fall back to the handshake if the server doesn't speak 2026-07-28). The official SDK client
talks to both servers in all three modes (`tests/test_mcp_sdk.py`, `SDKClientConformance`).

## Tests

```bash
scripts/sebs-patch.sh apply
python3 -m unittest tests.test_mcp_e2e
```

The tests package benchmarks the way SeBS builds AWS Python packages (without
installing dependencies) and run the real `handler.py`. No cloud account or Docker needed.

## Not done yet

- Run on GCP and Azure: the routing is tested only against local emulations (`tests/fake_cloud.py`: GCP under
  Google's functions-framework, Azure with `azure.functions` request objects; the Azure Functions host is not emulated).
- On GCP, functions-framework (installed by the platform) brings its own starlette/anyio, which come before the
  package's dependencies on `sys.path`. The SDK bridge reports the versions it actually loaded in `_meta.sebs.sdk_versions`
  of an instance's first response; check them on the first GCP run.
- The SeBS CLI does not know about the MCP mode. The driver takes a URL, so deploy with `sebs` and pass the function URL.
- Node.js wrappers.
- Session mode (`Mcp-Session-Id`) and SSE responses on the server side. The client already follows both.
