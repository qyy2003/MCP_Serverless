"""End-to-end: the 600.mcp tool benchmarks served over MCP, calling the mock upstream.

Requires the SeBS submodule checked out (make setup).

    python -m unittest tests.test_mcp_tools
"""

import importlib.util
import os
import threading
import unittest
from unittest import mock

from mcp_bench import mock_upstream
from mcp_bench.client import MCPClient
from tests.test_mcp_e2e import BENCHMARKS, FakeLambda


def load_input_module(benchmark: str):
    path = os.path.join(BENCHMARKS, benchmark, "input.py")
    spec = importlib.util.spec_from_file_location(f"input_{benchmark.replace('/', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Upstream:
    def __init__(self):
        self.server = mock_upstream.serve("127.0.0.1", 0)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class ToolTest(unittest.TestCase):
    benchmark = None

    @classmethod
    def setUpClass(cls):
        cls.upstream = Upstream()
        cls.function = FakeLambda(cls.benchmark)

    @classmethod
    def tearDownClass(cls):
        cls.function.stop()
        cls.upstream.stop()

    def client(self) -> MCPClient:
        client = MCPClient(self.function.url)
        self.addCleanup(client.close)
        client.initialize()
        return client

    def sebs_input(self, size: str) -> dict:
        with mock.patch.dict(os.environ, {"SEBS_MOCK_UPSTREAM": self.upstream.url}):
            return load_input_module(self.benchmark).generate_input(
                None, size, None, [], [], None, None
            )

    def validate(self, arguments: dict, output: dict):
        error = load_input_module(self.benchmark).validate_output(None, arguments, output, "python")
        self.assertIsNone(error)


class ApiProxy(ToolTest):
    benchmark = "600.mcp/610.api-proxy"

    def test_sebs_input_and_validation(self):
        arguments = self.sebs_input("test")
        client = self.client()
        tools, _ = client.list_tools()
        self.assertEqual(tools[0]["name"], "search_products")
        result, record = client.call_tool("search_products", arguments)
        output = result["structuredContent"]
        self.validate(arguments, output)
        self.assertEqual(len(output["result"]["items"]), min(10, output["result"]["matching"]))
        # The function's own time covers the upstream wait.
        self.assertGreaterEqual(record["exec_us"], output["measurement"]["upstream_wait_us"])

    def test_upstream_connection_reused_across_warm_calls(self):
        client = self.client()
        arguments = {"upstream": self.upstream.url, "latency_ms": 20, "size": 4096}
        first = client.call_tool("search_products", arguments)[0]["structuredContent"]
        second = client.call_tool("search_products", arguments)[0]["structuredContent"]
        self.assertGreaterEqual(first["measurement"]["upstream_wait_us"], 20_000)
        self.assertFalse(second["measurement"]["upstream_new_connection"])
        self.assertEqual(second["measurement"]["upstream_connect_us"], 0)

        fresh = dict(arguments, reuse_connection=False)
        for _ in range(2):
            out = client.call_tool("search_products", fresh)[0]["structuredContent"]
            self.assertTrue(out["measurement"]["upstream_new_connection"])

    def test_response_size_follows_input(self):
        client = self.client()
        out = client.call_tool(
            "search_products", {"upstream": self.upstream.url, "size": 100_000, "limit": 3}
        )[0]["structuredContent"]
        self.assertGreaterEqual(out["measurement"]["upstream_bytes"], 100_000)
        self.assertLess(out["measurement"]["upstream_bytes"], 101_000)
        self.assertEqual(len(out["result"]["items"]), 3)

    def test_upstream_error_is_tool_error(self):
        client = self.client()
        with self.assertRaisesRegex(RuntimeError, "failed"):
            client.call_tool("search_products", {"upstream": self.upstream.url, "size": "x"})


class FetchMarkdown(ToolTest):
    benchmark = "600.mcp/620.fetch-markdown"

    def test_sebs_input_and_validation(self):
        arguments = self.sebs_input("test")
        client = self.client()
        tools, _ = client.list_tools()
        self.assertEqual(tools[0]["name"], "fetch")
        result, _ = client.call_tool("fetch", arguments)
        output = result["structuredContent"]
        self.validate(arguments, output)
        self.assertEqual(len(output["result"]["content"]), 5000)
        self.assertEqual(output["result"]["next_start_index"], 5000)

    def test_paging_through_a_page(self):
        client = self.client()
        arguments = {"upstream": self.upstream.url, "size": 30_000, "max_length": 4000}
        first = client.call_tool("fetch", arguments)[0]["structuredContent"]["result"]
        second = client.call_tool(
            "fetch", dict(arguments, start_index=first["next_start_index"])
        )[0]["structuredContent"]["result"]
        whole = client.call_tool(
            "fetch", dict(arguments, max_length=first["total_length"])
        )[0]["structuredContent"]["result"]
        self.assertEqual(first["content"] + second["content"], whole["content"][:8000])
        self.assertNotIn("next_start_index", whole)

    def test_conversion_drops_boilerplate(self):
        client = self.client()
        out = client.call_tool(
            "fetch", {"upstream": self.upstream.url, "size": 50_000, "max_length": 10**6}
        )[0]["structuredContent"]
        content = out["result"]["content"]
        self.assertTrue(content.startswith("# Benchmark article"))
        for leaked in ("<", "analytics", "Footer text", "Related"):
            self.assertNotIn(leaked, content)
        self.assertIn("| --- |", content)
        self.assertGreater(out["measurement"]["process_us"], 0)


if __name__ == "__main__":
    unittest.main()
