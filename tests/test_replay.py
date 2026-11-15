"""Trace conversion and replay against tools behind fake Function URLs.

Requires the SeBS patch to be applied (scripts/sebs-patch.sh apply).

    python -m unittest tests.test_replay
"""

import json
import unittest

from mcp_bench import replay, traces
from tests.test_mcp_e2e import FakeLambda
from tests.test_mcp_tools import Upstream


def tool_call(call_id, name, arguments):
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)}}


LIVEMCPBENCH_RUN = [{
    "task_id": "t1",
    "category": "work",
    "messages": [
        {"role": "system", "content": "s" * 100},
        {"role": "user", "content": "u" * 50},
        {"role": "assistant", "content": "a" * 20,
         "tool_calls": [tool_call("c1", "route", {"query": "find tools"})]},
        {"role": "tool", "tool_call_id": "c1", "content": "r" * 300},
        {"role": "assistant", "content": "",
         "tool_calls": [
             tool_call("c2", "execute-tool", {"server_name": "Asset Price MCP", "tool_name": "get_price", "params": {}}),
             tool_call("c3", "execute-tool", {"server_name": "fetch", "tool_name": "fetch", "params": {"url": "x"}}),
         ]},
        {"role": "tool", "tool_call_id": "c2", "content": "p" * 40},
        {"role": "tool", "tool_call_id": "c3", "content": "f" * 4000},
        {"role": "assistant", "content": "done"},
    ],
}]


class Conversion(unittest.TestCase):
    def test_livemcpbench(self):
        (session,) = traces.from_livemcpbench(LIVEMCPBENCH_RUN, "test")
        self.assertEqual(session["session"], "t1")
        turns = session["turns"]
        self.assertEqual([len(t["calls"]) for t in turns], [1, 2, 0])
        route, = turns[0]["calls"]
        self.assertEqual((route["tool"], route["class"], route["response_chars"]), ("route", "memory_rag", 300))
        price, fetch = turns[1]["calls"]
        # Server names are matched to the census regardless of case and separators.
        self.assertEqual(price["class"], "api_wrapper")
        self.assertEqual((fetch["class"], fetch["response_chars"]), ("search_fetch", 4000))
        # Context counts everything the model read before the turn, including tool results.
        self.assertEqual(turns[0]["context_chars"], 150)
        self.assertEqual(turns[1]["context_chars"], 150 + 20 + len(json.dumps({"query": "find tools"})) + 300)
        self.assertEqual(turns[0]["output_chars"], 20 + len(json.dumps({"query": "find tools"})))

    def test_think_time_model(self):
        llm = {"ttft_ms": 400, "prefill_tokens_per_s": 20000, "decode_tokens_per_s": 50, "chars_per_token": 4}
        self.assertAlmostEqual(replay.think_ms({"context_chars": 80000, "output_chars": 400}, llm),
                               400 + 1000 + 2000)

    def test_timeline(self):
        sessions = traces.from_livemcpbench(LIVEMCPBENCH_RUN, "test")
        llm = {"ttft_ms": 1000, "prefill_tokens_per_s": 1e12, "decode_tokens_per_s": 1e12}
        stats = replay.timeline(sessions, llm)
        self.assertEqual(stats["llm_ms_per_turn"]["n"], 3)
        self.assertEqual(stats["llm_s_per_session"]["p50_s"], 3.0)
        # Each class is called once, so there are no same-class gaps.
        self.assertNotIn("api_wrapper", stats["same_class_gap"])

    def test_fill_arguments(self):
        filled = replay.fill_arguments({"max_length": "{response_chars}", "size": 10, "u": "x"},
                                       {"response_chars": 123})
        self.assertEqual(filled, {"max_length": 123, "size": 10, "u": "x"})


class Replay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream = Upstream()
        cls.api = FakeLambda("600.mcp/610.api-proxy")
        cls.fetch = FakeLambda("600.mcp/620.fetch-markdown")
        cls.sleep = FakeLambda("000.microbenchmarks/010.sleep")
        cls.config = {
            "endpoints": {
                "api_wrapper": {"url": cls.api.url, "tool": "search_products",
                                "arguments": {"upstream": cls.upstream.url, "latency_ms": 5, "size": 4096}},
                "search_fetch": {"url": cls.fetch.url, "tool": "fetch",
                                 "arguments": {"upstream": cls.upstream.url, "size": 20000,
                                               "max_length": "{response_chars}"}},
                "default": {"url": cls.sleep.url, "tool": "sleep", "arguments": {"sleep": 0.001}},
            },
            "llm": {"ttft_ms": 30, "prefill_tokens_per_s": 1e9, "decode_tokens_per_s": 1e9},
        }

    @classmethod
    def tearDownClass(cls):
        for function in (cls.api, cls.fetch, cls.sleep):
            function.stop()
        cls.upstream.stop()

    def test_replay_two_sessions(self):
        sessions = traces.from_livemcpbench(LIVEMCPBENCH_RUN * 2, "test")
        sessions[1]["session"] = "t2"
        records = replay.replay(sessions, self.config, concurrency=2)
        calls = [r for r in records if r["type"] == "call"]
        self.assertEqual(len(calls), 6)
        self.assertFalse([r for r in calls if "error" in r])
        self.assertEqual({r["endpoint"] for r in calls}, {"default", "api_wrapper", "search_fetch"})
        fetches = [r for r in calls if r["class"] == "search_fetch"]
        self.assertTrue(all(r["exec_us"] > 0 for r in fetches))

        # With eager init the handshake reaches each fresh container first and absorbs
        # its cold start (at most one per container); tool calls are then warm.
        cold_inits = [r for r in records if r["type"] == "init" and r.get("is_cold")]
        self.assertEqual(len(cold_inits), len({r["endpoint"] for r in cold_inits}))
        self.assertFalse(any(r.get("is_cold") for r in calls))

        summary = replay.summarize(records)
        self.assertEqual(summary["sessions"], 2)
        self.assertEqual(summary["calls"], 6)
        self.assertGreater(summary["tool_share_of_session_median"], 0)
        session = next(r for r in records if r["type"] == "session")
        # Three turns with at least 30 ms of modeled LLM time each.
        self.assertGreaterEqual(session["think_ms"], 90)

    def test_lazy_init_and_parallel_calls(self):
        (session,) = traces.from_livemcpbench(LIVEMCPBENCH_RUN, "test")
        records = replay.replay([session], self.config, time_scale=0, eager_init=False)
        parallel = [r for r in records if r["type"] == "call" and r["turn"] == 1]
        self.assertEqual({r["class"] for r in parallel}, {"api_wrapper", "search_fetch"})
        # Both calls of the turn started before either could have finished sequentially.
        starts = sorted(r["t_start_ms"] for r in parallel)
        self.assertLess(starts[1] - starts[0], min(r["client_us"] for r in parallel) / 1000)

    def test_unmapped_class_is_skipped_without_default(self):
        config = dict(self.config, endpoints={"api_wrapper": self.config["endpoints"]["api_wrapper"]})
        (session,) = traces.from_livemcpbench(LIVEMCPBENCH_RUN, "test")
        records = replay.replay([session], config, time_scale=0)
        self.assertEqual(replay.summarize(records)["skipped"], 2)


if __name__ == "__main__":
    unittest.main()
