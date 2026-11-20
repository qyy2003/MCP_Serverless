"""Measure MCP tool calls against a serverless function, phase by phase.

Acts as an MCP client over Streamable HTTP and records, for every request,
the client-side timings (TCP/TLS connect, time to first byte, total) next to
the server-side measurements the SeBS MCP shim returns in `_meta.sebs`.
The same function can be invoked in `plain` mode (the benchmark input posted
as-is, as SeBS does) to isolate the cost of the MCP protocol.

    python -m mcp_bench.client --url http://host:9000/mcp --arguments '{"sleep": 0.1}'
    python -m mcp_bench.client --url http://host:9000/mcp --protocol modern --arguments '{"sleep": 0.1}'
    python -m mcp_bench.client --url http://host:9000/ --mode plain --arguments '{"sleep": 0.1}'

Protocol revisions (--protocol):
- legacy: the handshake revisions (default; what all earlier measurements used): a session
  starts with initialize + notifications/initialized.
- modern: 2026-07-28, pinned: no handshake; every request carries the protocol version and
  client info in params._meta and the Mcp-Method (and, for tools/call, Mcp-Name) headers.
- auto: what the official SDK client does by default: probe server/discover at 2026-07-28 and
  fall back to the handshake if the server doesn't speak it.

Only the standard library is used, so the driver runs anywhere.
"""

import argparse
import http.client
import json
import os
import secrets
import socket
import statistics
import sys
import time
from datetime import datetime
from typing import Optional
from urllib.parse import urlsplit

PROTOCOL_VERSION = "2025-06-18"  # handshake revision requested by `initialize`
MODERN_PROTOCOL_VERSION = "2026-07-28"
PROTOCOLS = ("legacy", "modern", "auto")
CLIENT_INFO = {"name": "mcp-serverless-bench", "version": "0.1.0"}


def _us(seconds: float) -> int:
    return int(seconds * 1e6)


class Connection:
    """One keep-alive HTTP connection that times connect, first byte and total per request."""

    # Send a fresh X-Cloud-Trace-Context with every request (--trace-header, or MCP_BENCH_TRACE_HEADER=1 for
    # the replay driver). Cloud Run logs it as the request's trace, so every request, including handshake
    # and 202 responses, can be matched with its entry in the platform's request log (GCP's counterpart of
    # x-amzn-RequestId).
    send_trace = os.environ.get("MCP_BENCH_TRACE_HEADER") == "1"

    def __init__(self, url: str, timeout: float = 900):
        parts = urlsplit(url)
        self.path = parts.path or "/"
        if parts.query:
            self.path += "?" + parts.query
        cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        self._conn = cls(parts.netloc, timeout=timeout)
        self._connected = False

    def post(self, body: bytes, headers: dict):
        timing = {"connect_us": 0, "ts": round(time.time(), 6)}
        begin = time.perf_counter()
        if not self._connected:
            self._conn.connect()
            # Like curl: avoid Nagle + delayed-ACK stalls on small requests.
            self._conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._connected = True
            timing["connect_us"] = _us(time.perf_counter() - begin)
        if self.send_trace:
            trace_id = secrets.token_hex(16)
            headers = dict(headers, **{"X-Cloud-Trace-Context": f"{trace_id}/{secrets.randbits(63) or 1};o=0"})
            timing["trace_id"] = trace_id
        sent = time.perf_counter()
        self._conn.request("POST", self.path, body=body, headers=headers)
        response = self._conn.getresponse()
        first_byte = time.perf_counter()
        data = response.read()
        end = time.perf_counter()
        if response.getheader("Connection", "").lower() == "close":
            self.close()
        timing["ttfb_us"] = _us(first_byte - sent)
        timing["client_us"] = _us(end - begin)
        # Lambda Function URLs name the invocation in a header, also for bodiless 202 responses,
        # so every request can be matched with its billed duration in the platform logs.
        amzn_id = response.getheader("x-amzn-RequestId")
        if amzn_id:
            timing["amzn_request_id"] = amzn_id
        return response.status, dict(response.getheaders()), data, timing

    def close(self):
        self._conn.close()
        self._connected = False


def _parse_body(status: int, headers: dict, data: bytes) -> Optional[dict]:
    if status == 202 or not data:
        return None
    content_type = {k.lower(): v for k, v in headers.items()}.get("content-type", "")
    if content_type.startswith("text/event-stream"):
        # A server may stream the response; the JSON-RPC response is the last data event.
        events = [line[5:].strip() for line in data.decode().splitlines() if line.startswith("data:")]
        return json.loads(events[-1]) if events else None
    return json.loads(data)


def _server_times(meta: dict) -> dict:
    """Execution time and cold-start flag as reported by the function."""
    if not meta:
        return {}
    times = {"is_cold": meta.get("is_cold"), "container_id": meta.get("container_id")}
    for key in ("request_id", "cpu_us", "child_cpu_us", "import_us", "init_import_us", "init_us", "sdk_versions"):
        if key in meta:
            times[key] = meta[key]
    if "begin" in meta and "end" in meta:
        begin = datetime.fromtimestamp(float(meta["begin"]))
        end = datetime.fromtimestamp(float(meta["end"]))
        times["exec_us"] = _us((end - begin).total_seconds())
    return times


def _tool_measurement(output) -> dict:
    """The benchmark's own measurements (upstream wait, processing, ...), prefixed with m_."""
    measurement = output.get("measurement") if isinstance(output, dict) else None
    if not isinstance(measurement, dict):
        return {}
    return {f"m_{k}": v for k, v in measurement.items() if isinstance(v, (int, float, bool))}


class MCPClient:
    """Stateless-friendly MCP client; follows Mcp-Session-Id if the server assigns one."""

    def __init__(self, url: str, fresh_connection: bool = False, protocol: str = "legacy"):
        if protocol not in PROTOCOLS:
            raise ValueError(f"protocol must be one of {PROTOCOLS}, got {protocol!r}")
        self.url = url
        self.fresh_connection = fresh_connection
        self.protocol = protocol
        self.conn = Connection(url)
        self.session_id: Optional[str] = None
        self.protocol_version: Optional[str] = None
        # 2026-07-28: no handshake, so the version is fixed up front (auto settles it in connect()).
        self.modern = protocol == "modern"
        if self.modern:
            self.protocol_version = MODERN_PROTOCOL_VERSION
        self._next_id = 0

    def _exchange(self, method: str, params: Optional[dict] = None, notification: bool = False):
        """Send one message; returns (status, response message or None, record). Raises only on transport errors."""
        if self.modern:
            # Each 2026-07-28 request is self-contained: it names the version and the client itself.
            params = dict(params or {})
            params["_meta"] = {
                **params.get("_meta", {}),
                "io.modelcontextprotocol/protocolVersion": self.protocol_version,
                "io.modelcontextprotocol/clientInfo": CLIENT_INFO,
                "io.modelcontextprotocol/clientCapabilities": {},
            }
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if not notification:
            self._next_id += 1
            message["id"] = self._next_id
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.protocol_version:
            headers["MCP-Protocol-Version"] = self.protocol_version
        if self.modern:
            # Mirrored into headers so gateways can route without parsing the body.
            headers["Mcp-Method"] = method
            if method == "tools/call":
                headers["Mcp-Name"] = params["name"]
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        if self.fresh_connection:
            self.conn.close()
        body = json.dumps(message).encode()
        status, resp_headers, data, timing = self.conn.post(body, headers)
        session = {k.lower(): v for k, v in resp_headers.items()}.get("mcp-session-id")
        if session:
            self.session_id = session
        try:
            response = _parse_body(status, resp_headers, data)
        except ValueError:
            response = None
        record = {"phase": method, "request_bytes": len(body), "response_bytes": len(data)}
        record.update(timing)
        return status, response, record

    def _send(self, method: str, params: Optional[dict] = None, notification: bool = False):
        status, response, record = self._exchange(method, params, notification)
        if response is not None and "error" in response:
            raise RuntimeError(f"{method}: {response['error']}")
        if status not in (200, 202):
            raise RuntimeError(f"{method}: HTTP {status}")
        return (response or {}).get("result"), record

    def close(self):
        self.conn.close()

    def initialize(self):
        result, record = self._send(
            "initialize",
            {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO},
        )
        self.protocol_version = result["protocolVersion"]
        record.update(_server_times(result.get("_meta", {}).get("sebs", {})))
        _, notify_record = self._send("notifications/initialized", notification=True)
        return result, [record, notify_record]

    def discover(self):
        """server/discover at 2026-07-28. Returns (result or None if the server doesn't speak it, record)."""
        self.modern, self.protocol_version = True, MODERN_PROTOCOL_VERSION
        status, response, record = self._exchange("server/discover")
        result = (response or {}).get("result")
        if status == 200 and result and MODERN_PROTOCOL_VERSION in result.get("supportedVersions", []):
            record.update(_server_times(result.get("_meta", {}).get("sebs", {})))
            return result, record
        self.modern, self.protocol_version = False, None
        record["error"] = (response or {}).get("error", {}).get("code", status)
        return None, record

    def connect(self):
        """Start a session as the chosen protocol does; returns the records of its requests."""
        if self.protocol == "legacy":
            return self.initialize()[1]
        if self.protocol == "modern":
            return []
        result, record = self.discover()
        if result is not None:
            return [record]
        return [record] + self.initialize()[1]  # the server only speaks the handshake revisions

    def list_tools(self):
        result, record = self._send("tools/list")
        record.update(_server_times(result.get("_meta", {}).get("sebs", {})))
        return result["tools"], record

    def call_tool(self, name: str, arguments: dict):
        result, record = self._send("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise RuntimeError(f"Tool {name} failed: {result['content']}")
        record.update(_server_times(result.get("_meta", {}).get("sebs", {})))
        record.update(_tool_measurement(result.get("structuredContent")))
        return result, record


def run_mcp(url: str, arguments: dict, calls: int, fresh_connection: bool, tool: Optional[str],
            interval: float = 0.0, protocol: str = "legacy"):
    client = MCPClient(url, fresh_connection, protocol)
    try:
        records = client.connect()
        tools, record = client.list_tools()
        records.append(record)
        name = tool or tools[0]["name"]
        for i in range(calls):
            if i and interval:
                time.sleep(interval)
            _, record = client.call_tool(name, arguments)
            record["call"] = i
            records.append(record)
    finally:
        client.close()
    return records


def run_plain(url: str, arguments: dict, calls: int, fresh_connection: bool, interval: float = 0.0):
    """Invoke the function the way SeBS's HTTP trigger does, for a protocol-free baseline."""
    conn = Connection(url)
    records = []
    body = json.dumps(arguments).encode()
    try:
        for i in range(calls):
            if i and interval:
                time.sleep(interval)
            if fresh_connection:
                conn.close()
            status, _, data, timing = conn.post(body, {"Content-Type": "application/json"})
            if status != 200:
                raise RuntimeError(f"HTTP {status}: {data[:500]!r}")
            output = json.loads(data)
            if "body" in output:
                body_out = output["body"]
                output = body_out if isinstance(body_out, dict) else json.loads(body_out)
            record = {"phase": "plain", "call": i, "request_bytes": len(body), "response_bytes": len(data)}
            record.update(timing)
            record.update(_server_times(output))
            record.update(_tool_measurement(output.get("result")))
            records.append(record)
    finally:
        conn.close()
    return records


def summarize(records: list) -> dict:
    phases: dict = {}
    for r in records:
        phases.setdefault(r["phase"], []).append(r)
    summary = {}
    for phase, rs in phases.items():
        entry = {"count": len(rs)}
        for key in ("client_us", "ttfb_us", "connect_us", "exec_us"):
            values = [r[key] for r in rs if key in r]
            if values:
                entry[f"{key}_median"] = int(statistics.median(values))
                entry[f"{key}_max"] = max(values)
        cold = [r for r in rs if r.get("is_cold")]
        if cold:
            entry["cold"] = len(cold)
        summary[phase] = entry
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", required=True, help="Function URL (the /mcp route on local)")
    parser.add_argument("--mode", choices=["mcp", "plain"], default="mcp")
    parser.add_argument("--protocol", choices=PROTOCOLS, default="legacy",
                        help="MCP revision: legacy (handshake), modern (2026-07-28), auto (discover, else handshake)")
    parser.add_argument("--arguments", default="{}", help="Tool arguments / benchmark input (JSON)")
    parser.add_argument("--tool", help="Tool name; defaults to the first tool listed")
    parser.add_argument("--calls", type=int, default=10, help="Tool calls per session")
    parser.add_argument("--fresh-connection", action="store_true",
                        help="Open a new TCP/TLS connection for every request")
    parser.add_argument("--interval", type=float, default=0.0,
                        help="Seconds to wait between tool calls (default: back to back)")
    parser.add_argument("--meta", default="{}",
                        help="JSON object merged into every output record (experiment labels)")
    parser.add_argument("--output", help="Write per-request records as JSON lines")
    parser.add_argument("--trace-header", action="store_true",
                        help="Send a fresh X-Cloud-Trace-Context per request and record it as trace_id (GCP)")
    args = parser.parse_args(argv)

    arguments = json.loads(args.arguments)
    if args.trace_header:
        Connection.send_trace = True
    if args.mode == "mcp":
        records = run_mcp(args.url, arguments, args.calls, args.fresh_connection, args.tool, args.interval,
                          args.protocol)
    else:
        records = run_plain(args.url, arguments, args.calls, args.fresh_connection, args.interval)
    labels = json.loads(args.meta)
    for r in records:
        r.update(labels)

    if args.output:
        with open(args.output, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
    json.dump(summarize(records), sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
