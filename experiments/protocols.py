"""MCP session start per protocol revision: what a client pays before its first tool result.

For each server (benchmark + language variant) and each client protocol mode
(see mcp_bench.client: legacy = handshake, modern = 2026-07-28 pinned, auto = the
SDK client's default, discover then fall back), open sessions and record every
request up to and including the first tools/call:

- warm: a fresh session (new connection) on an instance that is already up;
- cold: a fresh session right after the instance was replaced (forced cold start).

Per session the analysis gets the request count and the time to the first result
(sum of client times of all requests up to and including the first tools/call).
On local the round trips are nearly free, so this mainly checks the pipeline; the
numbers that matter come from a cloud run, where every request is a network round trip.

One JSON line per request in <out>/<server>.jsonl, tagged with protocol, condition,
session and position.

    python experiments/protocols.py --storage results/local/storage.json \
        --upstream http://172.17.0.1:8080 --out results/local/protocols
"""

import argparse
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mcp_bench.client import PROTOCOLS, MCPClient  # noqa: E402
from mcp_bench.local_suite import LocalFunction  # noqa: E402

# benchmark, language variant, SeBS input size, argument overrides
SERVERS = [
    ("010.sleep", "default", "test", {"sleep": 0.05}),
    ("610.api-proxy", "default", "small", {"latency_ms": 50, "size": 4096}),
    ("610.api-proxy", "sdk", "small", {"latency_ms": 50, "size": 4096}),
]


def session(url, protocol, arguments):
    """One fresh session up to the first tool result; returns its request records."""
    client = MCPClient(url, protocol=protocol)
    try:
        records = client.connect()
        tools, record = client.list_tools()
        records.append(record)
        _, record = client.call_tool(tools[0]["name"], arguments)
        records.append(record)
    finally:
        client.close()
    return records


def run_server(benchmark, variant, size, overrides, args, out):
    func = LocalFunction(benchmark, size, args, variant)
    func.start()
    arguments = dict(func.input, **(overrides or {}))
    try:
        session(func.url + "/mcp", "legacy", arguments)  # warm-up, discarded
        for condition, count in (("warm", args.warm), ("cold", args.cold)):
            for i in range(count):
                for protocol in args.protocols:  # interleaved, so drift hits all modes alike
                    if condition == "cold":
                        func.restart()
                    for position, r in enumerate(session(func.url + "/mcp", protocol, arguments)):
                        r.update(benchmark=benchmark, variant=variant, protocol=protocol, condition=condition,
                                 session=i, position=position)
                        out.write(json.dumps(r) + "\n")
                    out.flush()
    finally:
        func.stop()


def summarize(path):
    sessions = {}
    for line in open(path):
        r = json.loads(line)
        sessions.setdefault((r["protocol"], r["condition"], r["session"]), []).append(r)
    rows = {}
    for (protocol, condition, _), records in sessions.items():
        rows.setdefault((protocol, condition), []).append(
            (len(records), sum(r["client_us"] for r in records) / 1e3))
    for (protocol, condition), values in sorted(rows.items()):
        print(f"  {protocol:7s} {condition:5s} requests={values[0][0]}  "
              f"time to first result: median {statistics.median(v[1] for v in values):7.1f} ms (n={len(values)})")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--storage", required=True, help="output of `sebs storage start object ...`")
    parser.add_argument("--upstream", required=True, help="mock upstream URL as seen from the functions")
    parser.add_argument("--out", required=True)
    parser.add_argument("--protocols", nargs="*", default=list(PROTOCOLS), choices=PROTOCOLS)
    parser.add_argument("--warm", type=int, default=20, help="warm sessions per protocol")
    parser.add_argument("--cold", type=int, default=5, help="cold sessions per protocol")
    args = parser.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    for benchmark, variant, size, overrides in SERVERS:
        name = benchmark + ("" if variant == "default" else f"@{variant}")
        path = os.path.join(args.out, f"{name}.jsonl")
        print(f"[{name}]", file=sys.stderr)
        with open(path, "w") as out:
            run_server(benchmark, variant, size, overrides, args, out)
        summarize(path)


if __name__ == "__main__":
    main()
