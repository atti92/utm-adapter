.PHONY: setup test run

setup:
	uv sync

test:
	.venv/bin/python -m pytest

run:
	.venv/bin/utm-connector

