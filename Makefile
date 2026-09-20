.PHONY: setup doctor smoke test run demo demo-check gcs-demo gcs-demo-check gcs-router-demo gcs-router-demo-check integration-demo integration-demo-check integration-demo-verify integration-demo-router-check integration-demo-router-verify integration-demo-px4 integration-demo-px4-check integration-demo-px4-verify integration-verify mavlink-stream-check qgc-check mp-check router-check

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

demo-check:
	uv run python scripts/check_demo.py

gcs-demo:
	uv run python scripts/openutm_demo.py --gcs auto

gcs-demo-check:
	uv run python scripts/openutm_demo.py --gcs auto --check

gcs-router-demo:
	uv run python scripts/openutm_demo.py --topology router --gcs auto

gcs-router-demo-check:
	uv run python scripts/openutm_demo.py --topology router --gcs auto --check

integration-demo:
	uv run python scripts/openutm_demo.py

integration-demo-check:
	uv run python scripts/openutm_demo.py --check

integration-demo-verify:
	uv run python scripts/openutm_demo.py --gcs none --no-browser --verify

integration-demo-router-check:
	uv run python scripts/openutm_demo.py --topology router --gcs none --no-browser --check

integration-demo-router-verify:
	uv run python scripts/openutm_demo.py --topology router --gcs none --no-browser --verify

integration-demo-px4:
	uv run python scripts/openutm_demo.py --simulator px4

integration-demo-px4-check:
	uv run python scripts/openutm_demo.py --simulator px4 --check

integration-demo-px4-verify:
	uv run python scripts/openutm_demo.py --simulator px4 --gcs none --no-browser --verify

integration-verify:
	uv run python scripts/verify_running_demo.py

mavlink-stream-check:
	uv run python scripts/verify_mavlink_stream.py

qgc-check:
	uv run python scripts/check_qgc_overlay.py

mp-check:
	uv run python scripts/check_mission_planner_plugin.py

router-check:
	uv run python scripts/check_mavlink_router.py
