.PHONY: setup demo-setup doctor smoke test run demo demo-check gcs-demo gcs-demo-check gcs-demo-verify gcs-custom-qgc-demo gcs-custom-qgc-demo-check gcs-custom-qgc-demo-verify gcs-router-demo gcs-router-demo-check gcs-router-demo-verify integration-demo integration-demo-check integration-demo-verify integration-demo-router-check integration-demo-router-verify integration-demo-px4 integration-demo-px4-check integration-demo-px4-verify integration-verify mavlink-stream-check manifest-check qgc-check qgc-stage mp-check mp-compile-check router-check

setup:
	uv sync

demo-setup:
	uv run python scripts/setup_demo.py

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

gcs-demo-verify:
	uv run python scripts/openutm_demo.py --gcs auto --no-browser --verify

gcs-custom-qgc-demo:
	@test -n "$${QGROUNDCONTROL_COMMAND:-}" || (echo "Set QGROUNDCONTROL_COMMAND to the custom QGroundControl executable before using this target."; exit 2)
	uv run python scripts/openutm_demo.py --gcs qgroundcontrol --qgroundcontrol-command "$${QGROUNDCONTROL_COMMAND}"

gcs-custom-qgc-demo-check:
	@test -n "$${QGROUNDCONTROL_COMMAND:-}" || (echo "Set QGROUNDCONTROL_COMMAND to the custom QGroundControl executable before using this target."; exit 2)
	uv run python scripts/openutm_demo.py --gcs qgroundcontrol --qgroundcontrol-command "$${QGROUNDCONTROL_COMMAND}" --check

gcs-custom-qgc-demo-verify:
	@test -n "$${QGROUNDCONTROL_COMMAND:-}" || (echo "Set QGROUNDCONTROL_COMMAND to the custom QGroundControl executable before using this target."; exit 2)
	uv run python scripts/openutm_demo.py --gcs qgroundcontrol --qgroundcontrol-command "$${QGROUNDCONTROL_COMMAND}" --no-browser --verify

gcs-router-demo:
	uv run python scripts/openutm_demo.py --topology router --gcs auto

gcs-router-demo-check:
	uv run python scripts/openutm_demo.py --topology router --gcs auto --check

gcs-router-demo-verify:
	uv run python scripts/openutm_demo.py --topology router --gcs auto --no-browser --verify

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

manifest-check:
	uv run python scripts/check_connector_manifest.py

qgc-check:
	uv run python scripts/check_qgc_overlay.py

qgc-stage:
	uv run python scripts/stage_qgc_custom_build.py \
		--qgc-source "$${QGC_SOURCE_DIR:-../qgroundcontrol}" \
		--output "$${QGC_CUSTOM_DIR:-../qgroundcontrol/custom-utm-connector}"

mp-check:
	uv run python scripts/check_mission_planner_plugin.py

mp-compile-check:
	uv run python scripts/check_mission_planner_plugin.py --strict --compile

router-check:
	uv run python scripts/check_mavlink_router.py
