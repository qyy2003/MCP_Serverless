# Node 22 + Debian bookworm's Python 3.11 (the Python version our Lambda/GCP functions run).
FROM node:22-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv python3-pip git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
# uv provisions newer Pythons for servers that need them (as uvx does in LiveMCPBench's configs)
RUN python3 -m pip install --break-system-packages --no-cache-dir uv
COPY probe.py /probe.py
