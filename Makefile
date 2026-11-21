PYTHON ?= python3
TRACE  ?= data/traces/livemcpbench-claude-sonnet-4.jsonl

.PHONY: help setup test dry-run census sebs-status

help:
	@echo "make setup         check out the SeBS submodule (our fork, branch mcp)"
	@echo "make test          run all tests (no cloud account or Docker needed)"
	@echo "make dry-run       modeled timeline of the agent trace; calls nothing"
	@echo "make census        regenerate data/server-census/summary.md"
	@echo "make sebs-status   uncommitted or unpushed changes in serverless-benchmarks/?"

setup:
	git submodule update --init

test:
	$(PYTHON) -m unittest tests.test_mcp_e2e tests.test_mcp_tools tests.test_replay

dry-run:
	$(PYTHON) -m mcp_bench.replay $(TRACE) --config configs/replay.example.json --dry-run

census:
	$(PYTHON) analysis/server_census.py > data/server-census/summary.md

sebs-status:
	git -C serverless-benchmarks status --short --branch
