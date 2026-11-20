"""End-to-end: the patched SeBS AWS wrapper serves benchmarks over MCP and plain HTTP.

Requires the SeBS patch to be applied (scripts/sebs-patch.sh apply).

    python -m unittest tests.test_mcp_e2e
"""

import json
import os
import socket
import subprocess
import sys
import time
import unittest

from mcp_bench.client import MCPClient, run_mcp, run_plain

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCHMARKS = os.path.join(ROOT, "serverless-benchmarks", "benchmarks")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeLambda:
    """A fake function instance running the real wrapper of `platform` (aws, gcp or azure)."""

    def __init__(self, benchmark: str, variant: str = "default", python: str = sys.executable,
                 platform: str = "aws"):
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}/"
        benchmark_dir = os.path.join(BENCHMARKS, benchmark)
        if platform == "aws":
            command = [os.path.join(ROOT, "tests", "fake_lambda.py"), benchmark_dir, str(self.port), variant]
        else:
            command = [os.path.join(ROOT, "tests", "fake_cloud.py"), platform, benchmark_dir, str(self.port), variant]
        self.proc = subprocess.Popen([python, *command], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.time() + 30  # an SDK variant imports the SDK before it listens
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.2).close()
                return
            except OSError:
                time.sleep(0.05)
        self.stop()
        raise RuntimeError(self.error)

    def stop(self):
        self.proc.terminate()
        _, stderr = self.proc.communicate()
        self.error = stderr.decode()


class SleepOverMCP(unittest.TestCase):
    def setUp(self):
        self.function = FakeLambda("000.microbenchmarks/010.sleep")
        self.addCleanup(self.function.stop)

    def client(self) -> MCPClient:
        client = MCPClient(self.function.url)
        self.addCleanup(client.close)
        return client

    def test_session(self):
        client = self.client()
        result, records = client.initialize()
        self.assertEqual(result["serverInfo"]["name"], "sebs-mcp")
        self.assertEqual(records[1]["phase"], "notifications/initialized")
        # The handshake is the first request this fresh "container" sees.
        self.assertTrue(records[0]["is_cold"])

        tools, _ = client.list_tools()
        self.assertEqual(tools[0]["name"], "sleep")
        self.assertIn("sleep", tools[0]["inputSchema"]["properties"])

        result, record = client.call_tool("sleep", {"sleep": 0.05})
        self.assertAlmostEqual(result["structuredContent"]["result"], 0.05, delta=0.03)
        self.assertGreaterEqual(record["exec_us"], 50_000)
        # initialize already ran in this "container", so the tool call is warm
        self.assertFalse(record["is_cold"])

    def test_first_request_is_cold(self):
        records = run_mcp(self.function.url, {"sleep": 0.01}, 2, False, None)
        self.assertEqual([r["phase"] for r in records],
                         ["initialize", "notifications/initialized", "tools/list",
                          "tools/call", "tools/call"])
        container_ids = {r["container_id"] for r in records if "container_id" in r}
        self.assertEqual(len(container_ids), 1)

    def test_unknown_tool_and_method(self):
        client = self.client()
        client.initialize()
        with self.assertRaisesRegex(RuntimeError, "Unknown tool"):
            client.call_tool("nope", {})
        with self.assertRaisesRegex(RuntimeError, "Method not found"):
            client._send("resources/list")

    def test_tool_error_is_reported_in_result(self):
        client = self.client()
        client.initialize()
        with self.assertRaisesRegex(RuntimeError, "failed"):
            client.call_tool("sleep", {"sleep": "not a number"})

    def test_plain_invocation_still_works(self):
        records = run_plain(self.function.url, {"sleep": 0.01}, 2, False)
        self.assertTrue(records[0]["is_cold"])
        self.assertFalse(records[1]["is_cold"])
        self.assertGreaterEqual(records[1]["exec_us"], 10_000)


class DynamicHtmlOverMCP(unittest.TestCase):
    def test_render(self):
        function = FakeLambda("100.webapps/110.dynamic-html")
        try:
            client = MCPClient(function.url)
            self.addCleanup(client.close)
            client.initialize()
            tools, _ = client.list_tools()
            self.assertEqual(tools[0]["name"], "render_html")
            result, _ = client.call_tool("render_html", {"username": "ada", "random_len": 5})
            html = result["structuredContent"]["result"]
            self.assertIn("Welcome ada!", html)
            self.assertEqual(html.count("<li>"), 5)
            self.assertEqual(json.loads(result["content"][0]["text"])["result"], html)
        finally:
            function.stop()


if __name__ == "__main__":
    unittest.main()
