"""MCP protocol revisions: handshake era (legacy), 2026-07-28 (modern), and auto (discover, else handshake).

Requires the SeBS patch to be applied (scripts/sebs-patch.sh apply).

    python -m unittest tests.test_mcp_protocols
"""

import importlib.util
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mcp_bench.client import MCPClient, run_mcp
from tests.test_mcp_e2e import FakeLambda

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIM = os.path.join(ROOT, "serverless-benchmarks", "benchmarks", "wrappers", "mcp", "python", "mcp_shim.py")


class SleepOverModernMCP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.function = FakeLambda("000.microbenchmarks/010.sleep")

    @classmethod
    def tearDownClass(cls):
        cls.function.stop()

    def test_modern_session_has_no_handshake(self):
        records = run_mcp(self.function.url, {"sleep": 0.01}, 2, False, None, protocol="modern")
        self.assertEqual([r["phase"] for r in records], ["tools/list", "tools/call", "tools/call"])
        self.assertGreaterEqual(records[1]["exec_us"], 10_000)

    def test_auto_discovers_and_skips_handshake(self):
        records = run_mcp(self.function.url, {"sleep": 0.01}, 1, False, None, protocol="auto")
        self.assertEqual([r["phase"] for r in records], ["server/discover", "tools/list", "tools/call"])
        self.assertNotIn("error", records[0])

    def test_modern_results_carry_required_fields(self):
        client = MCPClient(self.function.url, protocol="modern")
        self.addCleanup(client.close)
        result, _ = client.discover()
        self.assertEqual(result["supportedVersions"], ["2026-07-28"])
        self.assertEqual(result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"], "sebs-mcp")
        for key in ("resultType", "cacheScope", "ttlMs"):
            self.assertIn(key, result)
        listed, _ = client._send("tools/list")
        self.assertEqual((listed["resultType"], listed["cacheScope"], listed["ttlMs"]), ("complete", "private", 0))
        called, _ = client.call_tool("sleep", {"sleep": 0.01})
        self.assertEqual(called["resultType"], "complete")

    def test_handshake_methods_are_gone_in_modern(self):
        client = MCPClient(self.function.url, protocol="modern")
        self.addCleanup(client.close)
        for method in ("initialize", "ping"):
            with self.assertRaisesRegex(RuntimeError, "-32601"):
                client._send(method, {})

    def test_unsupported_modern_version(self):
        client = MCPClient(self.function.url, protocol="modern")
        self.addCleanup(client.close)
        client.protocol_version = "2099-01-01"
        with self.assertRaisesRegex(RuntimeError, "-32022"):
            client._send("tools/list")

    def test_legacy_responses_unchanged(self):
        """Handshake-era results must not gain the 2026-07-28 fields (earlier measurements stay comparable)."""
        client = MCPClient(self.function.url)
        self.addCleanup(client.close)
        client.initialize()
        listed, _ = client._send("tools/list")
        called, _ = client.call_tool("sleep", {"sleep": 0.01})
        for result in (listed, called):
            self.assertNotIn("resultType", result)
            self.assertNotIn("cacheScope", result)


def load_old_shim():
    """The shim as deployed before 2026-07-28 support: it ignores the version in params._meta."""
    spec = importlib.util.spec_from_file_location("old_mcp_shim", SHIM)
    shim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shim)
    shim.PROTOCOL_VERSION_META = "not-a-key"  # never matches: every request takes the handshake-era path
    shim._tool = {"name": "echo", "description": "Echo.", "inputSchema": {"type": "object"}}
    return shim


class AutoAgainstOldServer(unittest.TestCase):
    """A new client meeting a server that only speaks the handshake revisions falls back to initialize."""

    def setUp(self):
        shim = load_old_shim()

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):
                message = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                response = shim.handle(message, lambda args: (args, {"is_cold": False}))
                body = b"" if response is None else json.dumps(response).encode()
                self.send_response(202 if response is None else 200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/"

    def test_fallback(self):
        records = run_mcp(self.url, {"x": 1}, 1, False, None, protocol="auto")
        self.assertEqual([r["phase"] for r in records],
                         ["server/discover", "initialize", "notifications/initialized", "tools/list", "tools/call"])
        self.assertEqual(records[0]["error"], -32601)


if __name__ == "__main__":
    unittest.main()
