# QGroundControl custom-build overlay

This example adds a native UTM workflow card to QGroundControl's Fly View. It
is intended for operators who want UTM readiness and approval actions visible
beside the normal flight controls while keeping all vehicle control inside
QGroundControl. The card shows connector health, vehicle telemetry quality,
onboard mission drift status, the latest UTM operation state, and buttons to
submit the current QGC plan and send UTM operation intents.

This is a **custom-build integration**, not a loose plugin for the stock
QGroundControl binary. QGroundControl's supported extension path is a custom
build using its plugin/resource override mechanisms. The two files in this
directory are designed to be copied into a QGroundControl custom build (or
merged into an existing custom build):

- `src/FlyViewCustomLayer.qml` provides the status card and opens the connector
  console, uploads the active QGC plan, and sends UTM operation intents.
- `src/UtmConnectorBridge.h/.cc` provides the Qt HTTP bridge used by the card.
- `utm_connector.qrc` registers the resource override under QGC's `/Custom`
  prefix.
- `CMakeLists.fragment.cmake` adds that resource to the executable through
  QGC's `CUSTOM_RESOURCES`/`QGC_RESOURCES` mechanism.

The overlay reads:

- `GET /v1/health`
- `GET /v1/vehicles`
- `GET /v1/vehicles/{vehicle_id}/status`

The **Submit current plan** button sends the plan produced by QGC's active
`PlanMasterController` to:

- `PUT /v1/missions/{vehicle_id}/qgroundcontrol`
- `POST /v1/operator-intents?vehicle_id={vehicle_id}` for submit, start,
  cancel, and complete actions

The **Open UTM** button opens `/ui/` in the system browser. The custom build
does not send MAVLink commands, upload the mission to the aircraft, arm, take
off, or change flight modes. QGroundControl/autopilot remain the flight-control
authority. The card uses a future 30-minute UTM validity window and a 30 m
corridor; operators can use the full web console when they need to edit those
values.
With the default URL it probes the standalone connector on port `8000` and
automatically falls back to the supervised full-stack connector on `8001`.

## Use it in a QGroundControl custom build

For the easiest setup, stage an isolated copy of QGC's upstream custom example:

```sh
uv run python scripts/stage_qgc_custom_build.py \
  --qgc-source ../qgroundcontrol
```

The command creates `../qgroundcontrol/custom-utm-connector`, leaves the stock
`custom-example` and installed QGroundControl untouched, and prints the exact
CMake commands. Re-run with `--force` only when the generated directory is the
one you want to replace; the old generated directory is moved to a timestamped
backup first. The generated build keeps QGC's normal ArduPilot factory enabled
so an existing ArduPilot-based GCS workflow is not silently removed. The
equivalent convenience check is `make qgc-stage`.

The generated build reuses QGC's existing `custom.qrc` Fly View alias, so no
manual resource merge is needed. If you already maintain a different custom
build, use the manual overlay merge below instead.

1. Start the connector, for example with `uv run utm-connector --demo`.
2. Copy `src/FlyViewCustomLayer.qml`, `src/UtmConnectorBridge.h`, and
   `src/UtmConnectorBridge.cc` into the QGroundControl custom-build source
   tree. Add the bridge files to `CUSTOM_SOURCES`, add the
   `UtmConnectorBridge* utmConnector` property/getter to the custom plugin,
   construct it in the plugin, and merge `CMakeLists.fragment.cmake` into that
   build's `CMakeLists.txt`. The staging script automates these edits.
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
   release. To have the supervised demo launch that binary directly, use
   `--gcs qgroundcontrol --qgroundcontrol-command /path/to/Custom-QGroundControl`
   (or set `QGROUNDCONTROL_COMMAND`). The stock QGC binary does not need to be
   rebuilt for the normal connector demo.

The stock QGroundControl binary and the provider-neutral files in
`qgcs-config/` remain useful without rebuilding QGroundControl: use the
browser console or a thin GCS adapter against `GET /v1/integration`.

## Single-router topology

For a real vehicle, connect the vehicle radio/UDP endpoint to one MAVLink
router and give QGroundControl and the connector separate router outputs. The
connector remains telemetry/mission-download only; QGroundControl remains the
flight-control authority. See [`examples/mavlink-router/README.md`](../mavlink-router/README.md).
