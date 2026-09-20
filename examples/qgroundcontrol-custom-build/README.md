# QGroundControl custom-build overlay

This example adds a small native UTM status card to QGroundControl's Fly View.
It is intended for operators who want UTM readiness visible beside the normal
flight controls while keeping all vehicle control inside QGroundControl. The
card shows connector health, vehicle telemetry quality, and the latest UTM
operation state.

This is a **custom-build integration**, not a loose plugin for the stock
QGroundControl binary. QGroundControl's supported extension path is a custom
build using its plugin/resource override mechanisms. The two files in this
directory are designed to be copied into a QGroundControl custom build (or
merged into an existing custom build):

- `src/FlyViewCustomLayer.qml` provides the status card and opens the connector
  console.
- `CMakeLists.fragment.cmake` shows the resource alias required to override
  `QGroundControl/FlyView/FlyViewCustomLayer.qml`.

The overlay reads only:

- `GET /v1/health`
- `GET /v1/vehicles`
- `GET /v1/vehicles/{vehicle_id}/status`

The **Open UTM** button opens `/ui/` in the system browser. It does not send
MAVLink commands, upload missions, arm, take off, or change flight modes.

## Use it in a QGroundControl custom build

1. Start the connector, for example with `uv run utm-connector --demo`.
2. Copy `src/FlyViewCustomLayer.qml` into the QGroundControl custom-build
   source tree and merge `CMakeLists.fragment.cmake` into that build's CMake
   configuration. Keep the resource alias unchanged.
3. Change `connectorBaseUrl` in the QML file if the connector is not running at
   `http://127.0.0.1:8000`.
4. Build and run the resulting QGroundControl custom binary.

The stock QGroundControl binary and the provider-neutral files in
`qgcs-config/` remain useful without rebuilding QGroundControl: use the
browser console or a thin GCS adapter against `GET /v1/integration`.

## Single-router topology

For a real vehicle, connect the vehicle radio/UDP endpoint to one MAVLink
router and give QGroundControl and the connector separate router outputs. The
connector remains telemetry/mission-download only; QGroundControl remains the
flight-control authority. See [`examples/mavlink-router/README.md`](../mavlink-router/README.md).
