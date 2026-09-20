.PHONY: setup doctor smoke test run demo integration-demo integration-demo-check qgc-check mp-check

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

integration-demo:
	uv run python scripts/openutm_demo.py

integration-demo-check:
	uv run python scripts/openutm_demo.py --check

qgc-check:
	uv run python scripts/check_qgc_overlay.py

mp-check:
	uv run python scripts/check_mission_planner_plugin.py
