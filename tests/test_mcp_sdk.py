"""End-to-end: the `sdk` variants of the 600.mcp tools, served by the official MCP Python SDK.

The fake Lambda runs the real AWS wrapper, so it needs an interpreter with the variant's
dependencies (mcp==2.3.0). Point SEBS_SDK_PYTHON at one; the tests are skipped otherwise:

    uv venv -p 3.11 /tmp/sdk && uv pip install -p /tmp/sdk/bin/python mcp==2.3.0
    SEBS_SDK_PYTHON=/tmp/sdk/bin/python python -m unittest tests.test_mcp_sdk

Requires the SeBS patch to be applied (scripts/sebs-patch.sh apply).
"""

import json
import os
import subprocess
import unittest
import urllib.request

from mcp_bench.client import MCPClient, run_mcp, run_plain
from tests.test_mcp_e2e import BENCHMARKS, FakeLambda
from tests.test_mcp_tools import Upstream, has_pandas

SDK_PYTHON = os.environ.get("SEBS_SDK_PYTHON")


def schema_summary(schema: dict) -> dict:
    """What a model sees of a tool's input: property names, types, descriptions, and what is required."""
    properties = {name: (spec.get("type"), spec.get("description")) for name, spec in schema["properties"].items()}
    return {"properties": properties, "required": sorted(schema.get("required", []))}


@unittest.skipUnless(SDK_PYTHON, "set SEBS_SDK_PYTHON to an interpreter with mcp==2.3.0")
class SDKVariant(unittest.TestCase):
    benchmark = None
    tool = None
    arguments = None

    @classmethod
    def setUpClass(cls):
        cls.upstream = Upstream()
        cls.function = FakeLambda(cls.benchmark, "sdk", SDK_PYTHON)

    @classmethod
    def tearDownClass(cls):
        cls.function.stop()
        cls.upstream.stop()

    def args(self) -> dict:
        return dict(self.arguments, upstream=self.upstream.url)

    def test_session(self):
        records = run_mcp(self.function.url, self.args(), 2, False, None)
        self.assertEqual([r["phase"] for r in records],
                         ["initialize", "notifications/initialized", "tools/list", "tools/call", "tools/call"])
        initialize, call = records[0], records[3]
        self.assertIn("container_id", initialize)
        self.assertEqual(call["container_id"], initialize["container_id"])
        self.assertFalse(call["is_cold"])
        # The server, and with it the SDK, was imported at startup, not during the call.
        self.assertEqual(call["import_us"], 0)
        self.assertGreater(call["init_import_us"], 0)
        self.assertGreater(call["exec_us"], self.arguments["latency_ms"] * 1000)
        self.assertGreater(call["m_upstream_wait_us"], self.arguments["latency_ms"] * 1000)

    def test_schema_matches_default_variant(self):
        """The SDK derives the schema from the typed signature; it must offer the model the same tool."""
        client = MCPClient(self.function.url)
        self.addCleanup(client.close)
        result, _ = client.initialize()
        tools, _ = client.list_tools()
        with open(os.path.join(BENCHMARKS, self.benchmark, "mcp.json")) as f:
            shim_tool = json.load(f)
        self.assertEqual([t["name"] for t in tools], [shim_tool["name"]])
        self.assertEqual(tools[0]["description"], shim_tool["description"])
        sdk_schema, shim_schema = tools[0]["inputSchema"], shim_tool["inputSchema"]
        self.assertEqual(schema_summary(sdk_schema), schema_summary(shim_schema))
        # The SDK states every default from the signature; mcp.json leaves the benchmark parameters'
        # defaults implicit. Where mcp.json states one, it must be the same.
        for name, spec in shim_schema["properties"].items():
            if "default" in spec:
                self.assertEqual(sdk_schema["properties"][name]["default"], spec["default"], name)

    def test_result_has_the_default_variant_payload(self):
        client = MCPClient(self.function.url)
        self.addCleanup(client.close)
        client.initialize()
        result, record = client.call_tool(self.tool, self.args())
        payload = result["structuredContent"]
        self.assertEqual(set(payload), {"result", "measurement"})
        self.assertEqual(json.loads(result["content"][0]["text"]), payload)
        self.assertIn("cpu_us", result["_meta"]["sebs"])

    def test_invalid_arguments_are_a_tool_error(self):
        client = MCPClient(self.function.url)
        self.addCleanup(client.close)
        client.initialize()
        with self.assertRaisesRegex(RuntimeError, "failed"):
            client.call_tool(self.tool, dict(self.args(), size="large"))

    def test_protocol_2026_07_28_without_handshake(self):
        """The current protocol revision needs no initialize: one self-contained POST per call."""
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": self.tool, "arguments": self.args(),
            "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                      "io.modelcontextprotocol/clientInfo": {"name": "sebs-test", "version": "0"},
                      "io.modelcontextprotocol/clientCapabilities": {}}}}).encode()
        request = urllib.request.Request(self.function.url, body, {
            "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/call", "Mcp-Name": self.tool})
        with urllib.request.urlopen(request, timeout=30) as response:
            message = json.loads(response.read())
        self.assertNotIn("error", message)
        self.assertFalse(message["result"]["isError"])
        self.assertIn("result", message["result"]["structuredContent"])
        self.assertIn("begin", message["result"]["_meta"]["sebs"])

    def test_our_client_in_every_protocol(self):
        expected = {
            "legacy": ["initialize", "notifications/initialized", "tools/list", "tools/call"],
            "modern": ["tools/list", "tools/call"],
            "auto": ["server/discover", "tools/list", "tools/call"],
        }
        for protocol, phases in expected.items():
            with self.subTest(protocol=protocol):
                records = run_mcp(self.function.url, self.args(), 1, False, None, protocol=protocol)
                self.assertEqual([r["phase"] for r in records], phases)
                self.assertGreater(records[-1]["exec_us"], self.arguments["latency_ms"] * 1000)

    def test_plain_invocation_still_works(self):
        records = run_plain(self.function.url, self.args(), 1, False)
        self.assertGreater(records[0]["exec_us"], self.arguments["latency_ms"] * 1000)


class ApiProxySDK(SDKVariant):
    benchmark = "600.mcp/610.api-proxy"
    tool = "search_products"
    arguments = {"latency_ms": 20, "size": 4096, "seed": 1, "limit": 5}


class FetchMarkdownSDK(SDKVariant):
    benchmark = "600.mcp/620.fetch-markdown"
    tool = "fetch"
    arguments = {"latency_ms": 20, "size": 20000, "seed": 1, "max_length": 2000}


@unittest.skipUnless(SDK_PYTHON and has_pandas(SDK_PYTHON), "SEBS_SDK_PYTHON needs pandas too for 630")
class DataAnalysisSDK(SDKVariant):
    benchmark = "600.mcp/630.data-analysis"
    tool = "summarize_catalog"
    arguments = {"latency_ms": 20, "size": 65536, "seed": 1, "group_by": "month"}
    seeds = iter(range(100, 10_000))

    def args(self) -> dict:
        # A new dataset each time: only a dataset's first call waits on the upstream, which the shared tests expect.
        return dict(super().args(), seed=next(self.seeds))


del SDKVariant  # abstract: only the subclasses run

SDK_CLIENT = """
import asyncio, json, sys
from mcp import Client

async def main(url, mode, tool, args):
    async with Client(url, mode=mode) as client:
        tools = await client.list_tools()
        result = await client.call_tool(tool, args)
        print(json.dumps({"tools": [t.name for t in tools.tools], "is_error": result.is_error,
                          "structured": result.structured_content is not None}))

asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3], json.loads(sys.argv[4])))
"""


@unittest.skipUnless(SDK_PYTHON, "set SEBS_SDK_PYTHON to an interpreter with mcp==2.3.0")
class SDKClientConformance(unittest.TestCase):
    """The official SDK client (which validates every result against the spec's types) talks to
    both servers in every connect mode: the stdlib shim and the SDK variant."""

    def run_client(self, url, mode, tool, args):
        out = subprocess.run([SDK_PYTHON, "-c", SDK_CLIENT, url, mode, tool, json.dumps(args)],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        return json.loads(out.stdout.strip().splitlines()[-1])

    def check(self, benchmark, variant, python, tool, args):
        function = FakeLambda(benchmark, variant, python)
        self.addCleanup(function.stop)
        for mode in ("legacy", "auto", "2026-07-28"):
            with self.subTest(benchmark=benchmark, variant=variant, mode=mode):
                result = self.run_client(function.url, mode, tool, args)
                self.assertEqual(result, {"tools": [tool], "is_error": False, "structured": True})

    def test_shim(self):
        import sys
        self.check("000.microbenchmarks/010.sleep", "default", sys.executable, "sleep", {"sleep": 0.01})

    def test_sdk_variant(self):
        upstream = Upstream()
        self.addCleanup(upstream.stop)
        self.check("600.mcp/610.api-proxy", "sdk", SDK_PYTHON, "search_products",
                   {"upstream": upstream.url, "latency_ms": 5, "size": 2048})

if __name__ == "__main__":
    unittest.main()
