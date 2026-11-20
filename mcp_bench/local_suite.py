"""Warm and cold MCP-vs-plain measurements on the SeBS local (Docker) platform.

For each benchmark: deploy it with `sebs local start`, then

- warm: S sessions of C calls each over MCP (a new connection and handshake per
  session), and S connections of C plain calls each, alternating MCP and plain;
- cold: K samples per mode; before each sample the function container is
  replaced (`sebs local stop` + `start`, as SeBS's own cold-start enforcement
  does), so the first request reaches a fresh server process.

Every request becomes one JSON line in <out>/<benchmark>.jsonl, tagged with
mode (mcp/plain), condition (warm/cold), sample and position in the sample.

Local cold starts begin after the container is up: SeBS waits until the
server answers before returning, so container creation is not included.

Needs Docker, the SeBS venv in serverless-benchmarks/.venv, the rebuilt local
run image, object storage (`sebs storage start object ...`) and the mock
upstream, e.g.:

    python -m mcp_bench.local_suite --storage results/local/storage.json \
        --upstream http://172.17.0.1:8080 --out results/local/run1
"""

import argparse
import json
import os
import subprocess
import sys
import time

from mcp_bench.client import run_mcp, run_plain

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEBS_DIR = os.path.join(ROOT, "serverless-benchmarks")
SEBS = os.path.join(SEBS_DIR, ".venv", "bin", "sebs")

# benchmark, SeBS input size, argument overrides (None: use SeBS's input)
BENCHMARKS = [
    ("010.sleep", "test", {"sleep": 0.05}),  # SeBS sizes are 1/100/1000 s; 50 ms stands in for a light tool
    ("110.dynamic-html", "small", None),
    ("610.api-proxy", "small", None),
    ("620.fetch-markdown", "small", None),
]


class LocalFunction:
    """One SeBS local deployment of a benchmark, restartable for cold starts."""

    def __init__(self, benchmark, size, args, variant="default"):
        self.benchmark, self.size, self.args, self.variant = benchmark, size, args, variant
        suffix = "" if variant == "default" else f"@{variant}"
        self.state = os.path.join(args.out, f"{benchmark}{suffix}.deployment.json")
        self.url = None
        self.input = None

    def _sebs(self, *cmd):
        env = dict(os.environ, SEBS_MOCK_UPSTREAM=self.args.upstream)
        env.setdefault("DOCKER_HOST", "unix:///var/run/docker.sock")
        log = os.path.join(self.args.out, "sebs.log")
        with open(log, "a") as f:
            subprocess.run([SEBS, *cmd], cwd=SEBS_DIR, env=env, check=True, stdout=f, stderr=subprocess.STDOUT)

    def start(self):
        self._sebs(
            "local", "start", self.benchmark, self.size, os.path.abspath(self.state),
            "--config", os.path.join(ROOT, "configs", "sebs-local.json"),
            "--storage-configuration", os.path.abspath(self.args.storage),
            "--deployments", "1", "--remove-containers", "--architecture", "x64",
            "--language-variant", self.variant,
            "--output-dir", os.path.abspath(self.args.out),
            "--cache", os.path.abspath(os.path.join(self.args.out, "cache")),
        )
        with open(self.state) as f:
            deployment = json.load(f)
        self.url = "http://" + deployment["functions"][0]["url"]
        self.input = deployment["inputs"][0]

    def stop(self):
        self._sebs("local", "stop", os.path.abspath(self.state))

    def restart(self):
        self.stop()
        self.start()


def measure(func, mode, calls):
    if mode == "mcp":
        return run_mcp(func.url + "/mcp", func.arguments, calls, False, None)
    return run_plain(func.url + "/", func.arguments, calls, False)


def run_benchmark(benchmark, size, overrides, args):
    func = LocalFunction(benchmark, size, args)
    out = open(os.path.join(args.out, f"{benchmark}.jsonl"), "w")

    def record(records, mode, condition, sample):
        for position, r in enumerate(records):
            r.update(benchmark=benchmark, mode=mode, condition=condition, sample=sample, position=position)
            out.write(json.dumps(r) + "\n")
        out.flush()

    print(f"[{benchmark}] deploying", file=sys.stderr)
    func.start()
    func.arguments = overrides if overrides is not None else func.input
    try:
        # Warm-up, discarded: the first requests import the function and open the upstream connection.
        measure(func, "plain", 2)
        measure(func, "mcp", 2)

        for sample in range(args.warm_sessions):
            for mode in ("mcp", "plain"):
                record(measure(func, mode, args.calls), mode, "warm", sample)
        print(f"[{benchmark}] warm done", file=sys.stderr)

        for sample in range(args.cold_samples):
            for mode in ("mcp", "plain"):
                func.restart()
                record(measure(func, mode, args.cold_calls), mode, "cold", sample)
        print(f"[{benchmark}] cold done", file=sys.stderr)
    finally:
        func.stop()
        out.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--storage", required=True, help="output of `sebs storage start object ...`")
    parser.add_argument("--upstream", required=True, help="mock upstream URL as seen from the functions")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--benchmarks", nargs="*", help="subset of: " + " ".join(b for b, _, _ in BENCHMARKS))
    parser.add_argument("--warm-sessions", type=int, default=20)
    parser.add_argument("--calls", type=int, default=5, help="calls per warm session")
    parser.add_argument("--cold-samples", type=int, default=15)
    parser.add_argument("--cold-calls", type=int, default=3, help="calls per cold session")
    args = parser.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "params.json"), "w") as f:
        json.dump(dict(vars(args), started=time.strftime("%Y-%m-%dT%H:%M:%S")), f, indent=1)
    for benchmark, size, overrides in BENCHMARKS:
        if not args.benchmarks or benchmark in args.benchmarks:
            run_benchmark(benchmark, size, overrides, args)


if __name__ == "__main__":
    main()
