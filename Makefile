.PHONY: setup doctor smoke test run demo

setup:
	uv sync

doctor:
	uv run python scripts/doctor.py

smoke:
	uv run python scripts/local_smoke.py

test:
	uv run pytest

run:
	uv run utm-connector

demo:
	uv run utm-connector --demo --open-browser
