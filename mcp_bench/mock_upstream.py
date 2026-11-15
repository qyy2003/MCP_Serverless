"""Mock upstream service for MCP tool benchmarks.

Most MCP tools wrap a remote API or fetch a web page (see docs/server-census.md).
Benchmarking against live services gives rate limits, regional blocking and
latency we don't control, so the tools call this server instead. Each request
says how long the server should wait and how large the response should be:

    GET /api?latency_ms=200&size=8192&seed=1    JSON list of records, ~size bytes
    GET /page?latency_ms=100&size=100000        HTML article with page boilerplate, ~size bytes
    GET /health

Responses for a (size, seed) pair are deterministic. The latency is added by the
server before it responds, so the tool's measured upstream wait minus latency_ms
is the network and HTTP overhead. Run it close to the functions, e.g. on a VM in
the same region, and pass its URL to SeBS input generation:

    python -m mcp_bench.mock_upstream --port 8080
    export SEBS_MOCK_UPSTREAM=http://<host>:8080
"""

import argparse
import functools
import json
import random
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

MAX_SIZE = 16 * 1024 * 1024
WORDS = (
    "agent tool server latency request cloud function cold warm protocol session result "
    "network region memory billing invocation container runtime payload stream gateway "
    "model context data query record update index cache storage compute timeout retry"
).split()


def _sentence(rng: random.Random, words: int) -> str:
    text = " ".join(rng.choice(WORDS) for _ in range(words))
    return text[0].upper() + text[1:] + "."


@functools.lru_cache(maxsize=256)
def api_body(size: int, seed: int) -> bytes:
    """A JSON page of records, like a REST list endpoint, padded to about `size` bytes."""
    rng = random.Random(seed)
    items, length = [], 40
    while length < size:
        item = {
            "id": len(items) + 1,
            "name": " ".join(rng.choice(WORDS) for _ in range(2)).title(),
            "price": round(rng.uniform(1, 1000), 2),
            "rating": round(rng.uniform(1, 5), 1),
            "in_stock": rng.random() > 0.3,
            "tags": rng.sample(WORDS, 3),
            "updated": f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}T12:00:00Z",
            "description": _sentence(rng, rng.randint(8, 30)),
        }
        items.append(item)
        length += len(json.dumps(item)) + 2
    return json.dumps({"total": len(items), "page": 1, "items": items}).encode()


@functools.lru_cache(maxsize=256)
def page_body(size: int, seed: int) -> bytes:
    """An HTML article wrapped in the boilerplate real pages carry (nav, scripts, footer)."""
    rng = random.Random(seed)
    head = (
        "<!doctype html><html><head><meta charset='utf-8'><title>Benchmark article</title>"
        "<style>body{font-family:sans-serif}.nav{display:flex}</style>"
        "<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}</script>"
        "</head><body><header><nav class='nav'>"
        + "".join(f"<a href='/section/{w}'>{w.title()}</a>" for w in WORDS[:12])
        + "</nav></header><main><article><h1>Benchmark article</h1>"
    )
    tail = (
        "</article></main><aside><h3>Related</h3><ul>"
        + "".join(f"<li><a href='/related/{i}'>{_sentence(rng, 5)}</a></li>" for i in range(5))
        + "</ul></aside><footer><p>Footer text and links.</p></footer>"
        "<script>console.log('analytics')</script></body></html>"
    )
    parts, length, section = [head], len(head) + len(tail), 0
    while length < size:
        kind = rng.random()
        if kind < 0.1:
            section += 1
            block = f"<h2>Section {section}: {_sentence(rng, 4)}</h2>"
        elif kind < 0.2:
            block = "<ul>" + "".join(f"<li>{_sentence(rng, 8)}</li>" for _ in range(4)) + "</ul>"
        elif kind < 0.25:
            rows = "".join(
                f"<tr><td>{rng.choice(WORDS)}</td><td>{rng.randint(1, 999)}</td></tr>" for _ in range(5)
            )
            block = f"<table><tr><th>Name</th><th>Value</th></tr>{rows}</table>"
        elif kind < 0.3:
            block = f"<pre><code>{' '.join(rng.choice(WORDS) for _ in range(12))}</code></pre>"
        else:
            words = [rng.choice(WORDS) for _ in range(rng.randint(30, 90))]
            link = rng.randrange(len(words))
            words[link] = f"<a href='https://example.com/{words[link]}'>{words[link]}</a>"
            block = "<p>" + " ".join(words) + ".</p>"
        parts.append(block)
        length += len(block)
    parts.append(tail)
    return "".join(parts).encode()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    disable_nagle_algorithm = True

    def do_GET(self):
        url = urlsplit(self.path)
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        try:
            latency_ms = float(query.get("latency_ms", 0))
            size = min(int(query.get("size", 1024)), MAX_SIZE)
            seed = int(query.get("seed", 0))
        except ValueError:
            return self._send(400, b'{"error": "invalid parameters"}', "application/json")

        if url.path == "/health":
            return self._send(200, b'{"status": "ok"}', "application/json")
        if url.path == "/api":
            body, content_type = api_body(size, seed), "application/json"
        elif url.path == "/page":
            body, content_type = page_body(size, seed), "text/html; charset=utf-8"
        else:
            return self._send(404, b'{"error": "not found"}', "application/json")
        # Generation is cached; the wait is the simulated upstream processing time.
        time.sleep(latency_ms / 1000)
        self._send(200, body, content_type, {"X-Upstream-Latency-Ms": str(latency_ms)})

    def _send(self, status: int, body: bytes, content_type: str, headers: dict = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def serve(host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description="Mock upstream API and web pages for MCP tool benchmarks.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    server = serve(args.host, args.port)
    print(f"mock upstream on http://{args.host}:{server.server_address[1]}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
