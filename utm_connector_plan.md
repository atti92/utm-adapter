# UTM Operations Connector — Implementation Plan

## 1. Purpose

This document defines a revised implementation plan for a provider-neutral **UTM Operations Connector** that bridges Ground Control Stations (GCS), MAVLink-based vehicles, and UTM/U-space backends such as Flight Blender.

The design synthesizes the strongest ideas from:

- Dronecode's `utm-adapter`
- OpenUTM Flight Blender's `GCS_CONNECTOR_IMPLEMENTATION_PLAN`
- MAVLink-based vehicle and telemetry integration
- Python geospatial, validation, testing, and observability libraries
- A backend-neutral canonical domain model
- Record/replay and conformance analysis suitable for future high-volume analytics

The primary goal is to avoid embedding UTM-provider logic inside Mission Planner, QGroundControl, or other GCS applications.

Instead, GCS-specific integrations stay thin while the connector owns operational state, telemetry normalization, authorization handling, geometry generation, conformance monitoring, diagnostics, and provider integration.

---

## 2. Architectural Principles

### 2.1 Keep GCS adapters thin

Mission Planner, QGroundControl, and future GCS integrations should only provide:

- operator intent
- mission snapshots
- vehicle identity hints
- telemetry source information when needed
- compact status display
- operation actions such as submit, start, cancel, and complete

They should **not** implement:

- Flight Blender API logic
- provider-specific authentication
- UTM lifecycle interpretation
- geospatial corridor generation
- telemetry retry and buffering
- authorization semantics
- conformance rules
- backend-specific DTOs

---

### 2.2 Make the connector backend-neutral

The connector should not be permanently modeled as a "Flight Blender connector".

Flight Blender should be the first backend implementation behind an abstraction such as:

```text
Ground Control Stations
        |
        v
UTM Operations Connector
        |
        +-- Canonical Domain Model
        +-- Mission/Geometry Engine
        +-- Vehicle/Telemetry Engine
        +-- Operation State Machine
        +-- Conformance Engine
        +-- Diagnostics / Record-Replay
        |
        v
Backend Adapter Interface
        |
        +-- Flight Blender
        +-- Future USSP / USS
        +-- Future national or vendor-specific backend
```

This prevents provider APIs from becoming the universal domain model.

---

### 2.3 MAVLink terminates at the connector boundary

MAVLink is an ingestion protocol, not the internal UTM domain model.

Use:

```text
MAVLink
   |
   v
MAVLink Gateway
   |
   v
Canonical Telemetry / Mission / Vehicle Events
```

No core domain object should depend on `pymavlink`, QGroundControl, Mission Planner, or generated provider API types.

---

### 2.4 Separate operational states

Never collapse all UTM status into a single "ready" or "approved" flag.

Model independently:

- declaration state
- legal authorization state
- backend submission state
- DSS / strategic coordination state
- telemetry publication state
- conformance state
- connector health
- backend reachability
- credential/authentication state

A successful declaration must **not** be treated as legal authorization.

---

## 3. Target Architecture

```text
                  +--------------------+
                  | Mission Planner    |
                  | thin plugin        |
                  +----------+---------+
                             |
                             |
                  +----------v---------+
                  | QGroundControl     |
                  | .plan / MAVLink    |
                  +----------+---------+
                             |
                             |
                +------------v-------------+
                | MAVLink Router / UDP     |
                | optional fan-out layer   |
                +------------+-------------+
                             |
                             v
              +------------------------------+
              | MAVLink Gateway              |
              | pymavlink                    |
              +--------------+---------------+
                             |
                             v
              +------------------------------+
              | Canonical Domain Model       |
              |                              |
              | Mission                      |
              | VehicleIdentity              |
              | TelemetryObservation         |
              | VehicleHealth                |
              | OperationIntent              |
              | AuthorizationState           |
              | ConformanceState             |
              +--------------+---------------+
                             |
         +-------------------+--------------------+
         |                   |                    |
         v                   v                    v
+----------------+  +----------------+  +------------------+
| Geometry       |  | Telemetry      |  | State /          |
| Engine         |  | Quality Engine |  | Conformance      |
| Shapely/pyproj |  | Aggregation    |  | Engine           |
+--------+-------+  +--------+-------+  +---------+--------+
         |                   |                    |
         +-------------------+--------------------+
                             |
                             v
              +------------------------------+
              | Backend Adapter Interface    |
              +--------------+---------------+
                             |
                    +--------+--------+
                    | Flight Blender  |
                    +-----------------+
```

---

## 4. Recommended Technology Stack

| Concern | Recommended Technology |
|---|---|
| MAVLink decoding | `pymavlink` |
| Optional high-level vehicle automation | `MAVSDK-Python` |
| Local connector API | `FastAPI` |
| Data validation | `Pydantic` |
| Async runtime | `asyncio` |
| Backend HTTP | `httpx` |
| Geometry | `Shapely` |
| Coordinate transforms | `pyproj` |
| Local persistence | SQLite |
| Testing | `pytest` |
| Property-based testing | `Hypothesis` |
| Metrics/tracing | OpenTelemetry |
| Metrics export | Prometheus-compatible exporter |
| SITL | ArduPilot SITL and PX4 SITL |
| Optional MAVLink fan-out | `mavlink-router` |
| High-volume historical analytics later | KX / kdb+ |

---

## 5. Core Components

## 5.1 MAVLink Gateway

Create a dedicated `MavlinkVehicleSession` abstraction around `pymavlink`.

Responsibilities:

- discover active MAVLink systems
- track heartbeat state
- decode supported messages
- normalize timestamps
- aggregate coherent vehicle state
- track autopilot/vehicle type
- detect connection loss
- read mission state
- expose canonical events only

Initial MAVLink message coverage:

| MAVLink Message | Use |
|---|---|
| `HEARTBEAT` | connection, mode, armed state |
| `GLOBAL_POSITION_INT` | primary position |
| `GPS_RAW_INT` | GNSS quality |
| `SYS_STATUS` | system health |
| `BATTERY_STATUS` | battery/energy state |
| `HOME_POSITION` | home/reference information |
| `MISSION_CURRENT` | mission progress |
| `MISSION_ITEM_INT` | mission reconstruction |
| `MISSION_COUNT` | mission size |
| `VFR_HUD` | heading and groundspeed |
| `ATTITUDE` | optional vehicle orientation |
| `SYSTEM_TIME` | clock diagnostics |
| `STATUSTEXT` | operator/system diagnostics |
| `AUTOPILOT_VERSION` | firmware/capabilities |

The gateway should emit canonical objects such as:

```python
VehicleTelemetry
VehicleHealth
VehicleConnectionState
MissionSnapshot
MissionProgress
VehicleIdentityObservation
```

---

## 5.2 Canonical Domain Model

The canonical model must be independent of:

- Mission Planner
- QGroundControl
- MAVLink classes
- Flight Blender generated classes
- HTTP transport
- persistence format

Recommended main entities:

```text
Mission
MissionRoute
Waypoint
OperationalVolume
Altitude
AltitudeDatum

VehicleIdentity
VehicleConnection
VehicleTelemetry
VehicleHealth
TelemetryQuality

OperationIntent
OperationIdentity
DeclarationState
AuthorizationState
BackendSubmissionState
TelemetryPublicationState
ConformanceState

Notification
DiagnosticEvent
CorrelationId
```

Use Pydantic models for strict validation.

Validate at the boundary:

- latitude range
- longitude range
- NaN / infinity rejection
- missing timestamps
- timezone awareness
- altitude datum presence
- invalid geometry
- invalid enum values
- stale telemetry
- impossible message ages

---

## 5.3 Altitude Model

Altitude handling must be explicit.

Support at least:

```text
AGL
AMSL / MSL
WGS84 ellipsoid
UNKNOWN
```

Rules:

1. Never silently infer altitude datum.
2. Store original source altitude and datum.
3. Store converted altitude separately.
4. Record conversion assumptions.
5. Surface assumptions to the operator.
6. Reject mission submission if required altitude semantics are unresolved.

---

## 5.4 Mission Acquisition

Support multiple mission sources.

### Source A — Mission Planner adapter

The Mission Planner plugin extracts the mission and sends a canonical mission snapshot.

### Source B — QGroundControl `.plan`

Parse `.plan` files into the canonical mission model.

### Source C — MAVLink mission protocol

Use:

```text
MISSION_COUNT
MISSION_REQUEST_INT
MISSION_ITEM_INT
MISSION_ACK
```

to reconstruct the mission from the vehicle.

The vehicle mission is useful because it represents what is actually onboard rather than merely what the GCS UI displays.

---

## 5.5 Mission Drift Detection

For each normalized mission:

1. canonicalize ordering and numeric representation
2. normalize altitudes
3. produce deterministic serialization
4. compute SHA-256 hash

Store:

```text
submitted_operation_mission_hash
current_onboard_mission_hash
```

If they differ after submission or authorization:

```text
WARNING:
Onboard mission differs from the mission used for the UTM declaration.
```

Optionally classify changes:

```text
NO_CHANGE
NON_OPERATIONAL_CHANGE
ROUTE_CHANGED
ALTITUDE_CHANGED
TIME_CHANGED
UNKNOWN_CHANGE
```

This should become a first-class safety feature.

---

## 5.6 Geometry Engine

Use `Shapely` and `pyproj`.

Never perform metre-based buffering directly in raw WGS84 latitude/longitude coordinates.

Recommended pipeline:

```text
WGS84 route
   |
   v
select appropriate projected CRS
   |
   v
LineString
   |
   v
buffer(corridor_radius_m)
   |
   v
validate / simplify / union
   |
   v
transform back to WGS84
```

Geometry invariants:

- every operational waypoint is covered
- polygons are valid
- no latitude/longitude swap
- altitude lower bound <= upper bound
- output is deterministic
- splitting geometry preserves coverage
- corridor radius is preserved within tolerance
- no self-intersections
- no invalid rings
- no silent unit conversion

---

## 5.7 Telemetry Aggregation

Do not forward every MAVLink packet directly to the UTM backend.

Recommended pipeline:

```text
MAVLink packets
     |
     v
decode
     |
     v
timestamp validation
     |
     v
per-field latest-value cache
     |
     v
coherent vehicle-state snapshot
     |
     v
quality checks
     |
     v
sampling / coalescing
     |
     v
UTM telemetry publication
```

Suggested initial rates:

```text
MAVLink ingestion: native rate
state aggregation: 5-10 Hz
quality evaluation: 2-5 Hz
UTM upload: ~1 Hz
```

Use a bounded queue.

When overloaded:

- coalesce obsolete position samples
- preserve important state transitions
- never block GCS callbacks
- expose queue depth
- expose last successful publication
- reject stale observations

---

## 5.8 Telemetry Quality Engine

Model telemetry quality as:

```text
GOOD
DEGRADED
STALE
INVALID
LOST
```

Quality factors may include:

- GNSS fix type
- horizontal accuracy
- vertical accuracy
- heartbeat age
- position age
- message age
- packet loss
- position jumps
- clock drift
- duplicate data sources
- unknown altitude reference
- source ownership conflict

This lets the conformance engine distinguish:

```text
vehicle is probably outside the authorized area
```

from:

```text
telemetry is insufficient to reliably determine conformance
```

---

## 5.9 Telemetry Ownership

Only one source may own authoritative telemetry for a vehicle at a time.

Example sources:

```text
MISSION_PLANNER
QGC
DIRECT_MAVLINK
SITL
EXTERNAL_TRACKER
```

Rules:

- ownership is explicit
- ownership transfers are logged
- duplicates are detected
- source loss may trigger controlled fallback
- simultaneous conflicting sources are never silently merged

---

## 5.10 Vehicle Identity

Keep identifiers separate.

Recommended structure:

```text
VehicleIdentity
  connector_vehicle_id
  mavlink_system_id
  mavlink_component_ids
  autopilot_type
  vehicle_type
  firmware_version
  serial_number?
  operator_aircraft_id?
  remote_id_serial?
  registration?
```

A MAVLink `sysid` must never be treated as globally unique.

---

## 5.11 Operation State Machine

Use independent substates instead of a giant monolithic enum.

Recommended groups:

### Declaration

```text
NOT_CREATED
DRAFT
SUBMITTED
ACCEPTED
REJECTED
CANCELLED
```

### Authorization

```text
UNKNOWN
NOT_REQUIRED
PENDING
AUTHORIZED
DENIED
EXPIRED
REVOKED
```

### Backend Connectivity

```text
UNKNOWN
AVAILABLE
DEGRADED
UNAVAILABLE
```

### Telemetry Publication

```text
NOT_STARTED
ACTIVE
DEGRADED
FAILED
STOPPED
```

### Conformance

```text
UNKNOWN
CONFORMING
NEAR_BOUNDARY
NON_CONFORMING
TELEMETRY_UNRELIABLE
```

The connector is the only component allowed to interpret provider lifecycle responses.

---

## 6. Local GCS Connector API

Use a versioned local API over loopback.

Example:

```text
PUT  /v1/missions/{vehicle_id}
PUT  /v1/vehicles/{vehicle_id}
POST /v1/operator-intents
GET  /v1/operations/{operation_id}
GET  /v1/vehicles/{vehicle_id}/status
GET  /v1/events
GET  /v1/health
```

Prefer commands representing **operator intent**:

```text
SUBMIT_OPERATION
START_OPERATION
CANCEL_OPERATION
COMPLETE_OPERATION
ACKNOWLEDGE_WARNING
```

Avoid leaking backend-specific commands such as:

```text
CreateFlightDeclaration
StartNetworkRID
UpdateDSSOperation
```

Those belong inside the backend adapter.

Every request should include:

- schema version
- correlation ID
- timestamp
- explicit units where relevant

---

## 7. Flight Blender Backend Adapter

Create a hand-written interface such as:

```python
class UTMBackend:
    async def submit_operation(...)
    async def update_operation(...)
    async def cancel_operation(...)
    async def publish_telemetry(...)
    async def fetch_authorization_state(...)
    async def fetch_conformance_state(...)
```

Then implement:

```text
FlightBlenderBackend
```

Do not expose generated OpenAPI types outside the backend adapter.

Pin the Flight Blender API definition with:

```text
specification.yaml
source-commit.txt
specification.sha256
generated/
```

Rules:

- no API download during normal builds
- no code generation during normal builds
- upgrades are explicit
- generated classes are wrapped by hand-written code
- compatibility changes require tests

---

## 8. Mission Planner Integration

Use a minimal runtime plugin.

Structure:

```text
MissionPlannerPluginEntry
        |
        v
IMissionPlannerFacade
        |
        v
MissionPlannerAdapter
        |
        v
Local Connector API
```

Only the facade layer may reference Mission Planner types.

The adapter should primarily handle:

- current mission snapshot
- selected vehicle
- operator actions
- connector status
- warnings

Prefer direct MAVLink ingestion for continuous telemetry where possible.

Build against a pinned Mission Planner release and verify its artifact checksum.

Publish an explicit compatibility range.

---

## 9. QGroundControl Integration

Avoid maintaining a QGroundControl fork initially.

Phase 1:

```text
QGC .plan
   +
MAVLink UDP
   |
   v
Connector
```

Use passive MAVLink observation for:

- vehicle telemetry
- connection status
- mission progress
- onboard mission state

Only pursue native QGC UI integration if operational use proves it necessary.

---

## 10. MAVLink Routing

Support both:

```text
direct UDP input
```

and:

```text
mavlink-router
```

Example:

```text
Autopilot
   |
   v
MAVLink Router
   +--> QGroundControl
   +--> Mission Planner
   +--> UTM Connector
   +--> Recorder
```

Treat the router as an optional deployment component, not as a hard dependency.

Document:

- network binding
- port configuration
- multicast/broadcast behavior
- firewall expectations
- security assumptions
- duplicate stream handling

---

## 11. Record and Replay

Implement record/replay from the beginning.

Record:

```text
raw MAVLink
canonical domain events
backend requests
backend responses
operation state transitions
authorization transitions
conformance events
operator actions
diagnostics
```

Use a common monotonic/event timestamp model.

Recommended local formats:

```text
flight.tlog
connector-events.jsonl
utm-events.jsonl
operation-metadata.json
```

Replay must feed the same core engines used in live operation.

Benefits:

- deterministic debugging
- reproducible incident analysis
- regression testing
- backend compatibility testing
- conformance investigation
- performance tuning
- training/demo playback

---

## 12. Security

Initial requirements:

- connector API binds to loopback by default
- local adapters authenticate
- backend credentials stored in OS credential store
- no plaintext secrets in logs
- redact OAuth tokens
- no implicit authentication bypass
- backend TLS validation enabled
- strict dependency pinning
- signed release artifacts where practical
- Mission Planner/QGC integrations have least privilege
- no remote command/control of aircraft unless explicitly enabled

MAVLink observation should be read-only by default.

Active vehicle commands should require a separate capability flag and are not part of the initial UTM connector scope.

---

## 13. Testing Strategy

## 13.1 Unit Tests

Test:

- MAVLink message mapping
- timestamp normalization
- altitude conversions
- Pydantic validation
- telemetry quality transitions
- operation state transitions
- backend mapping
- identity association

---

## 13.2 Property-Based Geometry Tests

Using Hypothesis:

- every waypoint remains inside generated corridor
- geometry output is valid
- repeated conversion is deterministic
- no lat/lon inversion
- all polygon rings remain valid
- geometry splitting preserves coverage
- altitude ordering remains valid
- metre-based buffer tolerances are respected

---

## 13.3 Golden Tests

Equivalent missions from:

```text
Mission Planner
QGroundControl .plan
MAVLink mission protocol
```

must produce equivalent canonical mission representations and equivalent operation geometry.

---

## 13.4 Backend Contract Tests

For each backend adapter:

- known API revision
- successful authentication
- operation submission
- rejection mapping
- authorization mapping
- telemetry publication
- retry behavior
- API timeout behavior
- schema mismatch behavior
- rate-limit behavior

---

## 13.5 SITL End-to-End Tests

Recommended scenarios:

### ArduPilot

```text
ArduPilot SITL
   |
Mission Planner / MAVLink
   |
Connector
   |
Flight Blender
```

### PX4

```text
PX4 SITL
   |
QGroundControl / MAVLink
   |
Connector
   |
Flight Blender
```

Test:

- successful operation
- mission amendment
- mission drift
- telemetry loss
- GNSS degradation
- route deviation
- authorization rejection
- backend outage
- reconnect
- source ownership transfer

---

## 13.6 Conformance Violation Test

Create a deliberate deviation:

```text
authorized route
       |
       v
aircraft deviates beyond threshold
       |
       v
connector detects non-conformance
       |
       v
Flight Blender / backend event
       |
       v
operator warning
```

The test must verify the full operational loop.

---

## 14. Observability

Expose:

```text
connector uptime
active MAVLink vehicles
heartbeat age
position age
telemetry quality
telemetry queue depth
published telemetry rate
backend request latency
backend error rate
authorization state
conformance state
mission hash mismatch
last successful backend contact
```

Use structured logs with correlation IDs.

Recommended event fields:

```text
timestamp
monotonic_time
vehicle_id
operation_id
correlation_id
source
event_type
severity
state_before
state_after
```

---

## 15. KX / kdb+ Extension

Do not require kdb+ for the desktop MVP.

Introduce it as an optional high-volume analytics backend.

Potential stream:

```text
raw MAVLink
canonical telemetry
operation state
authorization state
conformance events
backend events
```

Use cases:

- fleet-level temporal analysis
- geospatial deviation queries
- incident reconstruction
- telemetry quality analytics
- provider SLA monitoring
- cross-flight comparison
- near-real-time fleet risk dashboards
- long-term regulatory evidence
- replay of selected time windows

Example analytical query:

```text
Find every aircraft that exceeded its authorized corridor
by more than 20 metres while telemetry quality was GOOD,
and return the 30 seconds of vehicle state preceding the event.
```

---

## 16. Delivery Phases

## Phase 0 — Foundations

Deliver:

- repository structure
- canonical Pydantic models
- logging/correlation model
- connector configuration
- local FastAPI skeleton
- pinned backend specification
- test harness
- CI

Exit criteria:

- connector starts locally
- schemas validate
- tests run in CI
- backend API revision is reproducible

---

## Phase 1 — MAVLink Ingestion

Deliver:

- `pymavlink` gateway
- vehicle discovery
- heartbeat tracking
- position ingestion
- GPS quality
- basic vehicle identity
- telemetry aggregator
- telemetry quality model

Exit criteria:

- ArduPilot SITL detected
- PX4 SITL detected
- stable canonical telemetry generated
- stale/lost telemetry detected

---

## Phase 2 — Mission Model and Geometry

Deliver:

- Mission Planner mission adapter
- QGC `.plan` parser
- MAVLink mission reader
- canonical mission model
- Shapely/pyproj corridor generation
- altitude datum handling
- geometry invariants
- mission hashing

Exit criteria:

- equivalent mission sources produce equivalent canonical output
- no silent altitude inference
- geometry property tests pass

---

## Phase 3 — Flight Blender Integration

Deliver:

- OAuth handling
- Flight Blender backend gateway
- operation submission
- operation update/cancel
- telemetry upload
- authorization-state mapping
- conformance-state mapping
- retry/backoff
- diagnostics

Exit criteria:

- complete SITL -> connector -> Flight Blender flow
- successful telemetry publication
- state mappings verified

---

## Phase 4 — Mission Planner UX

Deliver:

- thin Mission Planner plugin
- submit/start/cancel/complete actions
- compact authorization status
- conformance warnings
- connector health indication

Exit criteria:

- plugin works against pinned Mission Planner release
- plugin does not contain backend-specific logic

---

## Phase 5 — QGroundControl Zero-Fork Integration

Deliver:

- QGC `.plan` import
- MAVLink UDP ingestion
- optional mavlink-router documentation
- QGC-specific test fixtures

Exit criteria:

- QGC can operate with no custom fork
- connector receives mission and live telemetry

---

## Phase 6 — Record/Replay and Drift Detection

Deliver:

- raw MAVLink recording
- canonical event journal
- backend event journal
- deterministic replay
- mission hash comparison
- operator warning on drift

Exit criteria:

- recorded flights replay through the same state machine
- mission drift is detected reliably

---

## Phase 7 — Advanced Conformance and Analytics

Deliver:

- richer telemetry quality
- projected-path conformance
- geofence intersections
- provider-neutral backend interface hardening
- optional kdb+ stream export
- fleet-level analytics

Exit criteria:

- multiple backend implementations can be added without changing GCS adapters
- high-volume analytics is decoupled from flight-critical desktop behavior

---

## 17. Suggested Repository Structure

```text
utm-operations-connector/
|
+-- src/
|   +-- connector/
|   |   +-- api/
|   |   +-- domain/
|   |   +-- mavlink/
|   |   +-- telemetry/
|   |   +-- missions/
|   |   +-- geometry/
|   |   +-- conformance/
|   |   +-- state/
|   |   +-- backends/
|   |   |   +-- base.py
|   |   |   +-- flight_blender/
|   |   +-- persistence/
|   |   +-- replay/
|   |   +-- observability/
|   |
|   +-- adapters/
|       +-- mission_planner/
|       +-- qgroundcontrol/
|
+-- specs/
|   +-- flight_blender/
|       +-- specification.yaml
|       +-- source-commit.txt
|       +-- specification.sha256
|
+-- tests/
|   +-- unit/
|   +-- property/
|   +-- golden/
|   +-- integration/
|   +-- sitl/
|
+-- fixtures/
|   +-- missions/
|   +-- mavlink/
|   +-- flight_blender/
|
+-- docs/
|   +-- architecture.md
|   +-- security.md
|   +-- altitude-model.md
|   +-- deployment.md
|   +-- mavlink-routing.md
|
+-- tools/
|   +-- replay/
|   +-- sitl/
|
+-- pyproject.toml
+-- README.md
```

---

## 18. Non-Goals for the Initial Release

Do not include initially:

- direct aircraft flight control
- autonomous mission rewriting
- mandatory QGroundControl fork
- mandatory cloud deployment
- mandatory kdb+ deployment
- custom MAVLink dialect unless proven necessary
- multi-USSP orchestration
- automatic legal interpretation of authorization
- silent altitude conversion
- silent telemetry-source switching

---

## 19. Key Design Decisions

### Decision 1

Use `pymavlink` for production MAVLink ingestion.

### Decision 2

Use MAVSDK primarily for automated vehicle/SITL testing and optional high-level control tooling.

### Decision 3

Use Shapely + pyproj for mission and operational-volume geometry.

### Decision 4

Keep Flight Blender behind a backend adapter.

### Decision 5

Keep canonical domain objects provider-neutral and GCS-neutral.

### Decision 6

Prefer zero-fork QGroundControl integration initially.

### Decision 7

Make record/replay a core capability rather than a later debugging add-on.

### Decision 8

Treat telemetry quality as a first-class safety signal.

### Decision 9

Detect onboard mission drift from the submitted UTM operation.

### Decision 10

Separate declaration, authorization, telemetry, connectivity, and conformance state.

---

## 20. Final Target

The final system should behave less like a simple API bridge and more like a **provider-neutral operational interoperability layer**.

```text
Mission Planner
QGroundControl
Future GCS
Direct MAVLink
External telemetry
        |
        v
+--------------------------------------+
| UTM Operations Connector             |
|                                      |
| Canonical mission model              |
| Canonical telemetry model            |
| MAVLink gateway                      |
| Identity mapping                     |
| Geometry engine                      |
| Telemetry quality                    |
| Authorization lifecycle              |
| Conformance engine                   |
| Mission drift detection              |
| Record / replay                      |
| Security / observability             |
+-------------------+------------------+
                    |
                    v
            Backend Adapter API
                    |
          +---------+---------+
          |                   |
          v                   v
  Flight Blender       Future backend
          |
          v
 ASTM / InterUSS / U-space ecosystem
```

This architecture preserves the pragmatic strengths of the Flight Blender GCS connector plan while incorporating the provider-neutrality of Dronecode's UTM adapter concept and adding a much stronger MAVLink, telemetry-quality, mission-integrity, testability, and analytics foundation.
