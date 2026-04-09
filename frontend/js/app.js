const LOCAL_API_BASE = "http://127.0.0.1:8000";
const API = resolveApiBase();
const STORAGE_KEY = "resq-vision-dashboard-state";

const state = {
  ws: null,
  uploadWs: null,
  uploadJobId: null,
  uploadSourceFps: 0,
  uploadAlertTriggered: false,
  cameraMode: false,
  cameraStream: null,
  captureTimer: null,
  cameraVideo: null,
  captureCanvas: null,
  uploadInProgress: false,
  soundEnabled: true,
  incidents: [],
  activeAlertFilter: "all",
  activeHistoryFilter: "all",
  clockTimer: null,
  sessionTimer: null,
  sessionStartedAt: null,
  frameReceiveTime: 0,
  lastPage: "live",
  map: null,
  mapMarkers: [],
  historyChart: null,
  uploadPreviewUrl: null,
  uploadSessions: [],
  activeUploadId: null,
  selectedIncidentId: null,
  activeHospFilter: "all",
};

const canvas = document.getElementById("videoCanvas");
const ctx = canvas.getContext("2d");
const uploadPreview = document.getElementById("uploadPreview");
const incidentClip = document.getElementById("incidentClip");
const placeholder = document.getElementById("placeholder");
const uploadModal = document.getElementById("uploadModal");
const uploadBox = document.getElementById("uploadBox");
const fileInput = document.getElementById("fileInput");
const btnBrowseFile = document.getElementById("btnBrowseFile");
const btnUpload = document.getElementById("btnUpload");
const btnCamera = document.getElementById("btnCamera");
const btnStop = document.getElementById("btnStop");
const soundBtn = document.getElementById("soundBtn");
const navToggle = document.getElementById("navToggle");
const dashboardShell = document.querySelector(".dashboard-shell");
const sidebar = document.getElementById("sidebar");
const statusDot = document.getElementById("statusDot");
const statusLabel = document.getElementById("statusLabel");
const recBadge = document.getElementById("recBadge");
const fpsBadge = document.getElementById("fpsBadge");
const progressFill = document.getElementById("progressFill");
const timestampBadge = document.getElementById("timestampBadge");
const enhancementBadge = document.getElementById("enhancementBadge");
const liveTicker = document.getElementById("liveTicker") || document.createElement("div");
const dispatchList = document.getElementById("dispatchList");
const historyTimeline = document.getElementById("historyTimeline");
const clockBadge = document.getElementById("clockBadge");
const dateBadge = document.getElementById("dateBadge");
const timeBadge = document.getElementById("timeBadge");

const hospitalAlerts = document.getElementById("hospitalAlerts");
const incidentDetail = document.getElementById("incidentDetail");
const nearbyHospitalList = document.getElementById("nearbyHospitalList");
const ambProgress = document.getElementById("ambProgress");
const ambTime = document.getElementById("ambTime");
const ambStatus = document.getElementById("ambStatus");
const incidentTimeline = document.getElementById("incidentTimeline");
const detailId = document.getElementById("detailId");
const detailTitle = document.getElementById("detailTitle");
const detailLoc = document.getElementById("detailLoc");
const detailSeverity = document.getElementById("detailSeverity");

const statIncidents = document.getElementById("statIncidents");
const liveActiveAlerts = document.getElementById("liveActiveAlerts");
const statLatency = document.getElementById("statLatency");
const liveResolved = document.getElementById("liveResolved");
const statVehicles = document.getElementById("statVehicles");
const statFrames = document.getElementById("statFrames");
const alertTotalCount = document.getElementById("alertTotalCount");
const agenciesCount = document.getElementById("agenciesCount");
const autoEscalatedCount = document.getElementById("autoEscalatedCount");
const falsePositiveRate = document.getElementById("falsePositiveRate");
const historyAvgResponse = document.getElementById("historyAvgResponse");
const historyImprovement = document.getElementById("historyImprovement");
const historyTotalIncidents = document.getElementById("historyTotalIncidents");
const videoPanelTitle = document.getElementById("videoPanelTitle");
const videoPanelSubtitle = document.getElementById("videoPanelSubtitle");

const PAGE_META = {
  live: {
    title: "Live Monitor Dashboard",
    subtitle: "Real-time accident detection and autonomous emergency dispatch",
  },
  alerts: {
    title: "Alert & Dispatch Panel",
    subtitle: "Autonomous multi-agency emergency notifications",
  },
  map: {
    title: "Accident Map View",
    subtitle: "Live incident locations and responder coverage",
  },
  history: {
    title: "Progress Tracker",
    subtitle: "Incident workflow progress and analytics",
  },
  hospital: {
    title: "Hospital Emergency Portal",
    subtitle: "Real-time trauma alerts and response coordination",
  },
};

const UPLOAD_DB_NAME = "resq-vision-upload-cache";
const UPLOAD_STORE_NAME = "videoFiles";
const UPLOAD_RECORD_KEY = "lastUploadVideo";

const LOCATION_PRESETS = [
  { label: "NH-44, Krishnagiri", lat: 12.5266, lng: 78.2137 },
  { label: "Salem Bypass Road", lat: 11.6643, lng: 78.1460 },
  { label: "Coimbatore Ring Road", lat: 11.0168, lng: 76.9558 },
  { label: "Avinashi Road, CBE", lat: 11.0278, lng: 77.0260 },
  { label: "Outer Ring, Hosur", lat: 12.7362, lng: 77.8323 },
  { label: "Mettupalayam Junction", lat: 11.2990, lng: 76.9402 },
];

const RESPONDERS = {
  police: { label: "Police", color: "blue" },
  ambulance: { label: "Ambulance", color: "green" },
  hospital: { label: "Hospital", color: "green" },
};

function resolveApiBase() {
  const { protocol, hostname, port } = window.location;
  if (protocol === "file:") return LOCAL_API_BASE;
  const isLocal = hostname === "localhost" || hostname === "127.0.0.1";
  if (isLocal && port && port !== "8000") return LOCAL_API_BASE;
  return "";
}

function resolveWsBase() {
  if (API) return API.replace(/^http/i, "ws");
  return location.protocol === "https:" ? `wss://${location.host}` : `ws://${location.host}`;
}

function openUpload() {
  uploadModal.classList.remove("hidden");
}

function closeUpload() {
  uploadModal.classList.add("hidden");
}

function setStatus(stateName, label) {
  statusLabel.textContent = label;
  statusDot.className = "status-dot";
  if (stateName === "active" || stateName === "ready") statusDot.classList.add("active");
  if (stateName === "uploading") statusDot.classList.add("uploading");
  if (stateName === "alert") statusDot.classList.add("alert");
}

async function checkBackendHealth() {
  try {
    const res = await fetch(`${API}/api/health`);
    const payload = await parseApiResponse(res);
    if (!res.ok || payload.status !== "ok") {
      throw new Error(payload.detail || payload.message || "Backend health check failed");
    }
    setStatus("ready", "Monitoring Active");
    liveTicker.textContent = "Backend connected. Upload a video or start live camera monitoring.";
  } catch (error) {
    setStatus("alert", "Backend Offline");
    liveTicker.textContent = `Backend not reachable at ${API || LOCAL_API_BASE}. Start the FastAPI server first.`;
    showToast(`Backend check failed: ${error.message}`, "error");
  }
}

function showToast(message, type = "info") {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  toast.title = "Click to dismiss";
  toast.addEventListener("click", () => toast.remove());
  document.getElementById("toastContainer").appendChild(toast);
  const timeout = type === "error" ? 15000 : type === "info" ? 9000 : 5000;
  setTimeout(() => toast.remove(), timeout);
}

function formatTime(seconds) {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function formatClock(date = new Date()) {
  const dateStr = new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "numeric",
    year: "numeric",
  }).format(date);
  
  const timeStr = new Intl.DateTimeFormat("en-IN", {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
  
  return { date: dateStr, time: timeStr };
}

function cycleClock() {
  const { date, time } = formatClock();
  if (dateBadge) dateBadge.textContent = date;
  if (timeBadge) timeBadge.textContent = time;
}

function setupNavigation() {
  document.querySelectorAll(".nav-link").forEach((btn) => {
    btn.addEventListener("click", () => {
      switchPage(btn.dataset.page);
      if (window.innerWidth <= 960) {
        dashboardShell.classList.remove("sidebar-open");
        navToggle?.setAttribute("aria-expanded", "false");
      }
    });
  });
}

function switchPage(page) {
  state.lastPage = page;
  document.querySelectorAll(".nav-link").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.page === page);
  });
  document.querySelectorAll(".page").forEach((panel) => {
    panel.classList.toggle("page-active", panel.dataset.page === page);
  });
  document.getElementById("pageTitle").textContent = PAGE_META[page].title;
  document.getElementById("pageSubtitle").textContent = PAGE_META[page].subtitle;
  if (page === "map" && state.map) {
    setTimeout(() => state.map.invalidateSize(), 60);
  }
  if (page === "hospital") {
    renderHospitalPortal();
  }
}

function setupSidebarToggle() {
  if (!dashboardShell) return;

  if (!navToggle) return;

  const syncToggleState = (expanded) => {
    navToggle.setAttribute("aria-expanded", String(expanded));
  };

  const handleToggle = () => {
    if (window.innerWidth <= 960) {
      const willOpen = !dashboardShell.classList.contains("sidebar-open");
      dashboardShell.classList.toggle("sidebar-open", willOpen);
      syncToggleState(willOpen);
      return;
    }

    const willCollapse = !dashboardShell.classList.contains("sidebar-collapsed");
    dashboardShell.classList.toggle("sidebar-collapsed", willCollapse);
    syncToggleState(!willCollapse);
  };

  navToggle.addEventListener("click", (event) => {
    event.stopPropagation();
    handleToggle();
  });

  document.addEventListener("click", (event) => {
    if (window.innerWidth > 960) return;
    if (!dashboardShell.classList.contains("sidebar-open")) return;
    if (sidebar?.contains(event.target) || navToggle.contains(event.target)) return;
    dashboardShell.classList.remove("sidebar-open");
    syncToggleState(false);
  });

  window.addEventListener("resize", () => {
    if (window.innerWidth > 960) {
      dashboardShell.classList.remove("sidebar-open");
      syncToggleState(!dashboardShell.classList.contains("sidebar-collapsed"));
      return;
    }
    dashboardShell.classList.remove("sidebar-collapsed");
    syncToggleState(dashboardShell.classList.contains("sidebar-open"));
  });
}

function setupFilters() {
  document.querySelectorAll("[data-alert-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.activeAlertFilter = btn.dataset.alertFilter;
      document.querySelectorAll("[data-alert-filter]").forEach((node) => node.classList.toggle("active", node === btn));
      renderDispatchList();
    });
  });

  document.querySelectorAll("[data-history-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.activeHistoryFilter = btn.dataset.historyFilter;
      document.querySelectorAll("[data-history-filter]").forEach((node) => node.classList.toggle("active", node === btn));
      renderHistoryTimeline();
    });
  });

  document.querySelectorAll("[data-hosp-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.activeHospFilter = btn.dataset.hospFilter;
      document.querySelectorAll("[data-hosp-filter]").forEach((node) => node.classList.toggle("active", node === btn));
      renderHospitalPortal();
    });
  });
}

function setupModals() {
  uploadModal.addEventListener("click", (event) => {
    if (event.target === uploadModal) closeUpload();
  });
  uploadBox.addEventListener("click", (event) => {
    if (event.target === fileInput || event.target.closest(".primary-btn")) return;
    fileInput.click();
  });
  btnBrowseFile.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    fileInput.click();
  });
  btnUpload.addEventListener("click", openUpload);
  fileInput.addEventListener("change", () => {
    if (fileInput.files[0]) handleFile(fileInput.files[0]);
  });
}

async function handleFile(file) {
  if (state.uploadInProgress) return;
  stopCameraSession();
  closeUploadStream();
  state.uploadInProgress = true;
  state.uploadAlertTriggered = false;
  state.sessionStartedAt = Date.now();
  startSessionTimer();
  closeUpload();
  setStatus("uploading", "Uploading...");
  btnUpload.disabled = true;
  btnCamera.disabled = true;
  btnStop.disabled = false;
  progressFill.style.width = "10%";
  const currentUpload = createUploadSession(file, file.name);
  showUploadPreview(currentUpload);
  storeUploadFile(currentUpload.id, file);
  videoPanelTitle.textContent = file.name || "Uploaded Video";
  videoPanelSubtitle.textContent = "Playing local preview while backend analysis runs";
  timestampBadge.textContent = "Analyzing...";
  liveTicker.textContent = "Video uploaded. Backend analysis is running.";

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch(`${API}/api/upload`, { method: "POST", body: formData });
    const payload = await parseApiResponse(res);
    if (!res.ok) {
      throw new Error(payload.detail || payload.message || `${res.status} ${res.statusText}`);
    }
    if (!payload.job_id) {
      throw new Error("Upload job did not start correctly");
    }
    state.uploadJobId = payload.job_id;
    connectUploadStream(payload.job_id, currentUpload.id);
  } catch (error) {
    const msg = error instanceof TypeError
      ? `Could not reach backend at ${API || LOCAL_API_BASE}`
      : error.message;
    showToast(`Upload error: ${msg}`, "error");
    setStatus("idle", "System Idle");
    progressFill.style.width = "0%";
  } finally {
    fileInput.value = "";
  }
}

function persistDashboardState() {
  try {
    const payload = {
      incidents: state.incidents.map((incident) => ({
        ...incident,
        timestamp: incident.timestamp instanceof Date ? incident.timestamp.toISOString() : incident.timestamp,
      })),
      lastStats: state.lastStats || {},
      selectedIncidentId: state.selectedIncidentId,
      lastPage: state.lastPage,
      uploadSourceFps: state.uploadSourceFps,
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  } catch {}
}

async function restoreDashboardState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const payload = JSON.parse(raw);
      const incidents = Array.isArray(payload.incidents) ? payload.incidents : [];
      state.incidents = incidents.map((incident) => ({
        ...incident,
        uid: incident.uid || `uid-${Date.now()}-${Math.random().toString(36).substr(2, 5)}`,
        timestamp: incident.timestamp ? new Date(incident.timestamp) : new Date(),
        sourceUrl: incident.uploadId ? null : incident.sourceUrl || null,
      }));
      state.lastStats = payload.lastStats || {};
      state.selectedIncidentId = payload.selectedIncidentId || null;
      state.lastPage = payload.lastPage || "live";
      state.uploadSourceFps = payload.uploadSourceFps || 25;
    }
    const storedFiles = await loadStoredUploadFiles();
    storedFiles.forEach((record) => {
      createUploadSession(record.file, record.name, record.id);
    });
  } catch {}
}

function openUploadDatabase() {
  return new Promise((resolve, reject) => {
    if (!window.indexedDB) return reject(new Error("IndexedDB not supported"));
    const request = window.indexedDB.open(UPLOAD_DB_NAME, 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(UPLOAD_STORE_NAME)) {
        db.createObjectStore(UPLOAD_STORE_NAME, { keyPath: "id" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function storeUploadFile(uploadId, file) {
  try {
    const db = await openUploadDatabase();
    const tx = db.transaction(UPLOAD_STORE_NAME, "readwrite");
    const store = tx.objectStore(UPLOAD_STORE_NAME);
    store.put({ id: uploadId, file, name: file.name, type: file.type, updatedAt: Date.now() });
    await new Promise((resolve, reject) => {
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
    db.close();
  } catch {
    // Fail silently if storage isn't available.
  }
}

async function removeStoredUploadFile(uploadId) {
  try {
    const db = await openUploadDatabase();
    const tx = db.transaction(UPLOAD_STORE_NAME, "readwrite");
    const store = tx.objectStore(UPLOAD_STORE_NAME);
    store.delete(uploadId);
    await new Promise((resolve, reject) => {
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
    db.close();
  } catch {
    // Fail silently
  }
}

async function loadStoredUploadFiles() {
  try {
    const db = await openUploadDatabase();
    const tx = db.transaction(UPLOAD_STORE_NAME, "readonly");
    const store = tx.objectStore(UPLOAD_STORE_NAME);
    const request = store.getAll();
    return await new Promise((resolve, reject) => {
      request.onsuccess = () => resolve(request.result || []);
      request.onerror = () => reject(request.error);
    }).finally(() => db.close());
  } catch {
    return [];
  }
}

async function parseApiResponse(res) {
  const raw = await res.text();
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch {
    throw new Error(raw.trim() || "Invalid server response");
  }
}

function createUploadSession(file, name, id = null) {
  const url = URL.createObjectURL(file);
  const sessionId = id || `upload-${Date.now()}-${Math.random().toString(36).substr(2, 5)}`;
  const session = {
    id: sessionId,
    name: name || file.name || "Uploaded Video",
    file,
    url,
    fps: 25,
  };
  state.uploadSessions.unshift(session);
  if (!id) { // only set active for new uploads
    state.activeUploadId = session.id;
    state.uploadPreviewUrl = url;
  }
  return session;
}

function getUploadSession(uploadId) {
  return state.uploadSessions.find((session) => session.id === uploadId) || null;
}

function getActiveUploadSession() {
  return getUploadSession(state.activeUploadId);
}

function resolveIncidentMedia(incident) {
  const session = incident?.uploadId ? getUploadSession(incident.uploadId) : null;
  return {
    sourceUrl: session?.url || incident?.sourceUrl || state.uploadPreviewUrl,
    sourceFps: incident?.sourceFps || session?.fps || state.uploadSourceFps || 25,
  };
}

function connectUploadStream(jobId, uploadId) {
  closeUploadStream();
  const session = getUploadSession(uploadId);
  state.uploadWs = new WebSocket(`${resolveWsBase()}/ws/${jobId}`);
  state.uploadWs.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    handleUploadStreamMessage(msg, uploadId);
  };

  state.uploadWs.onerror = () => {
    if (!state.uploadAlertTriggered) {
      showToast("Upload stream disconnected unexpectedly", "error");
      setStatus("alert", "Upload Stream Error");
    }
    finishUploadSession();
  };

  state.uploadWs.onclose = () => {
    if (state.uploadInProgress) {
      finishUploadSession();
    }
  };
}

function handleUploadStreamMessage(msg, uploadId) {
  const session = getUploadSession(uploadId);
  const sourceName = session?.name || "Uploaded Video";
  if (msg.type === "start") {
    const fps = msg.fps || 25;
    state.uploadSourceFps = fps;
    if (session) session.fps = fps;
    setStatus("active", "Analyzing Upload");
    videoPanelTitle.textContent = sourceName;
    videoPanelSubtitle.textContent = "Realtime accident scan on uploaded footage";
    return;
  }

  if (msg.type === "frame") {
    if (msg.stats) updateFeedStats(msg.stats);
    if (typeof msg.progress === "number" && msg.progress >= 0) progressFill.style.width = `${msg.progress}%`;
    if (typeof msg.timestamp === "number") timestampBadge.textContent = formatTime(msg.timestamp);
    return;
  }

  if (msg.type === "alert" && msg.incident) {
    state.uploadAlertTriggered = true;
    pauseUploadAtIncident(msg.incident, session);
    ingestIncident(msg.incident, {
      source: sourceName,
      fromLive: false,
      sourceUrl: session?.url,
      sourceFps: session?.fps,
      uploadId: session?.id,
    });
    liveTicker.textContent = "Accident detected. Playback paused and emergency workflow triggered.";
    return;
  }

  if (msg.type === "complete") {
    progressFill.style.width = "100%";
    setStatus("idle", state.uploadAlertTriggered ? "Accident Detected" : "No Accident Detected");
    if (!state.uploadAlertTriggered) {
      liveTicker.textContent = "Upload scan completed. No accident detected.";
      showToast("No accident detected in the uploaded video", "success");
    } else {
      showToast("Accident detected in the uploaded video", "alert");
    }
    finishUploadSession({ keepPreview: state.uploadAlertTriggered });
    return;
  }

  if (msg.type === "error") {
    setStatus("alert", "Server Error");
    showToast(`Server error: ${msg.message}`, "error");
    finishUploadSession();
  }
}

function applyAnalysisResult(payload, sourceName) {
  state.cameraMode = false;
  progressFill.style.width = "100%";
  recBadge.style.display = "none";
  fpsBadge.style.display = "none";
  btnStop.disabled = true;
  btnCamera.disabled = false;
  hideUploadPreview();
  videoPanelTitle.textContent = sourceName || payload.filename || "Uploaded Video";
  videoPanelSubtitle.textContent = "Backend accident analysis result";
  if (payload.preview_frame) {
    drawFrame(payload.preview_frame);
  }
  placeholder.style.display = "none";
  enhancementBadge.style.display = "none";
  timestampBadge.textContent = "Complete";
  if (payload.stats) updateFeedStats(payload.stats);
  setStatus("idle", payload.accident_detected ? "Accident Detected" : "No Accident Detected");
  liveTicker.textContent = payload.message || "Backend analysis completed.";

  const alerts = Array.isArray(payload.alerts) ? payload.alerts : [];
  if (alerts.length) {
    const session = getActiveUploadSession();
    alerts.forEach((alert, index) => ingestIncident(alert, {
      source: sourceName || "Uploaded video",
      order: index,
      fromLive: false,
      sourceUrl: session?.url,
      sourceFps: session?.fps,
      uploadId: session?.id,
    }));
  } else {
    renderAll();
  }
  persistDashboardState();

  if (!alerts.length) {
    showToast("No accident detected in the uploaded video", "success");
  } else {
    showToast("Accident detected in the uploaded video", "alert");
  }
}

async function startCamera() {
  if (state.cameraMode) return;
  if (state.uploadInProgress) {
    finishUploadSession();
  }
  hideUploadPreview();
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    showToast("Camera not available in this browser", "error");
    return;
  }

  setStatus("uploading", "Requesting Camera...");
  btnUpload.disabled = true;
  btnCamera.disabled = true;
  btnStop.disabled = false;
  try {
    state.cameraStream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 960 }, height: { ideal: 540 } },
      audio: false,
    });
  } catch (error) {
    setStatus("idle", "System Idle");
    btnUpload.disabled = false;
    btnCamera.disabled = false;
    btnStop.disabled = true;
    document.getElementById("cameraPermModal").classList.remove("hidden");
    return;
  }

  state.cameraMode = true;
  state.sessionStartedAt = Date.now();
  startSessionTimer();
  videoPanelTitle.textContent = "Live Camera Feed";
  videoPanelSubtitle.textContent = "Realtime backend accident monitoring";
  placeholder.style.display = "none";
  recBadge.style.display = "inline-flex";
  progressFill.style.width = "0%";

  state.cameraVideo = document.createElement("video");
  state.cameraVideo.srcObject = state.cameraStream;
  state.cameraVideo.autoplay = true;
  state.cameraVideo.playsInline = true;
  state.cameraVideo.muted = true;
  state.captureCanvas = document.createElement("canvas");

  state.ws = new WebSocket(`${resolveWsBase()}/ws/camera`);
  state.ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "ready") {
      setStatus("active", "Live Camera");
      enhancementBadge.style.display = "none";
      state.cameraVideo.play().then(() => {
        state.captureTimer = setInterval(sendCameraFrame, 120);
      });
      return;
    }
    handleRealtimeMessage(msg, { source: "Live Camera", live: true });
  };
  state.ws.onerror = () => stopCameraSession();
  state.ws.onclose = () => stopCameraSession();
}

function sendCameraFrame() {
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;
  if (!state.cameraVideo || state.cameraVideo.readyState < 2) return;
  const w = state.cameraVideo.videoWidth || 960;
  const h = state.cameraVideo.videoHeight || 540;
  state.captureCanvas.width = w;
  state.captureCanvas.height = h;
  state.captureCanvas.getContext("2d").drawImage(state.cameraVideo, 0, 0, w, h);
  state.ws.send(JSON.stringify({
    type: "frame",
    frame: state.captureCanvas.toDataURL("image/jpeg", 0.72).split(",")[1],
  }));
}

function stopCameraSession() {
  clearInterval(state.captureTimer);
  state.captureTimer = null;
  if (state.cameraStream) {
    state.cameraStream.getTracks().forEach((track) => track.stop());
    state.cameraStream = null;
  }
  if (state.ws) {
    try {
      state.ws.close();
    } catch {}
    state.ws = null;
  }
  state.cameraMode = false;
  recBadge.style.display = "none";
  fpsBadge.style.display = "none";
  enhancementBadge.style.display = "none";
  btnUpload.disabled = false;
  btnCamera.disabled = false;
  btnStop.disabled = true;
  setStatus("idle", "System Idle");
}

function stopProcessing() {
  if (state.uploadInProgress) {
    finishUploadSession();
    progressFill.style.width = "0%";
    setStatus("idle", "System Idle");
    liveTicker.textContent = "Upload analysis view reset.";
    showToast("Upload preview cleared", "info");
  }
  if (state.cameraMode && state.ws) {
    try {
      state.ws.send(JSON.stringify({ type: "stop" }));
    } catch {}
  }
  stopCameraSession();
}

function handleRealtimeMessage(msg, meta = {}) {
  if (msg.type === "info") {
    showToast(msg.message, "info");
    liveTicker.textContent = msg.message;
    return;
  }

  if (msg.type === "frame") {
    const now = performance.now();
    if (state.frameReceiveTime > 0) {
      const fps = Math.round(1000 / (now - state.frameReceiveTime));
      fpsBadge.textContent = `${Math.min(fps, 60)} FPS`;
    }
    state.frameReceiveTime = now;
    drawFrame(msg.frame);
    placeholder.style.display = "none";
    if (msg.stats) updateFeedStats(msg.stats);
    if (typeof msg.progress === "number" && msg.progress >= 0) progressFill.style.width = `${msg.progress}%`;
    if (typeof msg.timestamp === "number") timestampBadge.textContent = formatTime(msg.timestamp);
    enhancementBadge.style.display = msg.enhancement_mode && msg.enhancement_mode !== "Normal" ? "block" : "none";
    enhancementBadge.textContent = msg.enhancement_mode || "";
    return;
  }

  if (msg.type === "alert" && msg.incident) {
    ingestIncident(msg.incident, { source: meta.source || "Live feed", fromLive: true });
    return;
  }

  if (msg.type === "complete") {
    if (!state.cameraMode) setStatus("idle", "Analysis Complete");
    if (msg.stats) updateFeedStats(msg.stats);
    progressFill.style.width = "100%";
    liveTicker.textContent = "Backend processing completed.";
    if ((msg.total_alerts || 0) === 0) {
      showToast("No accident detected", "success");
    }
    return;
  }

  if (msg.type === "error") {
    setStatus("alert", "Server Error");
    showToast(`Server error: ${msg.message}`, "error");
  }
}

function drawFrame(b64) {
  const img = new Image();
  img.onload = () => {
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    ctx.drawImage(img, 0, 0);
  };
  img.src = `data:image/jpeg;base64,${b64}`;
}

function closeUploadStream() {
  if (!state.uploadWs) return;
  try {
    state.uploadWs.close();
  } catch {}
  state.uploadWs = null;
}

function finishUploadSession(options = {}) {
  const { keepPreview = false } = options;
  state.uploadInProgress = false;
  state.uploadJobId = null;
  state.uploadSourceFps = 0;
  btnUpload.disabled = false;
  btnCamera.disabled = false;
  btnStop.disabled = true;
  closeUploadStream();
  if (!keepPreview) {
    hideUploadPreview();
  }
}

function pauseUploadAtIncident(incident, uploadSession) {
  if (!uploadPreview) return;
  const fps = uploadSession?.fps || state.uploadSourceFps || 25;
  const incidentTime = incident.frame_number ? Math.max(0, incident.frame_number / fps) : uploadPreview.currentTime;
  try {
    uploadPreview.currentTime = incidentTime;
  } catch {}
  uploadPreview.pause();
}

function showUploadPreview(source) {
  if (!uploadPreview) return;
  let url;
  if (source && source.url) {
    url = source.url;
  } else {
    url = URL.createObjectURL(source);
  }
  state.uploadPreviewUrl = url;
  uploadPreview.src = url;
  uploadPreview.classList.remove("hidden");
  uploadPreview.currentTime = 0;
  uploadPreview.playbackRate = 0.9;
  uploadPreview.play().catch(() => {});
  placeholder.style.display = "none";
  enhancementBadge.style.display = "none";
}

function hideUploadPreview() {
  if (!uploadPreview) return;
  uploadPreview.pause();
  uploadPreview.removeAttribute("src");
  uploadPreview.load();
  uploadPreview.classList.add("hidden");
  if (state.uploadPreviewUrl) {
    URL.revokeObjectURL(state.uploadPreviewUrl);
    state.uploadPreviewUrl = null;
  }
}

function showIncidentClip(source, startTime = 0) {
  if (!incidentClip) return;
  if (!source) {
    incidentClip.pause();
    incidentClip.removeAttribute("src");
    incidentClip.classList.add("hidden");
    return;
  }

  const seekStart = Math.max(0, startTime);
  incidentClip.pause();
  incidentClip.removeAttribute("src");
  incidentClip.load();

  if (incidentClip._metadataListener) {
    incidentClip.removeEventListener("loadedmetadata", incidentClip._metadataListener);
    incidentClip._metadataListener = null;
  }

  const handleLoadedMetadata = () => {
    incidentClip.currentTime = seekStart;
    incidentClip.removeEventListener("loadedmetadata", handleLoadedMetadata);
    incidentClip._metadataListener = null;
    incidentClip.play().catch(() => {});
  };

  incidentClip._metadataListener = handleLoadedMetadata;
  incidentClip.src = source;
  incidentClip.classList.remove("hidden");
  incidentClip.addEventListener("loadedmetadata", handleLoadedMetadata);
  incidentClip.load();

  if (incidentClip.readyState >= 1) {
    incidentClip.currentTime = seekStart;
    incidentClip.play().catch(() => {});
  }
}

function hideIncidentClip() {
  if (!incidentClip) return;
  incidentClip.pause();
  incidentClip.removeAttribute("src");
  incidentClip.classList.add("hidden");
}

function updateFeedStats(stats) {
  state.lastStats = { ...(state.lastStats || {}), ...stats };
  statVehicles.textContent = state.lastStats.total_vehicles ?? 0;
  statFrames.textContent = state.lastStats.frame_count ?? 0;
  persistDashboardState();
}

function normalizeIncident(raw, meta = {}) {
  const index = state.incidents.length;
  const preset = LOCATION_PRESETS[index % LOCATION_PRESETS.length];
  const severity = raw.severity || "Major";
  const time = raw.timestamp ? new Date(raw.timestamp * 1000) : new Date();
  const ref = raw.plates?.[0] || raw.incident_id || `INC-${String(index + 1).padStart(4, "0")}`;
  const responseTime = severity === "Critical" ? 8 : severity === "Major" ? 14 : 21;
  const agencies = [
    { ...RESPONDERS.police, status: "Notified" },
    { ...RESPONDERS.ambulance, status: "Notified" },
    { ...RESPONDERS.hospital, status: severity === "Minor" ? "Pending" : "Notified" },
  ];

  return {
    id: raw.incident_id || `INC-${String(index + 1).padStart(4, "0")}`,
    uid: `uid-${Date.now()}-${Math.random().toString(36).substr(2, 5)}`,
    severity,
    type: raw.collision_type ? raw.collision_type.replace(/[_-]/g, " ") : "Vehicle collision",
    score: Math.round((raw.score || 0.68) * 100),
    timestamp: time,
    locationLabel: meta.locationLabel || preset.label,
    lat: meta.lat || preset.lat + (Math.random() - 0.5) * 0.05,
    lng: meta.lng || preset.lng + (Math.random() - 0.5) * 0.05,
    reference: ref,
    source: meta.source || "Backend stream",
    sourceUrl: meta.sourceUrl || null,
    sourceFps: meta.sourceFps || 25,
    uploadId: meta.uploadId || null,
    status: severity === "Minor" ? "Resolved" : "Responding",
    agencies,
    responseTime,
    improvement: severity === "Critical" ? 58 : severity === "Major" ? 44 : 31,
    autoEscalated: severity !== "Minor",
    frame_number: raw.frame_number || raw.frame || null,
    raw,
  };
}

function ingestIncident(raw, meta = {}) {
  const incident = normalizeIncident(raw, meta);
  state.incidents.unshift(incident);
  if (incident.severity === "Critical" || incident.severity === "Major") {
    showEmergencyModal(incident);
  }
  triggerAlertEffects(incident);
  liveTicker.textContent = `${incident.severity} incident detected on ${incident.locationLabel}. Dispatch initiated.`;
  renderAll();
  persistDashboardState();
}

function triggerAlertEffects(incident) {
  if (!state.soundEnabled) return;
  const flash = document.getElementById("screenFlash");
  flash.className = `screen-flash ${incident.severity}`;
  setTimeout(() => {
    flash.className = "screen-flash";
  }, 500);
}

function renderAll() {
  renderSummaryStats();
  renderDispatchList();
  renderHistoryTimeline();
  renderHospitalPortal();
  renderMap();
  renderHistoryChart();
  persistDashboardState();
}

function renderHospitalPortal() {
  if (!hospitalAlerts) return;
  const filter = state.activeHospFilter;
  let items = state.incidents;

  if (filter !== "all") {
    if (filter === "Active") items = items.filter(i => i.status === "Responding");
    else if (filter === "Accepted") items = items.filter(i => i.status === "Accepted");
    else if (filter === "Completed") items = items.filter(i => i.status === "Resolved");
  }

  if (!items.length) {
    hospitalAlerts.innerHTML = `
      <div class="panel placeholder-panel">
        <h3>No alerts found</h3>
        <p>Filtered list is currently empty.</p>
      </div>
    `;
    return;
  }

  hospitalAlerts.innerHTML = items.map(incident => `
    <div class="hospital-card ${state.selectedIncidentId === incident.uid ? "active-selection" : ""}" 
         onclick="selectIncident('${incident.uid}')" 
         data-severity="${incident.severity}">
      <div class="card-top">
        <span class="card-id">${incident.id}</span>
        <span class="card-time">${incident.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
      </div>
      <h3 class="card-title">${incident.locationLabel}</h3>
      <p class="card-desc">${incident.type} detected. Monitoring active.</p>
      <div class="card-footer">
        <span class="badge ${incident.severity}">${incident.severity}</span>
        <span class="card-confidence">${incident.score}% Conf.</span>
      </div>
    </div>
  `).join("");
}

function selectIncident(uid) {
  state.selectedIncidentId = uid;
  const incident = state.incidents.find((inc) => inc.uid === uid);
  if (!incident) return;

  const { sourceUrl, sourceFps } = resolveIncidentMedia(incident);
  if (sourceUrl) {
    const startTime = incident.frame_number ? Math.max(0, incident.frame_number / sourceFps) : 0;
    showIncidentClip(sourceUrl, startTime);
  } else {
    hideIncidentClip();
  }

  const panel = document.getElementById("incidentDetail");
  if (panel) {
    panel.classList.remove("hidden");
    document.querySelector('.hospital-layout').classList.add('panel-open');
  }

  // Populate all detail fields
  if (detailId) detailId.textContent = incident.id;
  if (detailTitle) detailTitle.textContent = incident.type;
  if (detailLoc) detailLoc.textContent = incident.locationLabel;
  if (detailSeverity) {
    detailSeverity.textContent = incident.severity;
    detailSeverity.className = `badge ${incident.severity.toLowerCase()}`;
  }
  
  const detailTimeEl = document.getElementById("detailTime");
  if (detailTimeEl) detailTimeEl.textContent = incident.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  
  const detailStatusEl = document.getElementById("detailStatus");
  if (detailStatusEl) {
    const hospitalAgency = incident.agencies.find(a => a.label === 'Hospital');
    detailStatusEl.textContent = incident.status || (hospitalAgency ? hospitalAgency.status : 'Responding');
    detailStatusEl.className = `status-text ${detailStatusEl.textContent.toLowerCase()}`;
  }
  
  const detailConfidenceEl = document.getElementById("detailConfidence");
  if (detailConfidenceEl) detailConfidenceEl.textContent = `${incident.score}%`;
  
  const detailDescEl = document.getElementById("detailDesc");
  if (detailDescEl) detailDescEl.textContent = `${incident.type} (${incident.severity} severity) detected at ${incident.locationLabel}. Confidence: ${incident.score}%. ${incident.source}.`;

  // Dynamic nearby hospitals based on incident severity/status
  if (nearbyHospitalList) {
    const hospitals = [
      { name: "KMCH Speciality Hospital", dist: "1.2 km", status: incident.severity === "Critical" ? "Accepted" : "Pending" },
      { name: "PSG Hospitals", dist: "2.8 km", status: "Pending" },
      { name: "Ganga Trauma Care", dist: "3.5 km", status: incident.severity === "Major" ? "Accepted" : "Pending" },
      { name: "Coimbatore Medical College", dist: "5.1 km", status: "Available" },
    ];

    nearbyHospitalList.innerHTML = hospitals.map(h => `
      <div class="hosp-item ${h.status === "Accepted" ? "accepted" : ""}">
        <div class="hosp-info">
          <div class="hosp-name">${h.name}</div>
          <div class="hosp-dist">${h.dist}</div>
        </div>
        <div class="hosp-status">
          <span class="status-badge ${h.status.toLowerCase().replace(/ /g, '-')}">${h.status}</span>
        </div>
      </div>
    `).join("");
  }

  renderHospitalPortal();
}

function closeIncidentDetail() {
  state.selectedIncidentId = null;
  const panel = document.getElementById("incidentDetail");
  if (panel) panel.classList.add("hidden");
  hideIncidentClip();
  document.querySelector('.hospital-layout').classList.remove('panel-open');
  renderHospitalPortal();
}

function updateAmbulanceStatus(incident) {
  const progress = incident.status === "Resolved" ? 100 : (incident.status === "Accepted" ? 60 : 30);
  ambProgress.style.width = `${progress}%`;
  ambTime.textContent = incident.status === "Resolved" ? "Arrived" : "ETA 4 min";
  ambStatus.textContent = incident.status === "Resolved" ? "Completed" : (incident.status === "Accepted" ? "En Route" : "Dispatched");
  
  const milestones = document.querySelectorAll(".milestone");
  milestones.forEach((m, i) => {
    if (progress > (i * 35)) m.classList.add("active");
    else m.classList.remove("active");
  });
}

function updateDetailTimeline(incident) {
  const events = [
    { title: "Accident Detected", desc: "Computer Vision Alert", time: "10:24 AM", active: true },
    { title: "Alert Sent", desc: "Agencies Notified Automatically", time: "10:24 AM", active: true },
    { title: "Hospital Accepted", desc: "Case Locked for KMCH", time: "10:25 AM", active: incident.status !== "Responding" },
    { title: "Ambulance Dispatched", desc: "GPS Tracking Active", time: "10:26 AM", active: incident.status !== "Responding" },
    { title: "Arrival at Location", desc: "Patient Stabilized", time: "--:--", active: incident.status === "Resolved" }
  ];

  incidentTimeline.innerHTML = events.map(e => `
    <div class="pulse-item ${e.active ? "active" : ""}">
      <div class="pulse-dot"></div>
      <div class="pulse-content">
        <b>${e.title}</b>
        <span>${e.desc} • ${e.time}</span>
      </div>
    </div>
  `).join("");
}

function renderSummaryStats() {
  const total = state.incidents.length;
  statIncidents.textContent = total;
  const active = state.incidents.filter((i) => i.status === "Responding").length;
  liveActiveAlerts.textContent = active;
  const resolved = state.incidents.filter((i) => i.status === "Resolved").length;
  liveResolved.textContent = resolved;
  alertTotalCount.textContent = total;
}

function getFilteredIncidents(filter) {
  if (filter === "all") return state.incidents;
  return state.incidents.filter((incident) => incident.severity === filter);
}

function renderDispatchList() {
  const items = getFilteredIncidents(state.activeAlertFilter);
  if (!items.length) {
    dispatchList.innerHTML = `<div class="dispatch-card"><div class="dispatch-title">No alerts yet</div><div class="dispatch-sub">Incoming incidents from upload and live camera will appear here.</div></div>`;
    return;
  }

  dispatchList.innerHTML = items.map((incident) => `
    <article class="dispatch-card clickable-card" onclick="viewIncidentFullDetail('${incident.uid}')">
      <div class="dispatch-header">
        <div>
          <div class="dispatch-title-row">
            <span class="badge ${incident.severity}">${incident.severity}</span>
            <span class="dispatch-title">${incident.locationLabel}</span>
            ${incident.autoEscalated ? `<span class="status-badge">Auto-Escalated</span>` : ""}
          </div>
          <div class="dispatch-sub">
            Reference: <strong>${incident.reference}</strong> | ${incident.type} | ${incident.score}% confidence
          </div>
        </div>
        <div class="mono">${incident.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</div>
      </div>

    </article>
  `).join("");
}

function renderHistoryTimeline() {
  if (!historyTimeline) return;
  const items = getFilteredIncidents(state.activeHistoryFilter);
  if (!items.length) {
    historyTimeline.innerHTML = `<article class="timeline-card"><div class="timeline-title">No history yet</div><div class="timeline-sub">Completed incidents will appear in this timeline.</div></article>`;
    return;
  }

  historyTimeline.innerHTML = items.map((incident) => `
    <article class="timeline-card">
      <div class="timeline-header">
        <div>
          <div class="timeline-title-row">
            <span class="badge ${incident.severity}">${incident.severity}</span>
            <span class="timeline-title">${incident.locationLabel}</span>
          </div>
          <div class="timeline-sub">${incident.type}. Agencies dispatched automatically through backend workflow.</div>
        </div>
        <div class="mono">${incident.timestamp.toLocaleDateString()} ${incident.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</div>
      </div>
      <div class="timeline-metrics">
        <div class="metric-chip"><span>Response Time</span><strong>${incident.responseTime}s</strong></div>
        <div class="metric-chip"><span>Agencies</span><strong>${incident.agencies.filter((a) => a.status === "Notified").length} Notified</strong></div>
        <div class="metric-chip"><span>Improvement</span><strong>+${incident.improvement}%</strong></div>
      </div>
    </article>
  `).join("");
}

function initMap() {
  state.map = L.map("coimbatoreMap", {
    center: [11.1, 78.2],
    zoom: 7,
    zoomControl: true,
  });

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(state.map);

  [
    { label: "Hospital", lat: 11.01, lng: 76.95, color: "#33d06f" },
  ].forEach((point) => {
    const marker = L.circleMarker([point.lat, point.lng], {
      radius: 8,
      color: point.color,
      fillColor: point.color,
      fillOpacity: 0.85,
      weight: 2,
    });
    marker.bindPopup(point.label);
    marker.addTo(state.map);
  });
}

function renderMap() {
  if (!state.map) return;
  state.mapMarkers.forEach((marker) => state.map.removeLayer(marker));
  state.mapMarkers = [];

  const items = state.incidents.slice(0, 12);
  items.forEach((incident) => {
    const marker = L.circleMarker([incident.lat, incident.lng], {
      radius: 11,
      color: severityColor(incident.severity),
      fillColor: severityColor(incident.severity),
      fillOpacity: 0.9,
      weight: 3,
    });
    marker.bindPopup(`
      <div>
        <strong>${incident.locationLabel}</strong><br/>
        ${incident.severity} | ${incident.type}<br/>
        ${incident.reference}
      </div>
    `);
    marker.addTo(state.map);
    state.mapMarkers.push(marker);
  });
}

function centerMap() {
  if (!state.map) return;
  if (!state.incidents.length) {
    state.map.setView([11.1, 78.2], 7);
    return;
  }
  const group = L.featureGroup(state.mapMarkers);
  state.map.fitBounds(group.getBounds().pad(0.35));
}

function clearMapIncidents() {
  state.mapMarkers.forEach((marker) => state.map.removeLayer(marker));
  state.mapMarkers = [];
  showToast("Map pins cleared", "info");
}

function severityColor(severity) {
  if (severity === "Critical") return "#ff504d";
  if (severity === "Major") return "#f5ad1d";
  return "#4f89ff";
}

function renderHistoryAnalytics() {
  const incidents = state.incidents || [];
  const total = incidents.length;
  const active = incidents.filter((incident) => incident.status === "Responding").length;
  const resolved = incidents.filter((incident) => incident.status === "Resolved").length;
  const alertsSent = total;
  const responseTimes = incidents.map((incident) => Number(incident.responseTime) || 0).filter((value) => value > 0);
  const averageResponse = responseTimes.length ? responseTimes.reduce((sum, value) => sum + value, 0) / responseTimes.length : 0;
  const fastestResponse = responseTimes.length ? Math.min(...responseTimes) : 0;
  const slowestResponse = responseTimes.length ? Math.max(...responseTimes) : 0;
const avgConfidence = 0;
const detectionAccuracy = 0;
  const falsePositive = 0;
  const avgImprovement = 0;
  const agenciesNotified = incidents.reduce((sum, incident) => sum + incident.agencies.filter((agency) => agency.status !== "Pending").length, 0);
  const livesSaved = Math.round(total * 2.7);

  const hourCounts = incidents.reduce((counts, incident) => {
    const timestamp = new Date(incident.timestamp);
    const hour = timestamp.getHours();
    counts[hour] = (counts[hour] || 0) + 1;
    return counts;
  }, {});
  const peakHour = Object.entries(hourCounts).reduce((best, [hour, count]) => (count > best.count ? { hour: Number(hour), count } : best), { hour: null, count: 0 });
  const peakTimeLabel = peakHour.hour !== null ? `${peakHour.hour}:00 - ${peakHour.hour + 1}:00` : "No data";

  const locationCounts = incidents.reduce((counts, incident) => {
    const location = incident.locationLabel || "Unknown";
    counts[location] = (counts[location] || 0) + 1;
    return counts;
  }, {});
  const topLocation = Object.entries(locationCounts).sort((a, b) => b[1] - a[1])[0];
  const locationLabel = topLocation ? topLocation[0] : "TBD";

  const responsiveHospital = "No data";

  const setText = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  };

  setText("metricTotalAccidents", total);
  setText("metricActiveIncidents", active);
  setText("metricResolvedIncidents", resolved);
  setText("metricAlertsSent", alertsSent);
  setText("metricAvgResponseTime", `${Math.round(averageResponse)}s`);
  setText("metricFastestResponseTime", `${Math.round(fastestResponse)}s`);
  setText("metricSlowestResponseTime", `${Math.round(slowestResponse)}s`);
  setText("metricDetectionAccuracy", `${detectionAccuracy}%`);
  setText("metricAverageConfidence", `${avgConfidence}%`);
  setText("metricFalsePositiveRate", `${falsePositive}%`);
  setText("metricLivesSaved", livesSaved);
  setText("metricGoldenHour", `${avgImprovement}%`);
  setText("metricAgenciesNotified", agenciesNotified);
  setText("peakAccidentTime", peakTimeLabel);
  setText("accidentProneLocation", locationLabel);
  setText("responsiveHospital", responsiveHospital);
}

function renderHistoryChart() {
  const canvasEl = document.getElementById("historyChart");
  if (!window.Chart || !canvasEl) return;

  renderHistoryAnalytics();

  const dayLabels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const criticalCounts = [0, 0, 0, 0, 0, 0, 0];
const majorCounts = [0, 0, 0, 0, 0, 0, 0];
const minorCounts = [0, 0, 0, 0, 0, 0, 0];

  const datasets = [
    {
      label: "Critical",
      data: criticalCounts,
      backgroundColor: "#dc2626",
      borderWidth: 0,
    },
    {
      label: "Major",
      data: majorCounts,
      backgroundColor: "#f59e0b",
      borderWidth: 0,
    },
    {
      label: "Minor",
      data: minorCounts,
      backgroundColor: "#3b82f6",
      borderWidth: 0,
    },
  ];

  if (state.historyChart) {
    state.historyChart.data.labels = dayLabels;
    state.historyChart.data.datasets = datasets;
    state.historyChart.update();
    return;
  }

  state.historyChart = new Chart(canvasEl.getContext("2d"), {
    type: "bar",
    data: {
      labels: dayLabels,
      datasets: datasets.map(ds => ({
        ...ds,
        borderRadius: 6,
        borderSkipped: false,
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        intersect: false,
        mode: 'index',
      },
      plugins: {
        legend: {
          display: false,
        },
        tooltip: {
          enabled: true,
          backgroundColor: 'transparent',
          padding: 0,
          borderColor: 'transparent',
          borderWidth: 0,
          borderRadius: 0,
          titleFont: {
            size: 14,
            weight: '700',
            color: '#000000',
          },
          bodyFont: {
            size: 13,
            color: '#000000',
            weight: '600',
          },
          titleSpacing: 0,
          bodySpacing: 2,
          displayColors: true,
          boxPadding: 4,
          boxWidth: 10,
          boxHeight: 10,
          xAlign: 'center',
          yAlign: 'bottom',
          callbacks: {
            title: function(context) {
              return context[0].label;
            },
            label: function(context) {
              const count = context.parsed.y;
              if (count === 0) return null;
              return ` ${context.dataset.label}: ${count}`;
            },
            footer: function() {
              return null;
            },
          },
        },
      },
      scales: {
        x: {
          stacked: true,
          ticks: {
            color: "#9ca3af",
            font: {
              size: 12,
              weight: '500',
            },
          },
          grid: {
            display: false,
          },
        },
        y: {
          stacked: true,
          beginAtZero: true,
          max: 4,
          ticks: {
            color: "#9ca3af",
            stepSize: 1,
            font: {
              size: 12,
              weight: '500',
            },
            callback: function(value) {
              return value;
            },
          },
          grid: {
            color: 'rgba(31, 41, 55, 0.5)',
            lineWidth: 1,
            drawBorder: false,
          },
        },
      },
    },
  });
}

function showEmergencyModal(incident) {
  const modal = document.getElementById("emergencyModal");
  modal.classList.remove("hidden");
  document.getElementById("emergencyTitle").textContent = `${incident.severity} accident detected`;
  document.getElementById("emergencyId").textContent = incident.id;
  document.getElementById("emergencyType").textContent = incident.type;
  document.getElementById("ambEta").textContent = `ETA ${Math.max(2, Math.round(incident.responseTime / 3))} min`;
  document.getElementById("polEta").textContent = `ETA ${Math.max(1, Math.round(incident.responseTime / 4))} min`;
  document.getElementById("fireEta").textContent = incident.severity === "Critical" ? "ETA 4 min" : "Standby";
  document.getElementById("emergencyScorePct").textContent = `${incident.score}%`;
  document.getElementById("emergencyScoreBar").style.width = `${incident.score}%`;
}

function closeEmergency() {
  document.getElementById("emergencyModal").classList.add("hidden");
}

function captureScreenshot() {
  if (!canvas.width) {
    showToast("No active frame to capture", "error");
    return;
  }
  const link = document.createElement("a");
  link.href = canvas.toDataURL("image/png");
  link.download = `resq_snapshot_${Date.now()}.png`;
  link.click();
  showToast("Screenshot saved", "success");
}

function toggleFullscreen() {
  const container = document.getElementById("videoContainer");
  if (!document.fullscreenElement) {
    container.requestFullscreen?.();
  } else {
    document.exitFullscreen?.();
  }
}

function setupUtilityEvents() {
  btnStop.addEventListener("click", stopProcessing);
  btnCamera.addEventListener("click", startCamera);
  soundBtn.addEventListener("click", () => {
    state.soundEnabled = !state.soundEnabled;
    showToast(state.soundEnabled ? "Sound alerts enabled" : "Sound alerts muted", "info");
  });
  const clearHistoryBtn = document.getElementById("clearHistoryBtn");
  if (clearHistoryBtn) {
    clearHistoryBtn.addEventListener("click", () => {
      state.incidents = [];
      persistDashboardState();
      renderAll();
      showToast("History cleared", "info");
    });
  }
}

function startSessionTimer() {
  if (state.sessionTimer) clearInterval(state.sessionTimer);
  if (!state.sessionStartedAt) state.sessionStartedAt = Date.now();
  state.sessionTimer = setInterval(() => {
    const seconds = (Date.now() - state.sessionStartedAt) / 1000;
    if (dateBadge) dateBadge.title = `Session uptime ${formatTime(seconds)}`;
  }, 1000);
}

function setupHospitalPanelEvents() {
  const hospitalLayout = document.querySelector('.hospital-layout');
  const incidentDetail = document.getElementById('incidentDetail');
  
  if (!hospitalLayout || !incidentDetail) return;

  // Click outside to close
  hospitalLayout.addEventListener('click', (e) => {
    if (e.target === hospitalLayout && !incidentDetail.classList.contains('hidden')) {
      closeIncidentDetail();
    }
  });

  // Prevent panel content clicks from closing
  incidentDetail.addEventListener('click', (e) => {
    e.stopPropagation();
  });
}

async function bootstrap() {
  await restoreDashboardState();
  setupNavigation();
  setupSidebarToggle();
  setupFilters();
  setupModals();
  setupUtilityEvents();
  setupHospitalPanelEvents();
  initMap();
  renderAll();
  switchPage(state.lastPage || "live");
  if (state.selectedIncidentId && state.lastPage === "hospital") {
    selectIncident(state.selectedIncidentId);
  }
  cycleClock();
  state.clockTimer = setInterval(cycleClock, 1000);
  startSessionTimer();
  setStatus("idle", "Checking Backend...");
  recBadge.style.display = "none";
  fpsBadge.style.display = "none";
  checkBackendHealth();
}

document.addEventListener("DOMContentLoaded", () => {
  bootstrap().catch((error) => {
    console.error("Bootstrap failed:", error);
  });
});

window.openUpload = openUpload;
window.startCamera = startCamera;
window.closeEmergency = closeEmergency;
window.captureScreenshot = captureScreenshot;
window.toggleFullscreen = toggleFullscreen;
window.centerMap = centerMap;
window.clearMapIncidents = clearMapIncidents;
window.closeIncidentDetail = closeIncidentDetail;
window.selectIncident = selectIncident;

function viewIncidentFullDetail(uid) {
  const incident = state.incidents.find((inc) => inc.uid === uid);
  if (!incident) return;

  // Title & Header
  document.getElementById("fsIncidentTitle").textContent = `Incident ${incident.reference || incident.id} Details`;
  const sevEl = document.getElementById("fsIncidentSeverity");
  sevEl.textContent = incident.severity;
  sevEl.className = `badge ${incident.severity}`;

  // Left Panel data
  document.getElementById("fsConfidence").textContent = `${incident.score}%`;
  document.getElementById("fsTime").textContent = incident.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  document.getElementById("fsLocation").textContent = incident.locationLabel;
  // Bounding box mock logic based on collision type
  const v1 = document.getElementById("fsBbox1");
  const v2 = document.getElementById("fsBbox2");
  v1.style.top = Math.floor(Math.random()*(40-10)+10) + "%";
  v1.style.left = Math.floor(Math.random()*(30-10)+10) + "%";
  if (incident.type.toLowerCase().includes("collision") || incident.type.toLowerCase().includes("multiple")) {
    v2.classList.remove("hidden");
    v2.style.top = Math.floor(Math.random()*(50-15)+15) + "%";
    v2.style.left = Math.floor(Math.random()*(85-50)+50) + "%";
  } else {
    v2.classList.add("hidden");
  }

  // Right Panel data
  document.getElementById("fsRespTime").textContent = `${(Math.random()*(12.5-4.2)+4.2).toFixed(1)}s`;
  const baseLoc = incident.locationLabel ? incident.locationLabel.split(",")[0] : "Central";
  document.getElementById("fsPoliceName").textContent = `${baseLoc} Police Station`;
  let acceptedHosp = "Pending Assignment";
  if (incident.severity === "Critical") acceptedHosp = "KMCH Speciality Hospital";
  else if (incident.severity === "Major") acceptedHosp = "Ganga Trauma Care";
  else acceptedHosp = "Coimbatore Medical College";
  document.getElementById("fsHospitalName").textContent = acceptedHosp;

  // Show the available incident video clip when opening full details
  const { sourceUrl, sourceFps } = resolveIncidentMedia(incident);
  if (sourceUrl) {
    const startTime = incident.frame_number ? Math.max(0, incident.frame_number / sourceFps) : 0;
    showIncidentClip(sourceUrl, startTime);
  } else {
    hideIncidentClip();
  }

  // Hide sidebar and transition
  if (dashboardShell) {
    dashboardShell.classList.add("sidebar-collapsed");
  }
  
  switchPage("incident-detail");
}

function closeIncidentFullDetail() {
  if (window.innerWidth > 960 && dashboardShell) {
    dashboardShell.classList.remove("sidebar-collapsed");
  }
  hideIncidentClip();
  switchPage("alerts");
}

window.viewIncidentFullDetail = viewIncidentFullDetail;
window.closeIncidentFullDetail = closeIncidentFullDetail;