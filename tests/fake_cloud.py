"""Serve a SeBS Python package as GCP or Azure would, behind a local HTTP endpoint.

The package is laid out as SeBS deploys it, and the platform's real wrapper handles
each request:

- gcp: `main.py` (the wrapper) at the top, the benchmark and the other wrappers in
  `function/`, served by Google's `functions-framework`, the HTTP layer of Cloud Run
  functions (it needs to be installed in the interpreter running this script);
- azure: everything in the `handler/` package; requests are handed to `main(req, context)`
  as `azure.functions.HttpRequest` objects (needs `azure-functions`). The Functions host
  itself is not emulated.

The process plays the role of one function instance: its first request is the cold start.

    python tests/fake_cloud.py <gcp|azure> <benchmark-dir> <port> [<language-variant>]

Dependencies are not installed: for a variant that needs some (e.g. `sdk`), run this
script with an interpreter that has them.
"""

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEBS = os.path.join(ROOT, "serverless-benchmarks")
WRAPPERS = os.path.join(SEBS, "benchmarks", "wrappers")
CODE_DIR = {"gcp": "function", "azure": "handler"}  # where SeBS puts the code in the package
MARKER = "os.path.join('/tmp', 'cold_run')"


def package(platform: str, benchmark_dir: str, variant: str = "default") -> str:
    """Lay out the code like Benchmark.build + <platform>.package_code, without dependencies."""
    directory = tempfile.mkdtemp(prefix=f"sebs-{platform}-")
    code_dir = os.path.join(directory, CODE_DIR[platform])
    shutil.copytree(os.path.join(benchmark_dir, "python"), code_dir)
    if variant != "default":
        # Overlay variant, as Benchmark.copy_code applies it: the variant's files over the default ones.
        variant_dir = os.path.join(benchmark_dir, "python", variant)
        for name in os.listdir(variant_dir):
            if name.endswith(".py") or name.startswith("requirements.txt"):
                shutil.copy2(os.path.join(variant_dir, name), code_dir)
    shutil.copy2(os.path.join(benchmark_dir, "mcp.json"), code_dir)
    with open(os.path.join(SEBS, "configs", "systems.json")) as f:
        files = json.load(f)[platform]["languages"]["python"]["deployment"]["files"]
    for file in files:
        source = os.path.join(WRAPPERS, platform, "python", file)
        target = os.path.join(code_dir, os.path.basename(file))
        if platform == "gcp" and file == "handler.py":
            target = os.path.join(directory, "main.py")  # GCP.package_code renames the handler
        shutil.copy2(source, target)

    # Each instance has its own /tmp, where the wrapper keeps its cold-start marker.
    handler = os.path.join(directory, "main.py") if platform == "gcp" else os.path.join(code_dir, "handler.py")
    with open(handler) as f:
        source = f.read()
    assert MARKER in source, f"cold-start marker not found in the {platform} wrapper"
    private_tmp = tempfile.mkdtemp(prefix="sebs-tmp-")
    with open(handler, "w") as f:
        f.write(source.replace(MARKER, repr(os.path.join(private_tmp, "cold_run"))))
    return directory


def serve_gcp(directory: str, port: int):
    # The framework imports main.py from the package directory, which is also the working
    # directory (so `function` is importable), as on Cloud Run functions.
    os.chdir(directory)
    os.execvp(sys.executable, [sys.executable, "-m", "functions_framework", "--target", "handler",
                               "--source", os.path.join(directory, "main.py"),
                               "--host", "127.0.0.1", "--port", str(port)])


def serve_azure(directory: str, port: int):
    import azure.functions as func

    os.environ.setdefault("CONTAINER_NAME", "fake-azure-" + uuid.uuid4().hex[:8])
    sys.path.insert(0, directory)
    handler = importlib.import_module("handler.handler")  # the function folder is a package
    instance = threading.Lock()  # one request at a time, like one worker

    class Context:
        def __init__(self):
            self.invocation_id = str(uuid.uuid4())

    class FunctionEndpoint(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        disable_nagle_algorithm = True

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            request = func.HttpRequest("POST", f"http://127.0.0.1:{port}/api/handler",
                                       headers=dict(self.headers.items()), body=body)
            with instance:
                response = handler.main(request, Context())
            payload = response.get_body() or b""
            self.send_response(response.status_code)
            headers = dict(response.headers)
            if response.mimetype and "content-type" not in {k.lower() for k in headers}:
                headers["Content-Type"] = response.mimetype
            for key, value in headers.items():
                if key.lower() != "content-length":
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    ThreadingHTTPServer(("127.0.0.1", port), FunctionEndpoint).serve_forever()


if __name__ == "__main__":
    platform, benchmark_dir, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
    directory = package(platform, benchmark_dir, *sys.argv[4:5])
    print(f"serving {benchmark_dir} as {platform} from {directory} on port {port}", flush=True)
    (serve_gcp if platform == "gcp" else serve_azure)(directory, port)
