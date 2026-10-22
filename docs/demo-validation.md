# Local demo validation — 15 October 2026

## Environment and scope

Apple Silicon macOS; installed stock QGroundControl; ArduCopter SITL at
47.4979, 19.0402, approximately 137 m AMSL; local Flight Blender in Docker;
connector on 127.0.0.1:8001. Vehicle `sitl-1` remained disarmed and stationary.
No real aircraft or flight execution was involved.

Mission Planner was unavailable on this Mac. Its native Windows runtime,
C# compilation, toolbar actions, file loading, and vehicle connection remain
**unverified**. The Windows instructions in [the runbook](demo-runbook.md)
are prepared steps, not recorded Windows results. PX4 on Windows was also not
executed in this rehearsal.

## Recorded results

| Check | Result |
| --- | --- |
| QGroundControl native vehicle display | Connected, Ready/Stabilize, GPS 10 satellites, battery 100%; live SITL position visible |
| QGC native mission file picker | Blocked by Qt accessibility automation: coordinate clicks returned `AXError.notImplemented`; manual check remains |
| QGC `.plan` → connector → Flight Blender | Passed; operation `223e1058-f138-4d19-a50b-1250229b899c`; 3 acknowledged publications; 17.1 s |
| Mission Planner WPL → connector → Flight Blender | Passed after adding planned home; operation `b832b9be-f02e-44c6-9670-57f001e1f5b4`; 2 acknowledged publications; 16.1 s |
| Mission Planner source contract | Passed against version 1.3.83, source revision `efb080190de0bf091f9aab982c8848a124de7588` |
| Clean supervised QGC restart | Passed after waiting for GPS; operation `b709eea1-34f1-4dc3-b2a0-037beab21cdc`; lifecycle 25.5 s including initialization; launcher exited 0 and cleaned up its stack |
| Focused regression suite | 77 passed across verifier, mission generation/parsing, launcher, MP plugin, QGC contract, and console window tests |

Both automated lifecycle runs imported a mission, received ACCEPTED and
AUTHORIZED, started publication, waited for CONFORMING and at least two **new**
provider acknowledgements, then completed with COMPLETED / STOPPED. These were
HTTP workflow tests using the native GCS file formats, not UI automation of
GCS mission editing or plugin buttons.

The browser console was also exercised in Safari with the actual generated
QGC file: Open mission file → Validate & save → Submit to UTM → Start operation.
It reached ACTIVE / CONFORMING with TELEMETRY_PUBLISHED, then completed with
COMPLETED / STOPPED. Operation: `d0c1f638-3f55-44b6-9140-511fdfd0439a`.
Its validity window was reviewed in local Budapest time.

The same Safari workflow passed with the generated Mission Planner file,
including its planned home row. Operation
`7fdb37ee-5a08-48e2-a301-b8d03b6c44a1` reached ACTIVE / CONFORMING with
TELEMETRY_PUBLISHED after 17:22 Budapest time and completed at 17:23:46 with
COMPLETED / STOPPED. The corrected console kept the saved window and displayed
“Operation is live and conforming” when that window opened. At cleanup the
connector reported zero active operations, 152 acknowledged publications
across the rehearsals, and zero failed publications.

## Demo fixes made during rehearsal

- The old verifier could pass on local conformance before the validity window
  opened, with zero provider publications. It now requires two new
  acknowledged publications and ACTIVE / CONFORMING before completing. It
  rejects other active operations so their counter increments cannot satisfy
  the check. Regression coverage includes a conforming operation whose
  counter never increases, including previously published samples.
- A cold-start rehearsal exposed initialization telemetry being used before
  SITL acquired GPS, producing a route outside its eventual position. The
  verifier now waits for GOOD telemetry and a 3D GPS fix before deriving its
  mission; the regression test starts with an unusable GPS sample.
- Generated Mission Planner files now include a planned home row. Mission
  Planner removes that row from its route grid; without it, the first takeoff
  command would disappear when loading the file.
- The supervised demo's canonical mission now labels the simulator altitude
  AMSL, matching the GCS files and live telemetry. The standalone WGS84 test
  mission generator retains its default datum.

- The console no longer resets the saved window or falsely marks the mission
  dirty when an active operation reaches its start time. New submissions still
  require a future start; the JavaScript regression test executes those rules
  with Node.js.

A complete `uv run pytest` run returned **267 passed, 2 failed**. The two
previously observed failures remain deferred:

- `tests/test_api.py::test_health_exposes_provider_failure_and_recovery`: a
  successful health probe clears the recorded provider failure.
- `tests/test_ui.py::test_operator_console_contains_the_complete_gcs_workflow`:
  an assertion expects an old JavaScript source expression.

The live rehearsal used provider publication counters and acknowledgements;
health alone is insufficient evidence of successful telemetry delivery.

## Repeat

After the manual rehearsal, the supervised stack stopped successfully and the
host preflight passed again. A fresh QGC launch then passed its full lifecycle
verification and automatic cleanup. Close an existing QGC instance before
repeating; a second instance can exit immediately.

Use [the demo runbook](demo-runbook.md) for startup, both sequential verifier
commands, the live presentation, Windows preparation, and cleanup. Do not run
the full-stack launchers against the same occupied ports simultaneously.
