"""Summarize the MCP server census: which workload classes the MCP benchmarks exercise.

Reads one JSON array of server records per benchmark (data/server-census/*.json)
and prints markdown tables: servers and tasks per category, dominant cost, state,
and how many need API keys.

    python analysis/server_census.py [data/server-census]
"""

import collections
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATEGORIES = [
    "api_wrapper", "search_fetch", "database", "filesystem_git", "browser", "code_exec",
    "memory_rag", "local_compute", "local_data", "desktop_app", "other",
]


def load(directory: str) -> list:
    records = []
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        with open(path) as f:
            records.extend(json.load(f))
    return records


def table(header: list, rows: list) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def crosstab(records: list, field: str, benchmarks: list, order: list = None) -> str:
    counts = collections.Counter((r["benchmark"], r.get(field)) for r in records)
    values = order or sorted({r.get(field) for r in records}, key=str)
    values = [v for v in values if any(counts[(b, v)] for b in benchmarks)]
    rows = []
    for v in values:
        per = [counts[(b, v)] for b in benchmarks]
        rows.append([v] + per + [sum(per)])
    totals = [sum(counts[(b, v)] for v in values) for b in benchmarks]
    rows.append(["**total**"] + totals + [sum(totals)])
    return table([field] + benchmarks + ["all"], rows)


def task_weighted(records: list, benchmarks: list) -> str:
    """Share of task references per category: what the benchmarks actually exercise."""
    rows = []
    totals = {b: sum(r.get("n_tasks") or 0 for r in records if r["benchmark"] == b)
              for b in benchmarks}
    for c in CATEGORIES:
        row, any_tasks = [c], False
        for b in benchmarks:
            n = sum(r.get("n_tasks") or 0 for r in records
                    if r["benchmark"] == b and r["category"] == c)
            any_tasks |= n > 0
            row.append(f"{n} ({100 * n / totals[b]:.0f}%)" if totals[b] else "–")
        if any_tasks:
            rows.append(row)
    return table(["category"] + benchmarks, rows)


def main(directory: str):
    records = load(directory)
    benchmarks = sorted({r["benchmark"] for r in records})
    print(f"{len(records)} servers, "
          f"{sum(r.get('n_tools') or 0 for r in records)} tools (where known)\n")
    print("## Servers per category\n")
    print(crosstab(records, "category", benchmarks, CATEGORIES) + "\n")
    print("## Task references per category\n")
    print(task_weighted(records, benchmarks) + "\n")
    for field in ("dominant_cost", "state", "needs_api_key"):
        print(f"## Servers by {field}\n")
        print(crosstab(records, field, benchmarks) + "\n")
    # Records phrase "no notable cost" as e.g. "none (fastmcp only)".
    heavy = [r for r in records
             if not str(r.get("heavy_init") or "none").lower().startswith(("none", "unknown"))]
    print("## Servers with notable startup cost\n")
    print(table(["benchmark", "server", "category", "heavy_init"],
                [[r["benchmark"], r["server"], r["category"], r["heavy_init"]] for r in heavy]))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "server-census"))
