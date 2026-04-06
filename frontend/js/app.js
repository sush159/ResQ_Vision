/* ── Rescue Vision — Command Center JS ── */

const API = "";
let ws             = null;
let currentJobId   = null;
let incidentCount  = 0;
let criticalCount  = 0;
let majorCount     = 0;
let minorCount     = 0;
let frameCount     = 0;
let vehicleCount   = 0;
let soundEnabled   = true;
let allIncidents   = [];
let activeFilter   = "all";
let _frameReceiveTime = 0;

// ── DOM ──
const canvas           = document.getElementById("videoCanvas");
const ctx              = canvas.getContext("2d");
const placeholder      = document.getElementById("placeholder");
const dropOverlay      = document.getElementById("dropOverlay");
const enhancementBadge = document.getElementById("enhancementBadge");
const progressFill     = document.getElementById("progressFill");
const timestampBadge   = document.getElementById("timestampBadge");
const alertList        = document.getElementById("alertList");
const alertCountBadge  = document.getElementById("alertCountBadge");
const uploadModal      = document.getElementById("uploadModal");
const uploadBox        = document.getElementById("uploadBox");
const fileInput        = document.getElementById("fileInput");
const btnStart         = document.getElementById("btnStart");
const btnStop          = document.getElementById("btnStop");
const btnUpload        = document.getElementById("btnUpload");
const btnCamera        = document.getElementById("btnCamera");
const statusDot        = document.getElementById("statusDot");
const statusLabel      = document.getElementById("statusLabel");
const soundBtn         = document.getElementById("soundBtn");
const soundIconOn      = document.getElementById("soundIconOn");
const soundIconOff     = document.getElementById("soundIconOff");
const screenFlash      = document.getElementById("screenFlash");
const videoAlertBanner = document.getElementById("videoAlertBanner");
const liveBadge        = document.getElementById("liveBadge");
const fpsBadge         = document.getElementById("fpsBadge");
const vidCorners       = document.getElementById("vidCorners");
const recBadge         = document.getElementById("recBadge");
const statusCardDot    = document.getElementById("statusCardDot");
const statusCardValue  = document.getElementById("statusCardValue");

const statVehicles  = document.getElementById("statVehicles");
const statFrames    = document.getElementById("statFrames");
const statIncidents = document.getElementById("statIncidents");
const statCritical  = document.getElementById("statCritical");
const statMajor     = document.getElementById("statMajor");
const statMinor     = document.getElementById("statMinor");
const statLatency   = document.getElementById("statLatency");

// ── Audio (Web Audio API) ──
let audioCtx = null;
function _ensureAudio() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
}
function playBeep(freq, dur, type, count) {
  if (!soundEnabled) return;
  try {
    _ensureAudio();
    for (let i = 0; i < count; i++) {
      const osc  = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      const t    = audioCtx.currentTime + i * (dur + 0.05);
      osc.connect(gain); gain.connect(audioCtx.destination);
      osc.type = type; osc.frequency.setValueAtTime(freq, t);
      gain.gain.setValueAtTime(0.2, t);
      gain.gain.exponentialRampToValueAtTime(0.001, t + dur);
      osc.start(t); osc.stop(t + dur);
    }
  } catch (_) {}
}
function playAlertSound(sev) {
  if (sev === "Critical") playBeep(660, 0.15, "square", 4);
  else if (sev === "Major") playBeep(520, 0.18, "square", 2);
  else playBeep(440, 0.2, "sine", 1);
}

// ── Sound toggle ──
soundBtn.addEventListener("click", () => {
  soundEnabled = !soundEnabled;
  soundIconOn.style.display  = soundEnabled ? "block" : "none";
  soundIconOff.style.display = soundEnabled ? "none"  : "block";
  soundBtn.classList.toggle("muted", !soundEnabled);
  showToast(soundEnabled ? "Sound alerts enabled" : "Sound alerts muted", "info");
});

// ── Upload modal ──
function openUpload()  { uploadModal.style.display = "flex"; }
function closeUpload() { uploadModal.style.display = "none"; }

uploadModal.addEventListener("click", e => { if (e.target === uploadModal) closeUpload(); });
;
uploadBox.addEventListener("click", () => fileInput.click());
btnUpload.addEventListener("click", openUpload);
fileInput.addEventListener("change", () => { if (fileInput.files[0]) handleFile(fileInput.files[0]); });

uploadBox.addEventListener("dragover",  e => { e.preventDefault(); uploadBox.classList.add("dragover"); });
uploadBox.addEventListener("dragleave", ()  => uploadBox.classList.remove("dragover"));
uploadBox.addEventListener("drop",      e  => { e.preventDefault(); uploadBox.classList.remove("dragover"); if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]); });

const videoContainer = document.querySelector(".video-wrap");
videoContainer.addEventListener("dragover",  e => { e.preventDefault(); dropOverlay.classList.add("active"); });
videoContainer.addEventListener("dragleave", ()  => dropOverlay.classList.remove("active"));
videoContainer.addEventListener("drop",      e  => { e.preventDefault(); dropOverlay.classList.remove("active"); if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]); });

// ── File upload ──
async function handleFile(file) {
  closeUpload();
  setStatus("uploading", "Uploading…");
  const formData = new FormData();
  formData.append("file", file);
  try {
    const res = await fetch(`${API}/api/upload`, { method: "POST", body: formData });
    if (!res.ok) {
      const err = await res.json();
      showToast("Upload failed: " + (err.detail || res.status), "error");
      setStatus("idle", "System Idle");
      return;
    }
    const data = await res.json();
    currentJobId = data.job_id;
    setStatus("ready", "Ready — " + data.filename);
    btnStart.disabled = false;
    showToast("Loaded: " + data.filename, "success");
    _promptCameraLocation();
  } catch (err) {
    showToast("Upload error: " + err.message, "error");
    setStatus("idle", "System Idle");
  }
}

// ── Controls ──
btnStart.addEventListener("click", startProcessing);
btnStop.addEventListener("click",  stopProcessing);
btnCamera.addEventListener("click", startCamera);

let cameraMode    = false;
let cameraStream  = null;
let captureTimer  = null;
let cameraVideo   = null;
let captureCanvas = null;

function startProcessing() {
  if (!currentJobId) return;
  cameraMode = false;
  resetAlerts();
  _onSessionStart();
  startWebSocket(currentJobId);
}

async function startCamera() {
  if (cameraMode) return;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    showToast("Camera not available. Use http://localhost:8000", "error");
    return;
  }
  setStatus("connecting", "Requesting camera…");
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 960 }, height: { ideal: 540 } }, audio: false });
  } catch (err) {
    setStatus("idle", "System Idle");
    if (err.name === "NotAllowedError" || err.name === "PermissionDeniedError") {
      document.getElementById("cameraPermModal").style.display = "flex";
    } else if (err.name === "NotFoundError") {
      showToast("No camera found.", "error");
    } else {
      showToast("Camera error: " + err.message, "error");
    }
    return;
  }

  cameraMode = true;
  resetAlerts();
  _onSessionStart();
  _requestGPSLocation();
  btnCamera.classList.add("active");
  placeholder.style.display = "none";
  vidCorners.style.display  = "block";
  liveBadge.style.display   = "flex";
  recBadge.style.display    = "flex";
  fpsBadge.style.display    = "block";
  btnStop.disabled  = false;
  btnStart.disabled = true;

  cameraVideo = document.createElement("video");
  cameraVideo.srcObject = cameraStream;
  cameraVideo.autoplay = true; cameraVideo.playsInline = true; cameraVideo.muted = true;
  captureCanvas = document.createElement("canvas");

  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/camera`);
  setStatus("connecting", "Connecting…");

  ws.onopen = () => {};
  ws.onmessage = e => {
    const msg = JSON.parse(e.data);
    if (msg.type === "ready") {
      setStatus("active", "Live Camera");
      setStatusCard("active", "Analyzing");
      cameraVideo.play().then(() => { captureTimer = setInterval(_sendFrame, 100); });
    } else {
      handleMessage(msg);
    }
  };
  ws.onerror = () => { showToast("Backend error.", "error"); _stopCamera(); };
  ws.onclose = () => _stopCamera();
}

function _sendFrame() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  if (!cameraVideo || cameraVideo.readyState < 2) return;
  const w = cameraVideo.videoWidth || 960;
  const h = cameraVideo.videoHeight || 540;
  captureCanvas.width = w; captureCanvas.height = h;
  captureCanvas.getContext("2d").drawImage(cameraVideo, 0, 0, w, h);
  ws.send(JSON.stringify({ type: "frame", frame: captureCanvas.toDataURL("image/jpeg", 0.75).split(",")[1] }));
}

function _stopCamera() {
  _onSessionStop();
  clearInterval(captureTimer); captureTimer = null;
  if (cameraStream) { cameraStream.getTracks().forEach(t => t.stop()); cameraStream = null; }
  cameraVideo = null; cameraMode = false;
  btnCamera.classList.remove("active");
  liveBadge.style.display  = "none";
  recBadge.style.display   = "none";
  fpsBadge.style.display   = "none";
  vidCorners.style.display = "none";
  setStatus("idle", "System Idle");
  setStatusCard("idle", "Standby");
  btnStop.disabled  = true;
  btnStart.disabled = !currentJobId;
}

function stopProcessing() {
  if (cameraMode) {
    if (ws) { ws.send(JSON.stringify({ type: "stop" })); ws.close(); ws = null; }
    _stopCamera();
    return;
  }
  _onSessionStop();
  if (ws) { ws.close(); ws = null; }
  setStatus("idle", "Stopped");
  setStatusCard("idle", "Standby");
  vidCorners.style.display = "none";
  btnStart.disabled = !currentJobId;
  btnStop.disabled  = true;
}

// ── WebSocket ──
function startWebSocket(jobId) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/${jobId}`);
  setStatus("connecting", "Connecting…");
  btnStart.disabled = true;
  btnStop.disabled  = false;

  ws.onopen = () => {
    setStatus("active", "Processing…");
    setStatusCard("active", "Analyzing");
    placeholder.style.display = "none";
    vidCorners.style.display  = "block";
    fpsBadge.style.display    = "block";
  };
  ws.onmessage = e => handleMessage(JSON.parse(e.data));
  ws.onerror   = () => { showToast("Connection error. Is the server running?", "error"); setStatus("idle", "Error"); btnStart.disabled = false; btnStop.disabled = true; };
  ws.onclose   = () => {
    if (statusDot.classList.contains("active")) setStatus("idle", "Analysis Complete");
    setStatusCard("idle", "Standby");
    vidCorners.style.display = "none";
    fpsBadge.style.display   = "none";
    btnStart.disabled = false; btnStop.disabled = true;
  };
}

// ── Message handler ──
function handleMessage(msg) {
  switch (msg.type) {
    case "start":
      setStatus("active", "Analyzing…");
      break;

    case "frame": {
      const now = performance.now();
      if (_frameReceiveTime > 0) {
        const fps = Math.round(1000 / (now - _frameReceiveTime));
        fpsBadge.textContent = Math.min(fps, 60) + " FPS";
      }
      _frameReceiveTime = now;

      drawFrame(msg.frame);
      updateStats(msg.stats);

      if (msg.enhancement_mode && msg.enhancement_mode !== "Normal") {
        enhancementBadge.textContent = msg.enhancement_mode.toUpperCase();
        enhancementBadge.style.display = "block";
        const label = document.getElementById("vidEnhLabel");
        if (label) { label.textContent = msg.enhancement_mode; label.style.display = "block"; }
      } else {
        enhancementBadge.style.display = "none";
        const label = document.getElementById("vidEnhLabel");
        if (label) label.style.display = "none";
      }

      if (msg.timestamp !== undefined) timestampBadge.textContent = formatTime(msg.timestamp);
      if (msg.progress  !== undefined && msg.progress >= 0) progressFill.style.width = msg.progress + "%";
      break;
    }

    case "alert":
      addIncidentCard(msg.incident);
      triggerAlertEffects(msg.incident);
      break;

    case "complete":
      setStatus("idle", "Analysis Complete");
      setStatusCard("idle", "Standby");
      progressFill.style.width = "100%";
      if (msg.stats) updateStats(msg.stats);
      clearBanner();
      showToast(`Done — ${msg.total_alerts || 0} incident(s) detected`, msg.total_alerts > 0 ? "alert" : "success");
      break;

    case "error":
      showToast("Server error: " + msg.message, "error");
      setStatus("idle", "Error");
      break;
  }
}

// ── Canvas ──
function drawFrame(b64) {
  const img = new Image();
  img.onload = () => { canvas.width = img.naturalWidth; canvas.height = img.naturalHeight; ctx.drawImage(img, 0, 0); };
  img.src = "data:image/jpeg;base64," + b64;
}

// ── Stats ──
function updateStats(stats) {
  if (!stats) return;
  vehicleCount = stats.total_vehicles ?? vehicleCount;
  frameCount   = stats.frame_count   ?? frameCount;
  statVehicles.textContent = vehicleCount;
  statFrames.textContent   = frameCount;
}

// ── Alert effects ──
function triggerAlertEffects(incident) {
  const sev = incident.severity;

  // Screen flash
  screenFlash.className = "screen-flash " + sev;
  setTimeout(() => { screenFlash.className = "screen-flash"; }, 800);

  // Status dot pulse
  statusDot.classList.remove("active");
  statusDot.classList.add("alert");
  setTimeout(() => { statusDot.classList.remove("alert"); statusDot.classList.add("active"); }, 2500);

  // Video banner
  const label = `${sev.toUpperCase()}  ·  ${(incident.collision_type || "COLLISION").toUpperCase()}  ·  ${incident.incident_id}`;
  videoAlertBanner.textContent = label;
  videoAlertBanner.className   = "vid-alert-banner " + sev;
  clearTimeout(videoAlertBanner._t);
  videoAlertBanner._t = setTimeout(clearBanner, 5000);

  // Sound
  playAlertSound(sev);

  // Emergency modal for Critical/Major
  if (sev === "Critical" || sev === "Major") showEmergencyModal(incident);
}

function clearBanner() {
  videoAlertBanner.className = "vid-alert-banner";
  videoAlertBanner.textContent = "";
}

// ── Emergency modal ──
function showEmergencyModal(incident) {
  const sev  = incident.severity;
  const dlg  = document.getElementById("emergencyDialog");
  dlg.className = sev === "Major" ? "emergency-dialog major" : "emergency-dialog";

  document.getElementById("emergencyTitle").textContent =
    sev === "Critical" ? "CRITICAL ACCIDENT DETECTED" : "MAJOR ACCIDENT DETECTED";
  document.getElementById("emergencyId").textContent  = incident.incident_id;
  document.getElementById("emergencyType").textContent = incident.collision_type || "Unknown collision type";

  const fireUnit = document.getElementById("fireUnit");
  if (sev === "Critical") {
    fireUnit.classList.add("dispatched");
    document.getElementById("fireStatus").textContent = "Dispatched";
    document.getElementById("fireStatus").className = "du-status dispatched";
    document.getElementById("fireEta").textContent = `ETA ${3 + Math.floor(Math.random()*2)} min`;
  } else {
    fireUnit.classList.remove("dispatched");
    document.getElementById("fireStatus").textContent = "On Standby";
    document.getElementById("fireStatus").className = "du-status";
    document.getElementById("fireEta").textContent = "If required";
  }

  document.getElementById("ambEta").textContent = `ETA ${2 + Math.floor(Math.random()*3)} min`;
  document.getElementById("polEta").textContent = `ETA ${1 + Math.floor(Math.random()*3)} min`;

  const now = new Date();
  ["logTime0","logTime1","logTime2","logTime3"].forEach((id, i) => {
    document.getElementById(id).textContent = new Date(now.getTime() + i*3000).toLocaleTimeString();
  });

  const pct = Math.round(incident.score * 100);
  const bar  = document.getElementById("emergencyScoreBar");
  const barColor = sev === "Critical" ? "#ef4444" : "#f97316";
  bar.style.background = barColor;
  bar.style.width = "0%";
  document.getElementById("emergencyScorePct").textContent = pct + "%";
  setTimeout(() => { bar.style.width = pct + "%"; }, 80);

  document.getElementById("emergencyModal").style.display = "flex";
}

function closeEmergency() {
  document.getElementById("emergencyModal").style.display = "none";
}

// ── Filter tabs ──
document.querySelectorAll(".ftab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".ftab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    activeFilter = tab.dataset.filter;
    applyFilter();
  });
});

function applyFilter() {
  alertList.querySelectorAll(".incident-card").forEach(card => {
    card.style.display = (activeFilter === "all" || card.classList.contains(activeFilter)) ? "" : "none";
  });
}

// ── Incident cards ──
function addIncidentCard(incident) {
  incidentCount++;
  allIncidents.unshift(incident);

  statIncidents.textContent = incidentCount;
  if (incident.severity === "Critical") { criticalCount++; statCritical.textContent = criticalCount; }
  else if (incident.severity === "Major") { majorCount++;  statMajor.textContent   = majorCount; }
  else { minorCount++; statMinor.textContent = minorCount; }

  alertCountBadge.textContent    = incidentCount;
  alertCountBadge.style.display  = "inline-block";
  document.getElementById("btnDownload").style.display = "flex";
  document.getElementById("btnClearLog").style.display  = "flex";

  const empty = document.getElementById("alertEmpty");
  if (empty) empty.remove();

  const sev = incident.severity;
  const scoreColor = sev === "Critical" ? "#ef4444" : sev === "Major" ? "#f97316" : "#eab308";
  const scorePct   = Math.round(incident.score * 100);
  const timeStr    = new Date(incident.timestamp * 1000).toLocaleTimeString();

  const platesHtml = (incident.plates || []).length
    ? incident.plates.map(p => `<span class="plate-chip">${p}</span>`).join("")
    : `<span style="color:var(--text-3); font-size:0.7rem;">Not detected</span>`;

  const card = document.createElement("div");
  card.className = `incident-card ${sev}`;
  if (activeFilter !== "all" && activeFilter !== sev) card.style.display = "none";

  card.innerHTML = `
    <div class="ic-header">
      <span class="ic-id">${incident.incident_id}</span>
      <span class="ic-badge ${sev}">${sev}</span>
    </div>
    <div class="ic-type">${(incident.collision_type || "Unknown Collision").replace(/-/g," ").replace(/_/g," ")}</div>
    <div class="ic-row">
      <span class="ic-key">Time</span>
      <span class="ic-val">${timeStr} &nbsp;·&nbsp; Frame ${incident.frame_number.toLocaleString()}</span>
    </div>
    <div class="ic-row">
      <span class="ic-key">Vehicles</span>
      <span class="ic-val">${incident.track_ids.length ? "IDs: " + incident.track_ids.join(", ") : "Model detection"}</span>
    </div>
    <div class="ic-row">
      <span class="ic-key">Plates</span>
      <span class="ic-val">${platesHtml}</span>
    </div>
    <div class="ic-score-row">
      <div class="ic-score-track">
        <div class="ic-score-fill" style="width:${scorePct}%; background:${scoreColor};"></div>
      </div>
      <div class="ic-score-label">Impact score: ${scorePct}%</div>
    </div>
  `;

  alertList.insertBefore(card, alertList.firstChild);
  statLatency.textContent = "~0.5s";

  // Drop pin on the Coimbatore map
  addIncidentToMap(incident);

  // New feature hooks
  _onNewIncident(incident);
}


// ── Download report ──
function downloadReport() {
  if (!allIncidents.length) return;
  const lines = [
    "RESQ VISION — INCIDENT REPORT",
    "Generated: " + new Date().toLocaleString(),
    "=".repeat(54), "",
    `Total: ${allIncidents.length}  |  Critical: ${criticalCount}  |  Major: ${majorCount}  |  Minor: ${minorCount}`,
    "", "=".repeat(54), "",
  ];
  allIncidents.forEach((inc, i) => {
    lines.push(`[${String(i+1).padStart(3,"0")}] ${inc.incident_id}  —  ${inc.severity}`);
    lines.push(`  Type       : ${inc.collision_type || "N/A"}`);
    lines.push(`  Time       : ${new Date(inc.timestamp*1000).toLocaleString()}`);
    lines.push(`  Frame      : ${inc.frame_number}`);
    lines.push(`  Score      : ${Math.round(inc.score*100)}%`);
    lines.push(`  Track IDs  : ${inc.track_ids.join(", ") || "N/A"}`);
    lines.push(`  Plates     : ${inc.plates.join(", ") || "Not detected"}`);
    lines.push(`  Location   : (${inc.location.map(v=>Math.round(v)).join(", ")})`);
    lines.push("");
  });
  const blob = new Blob([lines.join("\n")], { type: "text/plain" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `rescue_vision_report_${Date.now()}.txt`;
  a.click();
  URL.revokeObjectURL(a.href);
  showToast("Report downloaded", "success");
}

// ── Reset ──
function resetAlerts() {
  _onReset();
  incidentCount = criticalCount = majorCount = minorCount = 0;
  frameCount = vehicleCount = 0;
  allIncidents = []; activeFilter = "all"; _frameReceiveTime = 0;

  statIncidents.textContent = statCritical.textContent = statMajor.textContent =
  statMinor.textContent = statVehicles.textContent = statFrames.textContent = "0";
  statLatency.textContent = "—";

  alertCountBadge.style.display = "none";
  document.getElementById("btnDownload").style.display = "none";
  document.getElementById("btnClearLog").style.display  = "none";

  document.querySelectorAll(".ftab").forEach(t => t.classList.remove("active"));
  document.querySelector('.ftab[data-filter="all"]').classList.add("active");

  alertList.innerHTML = `
    <div class="incident-empty" id="alertEmpty">
      <svg class="ie-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1">
        <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"/>
      </svg>
      <div class="ie-title">No Incidents Detected</div>
      <div class="ie-sub">The AI system is monitoring for accidents in real time</div>
    </div>`;

  progressFill.style.width = "0%";
  clearBanner();

  // Also reset the map incident pins silently
  if (coimbatoreMap) {
    incidentMarkers.forEach(m => coimbatoreMap.removeLayer(m));
    incidentMarkers = [];
    mapIncidentTotal = mapIncidentCritical = mapIncidentMajor = mapIncidentMinor = 0;
    if (elMapTotal)      elMapTotal.textContent      = "0";
    if (elMapCritical)   elMapCritical.textContent   = "0";
    if (elMapMajor)      elMapMajor.textContent      = "0";
    if (elMapMinor)      elMapMinor.textContent      = "0";
    if (elMapLastUpdate) elMapLastUpdate.textContent = "—";
  }
}

// ── UI helpers ──
function setStatus(state, label) {
  statusLabel.textContent = label;
  statusDot.className = "status-dot";
  if (state === "active" || state === "connecting" || state === "ready") statusDot.classList.add("active");
  if (state === "uploading") statusDot.classList.add("uploading");
}

function setStatusCard(state, label) {
  if (!statusCardDot || !statusCardValue) return;
  statusCardValue.textContent = label;
  statusCardDot.className = "sc-indicator" + (state === "active" ? " active" : "");
}

function formatTime(s) {
  return String(Math.floor(s/60)).padStart(2,"0") + ":" + String(Math.floor(s%60)).padStart(2,"0");
}

function showToast(message, type = "info") {
  const t = document.createElement("div");
  t.className = `toast ${type}`;
  t.textContent = message;
  document.getElementById("toastContainer").appendChild(t);
  setTimeout(() => t.remove(), 4000);
}

// ── Live Map — Coimbatore ──────────────────────────────────────────────────────

// Coimbatore city center coordinates
const CBE_CENTER = [11.0168, 76.9558];

// Known accident black-spots in Coimbatore — verified coordinates
const HOTSPOTS = [
  { name: "Avanashi Road & TIDEL Park Junction", lat: 11.0317, lng: 77.0187, severity: "Critical", info: "High-speed mixed traffic corridor — NH-544" },
  { name: "Ukkadam Bus Stand Junction",          lat: 10.9886, lng: 76.9617, severity: "Critical", info: "Heavy pedestrian-vehicle conflict zone" },
  { name: "Gandhipuram Central Bus Terminus",    lat: 11.0175, lng: 76.9668, severity: "Major",    info: "Dense bus & auto-rickshaw traffic" },
  { name: "Singanallur Signal",                  lat: 10.9990, lng: 77.0324, severity: "Major",    info: "Frequent rear-end collisions at signal" },
  { name: "Peelamedu Flyover",                   lat: 11.0246, lng: 77.0072, severity: "Major",    info: "Two-wheeler accident hotspot near airport road" },
  { name: "Saravanampatti Junction",             lat: 11.0764, lng: 77.0030, severity: "Minor",    info: "IT corridor evening peak-hour congestion" },
  { name: "Hope College Junction",               lat: 11.0238, lng: 76.9732, severity: "Minor",    info: "School zone — morning pedestrian hazards" },
  { name: "Race Course Road",                    lat: 11.0060, lng: 76.9582, severity: "Minor",    info: "Night-time speeding incidents" },
  { name: "Trichy Road & Krishnaswamy Nagar",    lat: 10.9850, lng: 77.0020, severity: "Major",    info: "Lorry-car collision hotspot on Trichy Road" },
  { name: "Coimbatore Junction (Railway)",       lat: 11.0023, lng: 76.9629, severity: "Minor",    info: "Auto & pedestrian congestion near station" },
];

// Coimbatore road area – bounding box for fallback random incident pins
const CBE_BOUNDS = {
  minLat: 10.985, maxLat: 11.080,
  minLng: 76.955, maxLng: 77.035,
};

let coimbatoreMap  = null;
let incidentMarkers = [];
let mapIncidentTotal    = 0;
let mapIncidentCritical = 0;
let mapIncidentMajor    = 0;
let mapIncidentMinor    = 0;

// Map stats DOM elements (may not exist until DOMContentLoaded)
let elMapTotal, elMapCritical, elMapMajor, elMapMinor, elMapLastUpdate;

function _initMapStats() {
  elMapTotal      = document.getElementById("mapStatTotal");
  elMapCritical   = document.getElementById("mapStatCritical");
  elMapMajor      = document.getElementById("mapStatMajor");
  elMapMinor      = document.getElementById("mapStatMinor");
  elMapLastUpdate = document.getElementById("mapLastUpdate");
}

function _updateMapStats(sev) {
  mapIncidentTotal++;
  if (sev === "Critical") mapIncidentCritical++;
  else if (sev === "Major") mapIncidentMajor++;
  else mapIncidentMinor++;

  if (elMapTotal)     elMapTotal.textContent      = mapIncidentTotal;
  if (elMapCritical)  elMapCritical.textContent   = mapIncidentCritical;
  if (elMapMajor)     elMapMajor.textContent      = mapIncidentMajor;
  if (elMapMinor)     elMapMinor.textContent      = mapIncidentMinor;
  if (elMapLastUpdate) elMapLastUpdate.textContent = new Date().toLocaleTimeString();
}

function initMap() {
  if (!document.getElementById("coimbatoreMap")) return;

  coimbatoreMap = L.map("coimbatoreMap", {
    center: CBE_CENTER,
    zoom: 13,
    zoomControl: true,
    attributionControl: true,
  });

  // Dark tile layer (CartoDB Dark Matter)
  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" style="color:#00d4aa">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions" style="color:#00d4aa">CARTO</a>',
    subdomains: "abcd",
    maxZoom: 19,
  }).addTo(coimbatoreMap);

  // Plot known hotspots as blue pulsing circles
  HOTSPOTS.forEach(h => {
    const color = h.severity === "Critical" ? "#ef4444" : h.severity === "Major" ? "#f97316" : "#eab308";
    const circle = L.circleMarker([h.lat, h.lng], {
      radius: h.severity === "Critical" ? 10 : h.severity === "Major" ? 8 : 6,
      fillColor: color,
      color: color,
      weight: 2,
      opacity: 0.8,
      fillOpacity: 0.25,
    }).addTo(coimbatoreMap);

    circle.bindPopup(`
      <div style="min-width:180px;">
        <div style="font-weight:700;font-size:13px;color:${color};margin-bottom:4px;">📍 ${h.name}</div>
        <div style="color:#6b88a8;font-size:11px;margin-bottom:6px;">${h.info}</div>
        <div style="display:flex;align-items:center;gap:6px;">
          <span style="width:8px;height:8px;border-radius:50%;background:${color};display:inline-block;"></span>
          <span style="font-size:11px;font-weight:600;color:${color};">${h.severity} Hotspot</span>
        </div>
      </div>
    `);
  });

  // Add a labeled city boundary circle
  L.circle(CBE_CENTER, {
    radius: 8000,
    color: "rgba(0,212,170,0.3)",
    fillColor: "rgba(0,212,170,0.03)",
    fillOpacity: 1,
    weight: 1,
    dashArray: "6 4",
  }).addTo(coimbatoreMap);

  // City center marker
  const cityIcon = L.divIcon({
    html: `<div style="width:14px;height:14px;border-radius:50%;background:rgba(0,212,170,0.9);border:2px solid #fff;box-shadow:0 0 12px rgba(0,212,170,0.8);"></div>`,
    className: "",
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
  L.marker(CBE_CENTER, { icon: cityIcon })
    .addTo(coimbatoreMap)
    .bindPopup("<b style='color:#00d4aa'>Coimbatore City Centre</b><br><span style='color:#6b88a8;font-size:11px;'>Rescue Vision Monitoring Zone</span>");

  _initMapStats();
  _initMapClickHandler();
}

/**
 * Called when an incident is detected.
 * Uses real GPS/manual camera location if set, otherwise falls back to CBE scatter.
 */
function addIncidentToMap(incident) {
  if (!coimbatoreMap) return;

  let lat, lng;
  if (_cameraLocation) {
    // Real location: scatter within ~80m radius of camera position
    const jitter = 0.0007; // ~80m
    lat = _cameraLocation.lat + (Math.random() - 0.5) * jitter;
    lng = _cameraLocation.lng + (Math.random() - 0.5) * jitter;
  } else {
    // Fallback: pixel-based scatter within CBE bounding box
    const [px, py] = incident.location || [0.5, 0.5];
    lat = CBE_BOUNDS.minLat + (py / 100) * (CBE_BOUNDS.maxLat - CBE_BOUNDS.minLat);
    lng = CBE_BOUNDS.minLng + (px / 100) * (CBE_BOUNDS.maxLng - CBE_BOUNDS.minLng);
  }

  const sev   = incident.severity;
  const color = sev === "Critical" ? "#ef4444" : sev === "Major" ? "#f97316" : "#eab308";
  const pct   = Math.round(incident.score * 100);
  const time  = new Date(incident.timestamp * 1000).toLocaleTimeString();

  const icon = L.divIcon({
    html: `<div class="incident-marker ${sev}">${sev === "Critical" ? "🔴" : sev === "Major" ? "🟠" : "🟡"}</div>`,
    className: "",
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });

  const marker = L.marker([lat, lng], { icon })
    .addTo(coimbatoreMap)
    .bindPopup(`
      <div style="min-width:190px;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">
          <span style="font-family:monospace;font-size:11px;color:#6b88a8;">${incident.incident_id}</span>
          <span style="font-size:10px;font-weight:800;padding:2px 8px;border-radius:999px;background:${color}22;color:${color};border:1px solid ${color}44;">${sev}</span>
        </div>
        <div style="font-weight:700;font-size:13px;color:#dde8f5;margin-bottom:4px;text-transform:capitalize;">${(incident.collision_type || "Collision").replace(/-/g," ")} </div>
        <div style="color:#6b88a8;font-size:11px;margin-bottom:2px;">⏱ ${time}</div>
        <div style="color:#6b88a8;font-size:11px;margin-bottom:6px;">🎯 Impact Score: <span style="color:${color};font-weight:600;">${pct}%</span></div>
        <div style="height:4px;background:#172a44;border-radius:2px;overflow:hidden;">
          <div style="height:100%;width:${pct}%;background:${color};border-radius:2px;"></div>
        </div>
      </div>
    `);

  marker.openPopup();
  incidentMarkers.push(marker);
  _updateMapStats(sev);

  // Pan map to the incident with a short delay
  setTimeout(() => coimbatoreMap.panTo([lat, lng], { animate: true, duration: 0.6 }), 200);
}

function centerMap() {
  if (coimbatoreMap) coimbatoreMap.flyTo(CBE_CENTER, 13, { animate: true, duration: 1 });
}

function clearMapIncidents() {
  incidentMarkers.forEach(m => coimbatoreMap.removeLayer(m));
  incidentMarkers = [];
  mapIncidentTotal = mapIncidentCritical = mapIncidentMajor = mapIncidentMinor = 0;
  if (elMapTotal)      elMapTotal.textContent      = "0";
  if (elMapCritical)   elMapCritical.textContent   = "0";
  if (elMapMajor)      elMapMajor.textContent      = "0";
  if (elMapMinor)      elMapMinor.textContent      = "0";
  if (elMapLastUpdate) elMapLastUpdate.textContent = "—";
  showToast("Map incident pins cleared", "info");
}

// ── Camera Location (GPS / Manual) ────────────────────────────
let _cameraLocation   = null;   // { lat, lng, accuracy, source }
let _setLocationMode  = false;
let _cameraMarker     = null;
let _accuracyCircle   = null;

/**
 * Called when Live Camera starts — requests real GPS from browser.
 */
function _requestGPSLocation() {
  if (!navigator.geolocation) {
    showToast("GPS not available on this device", "info");
    return;
  }
  showToast("Requesting GPS location…", "info");
  navigator.geolocation.getCurrentPosition(
    pos => {
      _setCameraLocation(pos.coords.latitude, pos.coords.longitude, pos.coords.accuracy, "GPS");
    },
    err => {
      let msg = "GPS unavailable";
      if (err.code === 1) msg = "GPS permission denied — click 'Set Location' on the map";
      else if (err.code === 2) msg = "GPS position unavailable — click 'Set Location' on the map";
      showToast(msg, "info");
    },
    { enableHighAccuracy: true, timeout: 8000, maximumAge: 0 }
  );
}

/**
 * Called after video upload — prompts user to click map to set location.
 */
function _promptCameraLocation() {
  // Scroll to map smoothly
  document.querySelector(".map-section").scrollIntoView({ behavior: "smooth", block: "start" });
  setTimeout(() => enterSetLocationMode(), 600);
}

/**
 * Enter "click map to set location" mode.
 */
function enterSetLocationMode() {
  _setLocationMode = true;
  const banner  = document.getElementById("locBanner");
  const overlay = document.getElementById("mapSetLocOverlay");
  const wrap    = document.getElementById("mapContainerWrap");
  const btn     = document.getElementById("btnSetLocation");
  if (banner)  banner.style.display  = "flex";
  if (overlay) overlay.style.display = "flex";
  if (wrap)    wrap.classList.add("set-location-mode");
  if (btn)     btn.classList.add("active");
  document.getElementById("locInfoBar").style.display = "none";
}

/**
 * Exit set-location mode without saving.
 */
function exitSetLocationMode() {
  _setLocationMode = false;
  const banner  = document.getElementById("locBanner");
  const overlay = document.getElementById("mapSetLocOverlay");
  const wrap    = document.getElementById("mapContainerWrap");
  const btn     = document.getElementById("btnSetLocation");
  if (banner)  banner.style.display  = "none";
  if (overlay) overlay.style.display = "none";
  if (wrap)    wrap.classList.remove("set-location-mode");
  if (btn)     btn.classList.remove("active");
}

/**
 * Saves camera location and updates all UI.
 */
function _setCameraLocation(lat, lng, accuracy, source) {
  _cameraLocation = { lat, lng, accuracy, source };
  exitSetLocationMode();

  // Update info bar
  const infoBar  = document.getElementById("locInfoBar");
  const srcLabel = document.getElementById("locSourceLabel");
  const coords   = document.getElementById("locCoordsLabel");
  const acc      = document.getElementById("locAccLabel");
  if (infoBar)  infoBar.style.display  = "flex";
  if (srcLabel) srcLabel.textContent   = source;
  if (coords)   coords.textContent     = `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
  if (acc && accuracy) acc.textContent = `± ${Math.round(accuracy)}m`;

  // Update map subtitle
  const sub = document.getElementById("mapSubLabel");
  if (sub) sub.textContent = `Camera location locked · ${source} · ${lat.toFixed(5)}, ${lng.toFixed(5)}`;

  // Place/update camera marker on map
  if (coimbatoreMap) {
    if (_cameraMarker)  coimbatoreMap.removeLayer(_cameraMarker);
    if (_accuracyCircle) coimbatoreMap.removeLayer(_accuracyCircle);

    // Accuracy circle (only for GPS)
    if (accuracy && source === "GPS") {
      _accuracyCircle = L.circle([lat, lng], {
        radius: accuracy,
        color: "rgba(16,185,129,0.6)",
        fillColor: "rgba(16,185,129,0.08)",
        fillOpacity: 1,
        weight: 1.5,
        dashArray: "4 4",
      }).addTo(coimbatoreMap);
    }

    // Camera icon marker
    const camIcon = L.divIcon({
      html: `<div class="camera-loc-marker">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px;">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 10.5l4.72-4.72a.75.75 0 011.28.53v11.38a.75.75 0 01-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 002.25-2.25v-9a2.25 2.25 0 00-2.25-2.25h-9A2.25 2.25 0 002.25 7.5v9a2.25 2.25 0 002.25 2.25z"/>
        </svg>
      </div>`,
      className: "",
      iconSize: [36, 36],
      iconAnchor: [18, 18],
    });

    _cameraMarker = L.marker([lat, lng], { icon: camIcon })
      .addTo(coimbatoreMap)
      .bindPopup(`
        <div style="min-width:180px;">
          <div style="font-weight:800;font-size:12px;color:#10b981;margin-bottom:4px;">CAMERA LOCATION</div>
          <div style="font-size:11px;color:#6b88a8;margin-bottom:2px;">Source: <span style="color:#e8f0fe;font-weight:600;">${source}</span></div>
          <div style="font-size:11px;color:#6b88a8;margin-bottom:2px;">Lat: <span style="color:#e8f0fe;font-family:monospace;">${lat.toFixed(6)}</span></div>
          <div style="font-size:11px;color:#6b88a8;margin-bottom:2px;">Lng: <span style="color:#e8f0fe;font-family:monospace;">${lng.toFixed(6)}</span></div>
          ${accuracy ? `<div style="font-size:11px;color:#6b88a8;">Accuracy: <span style="color:#10b981;font-weight:600;">±${Math.round(accuracy)}m</span></div>` : ""}
          <div style="margin-top:8px;font-size:10px;color:#3a5070;">Accident pins will appear around this location</div>
        </div>
      `);

    // Fly to camera location
    coimbatoreMap.flyTo([lat, lng], 16, { animate: true, duration: 1.2 });
  }

  const srcMsg = source === "GPS" ? `GPS locked — accuracy ±${Math.round(accuracy || 0)}m` : "Camera location set on map";
  showToast(srcMsg, "success");
}

// Add map click handler inside initMap
function _initMapClickHandler() {
  if (!coimbatoreMap) return;
  coimbatoreMap.on("click", e => {
    if (!_setLocationMode) return;
    _setCameraLocation(e.latlng.lat, e.latlng.lng, null, "Manual");
  });
}

// Initialise map on DOM ready
document.addEventListener("DOMContentLoaded", initMap);

// ═══════════════════════════════════════════════════════════════
// NEW FEATURES: Session Timer · Chart · Screenshot · Fullscreen
// ═══════════════════════════════════════════════════════════════

// ── Session Timer ──────────────────────────────────────────────
let _sessionStart    = null;
let _sessionInterval = null;
let _screenshotCount = 0;
let _peakVehicles    = 0;

function _onSessionStart() {
  _sessionStart = Date.now();
  clearInterval(_sessionInterval);
  _sessionInterval = setInterval(() => {
    const secs = Math.floor((Date.now() - _sessionStart) / 1000);
    const el = document.getElementById("sessionUptime");
    if (el) el.textContent = formatTime(secs);
    const anEl = document.getElementById("anRuntime");
    if (anEl) anEl.textContent = formatTime(secs);
    // Track peak vehicles
    if (vehicleCount > _peakVehicles) {
      _peakVehicles = vehicleCount;
      const pk = document.getElementById("anPeakVehicles");
      if (pk) pk.textContent = _peakVehicles;
    }
  }, 1000);
  _startChartUpdates();
}

function _onSessionStop() {
  clearInterval(_sessionInterval);
  _stopChartUpdates();
}

function _onReset() {
  _collisionCounts  = {};
  _cameraLocation   = null;
  // Remove camera marker from map
  if (_cameraMarker && coimbatoreMap)  { coimbatoreMap.removeLayer(_cameraMarker);  _cameraMarker = null; }
  if (_accuracyCircle && coimbatoreMap){ coimbatoreMap.removeLayer(_accuracyCircle); _accuracyCircle = null; }
  document.getElementById("locInfoBar").style.display  = "none";
  document.getElementById("locBanner").style.display   = "none";
  const sub = document.getElementById("mapSubLabel");
  if (sub) sub.textContent = "Real-time accident hotspot monitoring across the city";
  _peakVehicles    = 0;
  _screenshotCount = 0;
  const el = document.getElementById("topCollision");
  if (el) el.textContent = "—";
  const sc = document.getElementById("screenshotCount");
  if (sc) sc.textContent = "0";
  const pk = document.getElementById("anPeakVehicles");
  if (pk) pk.textContent = "0";
  const ti = document.getElementById("anTotalInc");
  if (ti) ti.textContent = "0";
  _clearChartData();
}

// ── Collision type tracking ────────────────────────────────────
let _collisionCounts = {};

function _onNewIncident(incident) {
  // Track most common collision type
  const raw  = (incident.collision_type || "Unknown").replace(/-/g," ").replace(/_/g," ");
  _collisionCounts[raw] = (_collisionCounts[raw] || 0) + 1;
  let top = "—", topCount = 0;
  for (const [t, c] of Object.entries(_collisionCounts)) {
    if (c > topCount) { topCount = c; top = t; }
  }
  const el = document.getElementById("topCollision");
  if (el) el.textContent = top.split(" ").slice(0, 4).join(" ");

  // Update analytics total
  const ti = document.getElementById("anTotalInc");
  if (ti) ti.textContent = incidentCount;

  // Auto-screenshot & store on incident
  _autoScreenshot(incident);

  // SMS simulation for Critical
  if (incident.severity === "Critical") {
    setTimeout(() => showToast("SMS dispatched to emergency contacts", "alert"), 1400);
  }
}

// ── Screenshot ─────────────────────────────────────────────────
function _autoScreenshot(incident) {
  if (!canvas || !canvas.width) return;
  try { incident._screenshot = canvas.toDataURL("image/jpeg", 0.85); } catch(_) {}
}

function captureScreenshot() {
  if (!canvas || !canvas.width) { showToast("No active video frame to capture", "error"); return; }
  try {
    const a = document.createElement("a");
    const ts = new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-");
    a.href     = canvas.toDataURL("image/png");
    a.download = `resq_capture_${ts}.png`;
    a.click();
    _screenshotCount++;
    const sc = document.getElementById("screenshotCount");
    if (sc) sc.textContent = _screenshotCount;
    showToast("Frame saved as PNG", "success");
  } catch(e) { showToast("Screenshot failed", "error"); }
}

// ── Fullscreen ─────────────────────────────────────────────────
function toggleFullscreen() {
  const container = document.getElementById("videoContainer");
  if (!document.fullscreenElement) {
    const fn = container.requestFullscreen || container.webkitRequestFullscreen || container.mozRequestFullScreen;
    if (fn) fn.call(container).catch(() => showToast("Fullscreen not available", "error"));
  } else {
    const ex = document.exitFullscreen || document.webkitExitFullscreen;
    if (ex) ex.call(document);
  }
}

document.addEventListener("fullscreenchange", () => {
  const btn = document.getElementById("btnFullscreen");
  if (!btn) return;
  const svg = btn.querySelector("svg");
  if (document.fullscreenElement) {
    btn.title = "Exit fullscreen";
    svg.innerHTML = `<path stroke-linecap="round" stroke-linejoin="round" d="M9 9V4.5M9 9H4.5M9 9L3.75 3.75M9 15v4.5M9 15H4.5M9 15l-5.25 5.25M15 9h4.5M15 9V4.5M15 9l5.25-5.25M15 15h4.5M15 15v4.5m0-4.5l5.25 5.25"/>`;
  } else {
    btn.title = "Fullscreen";
    svg.innerHTML = `<path stroke-linecap="round" stroke-linejoin="round" d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15"/>`;
  }
});

// ── Activity Chart ─────────────────────────────────────────────
let _activityChart  = null;
const _chartLabels   = [];
const _chartVehicles = [];
const _chartIncidents = [];
let _chartTimer = null;

function initActivityChart() {
  const el = document.getElementById("activityChart");
  if (!el || !window.Chart) return;

  _activityChart = new Chart(el.getContext("2d"), {
    type: "line",
    data: {
      labels: _chartLabels,
      datasets: [
        {
          label: "Vehicles Detected",
          data: _chartVehicles,
          borderColor: "#10b981",
          backgroundColor: "rgba(16,185,129,0.08)",
          fill: true, tension: 0.45,
          pointRadius: 0, pointHoverRadius: 4, borderWidth: 2,
        },
        {
          label: "Incidents",
          data: _chartIncidents,
          borderColor: "#f43f5e",
          backgroundColor: "rgba(244,63,94,0.08)",
          fill: true, tension: 0.45,
          pointRadius: 3, pointHoverRadius: 5, borderWidth: 2,
          yAxisID: "yRight",
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: {
          ticks: { color: "#3a5070", font: { size: 9, family: "JetBrains Mono" }, maxTicksLimit: 8, maxRotation: 0 },
          grid: { color: "rgba(255,255,255,0.04)" },
          border: { color: "rgba(255,255,255,0.05)" },
        },
        y: {
          beginAtZero: true,
          ticks: { color: "#10b981", font: { size: 9 } },
          grid: { color: "rgba(16,185,129,0.05)" },
          border: { color: "rgba(255,255,255,0.05)" },
          title: { display: true, text: "Vehicles", color: "#10b981", font: { size: 9 } },
        },
        yRight: {
          position: "right", beginAtZero: true,
          ticks: { color: "#f43f5e", font: { size: 9 }, stepSize: 1 },
          grid: { drawOnChartArea: false },
          border: { color: "rgba(255,255,255,0.05)" },
          title: { display: true, text: "Incidents", color: "#f43f5e", font: { size: 9 } },
        }
      },
      plugins: {
        legend: {
          labels: { color: "#7c93b8", font: { size: 11, family: "Inter" }, padding: 20, usePointStyle: true }
        },
        tooltip: {
          backgroundColor: "rgba(7,8,15,0.95)",
          borderColor: "rgba(255,255,255,0.08)", borderWidth: 1,
          titleColor: "#e8f0fe", bodyColor: "#7c93b8", padding: 10,
        }
      }
    }
  });
}

function _startChartUpdates() {
  clearInterval(_chartTimer);
  _chartTimer = setInterval(() => {
    if (!_activityChart) return;
    const t = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    _chartLabels.push(t);
    _chartVehicles.push(vehicleCount);
    _chartIncidents.push(incidentCount);
    if (_chartLabels.length > 60) { _chartLabels.shift(); _chartVehicles.shift(); _chartIncidents.shift(); }
    _activityChart.update("none");
  }, 3000);
}

function _stopChartUpdates() {
  clearInterval(_chartTimer);
  _chartTimer = null;
}

function _clearChartData() {
  _chartLabels.length = 0;
  _chartVehicles.length = 0;
  _chartIncidents.length = 0;
  if (_activityChart) _activityChart.update();
}

function clearChart() {
  _clearChartData();
  showToast("Chart cleared", "info");
}

document.addEventListener("DOMContentLoaded", initActivityChart);
