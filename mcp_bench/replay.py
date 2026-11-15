"""Replay agent traces against MCP tools deployed on serverless platforms.

Each trace session is replayed as an agent would run it: the host connects to
its MCP servers, then for every turn it waits while the LLM "thinks" and issues
that turn's tool calls (in parallel when there are several). A call's workload
class (api_wrapper, search_fetch, ...) selects the deployed tool that serves it.

    python -m mcp_bench.replay data/traces/livemcpbench-claude-sonnet-4.jsonl \\
        --config configs/replay-local.json --sessions 10 --output results/replay.jsonl

The config maps classes to endpoints and sets the LLM timing model:

    {"endpoints": {
        "api_wrapper":  {"url": "https://.../", "tool": "search_products",
                         "arguments": {"upstream": "http://...", "latency_ms": 200, "size": 16384}},
        "search_fetch": {"url": "https://.../", "tool": "fetch",
                         "arguments": {"upstream": "http://...", "size": 200000,
                                       "max_length": "{response_chars}"}},
        "default":      {"url": "https://.../", "tool": "sleep", "arguments": {"sleep": 0.01}}},
     "llm": {"ttft_ms": 400, "prefill_tokens_per_s": 20000, "decode_tokens_per_s": 60,
             "chars_per_token": 4}}

Classes without an endpoint use "default", or are skipped if there is none.
Argument values "{response_chars}" and "{arguments_chars}" are replaced with the
recorded call's sizes. Recorded runs have no timestamps, so the LLM time of a
turn is estimated: ttft + context tokens / prefill speed + output tokens / decode speed.
"""

import argparse
import json
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from mcp_bench.client import MCPClient
from mcp_bench.traces import load

DEFAULT_LLM = {"ttft_ms": 400, "prefill_tokens_per_s": 20000, "decode_tokens_per_s": 60,
               "chars_per_token": 4}
GAP_BUCKETS_S = [(0, 1), (1, 10), (10, 60), (60, 300), (300, 900), (900, float("inf"))]


def think_ms(turn: dict, llm: dict) -> float:
    context_tokens = turn["context_chars"] / llm["chars_per_token"]
    output_tokens = turn["output_chars"] / llm["chars_per_token"]
    return (llm["ttft_ms"] + 1000 * context_tokens / llm["prefill_tokens_per_s"]
            + 1000 * output_tokens / llm["decode_tokens_per_s"])


def fill_arguments(template: dict, call: dict) -> dict:
    values = {"{response_chars}": call.get("response_chars", 0),
              "{arguments_chars}": call.get("arguments_chars", 0)}
    return {k: values.get(v, v) if isinstance(v, str) else v for k, v in template.items()}


class Recorder:
    """Thread-safe record sink; also tracks when each endpoint last finished a call."""

    def __init__(self, start: float):
        self.start = start
        self.records = []
        self.last_end = {}
        self.lock = threading.Lock()

    def now_ms(self) -> float:
        return (time.monotonic() - self.start) * 1000

    def add(self, record: dict):
        with self.lock:
            self.records.append(record)

    def idle_gap_ms(self, endpoint: str, begin_ms: float):
        with self.lock:
            last = self.last_end.get(endpoint)
        return None if last is None else max(0.0, begin_ms - last)

    def finished(self, endpoint: str, end_ms: float):
        with self.lock:
            self.last_end[endpoint] = max(end_ms, self.last_end.get(endpoint, 0))


class Session:
    """One agent session: an MCP client per endpoint, plus extra ones for parallel calls."""

    def __init__(self, trace: dict, endpoints: dict, recorder: Recorder):
        self.trace = trace
        self.endpoints = endpoints
        self.recorder = recorder
        self.idle = {}
        self.lock = threading.Lock()
        self.init_ms = 0.0

    def endpoint_for(self, call: dict):
        name = call["class"] if call["class"] in self.endpoints else "default"
        return name if name in self.endpoints else None

    def acquire(self, name: str) -> MCPClient:
        with self.lock:
            if self.idle.get(name):
                return self.idle[name].pop()
        client = MCPClient(self.endpoints[name]["url"])
        begin = self.recorder.now_ms()
        _, records = client.initialize()
        self.init_ms += self.recorder.now_ms() - begin
        for r in records:
            self.recorder.add(dict(r, type="init", session=self.trace["session"], endpoint=name))
        return client

    def release(self, name: str, client: MCPClient):
        with self.lock:
            self.idle.setdefault(name, []).append(client)

    def close(self):
        for clients in self.idle.values():
            for client in clients:
                client.close()

    def call(self, turn_index: int, index: int, call: dict, think: float):
        name = self.endpoint_for(call)
        record = {"type": "call", "session": self.trace["session"], "turn": turn_index,
                  "index": index, "class": call["class"], "server": call["server"],
                  "tool": call["tool"], "endpoint": name, "think_ms": round(think, 1)}
        if name is None:
            record["skipped"] = True
            self.recorder.add(record)
            return 0.0
        endpoint = self.endpoints[name]
        client = self.acquire(name)
        begin = self.recorder.now_ms()
        record["t_start_ms"] = round(begin, 1)
        gap = self.recorder.idle_gap_ms(endpoint["url"], begin)
        record["idle_gap_ms"] = None if gap is None else round(gap, 1)
        try:
            _, measured = client.call_tool(endpoint["tool"], fill_arguments(endpoint.get("arguments", {}), call))
            record.update({k: v for k, v in measured.items() if k != "phase"})
        except Exception as e:
            record["error"] = f"{type(e).__name__}: {e}"
            client.close()
        end = self.recorder.now_ms()
        self.recorder.finished(endpoint["url"], end)
        self.release(name, client)
        self.recorder.add(record)
        return end - begin

    def run(self, llm: dict, time_scale: float, eager_init: bool):
        begin = self.recorder.now_ms()
        if eager_init:
            # Hosts connect to their configured servers when the session starts.
            used = {self.endpoint_for(c) for t in self.trace["turns"] for c in t["calls"]} - {None}
            for name in sorted(used):
                self.release(name, self.acquire(name))
        think_total = tools_total = 0.0
        with ThreadPoolExecutor(max_workers=8) as pool:
            for turn_index, turn in enumerate(self.trace["turns"]):
                think = think_ms(turn, llm) * time_scale
                time.sleep(think / 1000)
                think_total += think
                turn_begin = self.recorder.now_ms()
                futures = [pool.submit(self.call, turn_index, i, c, think)
                           for i, c in enumerate(turn["calls"])]
                for f in futures:
                    f.result()
                tools_total += self.recorder.now_ms() - turn_begin
        self.close()
        self.recorder.add({
            "type": "session", "session": self.trace["session"],
            "wall_ms": round(self.recorder.now_ms() - begin, 1), "think_ms": round(think_total, 1),
            "tools_ms": round(tools_total, 1), "init_ms": round(self.init_ms, 1),
            "turns": len(self.trace["turns"]),
        })


def replay(traces: list, config: dict, concurrency: int = 1, arrival_interval_s: float = 0,
           time_scale: float = 1.0, eager_init: bool = True) -> list:
    llm = dict(DEFAULT_LLM, **config.get("llm", {}))
    recorder = Recorder(time.monotonic())

    def run(index_trace):
        index, trace = index_trace
        delay = index * arrival_interval_s - (time.monotonic() - recorder.start)
        if delay > 0:
            time.sleep(delay)
        Session(trace, config["endpoints"], recorder).run(llm, time_scale, eager_init)

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(run, enumerate(traces)))
    return recorder.records


def _percentile(values: list, q: float):
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))] if values else None


def summarize(records: list) -> dict:
    calls = [r for r in records if r["type"] == "call" and not r.get("skipped")]
    ok = [r for r in calls if "error" not in r]
    sessions = [r for r in records if r["type"] == "session"]
    summary = {
        "sessions": len(sessions),
        "calls": len(calls),
        "errors": len(calls) - len(ok),
        "skipped": sum(1 for r in records if r.get("skipped")),
        "cold_calls": sum(1 for r in ok if r.get("is_cold")),
        # Cold starts absorbed by the session handshake, before any tool call.
        "cold_inits": sum(1 for r in records if r["type"] == "init" and r.get("is_cold")),
        "containers": len({(r["endpoint"], r.get("container_id")) for r in ok if r.get("container_id")}),
    }
    if sessions:
        shares = [s["tools_ms"] / s["wall_ms"] for s in sessions if s["wall_ms"]]
        summary["tool_share_of_session_median"] = round(statistics.median(shares), 3)
        summary["session_wall_s_median"] = round(statistics.median(s["wall_ms"] for s in sessions) / 1000, 1)
    by_class = {}
    for r in ok:
        by_class.setdefault(r["class"], []).append(r)
    summary["by_class"] = {
        c: {"calls": len(rs), "cold": sum(1 for r in rs if r.get("is_cold")),
            "client_ms_median": round(statistics.median(r["client_us"] for r in rs) / 1000, 1),
            "client_ms_p95": round(_percentile([r["client_us"] for r in rs], 0.95) / 1000, 1)}
        for c, rs in sorted(by_class.items())
    }
    gaps = {"first call": [r for r in ok if r.get("idle_gap_ms") is None]}
    for low, high in GAP_BUCKETS_S:
        gaps[f"{low}-{high}s"] = [r for r in ok if r.get("idle_gap_ms") is not None
                                  and low <= r["idle_gap_ms"] / 1000 < high]
    summary["cold_rate_by_idle_gap"] = {
        k: {"calls": len(rs), "cold": sum(1 for r in rs if r.get("is_cold"))}
        for k, rs in gaps.items() if rs
    }
    return summary


def timeline(traces: list, llm: dict) -> dict:
    """Modeled LLM time and idle gaps per tool class, without calling any tools.

    A gap is the LLM time between two consecutive calls of the same class in a
    session: how long that tool's instance sits idle, if nothing else uses it.
    """
    llm = dict(DEFAULT_LLM, **llm)
    thinks, durations, gaps = [], [], {}
    for trace in traces:
        clock, last_call, total = 0.0, {}, 0.0
        for turn in trace["turns"]:
            think = think_ms(turn, llm)
            thinks.append(think)
            clock += think
            total += think
            for call in turn["calls"]:
                if call["class"] in last_call:
                    gaps.setdefault(call["class"], []).append(clock - last_call[call["class"]])
                last_call[call["class"]] = clock
        durations.append(total)

    def stats(values):
        if not values:
            return {"n": 0}
        return {"n": len(values), "p50_s": round(_percentile(values, 0.5) / 1000, 1),
                "p90_s": round(_percentile(values, 0.9) / 1000, 1),
                "max_s": round(max(values) / 1000, 1)}

    all_gaps = [g for v in gaps.values() for g in v]
    return {
        "llm_ms_per_turn": stats(thinks),
        "llm_s_per_session": stats(durations),
        "same_class_gap": dict({"all": stats(all_gaps)},
                               **{c: stats(v) for c, v in sorted(gaps.items())}),
        "gaps_over_60s": sum(1 for g in all_gaps if g > 60_000),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("trace", help="Trace file (JSON lines, see mcp_bench/traces.py)")
    parser.add_argument("--config", required=True, help="Endpoint and LLM-model config (JSON)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Only report modeled LLM time and idle gaps; call nothing")
    parser.add_argument("--sessions", type=int, help="Replay only the first N sessions")
    parser.add_argument("--concurrency", type=int, default=1, help="Sessions running at once")
    parser.add_argument("--arrival-interval", type=float, default=0,
                        help="Seconds between session starts (open-loop arrivals)")
    parser.add_argument("--time-scale", type=float, default=1.0,
                        help="Multiply estimated LLM think times (0 replays back to back)")
    parser.add_argument("--lazy-init", action="store_true",
                        help="Connect to a server at its first call instead of at session start")
    parser.add_argument("--output", help="Write all records as JSON lines")
    args = parser.parse_args(argv)

    traces = load(args.trace)[: args.sessions]
    with open(args.config) as f:
        config = json.load(f)
    if args.dry_run:
        json.dump(timeline(traces, config.get("llm", {})), sys.stdout, indent=2)
        print()
        return
    records = replay(traces, config, args.concurrency, args.arrival_interval,
                     args.time_scale, not args.lazy_init)
    if args.output:
        with open(args.output, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
    json.dump(summarize(records), sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
