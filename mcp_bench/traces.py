"""Agent traces: the sequence of tool calls an agent made, for replay against serverless tools.

A trace is a JSON-lines file with one agent session per line:

    {"session": "<task id>", "source": "...", "turns": [
        {"output_chars": 512,      # text the model generated this turn (message + tool arguments)
         "context_chars": 20480,   # conversation length the model read before generating
         "calls": [{"server": "...", "tool": "...", "class": "api_wrapper",
                    "arguments_chars": 120, "response_chars": 855}]}
    ]}

Each turn is one LLM generation followed by the tool calls it issued (in
parallel when there are several). Recorded runs rarely keep timestamps, so the
LLM time per turn is estimated at replay time from output_chars and
context_chars (see replay.py).

`class` is the server's workload class from the server census
(data/server-census/*.json), which decides which benchmark tool replays the call.

    python -m mcp_bench.traces livemcpbench <run.json> <out.jsonl>
"""

import argparse
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CENSUS = os.path.join(ROOT, "data", "server-census")

# LiveMCPBench agents find tools with a retrieval meta-tool ("route", an embedding
# search over tool descriptions) and run them through "execute-tool".
LIVEMCPBENCH_ROUTER = {"server": "tool-router", "tool": "route", "class": "memory_rag"}


def _normalize(name: str) -> str:
    """Server names differ in case and separators between configs and runs."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


def server_classes(benchmark: str) -> dict:
    classes = {}
    for path in glob.glob(os.path.join(CENSUS, "*.json")):
        with open(path) as f:
            for record in json.load(f):
                if record["benchmark"] == benchmark:
                    classes[_normalize(record["server"])] = record["category"]
    return classes


def _content_chars(message: dict) -> int:
    content = message.get("content") or ""
    return len(content if isinstance(content, str) else json.dumps(content))


def from_livemcpbench(run: list, source: str) -> list:
    """Convert a LiveMCPBench baseline output (list of tasks with OpenAI-style messages)."""
    classes = server_classes("LiveMCPBench")
    sessions = []
    for task in run:
        messages = task["messages"]
        responses = {m["tool_call_id"]: _content_chars(m) for m in messages if m.get("role") == "tool"}
        turns, context = [], 0
        for message in messages:
            if message.get("role") == "assistant":
                calls, output = [], _content_chars(message)
                for call in message.get("tool_calls") or []:
                    function = call["function"]
                    arguments = function.get("arguments") or "{}"
                    output += len(arguments)
                    if function["name"] == "execute-tool":
                        try:
                            parsed = json.loads(arguments)
                        except ValueError:
                            parsed = {}
                        server = parsed.get("server_name", "unknown")
                        entry = {
                            "server": server,
                            "tool": parsed.get("tool_name", "unknown"),
                            "class": classes.get(_normalize(server), "unknown"),
                        }
                    elif function["name"] == "route":
                        entry = dict(LIVEMCPBENCH_ROUTER)
                    else:
                        entry = {"server": "unknown", "tool": function["name"], "class": "unknown"}
                    entry["arguments_chars"] = len(arguments)
                    entry["response_chars"] = responses.get(call.get("id"), 0)
                    calls.append(entry)
                turns.append({"output_chars": output, "context_chars": context, "calls": calls})
            context += _content_chars(message) + sum(
                len(c["function"].get("arguments") or "") for c in message.get("tool_calls") or []
            )
        sessions.append({
            "session": task["task_id"],
            "source": source,
            "category": task.get("category"),
            "turns": turns,
        })
    return sessions


def load(path: str) -> list:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def save(sessions: list, path: str):
    with open(path, "w") as f:
        for session in sessions:
            f.write(json.dumps(session) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Convert recorded agent runs to replay traces.")
    parser.add_argument("format", choices=["livemcpbench"])
    parser.add_argument("run", help="Recorded run (LiveMCPBench: baseline/output/<model>.json)")
    parser.add_argument("output", help="Trace file to write (JSON lines)")
    parser.add_argument("--source", help="Label stored in each session; defaults to the run's file name")
    args = parser.parse_args(argv)

    with open(args.run) as f:
        run = json.load(f)
    source = args.source or f"LiveMCPBench/{os.path.splitext(os.path.basename(args.run))[0]}"
    sessions = from_livemcpbench(run, source)
    save(sessions, args.output)
    calls = [c for s in sessions for t in s["turns"] for c in t["calls"]]
    unknown = sorted({c["server"] for c in calls if c["class"] == "unknown"})
    print(f"{len(sessions)} sessions, {sum(len(s['turns']) for s in sessions)} turns, "
          f"{len(calls)} tool calls -> {args.output}", file=sys.stderr)
    if unknown:
        print(f"servers without a census class: {', '.join(unknown)}", file=sys.stderr)


if __name__ == "__main__":
    main()
