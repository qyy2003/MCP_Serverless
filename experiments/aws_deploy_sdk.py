#!/usr/bin/env python3
"""Deploy 610 (default + sdk), 620 (sdk), 630 (default + sdk) to AWS Lambda via SeBS."""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEBS_DIR = os.path.join(ROOT, "serverless-benchmarks")
SEBS_BIN = os.path.join(SEBS_DIR, ".venv", "bin", "sebs")
STATE_PATH = os.path.join(ROOT, "results", "aws", "ec2-upstream.json")

TARGETS = [
    ("610.api-proxy", None),
    ("610.api-proxy", "sdk"),
    ("620.fetch-markdown", "sdk"),
    ("630.data-analysis", None),
    ("630.data-analysis", "sdk"),
]


def load_env(path: str = os.path.expanduser("~/.aws-mcpbench.env")):
    env = dict(os.environ)
    if not env.get("AWS_ACCESS_KEY_ID") and os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            if "=" in line:
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def main():
    env = load_env()
    if os.path.exists(STATE_PATH):
        env["SEBS_MOCK_UPSTREAM"] = json.load(open(STATE_PATH))["url"]
    print(f"Using SEBS_MOCK_UPSTREAM={env.get('SEBS_MOCK_UPSTREAM')}", flush=True)

    out_root = os.path.join(ROOT, "results", "aws", "2026-11-23-deploy")
    os.makedirs(out_root, exist_ok=True)

    for bench, variant in TARGETS:
        label = f"{bench}-{variant or 'default'}"
        out_dir = os.path.join(out_root, label)
        os.makedirs(out_dir, exist_ok=True)
        cmd = [
            SEBS_BIN, "benchmark", "invoke", bench, "test",
            "--config", "../configs/sebs-aws.json",
            "--deployment", "aws",
            "--trigger", "http",
            "--output-dir", out_dir,
            "--output-file", os.path.join(out_dir, "sebs.log"),
        ]
        if variant:
            cmd += ["--language-variant", variant]
        print(f"\n=== Deploying {label} ===", flush=True)
        proc = subprocess.run(cmd, cwd=SEBS_DIR, env=env)
        print(f"=== {label}: exit code {proc.returncode} ===", flush=True)


if __name__ == "__main__":
    sys.exit(main())
