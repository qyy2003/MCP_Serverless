"""Characterize SeBS benchmarks and MCP tools on the same axes (the "gap" comparison).

For each benchmark configuration (benchmark, input size, optional argument
overrides), deploy it on the SeBS local platform and record per invocation:

- execution time (function-side begin/end) and client time,
- CPU time of the process (cpu_us) and of finished child processes (child_cpu_us),
- network bytes received/sent by the function container (from /proc/<pid>/net/dev
  on the host, so no code runs inside the function), and the HTTP request/response
  sizes of the invocation itself, to subtract,
- import time and cold-start penalty, from calls after a forced cold start
  (container replaced, as SeBS does),
- the code package size (the container's bind-mounted code directory).

SeBS benchmarks are invoked as SeBS does (the input posted to the function). MCP tools
are invoked over MCP (`tools/call`), in both language variants: `default` (stdlib shim)
and `sdk` (official MCP SDK, config names `<benchmark>@sdk-...`). The SDK variant can
only be reached over MCP, and the tool's own measurements don't depend on the protocol
revision, so the revision is a parameter (--protocol, default: 2026-07-28, one request
per call). A cold sample opens a new session on the fresh instance; its records hold
the session start too (`session_records`), for time to first result.

One JSON line per invocation in <out>/<config>.jsonl, plus <out>/packages.json.

Local is for developing the pipeline: storage runs on the same machine, so
SeBS's storage I/O is unrealistically fast. The numbers to report must come
from a cloud run.

    python experiments/characterize.py --storage results/local/storage-all.json \
        --upstream http://172.17.0.1:8080 --out results/local/characterize
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mcp_bench.client import MCPClient  # noqa: E402
from mcp_bench.local_suite import LocalFunction  # noqa: E402

# (benchmark, size, overrides, label). Overrides replace or update SeBS's generated input.
SEBS = [
    ("010.sleep", "test", {"sleep": 0.05}, None),
    ("110.dynamic-html", "test", None, None),
    ("110.dynamic-html", "small", None, None),
    ("120.uploader", "test", None, None),
    ("120.uploader", "small", None, None),
    ("130.crud-api", "test", None, None),
    ("130.crud-api", "small", None, None),
    ("210.thumbnailer", "test", None, None),
    ("210.thumbnailer", "small", None, None),
    ("220.video-processing", "test", None, None),
    ("220.video-processing", "small", None, None),
    ("311.compression", "test", None, None),
    ("311.compression", "small", None, None),
    ("411.image-recognition", "test", None, None),
    ("411.image-recognition", "small", None, None),
    ("501.graph-pagerank", "test", None, None),
    ("501.graph-pagerank", "small", None, None),
    ("502.graph-mst", "test", None, None),
    ("502.graph-mst", "small", None, None),
    ("503.graph-bfs", "test", None, None),
    ("503.graph-bfs", "small", None, None),
    ("504.dna-visualisation", "test", None, None),
    ("504.dna-visualisation", "small", None, None),
]

# MCP tools across their parameter ranges (upstream latency, response/page size).
MCP = [
    ("610.api-proxy", "small", {"latency_ms": lat, "size": size}, f"lat{lat}-{size // 1024}k")
    for lat in (50, 200, 1000) for size in (4096, 65536)
] + [
    ("620.fetch-markdown", "small", {"latency_ms": 200, "size": size}, f"{size // 1000}kB")
    for size in (10000, 200000, 1000000)
]
VARIANTS = ("default", "sdk")  # language variants of the MCP tools


class Counters:
    """Network byte counters of a container's eth0, read from the host."""

    def __init__(self, instance_id):
        pid = subprocess.check_output(
            ["docker", "inspect", "-f", "{{.State.Pid}}", instance_id], text=True).strip()
        self.path = f"/proc/{pid}/net/dev"

    def read(self):
        with open(self.path) as f:
            for line in f:
                if line.strip().startswith("eth0:"):
                    v = line.split(":", 1)[1].split()
                    return int(v[0]), int(v[8])
        raise RuntimeError("eth0 not found")


def invoke(func, arguments, counters):
    body = json.dumps(arguments).encode()
    rx0, tx0 = counters.read()
    begin = time.perf_counter()
    request = urllib.request.Request(func.url + "/", body, {"Content-Type": "application/json"})
    data = urllib.request.urlopen(request, timeout=600).read()
    client_us = int((time.perf_counter() - begin) * 1e6)
    time.sleep(0.05)  # let the last packets reach the counters
    rx1, tx1 = counters.read()
    out = json.loads(data)
    result = out.get("result", {})
    return {
        "client_us": client_us,
        "exec_us": int((float(out["end"]) - float(out["begin"])) * 1e6),
        "cpu_us": out.get("cpu_us"),
        "child_cpu_us": out.get("child_cpu_us"),
        "import_us": out.get("import_us"),
        "is_cold": out.get("is_cold"),
        "net_rx": rx1 - rx0,
        "net_tx": tx1 - tx0,
        "request_bytes": len(body),
        "response_bytes": len(data),
        "tool_measurement": result.get("measurement") if isinstance(result, dict) else None,
    }


class MCPInvoker:
    """tools/call over one MCP session, with the same record fields as invoke()."""

    def __init__(self, func, protocol):
        self.client = MCPClient(func.url + "/mcp", protocol=protocol)
        self.session_records = self.client.connect()
        tools, record = self.client.list_tools()
        self.session_records.append(record)
        self.tool = tools[0]["name"]

    def __call__(self, func, arguments, counters):
        rx0, tx0 = counters.read()
        result, record = self.client.call_tool(self.tool, arguments)
        time.sleep(0.05)  # let the last packets reach the counters
        rx1, tx1 = counters.read()
        return {
            "client_us": record["client_us"],
            "exec_us": record["exec_us"],
            "cpu_us": record.get("cpu_us"),
            "child_cpu_us": record.get("child_cpu_us"),
            "import_us": record.get("import_us"),
            "init_import_us": record.get("init_import_us"),
            "init_us": record.get("init_us"),
            "is_cold": record.get("is_cold"),
            "net_rx": rx1 - rx0,
            "net_tx": tx1 - tx0,
            "request_bytes": record["request_bytes"],
            "response_bytes": record["response_bytes"],
            "tool_measurement": result.get("structuredContent", {}).get("measurement"),
        }

    def close(self):
        self.client.close()


def package_size(func):
    mounts = json.loads(subprocess.check_output(
        ["docker", "inspect", "-f", "{{json .Mounts}}", func.instance_id], text=True))
    code = next(m["Source"] for m in mounts if m["Destination"] == "/function")
    return int(subprocess.check_output(["du", "-sb", code], text=True).split()[0])


def run_config(benchmark, size, overrides, label, args, packages, variant="default", via="plain"):
    tag = "" if variant == "default" else f"@{variant}"
    name = f"{benchmark}{tag}-{size}" + (f"-{label}" if label else "")
    path = os.path.join(args.out, f"{name}.jsonl")
    if os.path.exists(path) and not args.force:
        print(f"[{name}] exists, skipped", file=sys.stderr)
        return
    func = LocalFunction(benchmark, size, args, variant)
    print(f"[{name}] deploying", file=sys.stderr)
    func.start()
    arguments = dict(func.input, **overrides) if overrides else func.input
    records = []
    session = None

    def invoker():
        """Plain: post the input. MCP: a session per instance, opened on its first use."""
        nonlocal session
        if via == "plain":
            return invoke, []
        if session is None:
            session = MCPInvoker(func, args.protocol)
            return session, session.session_records
        return session, []

    try:
        func.instance_id = json.load(open(func.state))["functions"][0]["instance_id"]
        packages[benchmark + tag] = package_size(func)
        counters = Counters(func.instance_id)
        for _ in range(2):  # warm-up, discarded
            call, _ = invoker()
            call(func, arguments, counters)
        for i in range(args.warm):
            call, _ = invoker()
            records.append(dict(call(func, arguments, counters), condition="warm", sample=i))
        for i in range(args.cold):
            if session is not None:
                session.close()
                session = None
            func.restart()
            func.instance_id = json.load(open(func.state))["functions"][0]["instance_id"]
            counters = Counters(func.instance_id)
            call, opened = invoker()
            record = dict(call(func, arguments, counters), condition="cold", sample=i)
            if opened:
                record["session_records"] = opened
            records.append(record)
    except Exception as e:  # keep going with the other benchmarks; record why this one failed
        print(f"[{name}] FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        with open(os.path.join(args.out, f"{name}.failed"), "w") as f:
            f.write(f"{type(e).__name__}: {e}\n")
        return
    finally:
        if session is not None:
            session.close()
        func.stop()
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(dict(r, config=name, benchmark=benchmark, variant=variant, via=via,
                                    protocol=args.protocol if via == "mcp" else None, size=size,
                                    label=label, arguments_override=overrides)) + "\n")
    print(f"[{name}] done", file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--storage", required=True, help="output of `sebs storage start all ...`")
    parser.add_argument("--upstream", required=True, help="mock upstream URL as seen from the functions")
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", nargs="*", help="run only configs whose benchmark starts with one of these")
    parser.add_argument("--warm", type=int, default=10)
    parser.add_argument("--cold", type=int, default=5)
    parser.add_argument("--force", action="store_true", help="re-run configs that already have results")
    parser.add_argument("--protocol", choices=("legacy", "modern", "auto"), default="modern",
                        help="MCP revision for the MCP tools (default: modern, i.e. 2026-07-28)")
    parser.add_argument("--variants", nargs="*", default=list(VARIANTS), choices=VARIANTS,
                        help="language variants of the MCP tools to run")
    args = parser.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    packages_path = os.path.join(args.out, "packages.json")
    packages = json.load(open(packages_path)) if os.path.exists(packages_path) else {}
    configs = [(c, "default", "plain") for c in SEBS] + [(c, v, "mcp") for v in args.variants for c in MCP]
    for (benchmark, size, overrides, label), variant, via in configs:
        if args.only and not any(benchmark.startswith(o) for o in args.only):
            continue
        run_config(benchmark, size, overrides, label, args, packages, variant, via)
        with open(packages_path, "w") as f:
            json.dump(packages, f, indent=1)


if __name__ == "__main__":
    main()
