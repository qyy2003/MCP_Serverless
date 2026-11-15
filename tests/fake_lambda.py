"""Serve a SeBS AWS Python package behind a local HTTP endpoint that mimics a Lambda Function URL.

The package is laid out as SeBS deploys it (handler.py at the top, the benchmark
and the remaining wrappers in function/), and each request is turned into a
Function URL event for the real wrapper's handler(event, context). The process
plays the role of one Lambda container: its first request is the cold start.

    python tests/fake_lambda.py <benchmark-dir> <port>
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEBS = os.path.join(ROOT, "serverless-benchmarks")
WRAPPERS = os.path.join(SEBS, "benchmarks", "wrappers")


def package(benchmark_dir: str) -> str:
    """Build the code package like Benchmark.build + AWS.package_code, without dependencies."""
    directory = tempfile.mkdtemp(prefix="sebs-package-")
    function_dir = os.path.join(directory, "function")
    shutil.copytree(os.path.join(benchmark_dir, "python"), function_dir)
    shutil.copy2(os.path.join(benchmark_dir, "mcp.json"), function_dir)
    with open(os.path.join(SEBS, "configs", "systems.json")) as f:
        files = json.load(f)["aws"]["languages"]["python"]["deployment"]["files"]
    for file in files:
        source = os.path.join(WRAPPERS, "aws", "python", file)
        target = directory if file == "handler.py" else function_dir
        shutil.copy2(source, os.path.join(target, os.path.basename(file)))
    return directory


class Context:
    def __init__(self):
        self.aws_request_id = str(uuid.uuid4())


def serve(benchmark_dir: str, port: int):
    directory = package(benchmark_dir)
    # Each Lambda instance has its own /tmp, where the wrapper keeps its cold-start
    # marker. Point the marker at a directory private to this fake container.
    handler_path = os.path.join(directory, "handler.py")
    with open(handler_path) as f:
        source = f.read()
    marker = "os.path.join('/tmp', 'cold_run')"
    assert marker in source, "cold-start marker not found in the AWS wrapper"
    private_tmp = tempfile.mkdtemp(prefix="sebs-tmp-")
    with open(handler_path, "w") as f:
        f.write(source.replace(marker, repr(os.path.join(private_tmp, "cold_run"))))
    sys.path.insert(0, directory)
    import handler

    # A Lambda instance handles one request at a time; concurrent requests queue here
    # (on Lambda they would start more instances).
    instance = threading.Lock()

    class FunctionURL(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        # Headers and body go out in separate writes; without this, Nagle + delayed ACK add ~40 ms.
        disable_nagle_algorithm = True

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
            with instance:
                ret = handler.handler({"body": body, "isBase64Encoded": False}, Context())
            # Function URLs return the handler's statusCode/headers/body as the HTTP response.
            payload = ret.get("body", "").encode()
            self.send_response(ret.get("statusCode", 200))
            for key, value in ret.get("headers", {"Content-Type": "application/json"}).items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    print(f"serving {benchmark_dir} from {directory} on port {port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), FunctionURL).serve_forever()


if __name__ == "__main__":
    serve(sys.argv[1], int(sys.argv[2]))
