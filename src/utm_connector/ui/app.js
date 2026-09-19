const state = {
  vehicleId: "",
  plan: null,
  planFormat: "qgroundcontrol",
  planName: "",
  mission: null,
  operation: null,
  latestStatus: null,
};

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
  return value ? String(value).replaceAll("_", " ") : "—";
}

function localInputValue(date) {
  const offset = date.getTimezoneOffset();
  return new Date(date.getTime() - offset * 60000).toISOString().slice(0, 16);
}

function setDefaultWindow() {
  const start = new Date(Date.now() + 60_000);
  const end = new Date(Date.now() + 35 * 60_000);
  $("valid-from").value = localInputValue(start);
  $("valid-until").value = localInputValue(end);
}

function inputAsIso(id) {
  const value = $(id).value;
  if (!value) throw new Error(`${id === "valid-from" ? "Valid from" : "Valid until"} is required.`);
  return new Date(value).toISOString();
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "content-type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `${response.status} ${response.statusText}`);
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

function renderReadiness(capabilities, vehicles, health) {
  const backend = capabilities.backend || "unknown";
  if (health?.backend_error) {
    setReadiness("backend-readiness", "backend-readiness-label", "warning", "Provider error");
  } else {
    setReadiness("backend-readiness", "backend-readiness-label", "ok", formatStatus(backend));
  }

  if (capabilities.demo_mode) {
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
}

function renderVehicleDirectory(vehicles) {
  const select = $("vehicle-select");
  const previous = state.vehicleId;
  select.replaceChildren();
  if (!vehicles.length) {
    select.add(new Option("Waiting for a vehicle…", ""));
    state.vehicleId = "";
    renderVehicle(null);
    return;
  }
  vehicles.forEach((vehicle) => select.add(new Option(vehicle.vehicle_id, vehicle.vehicle_id)));
  state.vehicleId = vehicles.some((vehicle) => vehicle.vehicle_id === previous) ? previous : vehicles[0].vehicle_id;
  select.value = state.vehicleId;
  const vehicle = vehicles.find((item) => item.vehicle_id === state.vehicleId);
  renderVehicle(vehicle);
}

function renderVehicle(vehicle) {
  const element = $("vehicle-summary");
  if (!vehicle) {
    element.innerHTML = '<div class="empty-state">Start the connector with a simulator or router to see a vehicle here.</div>';
    return;
  }
  element.innerHTML = `<div class="vehicle-card">
    <div><strong>${escapeHtml(vehicle.vehicle_id)}</strong><br /><small>MAVLink system ${escapeHtml(vehicle.mavlink_system_id || "not discovered")}</small></div>
    <div class="vehicle-state">${escapeHtml(formatStatus(vehicle.connection_state))}</div>
    <div><small>Last telemetry: ${escapeHtml(formatDate(vehicle.latest_telemetry_at))}</small></div>
    <div class="vehicle-state">${escapeHtml(formatStatus(vehicle.quality))}</div>
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
  badge.className = `badge ${telemetry.quality === "GOOD" ? "" : "warning"}`;
  $("telemetry-grid").innerHTML = `
    <div><span>Position</span><strong>${Number(telemetry.latitude).toFixed(5)}, ${Number(telemetry.longitude).toFixed(5)}</strong></div>
    <div><span>Altitude</span><strong>${Number(telemetry.altitude.meters).toFixed(1)} m</strong></div>
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
      if (fields.length < 11 || ![16, 22].includes(Number(fields[3]))) return;
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
  const waypoints = items.filter((item) => [16, 22].includes(Number(item.command))).map((item, index) => {
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
      return;
    }
    $("mission-title").textContent = "No mission loaded";
    $("mission-meta").textContent = "Load a QGroundControl .plan or Mission Planner .waypoints file.";
    $("save-button").disabled = !state.plan;
    $("submit-button").disabled = true;
    drawRoute();
    return;
  }
  const mission = snapshot.mission;
  $("mission-title").textContent = `${mission.waypoints.length} waypoint route`;
  $("mission-meta").textContent = `${mission.source} · ${mission.corridor_radius_m} m corridor · hash ${snapshot.mission_hash.slice(0, 12)}…`;
  $("corridor-radius").value = mission.corridor_radius_m;
  $("save-button").disabled = !state.plan;
  $("submit-button").disabled = false;
  drawRoute();
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
    $("cancel-button").disabled = ["CANCELLED", "COMPLETED"].includes(declaration);
    $("complete-button").disabled = declaration !== "ACCEPTED";
    $("start-button").disabled = declaration !== "ACCEPTED";
  }
  const values = operation ? operation.state : {};
  const steps = [values.declaration, values.authorization, values.telemetry_publication, values.conformance];
  document.querySelectorAll(".state-step").forEach((step, index) => {
    const value = steps[index];
    step.dataset.state = value === "CONFORMING" || value === "ACCEPTED" || value === "AUTHORIZED" || value === "ACTIVE" ? "ok" : value && ["NON_CONFORMING", "FAILED", "REJECTED"].includes(value) ? "error" : value ? "warning" : "";
    step.querySelector("em").textContent = formatStatus(value);
  });
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
  renderTelemetry(status);
  renderMission(mission);
  const operations = status.operations || [];
  renderOperation(operations.length ? operations[operations.length - 1] : null);
}

async function refresh() {
  try {
    const [health, capabilities, integration, vehicles, events] = await Promise.all([
      request("/v1/health"), request("/v1/capabilities"), request("/v1/integration"), request("/v1/vehicles"), request("/v1/events?limit=12"),
    ]);
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
  }
}

function samplePlan() {
  return {
    valid_from: new Date(Date.now() + 60_000).toISOString(),
    valid_until: new Date(Date.now() + 35 * 60_000).toISOString(),
    source: "operator-console-demo",
    waypoints: [
      { sequence: 0, latitude: 47.4979, longitude: 19.0402, altitude: { meters: 135, datum: "WGS84" } },
      { sequence: 1, latitude: 47.4992, longitude: 19.0420, altitude: { meters: 140, datum: "WGS84" } },
      { sequence: 2, latitude: 47.5000, longitude: 19.0390, altitude: { meters: 135, datum: "WGS84" } },
    ],
  };
}

async function saveMission() {
  if (!state.vehicleId || !state.plan) return;
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
  const operationId = state.operation?.operation_id || newOperationId();
  try {
    const operation = await request(`/v1/operator-intents?vehicle_id=${encodeURIComponent(state.vehicleId)}`, { method: "POST", body: JSON.stringify({ schema_version: "1.0", command, operation_id: operationId }) });
    renderOperation(operation);
    setMessage(`${formatStatus(command)} completed.`, "success");
    await refresh();
  } catch (error) { setMessage(error.message, "error"); }
}

$("vehicle-select").addEventListener("change", async (event) => { state.vehicleId = event.target.value; state.operation = null; await refreshVehicle(); });
$("sample-button").addEventListener("click", () => { state.plan = samplePlan(); state.planFormat = "canonical"; state.planName = "Demo route"; renderMission(null); setMessage("Demo route loaded. Review the validity window, then validate it."); });
$("plan-file").addEventListener("change", async (event) => { const file = event.target.files[0]; if (!file) return; try { const text = await file.text(); state.plan = text.trimStart().startsWith("QGC WPL ") ? text : JSON.parse(text); state.planFormat = typeof state.plan === "string" ? "mission-planner" : "qgroundcontrol"; state.planName = file.name; state.mission = null; renderMission(null); setMessage(file.name + " loaded."); } catch (error) { setMessage("Could not read mission file: " + error.message, "error"); } });
$("save-button").addEventListener("click", saveMission);
$("submit-button").addEventListener("click", () => sendIntent("SUBMIT_OPERATION"));
$("start-button").addEventListener("click", () => sendIntent("START_OPERATION"));
$("cancel-button").addEventListener("click", () => sendIntent("CANCEL_OPERATION"));
$("complete-button").addEventListener("click", () => sendIntent("COMPLETE_OPERATION"));
$("refresh-operation-button").addEventListener("click", async () => { if (!state.operation) return; try { renderOperation(await request(`/v1/operations/${state.operation.operation_id}/refresh`, { method: "POST" })); setMessage("Provider state refreshed.", "success"); } catch (error) { setMessage(error.message, "error"); } });

setDefaultWindow();
refresh();
setInterval(refresh, 2500);
