# MCP wrapper for SeBS (milestone 1)

Goal: serve any SeBS benchmark as an MCP tool, from the *same* deployed function
that SeBS already invokes, so we can measure what MCP adds on serverless
(protocol round trips, handshake, cold starts) against a plain invocation.

## Layout

The files of this milestone; the README has the full repository map.

```
serverless-benchmarks/            SeBS submodule, pinned to upstream (never committed to)
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
| `configs/systems.json` | Ships the shim with local and AWS Python packages (`../../mcp/python/mcp_shim.py`). |
| `sebs/benchmark.py` | Copies the benchmark's `mcp.json` into the package, and hashes it and the shim so edits invalidate the SeBS build cache. |
| `benchmarks/*/mcp.json` | Tool definition (name, description, inputSchema) for `010.sleep` and `110.dynamic-html`. Arguments are the benchmark's normal input. |

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

## Tests

```bash
scripts/sebs-patch.sh apply
python3 -m unittest tests.test_mcp_e2e
```

The tests package benchmarks the way SeBS builds AWS Python packages (without
installing dependencies) and run the real `handler.py`. No cloud account or Docker needed.

## Not done yet

- Run on real AWS Lambda (needs credentials) and on the local Docker platform (needs the rebuilt run image).
- The SeBS CLI does not know about the MCP mode. The driver takes a URL, so deploy with `sebs` and pass the function URL.
- Node.js wrappers, and the other platforms (Azure, GCP).
- Session mode (`Mcp-Session-Id`) and SSE responses on the server side. The client already follows both.
