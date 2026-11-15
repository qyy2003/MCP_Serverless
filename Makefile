PYTHON ?= python3
TRACE  ?= data/traces/livemcpbench-claude-sonnet-4.jsonl

.PHONY: help setup test dry-run census patch-status patch-export

help:
	@echo "make setup         init the SeBS submodule and apply our patch"
	@echo "make test          run all tests (no cloud account or Docker needed)"
	@echo "make dry-run       modeled timeline of the agent trace; calls nothing"
	@echo "make census        regenerate data/server-census/summary.md"
	@echo "make patch-status  is the SeBS patch applied?"
	@echo "make patch-export  write edits in serverless-benchmarks/ back to patches/"

setup:
	git submodule update --init
	scripts/sebs-patch.sh apply

test:
	scripts/sebs-patch.sh apply
	$(PYTHON) -m unittest tests.test_mcp_e2e tests.test_mcp_tools tests.test_replay

dry-run:
	$(PYTHON) -m mcp_bench.replay $(TRACE) --config configs/replay.example.json --dry-run

census:
	$(PYTHON) analysis/server_census.py > data/server-census/summary.md

patch-status:
	scripts/sebs-patch.sh status

patch-export:
	scripts/sebs-patch.sh export
