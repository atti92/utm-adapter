const state = {
  vehicleId: "",
  plan: null,
  planFormat: "qgroundcontrol",
  planName: "",
  mission: null,
  operation: null,
  latestStatus: null,
  capabilities: null,
  windowCustomized: false,
};

const DEMO_LEAD_TIME_MS = 15_000;
const TERMINAL_DECLARATIONS = new Set(["COMPLETED", "CANCELLED", "REJECTED"]);
let refreshInFlight = false;
let missionReadInFlight = false;
const intentInFlight = new Set();

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  }[character]));
}

function setMessage(message, kind = "") {
  const element = $("action-message");
  element.textContent = message;
  element.dataset.kind = kind;
}

function formatDate(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString([], { dateStyle: "short", timeStyle: "medium" });
}

function formatStatus(value) {
  return value ? String(value).replace(/_/g, " ") : "—";
}

function statusTone(value) {
  if (["LOST", "INVALID"].includes(value)) return "error";
  if (["DEGRADED", "STALE", "UNKNOWN"].includes(value)) return "warning";
  if (["GOOD", "CONNECTED", "ONLINE"].includes(value)) return "ok";
  return "neutral";
}

function localInputValue(date) {
  const offset = date.getTimezoneOffset();
  return new Date(date.getTime() - offset * 60000).toISOString().slice(0, 16);
}

function setDefaultWindow() {
  const start = new Date(Date.now() + DEMO_LEAD_TIME_MS);
  const end = new Date(Date.now() + 35 * 60_000);
  $("valid-from").value = localInputValue(start);
  $("valid-until").value = localInputValue(end);
  state.windowCustomized = false;
}

function inputAsIso(id) {
  const value = $(id).value;
  if (!value) throw new Error(`${id === "valid-from" ? "Valid from" : "Valid until"} is required.`);
  return new Date(value).toISOString();
}

function validateMissionWindow() {
  const validFrom = new Date(inputAsIso("valid-from"));
  const validUntil = new Date(inputAsIso("valid-until"));
  if (validUntil <= validFrom) throw new Error("Valid until must be later than valid from.");

  const constraints = state.capabilities?.mission_window || {};
  const now = Date.now();
  if (constraints.requires_future_start && validFrom.getTime() <= now) {
    throw new Error("Flight Blender requires the operation to start in the future. Move Valid from forward and try again.");
  }
  if (Number.isFinite(constraints.max_future_seconds)) {
    const latest = now + Number(constraints.max_future_seconds) * 1000;
    if (validFrom.getTime() > latest || validUntil.getTime() > latest) {
      throw new Error("This provider accepts declaration times only within the next two days.");
    }
  }
  return { validFrom, validUntil };
}

function missionMatchesForm() {
  const mission = state.mission?.mission;
  if (!mission) return false;
  try {
    const { validFrom, validUntil } = validateMissionWindow();
    return Math.abs(validFrom.getTime() - new Date(mission.valid_from).getTime()) < 1000
      && Math.abs(validUntil.getTime() - new Date(mission.valid_until).getTime()) < 1000
      && Math.abs(Number($("corridor-radius").value) - Number(mission.corridor_radius_m)) < 0.001;
  } catch (_error) {
    return false;
  }
}

function updateMissionActionState() {
  const preview = state.mission?.mission_hash === "preview";
  const saved = Boolean(state.mission && !preview);
  const dirty = saved && !missionMatchesForm();
  const declaration = state.operation?.state?.declaration;
  const operationOpen = Boolean(declaration && !TERMINAL_DECLARATIONS.has(declaration));
  $("save-button").disabled = !state.vehicleId || !state.plan || operationOpen;
  $("submit-button").disabled = !state.vehicleId || !saved || dirty || operationOpen;
  if (dirty && document.activeElement?.id !== "submit-button") {
    setMessage("Mission settings changed. Validate & save before submitting.");
  }
  updateMissionReadButton();
}

function renderNextAction() {
  const element = $("operation-next-action");
  const text = $("operation-next-action-text");
  if (!element || !text) return;

  let message = "Select a vehicle and load a mission to begin.";
  let stateName = "neutral";
  const declaration = state.operation?.state?.declaration;
  const telemetryPublication = state.operation?.state?.telemetry_publication;
  const conformance = state.operation?.state?.conformance;
  const connectionState = state.latestStatus?.vehicle_state?.connection_state;
  const telemetryQuality = state.latestStatus?.vehicle_state?.quality;

  if (!state.vehicleId) {
    message = "Connect a vehicle or start the simulator, then select it above.";
  } else if (connectionState === "LOST") {
    message = "Vehicle link lost. Restore the GCS/router link before starting or completing the operation.";
    stateName = "warning";
  } else if (["DEGRADED", "UNKNOWN"].includes(connectionState) || ["DEGRADED", "STALE", "LOST", "INVALID"].includes(telemetryQuality)) {
    message = "Vehicle telemetry is degraded. Review the GCS link and telemetry quality before continuing.";
    stateName = "warning";
  } else if (!state.plan && !state.mission) {
    message = "Load a QGroundControl or Mission Planner mission, or choose Sample route.";
  } else if (state.mission?.mission_hash === "preview") {
    message = "Review the validity window and corridor, then choose Validate & save.";
  } else if (state.mission && !missionMatchesForm()) {
    message = "Mission settings changed. Validate & save before submitting to UTM.";
    stateName = "warning";
  } else if (!state.operation) {
    message = "Mission is ready. Choose Submit to UTM to request authorization.";
  } else if (["REJECTED", "CANCELLED"].includes(declaration)) {
    message = "This operation is closed. Load and validate another mission to continue.";
    stateName = "warning";
  } else if (declaration === "COMPLETED") {
    message = "Operation completed. The vehicle remains under GCS control; load the next mission when ready.";
    stateName = "ok";
  } else if (declaration === "ACCEPTED" && telemetryPublication === "NOT_STARTED") {
    const startsAt = state.mission?.mission?.valid_from ? new Date(state.mission.mission.valid_from) : null;
    message = startsAt && startsAt > new Date()
      ? `Authorized. Choose Start operation; telemetry will publish when the window opens at ${formatDate(startsAt)}.`
      : "Authorized. Choose Start operation when the vehicle is ready.";
    stateName = "ok";
  } else if (telemetryPublication === "ACTIVE" && conformance === "CONFORMING") {
    message = "Operation is live and conforming. Complete it when the flight has finished.";
    stateName = "ok";
  } else if (telemetryPublication === "ACTIVE") {
    message = "Operation is live. Review the telemetry and conformance state before continuing.";
    stateName = "warning";
  } else {
    message = "Review the operation state and recent events for the next available action.";
  }

  element.dataset.state = stateName;
  text.textContent = message;
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "content-type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(body.detail || `${response.status} ${response.statusText}`);
    error.status = response.status;
    throw error;
  }
  return body;
}

function setConnection(status, label) {
  $("connection-pill").dataset.state = status;
  $("connection-label").textContent = label;
}

function setReadiness(id, labelId, state, label) {
  $(id).dataset.state = state;
  $(labelId).textContent = label;
}

function clearVehicleWorkspace(message = "") {
  state.plan = null;
  state.mission = null;
  state.operation = null;
  state.latestStatus = null;
  state.planName = "";
  $("plan-file").value = "";
  renderMission(null);
  renderMissionDrift(null);
  renderOperation(null);
  if (message) setMessage(message);
}

function renderReadiness(capabilities, vehicles, health) {
  const backend = capabilities.backend || "unknown";
  if (health?.backend_error) {
    setReadiness("backend-readiness", "backend-readiness-label", "warning", "Provider error");
  } else if (health?.status !== "ok") {
    setReadiness("backend-readiness", "backend-readiness-label", "warning", "Connector degraded");
  } else {
    setReadiness("backend-readiness", "backend-readiness-label", "ok", formatStatus(backend));
  }

  const lostVehicles = vehicles.filter((vehicle) => vehicle.connection_state === "LOST");
  const degradedVehicles = vehicles.filter((vehicle) => ["DEGRADED", "UNKNOWN"].includes(vehicle.connection_state));
  if (lostVehicles.length) {
    const suffix = lostVehicles.length === 1 ? "vehicle link lost" : "vehicle links lost";
    setReadiness("mavlink-readiness", "mavlink-readiness-label", "warning", `${lostVehicles.length} ${suffix}`);
  } else if (degradedVehicles.length) {
    const suffix = degradedVehicles.length === 1 ? "vehicle link degraded" : "vehicle links degraded";
    setReadiness("mavlink-readiness", "mavlink-readiness-label", "warning", `${degradedVehicles.length} ${suffix}`);
  } else if (capabilities.demo_mode) {
    setReadiness("mavlink-readiness", "mavlink-readiness-label", "ok", "Demo vehicle mode");
  } else if (!capabilities.mavlink?.configured) {
    setReadiness("mavlink-readiness", "mavlink-readiness-label", "warning", "No vehicle link configured");
  } else if (vehicles.length) {
    const suffix = vehicles.length === 1 ? "vehicle online" : "vehicles online";
    setReadiness("mavlink-readiness", "mavlink-readiness-label", "ok", `${vehicles.length} ${suffix}`);
  } else {
    setReadiness("mavlink-readiness", "mavlink-readiness-label", "warning", "Waiting for vehicle");
  }

  setReadiness(
    "recording-readiness",
    "recording-readiness-label",
    capabilities.recording?.mavlink_raw ? "ok" : "neutral",
    capabilities.recording?.mavlink_raw ? "Raw capture enabled" : "Raw capture off",
  );

  const altitude = capabilities.altitude || {};
  if (backend === "flight-blender" && !altitude.geoid_conversion_configured) {
    setReadiness("altitude-readiness", "altitude-readiness-label", "warning", "Geoid grid required");
  } else if (altitude.geoid_conversion_configured) {
    setReadiness("altitude-readiness", "altitude-readiness-label", "ok", "AMSL ↔ WGS84 ready");
  } else {
    setReadiness("altitude-readiness", "altitude-readiness-label", "neutral", "Not needed locally");
  }

  if (capabilities.mavlink?.non_commanding && capabilities.mavlink?.read_only) {
    setReadiness("control-readiness", "control-readiness-label", "ok", "GCS remains in control");
  } else {
    setReadiness("control-readiness", "control-readiness-label", "warning", "Review command boundary");
  }
}

function renderVehicleDirectory(vehicles) {
  const select = $("vehicle-select");
  const previous = state.vehicleId;
  select.replaceChildren();
  if (!vehicles.length) {
    select.add(new Option("Waiting for a vehicle…", ""));
    if (previous) clearVehicleWorkspace("The selected vehicle went offline. Load a mission after it reconnects.");
    state.vehicleId = "";
    renderVehicle(null);
    updateMissionReadButton();
    return;
  }
  vehicles.forEach((vehicle) => select.add(new Option(vehicle.vehicle_id, vehicle.vehicle_id)));
  const nextVehicleId = vehicles.some((vehicle) => vehicle.vehicle_id === previous) ? previous : vehicles[0].vehicle_id;
  if (previous && previous !== nextVehicleId) {
    clearVehicleWorkspace("The selected vehicle changed. Load a mission for the new vehicle.");
  }
  state.vehicleId = nextVehicleId;
  select.value = state.vehicleId;
  const vehicle = vehicles.find((item) => item.vehicle_id === state.vehicleId);
  renderVehicle(vehicle);
  updateMissionReadButton();
}

function updateMissionReadButton() {
  const button = $("read-mission-button");
  const configured = Boolean(state.capabilities?.mavlink?.configured);
  const savedMission = Boolean(state.mission?.mission_hash && state.mission.mission_hash !== "preview");
  const missionReady = savedMission && missionMatchesForm();
  button.disabled = !state.vehicleId || !configured || !missionReady || missionReadInFlight;
  button.textContent = missionReadInFlight ? "Checking vehicle mission…" : "Check vehicle mission";
  button.title = !configured
    ? "Configure a MAVLink vehicle link to read the onboard mission."
    : !missionReady
      ? "Validate and save the mission before checking the vehicle's onboard route."
      : "Request the current mission from the vehicle over the read-only MAVLink mission protocol.";
}

function renderVehicle(vehicle) {
  const element = $("vehicle-summary");
  if (!vehicle) {
    element.innerHTML = '<div class="empty-state">Start the connector with a simulator or router to see a vehicle here.</div>';
    return;
  }
  element.innerHTML = `<div class="vehicle-card">
    <div><strong>${escapeHtml(vehicle.vehicle_id)}</strong><br /><small>MAVLink system ${escapeHtml(vehicle.mavlink_system_id || "not discovered")}</small></div>
    <div class="vehicle-state" data-state="${statusTone(vehicle.connection_state)}">${escapeHtml(formatStatus(vehicle.connection_state))}</div>
    <div><small>Last telemetry: ${escapeHtml(formatDate(vehicle.latest_telemetry_at))}</small></div>
    <div class="vehicle-state" data-state="${statusTone(vehicle.quality)}">${escapeHtml(formatStatus(vehicle.quality))}</div>
  </div>`;
}

function renderVehicleStatus(status) {
  const snapshot = status?.vehicle_state;
  if (!snapshot) return;
  const health = snapshot.health || {};
  const battery = health.battery_remaining_pct == null
    ? "—"
    : `${Number(health.battery_remaining_pct).toFixed(0)}%${health.battery_voltage_v == null ? "" : ` · ${Number(health.battery_voltage_v).toFixed(1)} V`}`;
  const gps = health.satellites_visible == null
    ? "—"
    : `${health.satellites_visible} sats${health.gps_fix_type == null ? "" : ` · fix ${health.gps_fix_type}`}`;
  const armState = health.armed == null ? "Unavailable" : health.armed ? "Armed" : "Disarmed";
  const diagnostics = snapshot.diagnostics || [];
  const diagnostic = diagnostics.length ? diagnostics[diagnostics.length - 1] : "";
  $("vehicle-summary").innerHTML = `<div class="vehicle-card">
    <div><strong>${escapeHtml(snapshot.identity.connector_vehicle_id)}</strong><br /><small>MAVLink system ${escapeHtml(snapshot.identity.mavlink_system_id || "not discovered")}</small></div>
    <div class="vehicle-state" data-state="${statusTone(snapshot.connection_state)}">${escapeHtml(formatStatus(snapshot.connection_state))}<br /><small data-state="${statusTone(snapshot.quality)}">${escapeHtml(formatStatus(snapshot.quality))}</small></div>
    <div class="vehicle-metrics">
      <div class="vehicle-metric"><span>Arm state</span><strong>${escapeHtml(armState)}</strong></div>
      <div class="vehicle-metric"><span>GPS</span><strong>${escapeHtml(gps)}</strong></div>
      <div class="vehicle-metric"><span>Battery</span><strong>${escapeHtml(battery)}</strong></div>
    </div>
    <div class="vehicle-diagnostic" title="${escapeHtml(diagnostic || "No vehicle diagnostic received")}"><small>${escapeHtml(diagnostic || "No vehicle diagnostic received")}</small></div>
  </div>`;
}

function renderTelemetry(status) {
  const telemetry = status?.latest_telemetry;
  const badge = $("telemetry-badge");
  if (!telemetry) {
    badge.textContent = "No telemetry";
    badge.className = "badge neutral";
    $("telemetry-grid").innerHTML = ["Position", "Altitude", "Speed", "Quality"].map((label) => `<div><span>${label}</span><strong>—</strong></div>`).join("");
    drawRoute();
    return;
  }
  badge.textContent = formatStatus(telemetry.quality);
  const telemetryClass = telemetry.quality === "GOOD"
    ? ""
    : ["LOST", "INVALID"].includes(telemetry.quality) ? "error" : "warning";
  badge.className = `badge ${telemetryClass}`;
  $("telemetry-grid").innerHTML = `
    <div><span>Position</span><strong>${Number(telemetry.latitude).toFixed(5)}, ${Number(telemetry.longitude).toFixed(5)}</strong></div>
    <div><span>Altitude</span><strong>${Number(telemetry.altitude.meters).toFixed(1)} m ${escapeHtml(formatStatus(telemetry.altitude.datum))}</strong></div>
    <div><span>Speed</span><strong>${telemetry.groundspeed_mps == null ? "—" : `${Number(telemetry.groundspeed_mps).toFixed(1)} m/s`}</strong></div>
    <div><span>Quality</span><strong>${escapeHtml(formatStatus(telemetry.quality))}</strong></div>`;
  drawRoute();
}

function previewWaypoint(latitude, longitude, altitude, datum, sequence) {
  if (![latitude, longitude, altitude].every(Number.isFinite)) return null;
  return {
    sequence,
    latitude,
    longitude,
    altitude: { meters: altitude, datum },
  };
}

function buildPreviewMission() {
  if (!state.plan) return null;
  if (state.planFormat === "canonical") {
    const waypoints = (state.plan.waypoints || []).map((waypoint, index) => previewWaypoint(
      Number(waypoint.latitude), Number(waypoint.longitude), Number(waypoint.altitude?.meters),
      waypoint.altitude?.datum || "UNKNOWN", index,
    )).filter(Boolean);
    return waypoints.length >= 2 ? waypoints : null;
  }
  if (state.planFormat === "mission-planner") {
    const waypoints = [];
    String(state.plan).split(/\r?\n/).slice(1).forEach((line) => {
      const fields = line.trim().split(/\s+/);
      if (fields.length < 11 || ![16, 21, 22].includes(Number(fields[3]))) return;
      const frame = Number(fields[2]);
      const waypoint = previewWaypoint(
        Number(fields[8]), Number(fields[9]), Number(fields[10]),
        [3, 6].includes(frame) ? "AGL" : "AMSL", waypoints.length,
      );
      if (waypoint) waypoints.push(waypoint);
    });
    return waypoints.length >= 2 ? waypoints : null;
  }
  const items = state.plan.mission?.items || [];
  const waypoints = items.filter((item) => [16, 21, 22].includes(Number(item.command))).map((item, index) => {
    const frame = Number(item.frame);
    const params = item.params || [];
    return previewWaypoint(
      Number(params[4]), Number(params[5]), Number(params[6]),
      [3, 6].includes(frame) ? "AGL" : "AMSL", index,
    );
  }).filter(Boolean);
  return waypoints.length >= 2 ? waypoints : null;
}

function renderMission(snapshot) {
  state.mission = snapshot;
  if (!snapshot) {
    renderMissionDrift(null);
    const waypoints = buildPreviewMission();
    if (waypoints) {
      state.mission = {
        mission: {
          source: "operator-console-preview",
          vehicle_id: state.vehicleId,
          corridor_radius_m: Number($("corridor-radius").value),
          waypoints,
        },
        mission_hash: "preview",
      };
      $("mission-title").textContent = `${waypoints.length} waypoint route`;
      $("mission-meta").textContent = `${state.planName || "Mission file"} loaded · validate before submission`;
      $("save-button").disabled = !state.vehicleId || !state.plan;
      $("submit-button").disabled = true;
      drawRoute();
      updateMissionActionState();
      renderNextAction();
      return;
    }
    $("mission-title").textContent = "No mission loaded";
    $("mission-meta").textContent = "Load a QGroundControl .plan or Mission Planner .waypoints file.";
    $("save-button").disabled = !state.plan;
    $("submit-button").disabled = true;
    drawRoute();
    updateMissionActionState();
    renderNextAction();
    return;
  }
  const mission = snapshot.mission;
  $("mission-title").textContent = `${mission.waypoints.length} waypoint route`;
  $("mission-meta").textContent = `${mission.source} · ${mission.corridor_radius_m} m corridor · hash ${snapshot.mission_hash.slice(0, 12)}…`;
  if (!state.windowCustomized) {
    $("valid-from").value = localInputValue(new Date(mission.valid_from));
    $("valid-until").value = localInputValue(new Date(mission.valid_until));
    $("corridor-radius").value = mission.corridor_radius_m;
  }
  $("save-button").disabled = !state.plan;
  drawRoute();
  updateMissionActionState();
  renderNextAction();
}

function renderMissionDrift(report) {
  const element = $("drift-summary");
  if (!report) {
    element.hidden = true;
    element.textContent = "";
    element.dataset.state = "";
    return;
  }
  const classification = formatStatus(report.classification);
  const changedFields = (report.changed_fields || []).map(escapeHtml).join(", ");
  const matches = report.classification === "NO_CHANGE";
  element.hidden = false;
  element.dataset.state = matches ? "ok" : "warning";
  element.innerHTML = `<strong>${matches ? "Vehicle mission matches the submitted route" : `Mission drift detected: ${escapeHtml(classification)}`}</strong>
    <span>${matches ? "No route or altitude changes found." : `Changed fields: ${changedFields || "review the current vehicle mission"}`}</span>
    <small>Checked ${escapeHtml(formatDate(report.checked_at))}</small>`;
}

function renderOperation(operation) {
  state.operation = operation;
  const title = $("operation-title");
  const badge = $("operation-badge");
  if (!operation) {
    title.textContent = "No active operation";
    badge.textContent = "Not submitted";
    badge.className = "badge neutral";
    ["refresh-operation-button", "cancel-button", "complete-button", "start-button"].forEach((id) => { $(id).disabled = true; });
  } else {
    title.textContent = `Operation ${operation.operation_id.slice(0, 8)}…`;
    const declaration = operation.state.declaration;
    badge.textContent = formatStatus(declaration);
    badge.className = `badge ${["CANCELLED", "REJECTED"].includes(declaration) ? "error" : declaration === "COMPLETED" ? "neutral" : ""}`;
    $("refresh-operation-button").disabled = false;
    $("cancel-button").disabled = TERMINAL_DECLARATIONS.has(declaration);
    $("complete-button").disabled = declaration !== "ACCEPTED";
    $("start-button").disabled = declaration !== "ACCEPTED" || operation.state.telemetry_publication !== "NOT_STARTED";
  }
  const values = operation ? operation.state : {};
  const steps = [values.declaration, values.authorization, values.telemetry_publication, values.conformance];
  document.querySelectorAll(".state-step").forEach((step, index) => {
    const value = steps[index];
    step.dataset.state = value === "CONFORMING" || value === "ACCEPTED" || value === "AUTHORIZED" || value === "ACTIVE" ? "ok" : value && ["NON_CONFORMING", "FAILED", "REJECTED"].includes(value) ? "error" : value ? "warning" : "";
    step.querySelector("em").textContent = formatStatus(value);
  });
  updateMissionActionState();
  renderNextAction();
}

function newOperationId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (character) => {
    const random = Math.random() * 16 | 0;
    const value = character === "x" ? random : (random & 0x3 | 0x8);
    return value.toString(16);
  });
}

function drawRoute() {
  const layer = $("route-layer");
  const waypoints = state.mission?.mission?.waypoints || [];
  const telemetry = state.latestStatus?.latest_telemetry;
  if (!waypoints.length) { layer.innerHTML = ""; return; }
  const points = waypoints.map((waypoint) => ({ x: waypoint.longitude, y: waypoint.latitude }));
  if (telemetry) points.push({ x: telemetry.longitude, y: telemetry.latitude });
  const minX = Math.min(...points.map((point) => point.x));
  const maxX = Math.max(...points.map((point) => point.x));
  const minY = Math.min(...points.map((point) => point.y));
  const maxY = Math.max(...points.map((point) => point.y));
  const padX = Math.max((maxX - minX) * 0.22, 0.0002);
  const padY = Math.max((maxY - minY) * 0.22, 0.0002);
  const project = (point) => ({ x: 7 + ((point.x - minX + padX) / (maxX - minX + 2 * padX)) * 86, y: 52 - ((point.y - minY + padY) / (maxY - minY + 2 * padY)) * 44 });
  const projected = waypoints.map((waypoint) => project({ x: waypoint.longitude, y: waypoint.latitude }));
  const path = projected.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(" ");
  const routePoints = projected.map((point, index) => `<circle class="route-point" cx="${point.x.toFixed(2)}" cy="${point.y.toFixed(2)}" r="1.7"><title>Waypoint ${index + 1}</title></circle>`).join("");
  const vehiclePoint = telemetry ? project({ x: telemetry.longitude, y: telemetry.latitude }) : null;
  const vehicleMarkup = vehiclePoint ? `<circle class="vehicle-point" cx="${vehiclePoint.x.toFixed(2)}" cy="${vehiclePoint.y.toFixed(2)}" r="2.4"><title>Vehicle</title></circle>` : "";
  layer.innerHTML = `<path class="route-line" d="${path}" />${routePoints}${vehicleMarkup}`;
}

function renderEvents(events) {
  const list = $("event-list");
  if (!events.length) { list.innerHTML = '<div class="empty-state">No events yet.</div>'; return; }
  list.innerHTML = events.slice(0, 8).map((event) => `<div class="event" data-severity="${escapeHtml(event.severity)}">
    <span class="event-dot"></span><div><strong>${escapeHtml(event.event_type)}</strong><small>${escapeHtml(event.vehicle_id || "connector")}</small></div><time>${escapeHtml(formatDate(event.timestamp))}</time>
  </div>`).join("");
}

async function refreshVehicle() {
  if (!state.vehicleId) return;
  const [status, mission] = await Promise.all([
    request(`/v1/vehicles/${encodeURIComponent(state.vehicleId)}/status`),
    request(`/v1/missions/${encodeURIComponent(state.vehicleId)}`).catch(() => null),
  ]);
  state.latestStatus = status;
  renderVehicleStatus(status);
  renderTelemetry(status);
  renderMission(mission);
  renderMissionDrift(status.mission_drift);
  const operations = status.operations || [];
  renderOperation(operations.length ? operations[operations.length - 1] : null);
}

async function refresh() {
  if (refreshInFlight) return;
  refreshInFlight = true;
  try {
    const [health, capabilities, integration, vehicles, events] = await Promise.all([
      request("/v1/health"), request("/v1/capabilities"), request("/v1/integration"), request("/v1/vehicles"), request("/v1/events?limit=12"),
    ]);
    state.capabilities = capabilities;
    setConnection(health.status === "ok" ? "ok" : "degraded", health.status === "ok" ? "Connector online" : "Connector degraded");
    $("backend-badge").textContent = capabilities.backend;
    $("backend-badge").title = integration.connector?.name || "UTM connector";
    renderReadiness(capabilities, vehicles, health);
    renderVehicleDirectory(vehicles);
    renderEvents(events);
    await refreshVehicle();
  } catch (error) {
    setConnection("error", "Connector unavailable");
    setMessage(error.message, "error");
  } finally {
    refreshInFlight = false;
  }
}

async function checkVehicleMission() {
  if (!state.vehicleId || missionReadInFlight) return;
  if (!state.mission?.mission_hash || state.mission.mission_hash === "preview" || !missionMatchesForm()) {
    setMessage("Validate & save the current mission before checking the vehicle mission.", "error");
    updateMissionReadButton();
    return;
  }
  const vehicleId = state.vehicleId;
  const onboardPath = `/v1/vehicles/${encodeURIComponent(vehicleId)}/onboard-mission`;
  missionReadInFlight = true;
  updateMissionReadButton();
  try {
    await request(`/v1/vehicles/${encodeURIComponent(vehicleId)}/onboard-mission/refresh`, { method: "POST" });
    setMessage("Requested the current mission from the vehicle. Waiting for the MAVLink response…");
    const deadline = Date.now() + 8_000;
    let onboard = null;
    while (Date.now() < deadline) {
      try {
        onboard = await request(onboardPath);
        break;
      } catch (error) {
        if (error.status !== 404) throw error;
      }
      await new Promise((resolve) => setTimeout(resolve, 750));
    }
    await refreshVehicle();
    if (onboard) {
      const count = onboard.mission?.waypoints?.length || 0;
      setMessage(`Vehicle mission received (${count} waypoint${count === 1 ? "" : "s"}). Review the drift result above.`, "success");
    } else {
      setMessage("The vehicle did not return a mission within 8 seconds. Check the MAVLink link and try again.", "error");
    }
  } catch (error) {
    setMessage(error.message, "error");
  } finally {
    missionReadInFlight = false;
    updateMissionReadButton();
  }
}

function samplePlan() {
  const telemetry = state.latestStatus?.latest_telemetry;
  const latitude = Number.isFinite(Number(telemetry?.latitude)) ? Number(telemetry.latitude) : 47.4979;
  const longitude = Number.isFinite(Number(telemetry?.longitude)) ? Number(telemetry.longitude) : 19.0402;
  const altitude = Number.isFinite(Number(telemetry?.altitude?.meters)) ? Number(telemetry.altitude.meters) : 137;
  const datum = telemetry?.altitude?.datum || "WGS84";
  return {
    valid_from: new Date(Date.now() + DEMO_LEAD_TIME_MS).toISOString(),
    valid_until: new Date(Date.now() + 35 * 60_000).toISOString(),
    source: "operator-console-demo",
    waypoints: [
      { sequence: 0, latitude, longitude, altitude: { meters: altitude - 2, datum } },
      { sequence: 1, latitude: latitude + 0.0012, longitude: longitude + 0.0018, altitude: { meters: altitude + 2, datum } },
      { sequence: 2, latitude: latitude + 0.0021, longitude: longitude - 0.0011, altitude: { meters: altitude - 2, datum } },
    ],
  };
}

async function saveMission() {
  if (!state.vehicleId || !state.plan) return;
  try {
    validateMissionWindow();
  } catch (error) {
    setMessage(error.message, "error");
    return;
  }
  const metadata = {
    valid_from: inputAsIso("valid-from"),
    valid_until: inputAsIso("valid-until"),
    corridor_radius_m: Number($("corridor-radius").value),
  };
  if (state.planFormat === "canonical") {
    try {
      const response = await request("/v1/missions/" + encodeURIComponent(state.vehicleId), {
        method: "PUT",
        body: JSON.stringify({ ...state.plan, vehicle_id: state.vehicleId, ...metadata }),
      });
      renderMission(response);
      setMessage("Mission validated and saved locally.", "success");
    } catch (error) { setMessage(error.message, "error"); }
    return;
  }
  if (state.planFormat === "mission-planner") {
    try {
      const response = await request("/v1/missions/" + encodeURIComponent(state.vehicleId) + "/mission-planner", {
        method: "PUT",
        body: JSON.stringify({ ...metadata, text: state.plan }),
      });
      renderMission(response);
      setMessage("Mission validated and saved locally.", "success");
    } catch (error) { setMessage(error.message, "error"); }
    return;
  }
  try {
    const response = await request(`/v1/missions/${encodeURIComponent(state.vehicleId)}/qgroundcontrol`, { method: "PUT", body: JSON.stringify({ valid_from: inputAsIso("valid-from"), valid_until: inputAsIso("valid-until"), corridor_radius_m: Number($("corridor-radius").value), plan: state.plan }) });
    renderMission(response);
    setMessage("Mission validated and saved locally.", "success");
  } catch (error) { setMessage(error.message, "error"); }
}

async function sendIntent(command) {
  if (!state.vehicleId) return;
  if (intentInFlight.has(command)) return;
  intentInFlight.add(command);
  try {
    if (command === "SUBMIT_OPERATION") {
      validateMissionWindow();
      if (!state.mission || state.mission.mission_hash === "preview" || !missionMatchesForm()) {
        throw new Error("Validate & save the current mission before submitting it to UTM.");
      }
    }
    const operationId = command === "SUBMIT_OPERATION"
      ? newOperationId()
      : state.operation?.operation_id;
    if (!operationId) throw new Error("Submit an operation first, then retry this action.");
    const operation = await request(`/v1/operator-intents?vehicle_id=${encodeURIComponent(state.vehicleId)}`, { method: "POST", body: JSON.stringify({ schema_version: "1.0", command, operation_id: operationId }) });
    renderOperation(operation);
    const startsAt = state.mission?.mission?.valid_from ? new Date(state.mission.mission.valid_from) : null;
    const waitingForWindow = command === "START_OPERATION" && startsAt && startsAt > new Date();
    setMessage(
      waitingForWindow
        ? `Operation started. Telemetry will publish automatically when the mission window opens at ${formatDate(startsAt)}.`
        : `${formatStatus(command)} completed.`,
      "success",
    );
    await refresh();
  } catch (error) { setMessage(error.message, "error"); }
  finally { intentInFlight.delete(command); }
}

$("vehicle-select").addEventListener("change", async (event) => {
  state.vehicleId = event.target.value;
  clearVehicleWorkspace(state.vehicleId ? "Vehicle changed. Load or create a mission for this vehicle." : "Select a vehicle to continue.");
  await refreshVehicle();
});
$("sample-button").addEventListener("click", () => {
  state.plan = samplePlan();
  state.planFormat = "canonical";
  state.planName = "Demo route";
  if (!state.windowCustomized) setDefaultWindow();
  renderMission(null);
  setMessage("Demo route loaded. Review the validity window, then validate it.");
});
$("plan-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const text = await file.text();
    state.plan = text.trimStart().startsWith("QGC WPL ") ? text : JSON.parse(text);
    state.planFormat = typeof state.plan === "string" ? "mission-planner" : "qgroundcontrol";
    state.planName = file.name;
    state.mission = null;
    if (!state.windowCustomized) setDefaultWindow();
    renderMission(null);
    setMessage(file.name + " loaded.");
  } catch (error) {
    setMessage("Could not read mission file: " + error.message, "error");
  }
});
$("save-button").addEventListener("click", saveMission);
$("read-mission-button").addEventListener("click", checkVehicleMission);
$("submit-button").addEventListener("click", () => sendIntent("SUBMIT_OPERATION"));
$("start-button").addEventListener("click", () => sendIntent("START_OPERATION"));
$("cancel-button").addEventListener("click", () => sendIntent("CANCEL_OPERATION"));
$("complete-button").addEventListener("click", () => sendIntent("COMPLETE_OPERATION"));
$("refresh-operation-button").addEventListener("click", async () => { if (!state.operation) return; try { renderOperation(await request(`/v1/operations/${state.operation.operation_id}/refresh`, { method: "POST" })); setMessage("Provider state refreshed.", "success"); } catch (error) { setMessage(error.message, "error"); } });
["valid-from", "valid-until", "corridor-radius"].forEach((id) => $(id).addEventListener("input", () => {
  state.windowCustomized = true;
  updateMissionActionState();
  renderNextAction();
}));

setDefaultWindow();
refresh();
setInterval(refresh, 2500);
