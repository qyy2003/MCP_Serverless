"""MCP routing in the GCP and Azure wrappers: stdlib shim and SDK variant, every protocol revision.

The fake instances (tests/fake_cloud.py) run the platforms' real wrappers: GCP under
Google's functions-framework, Azure with azure.functions request objects. They need an
interpreter with mcp==2.3.0, functions-framework and azure-functions; point
SEBS_SDK_PYTHON at one, the tests are skipped otherwise:

    uv venv -p 3.11 /tmp/sdk && uv pip install -p /tmp/sdk/bin/python mcp==2.3.0 functions-framework azure-functions
    SEBS_SDK_PYTHON=/tmp/sdk/bin/python python -m unittest tests.test_mcp_platforms

Requires the SeBS patch to be applied (scripts/sebs-patch.sh apply).
"""

import json
import os
import subprocess
import unittest

from mcp_bench.client import run_mcp, run_plain
from tests.test_mcp_e2e import FakeLambda
from tests.test_mcp_sdk import SDK_CLIENT
from tests.test_mcp_tools import Upstream

SDK_PYTHON = os.environ.get("SEBS_SDK_PYTHON")


def has_platform_libraries() -> bool:
    if not SDK_PYTHON:
        return False
    check = "import mcp, functions_framework, azure.functions"
    return subprocess.run([SDK_PYTHON, "-c", check], capture_output=True).returncode == 0


AVAILABLE = has_platform_libraries()
SKIP_REASON = "set SEBS_SDK_PYTHON to an interpreter with mcp==2.3.0, functions-framework and azure-functions"
SLEEP = "000.microbenchmarks/010.sleep"
API_PROXY = "600.mcp/610.api-proxy"


@unittest.skipUnless(AVAILABLE, SKIP_REASON)
class PlatformRouting(unittest.TestCase):
    platform = None

    @classmethod
    def setUpClass(cls):
        cls.upstream = Upstream()
        cls.shim = FakeLambda(SLEEP, "default", SDK_PYTHON, cls.platform)
        cls.sdk = FakeLambda(API_PROXY, "sdk", SDK_PYTHON, cls.platform)
        cls.proxy_args = {"upstream": cls.upstream.url, "latency_ms": 20, "size": 2048, "seed": 1, "limit": 5}

    @classmethod
    def tearDownClass(cls):
        cls.shim.stop()
        cls.sdk.stop()
        cls.upstream.stop()

    def test_1_shim_first_request_is_cold(self):
        # Runs first (name order) on a fresh instance: the handshake meets the cold start.
        records = run_mcp(self.shim.url, {"sleep": 0.01}, 1, False, None)
        self.assertEqual([r["phase"] for r in records],
                         ["initialize", "notifications/initialized", "tools/list", "tools/call"])
        self.assertTrue(records[0]["is_cold"])
        call = records[-1]
        self.assertFalse(call["is_cold"])
        self.assertEqual(call["container_id"], records[0]["container_id"])
        self.assertGreaterEqual(call["exec_us"], 10_000)
        for key in ("cpu_us", "child_cpu_us", "import_us"):
            self.assertIn(key, call)

    def test_shim_modern_and_auto(self):
        for protocol, phases in (("modern", ["tools/list", "tools/call"]),
                                 ("auto", ["server/discover", "tools/list", "tools/call"])):
            with self.subTest(protocol=protocol):
                records = run_mcp(self.shim.url, {"sleep": 0.01}, 1, False, None, protocol=protocol)
                self.assertEqual([r["phase"] for r in records], phases)
                self.assertGreaterEqual(records[-1]["exec_us"], 10_000)

    def test_plain_invocation_reports_cpu_and_import(self):
        records = run_plain(self.shim.url, {"sleep": 0.01}, 2, False)
        self.assertGreaterEqual(records[1]["exec_us"], 10_000)
        for key in ("cpu_us", "child_cpu_us", "import_us"):
            self.assertIn(key, records[1])

    def test_0_sdk_reports_loaded_versions_once(self):
        # Runs first (name order) on a fresh instance: its first request is the cold one.
        records = run_mcp(self.sdk.url, self.proxy_args, 1, False, None)
        self.assertEqual(records[0]["sdk_versions"]["mcp"], "2.3.0")
        self.assertEqual(set(records[0]["sdk_versions"]), {"mcp", "starlette", "anyio", "pydantic"})
        self.assertNotIn("sdk_versions", records[-1])

    def test_sdk_variant(self):
        for protocol in ("legacy", "modern", "auto"):
            with self.subTest(protocol=protocol):
                records = run_mcp(self.sdk.url, self.proxy_args, 1, False, None, protocol=protocol)
                call = records[-1]
                self.assertEqual(call["phase"], "tools/call")
                self.assertEqual(call["import_us"], 0)  # imported at startup instead
                self.assertGreater(call["init_import_us"], 0)
                self.assertGreater(call["m_upstream_wait_us"], 20_000)

    def test_sdk_client_conformance(self):
        """The official SDK client, which validates every result, works with both servers in every mode."""
        cases = ((self.shim, "sleep", {"sleep": 0.01}), (self.sdk, "search_products", self.proxy_args))
        for function, tool, args in cases:
            for mode in ("legacy", "auto", "2026-07-28"):
                with self.subTest(tool=tool, mode=mode):
                    out = subprocess.run([SDK_PYTHON, "-c", SDK_CLIENT, function.url, mode, tool, json.dumps(args)],
                                         capture_output=True, text=True, timeout=60)
                    self.assertEqual(out.returncode, 0, out.stderr[-2000:])
                    self.assertEqual(json.loads(out.stdout.strip().splitlines()[-1]),
                                     {"tools": [tool], "is_error": False, "structured": True})


class GCP(PlatformRouting):
    platform = "gcp"


class Azure(PlatformRouting):
    platform = "azure"


del PlatformRouting  # abstract: only the subclasses run

if __name__ == "__main__":
    unittest.main()
