.PHONY: setup doctor smoke test run demo integration-demo integration-demo-check integration-demo-verify integration-demo-px4 integration-demo-px4-check integration-demo-px4-verify integration-verify qgc-check mp-check

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

integration-demo-verify:
	uv run python scripts/openutm_demo.py --gcs none --no-browser --verify

integration-demo-px4:
	uv run python scripts/openutm_demo.py --simulator px4

integration-demo-px4-check:
	uv run python scripts/openutm_demo.py --simulator px4 --check

integration-demo-px4-verify:
	uv run python scripts/openutm_demo.py --simulator px4 --gcs none --no-browser --verify

integration-verify:
	uv run python scripts/verify_running_demo.py

qgc-check:
	uv run python scripts/check_qgc_overlay.py

mp-check:
	uv run python scripts/check_mission_planner_plugin.py
