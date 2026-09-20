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
- `utm_connector.qrc` registers the resource override under QGC's `/Custom`
  prefix.
- `CMakeLists.fragment.cmake` adds that resource to the executable through
  QGC's `CUSTOM_RESOURCES`/`QGC_RESOURCES` mechanism.

The overlay reads only:

- `GET /v1/health`
- `GET /v1/vehicles`
- `GET /v1/vehicles/{vehicle_id}/status`

The **Open UTM** button opens `/ui/` in the system browser. It does not send
MAVLink commands, upload missions, arm, take off, or change flight modes.
With the default URL it probes the standalone connector on port `8000` and
automatically falls back to the supervised full-stack connector on `8001`.

## Use it in a QGroundControl custom build

1. Start the connector, for example with `uv run utm-connector --demo`.
2. Copy `src/FlyViewCustomLayer.qml` and `utm_connector.qrc` into the
   QGroundControl custom-build source tree, then merge
   `CMakeLists.fragment.cmake` into that build's `CMakeLists.txt`.
3. Keep the stock `CustomOverrideInterceptor` from QGC's custom-example (it
   installs the `/Custom` URL interceptor). If an existing custom build has
   replaced it, retain the equivalent `addUrlInterceptor` mapping.
4. Change `connectorBaseUrl` in the QML file only when the connector is not
   running on the local machine or uses a different port. The default covers
   both the standalone and supervised demo ports.
5. From the adapter checkout, validate the source contract before building:

   ```sh
   uv run python scripts/check_qgc_overlay.py --qgc-source /path/to/qgroundcontrol --strict
   ```

6. Build and run the resulting QGroundControl custom binary. The native build
   needs the Qt version and compiler toolchain required by the pinned QGC
   release; the stock QGC binary does not need to be rebuilt for the normal
   connector demo.

The stock QGroundControl binary and the provider-neutral files in
`qgcs-config/` remain useful without rebuilding QGroundControl: use the
browser console or a thin GCS adapter against `GET /v1/integration`.

## Single-router topology

For a real vehicle, connect the vehicle radio/UDP endpoint to one MAVLink
router and give QGroundControl and the connector separate router outputs. The
connector remains telemetry/mission-download only; QGroundControl remains the
flight-control authority. See [`examples/mavlink-router/README.md`](../mavlink-router/README.md).
