## GCS configuration

This directory contains the provider metadata and the zero-fork connector
contract used by a GCS integration.

- [`product.json`](product.json) describes the UTM/USSP capabilities shown in
  the GCS product configuration.
- [`connector-manifest.json`](connector-manifest.json) describes the local
  connector API and browser operator console. It is intentionally
  provider-neutral and can be consumed by a thin QGroundControl or other GCS
  adapter without modifying the stock flight-control application.
- [`../examples/qgroundcontrol-custom-build/`](../examples/qgroundcontrol-custom-build/)
  contains an optional native Fly View status overlay for a QGroundControl
  custom build. A stock QGroundControl binary cannot load this resource as a
  loose runtime plugin.

The live service exposes the same contract at `GET /v1/integration`. The
relative paths in the manifest are resolved against the connector origin, for
example `http://127.0.0.1:8000/v1/integration`. Opening the service root
(`http://127.0.0.1:8000/`) redirects to the operator console.

Run `make manifest-check` after changing integration endpoints or mission
capabilities. It verifies that this checked-in GCS manifest still matches the
runtime contract served by the connector.

The connector is non-commanding with respect to vehicle control: MAVLink is
used for telemetry and optional onboard-mission download, while operation
submit/start/cancel/complete actions are UTM-side API intents. Use the
single-router topology in `examples/mavlink-router/` when the GCS and
connector need to observe the same vehicle link.

## Definitions 

The adapter containts specific terms as defined in the [interuss/monitoring](https://github.com/interuss/monitoring) test suite. The specific definitions and 

### Flight Authorization
The capabilities of [Flight Authorization](https://github.com/interuss/automated_testing_interfaces/blob/8c83e2735c762f6fee8d6ca62ee1c1c0d479512c/scd/v1/scd.yaml) match the ones defined in `interuss/monitoring`

- `FlightAuthorisationValidation`: USS supports EU flight authorisation parameter validation.
- `BasicStrategicConflictDetection`: USS supports strategic conflict detection for typical flights, including future planning (Accepted
operational intents), activation (Accepted operational intents), and closing (deleting the operational intent reference).
- `HighPriorityFlights`: USS supports flights at priority levels higher than typical flights.

### Network Remote ID
