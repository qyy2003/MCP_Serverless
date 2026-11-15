"""Measure MCP tool calls against a serverless function, phase by phase.

Acts as an MCP client over Streamable HTTP and records, for every request,
the client-side timings (TCP/TLS connect, time to first byte, total) next to
the server-side measurements the SeBS MCP shim returns in `_meta.sebs`.
The same function can be invoked in `plain` mode (the benchmark input posted
as-is, as SeBS does) to isolate the cost of the MCP protocol.

    python -m mcp_bench.client --url http://host:9000/mcp --arguments '{"sleep": 0.1}'
    python -m mcp_bench.client --url http://host:9000/ --mode plain --arguments '{"sleep": 0.1}'

Only the standard library is used, so the driver runs anywhere.
"""

import argparse
import http.client
import json
import socket
import statistics
import sys
import time
from datetime import datetime
from typing import Optional
from urllib.parse import urlsplit

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "mcp-serverless-bench", "version": "0.1.0"}


def _us(seconds: float) -> int:
    return int(seconds * 1e6)


class Connection:
    """One keep-alive HTTP connection that times connect, first byte and total per request."""

    def __init__(self, url: str, timeout: float = 900):
        parts = urlsplit(url)
        self.path = parts.path or "/"
        if parts.query:
            self.path += "?" + parts.query
        cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        self._conn = cls(parts.netloc, timeout=timeout)
        self._connected = False

    def post(self, body: bytes, headers: dict):
        timing = {"connect_us": 0}
        begin = time.perf_counter()
        if not self._connected:
            self._conn.connect()
            # Like curl: avoid Nagle + delayed-ACK stalls on small requests.
            self._conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._connected = True
            timing["connect_us"] = _us(time.perf_counter() - begin)
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
    if "begin" in meta and "end" in meta:
        begin = datetime.fromtimestamp(float(meta["begin"]))
        end = datetime.fromtimestamp(float(meta["end"]))
        times["exec_us"] = _us((end - begin).total_seconds())
    return times


class MCPClient:
    """Stateless-friendly MCP client; follows Mcp-Session-Id if the server assigns one."""

    def __init__(self, url: str, fresh_connection: bool = False):
        self.url = url
        self.fresh_connection = fresh_connection
        self.conn = Connection(url)
        self.session_id: Optional[str] = None
        self.protocol_version: Optional[str] = None
        self._next_id = 0

    def _send(self, method: str, params: Optional[dict] = None, notification: bool = False):
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
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        if self.fresh_connection:
            self.conn.close()
        body = json.dumps(message).encode()
        status, resp_headers, data, timing = self.conn.post(body, headers)
        session = {k.lower(): v for k, v in resp_headers.items()}.get("mcp-session-id")
        if session:
            self.session_id = session
        if status not in (200, 202):
            raise RuntimeError(f"{method}: HTTP {status}: {data[:500]!r}")
        response = _parse_body(status, resp_headers, data)
        if response is not None and "error" in response:
            raise RuntimeError(f"{method}: {response['error']}")
        record = {"phase": method, "request_bytes": len(body), "response_bytes": len(data)}
        record.update(timing)
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

    def list_tools(self):
        result, record = self._send("tools/list")
        record.update(_server_times(result.get("_meta", {}).get("sebs", {})))
        return result["tools"], record

    def call_tool(self, name: str, arguments: dict):
        result, record = self._send("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise RuntimeError(f"Tool {name} failed: {result['content']}")
        record.update(_server_times(result.get("_meta", {}).get("sebs", {})))
        return result, record


def run_mcp(url: str, arguments: dict, calls: int, fresh_connection: bool, tool: Optional[str]):
    client = MCPClient(url, fresh_connection)
    try:
        _, records = client.initialize()
        tools, record = client.list_tools()
        records.append(record)
        name = tool or tools[0]["name"]
        for _ in range(calls):
            _, record = client.call_tool(name, arguments)
            records.append(record)
    finally:
        client.close()
    return records


def run_plain(url: str, arguments: dict, calls: int, fresh_connection: bool):
    """Invoke the function the way SeBS's HTTP trigger does, for a protocol-free baseline."""
    conn = Connection(url)
    records = []
    body = json.dumps(arguments).encode()
    try:
        for _ in range(calls):
            if fresh_connection:
                conn.close()
            status, _, data, timing = conn.post(body, {"Content-Type": "application/json"})
            if status != 200:
                raise RuntimeError(f"HTTP {status}: {data[:500]!r}")
            output = json.loads(data)
            if "body" in output:
                body_out = output["body"]
                output = body_out if isinstance(body_out, dict) else json.loads(body_out)
            record = {"phase": "plain", "request_bytes": len(body), "response_bytes": len(data)}
            record.update(timing)
            record.update(_server_times(output))
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
    parser.add_argument("--arguments", default="{}", help="Tool arguments / benchmark input (JSON)")
    parser.add_argument("--tool", help="Tool name; defaults to the first tool listed")
    parser.add_argument("--calls", type=int, default=10, help="Tool calls per session")
    parser.add_argument("--fresh-connection", action="store_true",
                        help="Open a new TCP/TLS connection for every request")
    parser.add_argument("--output", help="Write per-request records as JSON lines")
    args = parser.parse_args(argv)

    arguments = json.loads(args.arguments)
    if args.mode == "mcp":
        records = run_mcp(args.url, arguments, args.calls, args.fresh_connection, args.tool)
    else:
        records = run_plain(args.url, arguments, args.calls, args.fresh_connection)

    if args.output:
        with open(args.output, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
    json.dump(summarize(records), sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
