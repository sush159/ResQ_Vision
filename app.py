"""
ResQ Vision FastAPI application.

This server is shaped around the current frontend contract:
1. `POST /api/analyze` handles uploaded-video analysis and returns one JSON payload.
2. `WS /ws/camera` handles live browser-camera frames in realtime.
3. Legacy upload/job websocket routes remain available for compatibility.
"""

import asyncio
import base64
import logging
import threading
import uuid
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.hospitals import HOSPITALS, find_nearby_hospitals

_pipeline_cls = None
_upload_pipeline = None
logger = logging.getLogger("resq_vision")


def _get_pipeline_cls():
    global _pipeline_cls
    if _pipeline_cls is None:
        import cv2  # noqa: F401
        from backend.pipeline import AccidentDetectionPipeline
        _pipeline_cls = AccidentDetectionPipeline
    return _pipeline_cls


def _get_upload_pipeline():
    global _upload_pipeline
    if _upload_pipeline is None:
        _upload_pipeline = _get_pipeline_cls()()
    return _upload_pipeline


BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
DEFAULT_TARGET_FPS = 10
UPLOAD_TARGET_FPS = 8
UPLOAD_MAX_WIDTH = 512
UPLOAD_MAX_PROCESSED_FRAMES = 240
UPLOAD_STREAM_TARGET_FPS = 12

# Active job registry: job_id -> {status, path, alerts, filename}
jobs: Dict[str, dict] = {}

# Incident Lifecycle Registry: incident_id -> {status, accepted_by, hospitals, timeline}
incident_states: Dict[str, dict] = {}
# History for the dashboard
incident_history: List[dict] = []

# Connected WebSocket clients for broadcasting status
connected_clients: List[WebSocket] = []

async def broadcast_status(data: dict):
    """Utility to broadcast status updates to all active UI clients."""
    dead_clients = []
    for client in connected_clients:
        try:
            await client.send_json(data)
        except Exception:
            dead_clients.append(client)
    for dead in dead_clients:
        if dead in connected_clients:
            connected_clients.remove(dead)

app = FastAPI(
    title="ResQ Vision",
    description="AI-powered accident detection and emergency response backend",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")


@app.on_event("startup")
async def warm_upload_pipeline():
    def _warm():
        try:
            pipeline = _get_upload_pipeline()
            pipeline.reset_session()
            logger.info("Upload pipeline warmed successfully")
        except Exception:
            logger.exception("Upload pipeline warmup failed")

    threading.Thread(target=_warm, daemon=True).start()


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    return HTMLResponse((FRONTEND_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "service": "resq-vision-backend",
        "upload_endpoint": "/api/analyze",
        "live_socket": "/ws/camera",
    }


@app.get("/api/hospitals")
async def get_hospitals():
    """Returns all registered hospitals."""
    return HOSPITALS


@app.get("/api/incident/{incident_id}")
async def get_incident_details(incident_id: str):
    """Returns the full state of an incident."""
    if incident_id not in incident_states:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident_states[incident_id]


@app.post("/api/incident/{incident_id}/accept")
async def accept_incident(incident_id: str, hospital_id: str = Body(..., embed=True)):
    """Handles first-come-first-serve acceptance."""
    if incident_id not in incident_states:
        raise HTTPException(status_code=404, detail="Incident not found")
    
    state = incident_states[incident_id]
    if state["status"] != "Pending":
        return {
            "success": False, 
            "message": f"Already accepted by {state['accepted_by']['name'] if state['accepted_by'] else 'another agency'}"
        }

    hospital = next((h for h in HOSPITALS if h["id"] == hospital_id), None)
    if not hospital:
        raise HTTPException(status_code=400, detail="Invalid hospital ID")

    state["status"] = "Accepted"
    state["accepted_by"] = hospital
    state["timeline"].append({
        "status": "Accepted",
        "time": datetime.now().strftime("%I:%M %p"),
        "message": f"Accepted by {hospital['name']}"
    })

    await broadcast_status({
        "type": "incident_update",
        "incident_id": incident_id,
        "state": state
    })
    return {"success": True, "state": state}


@app.post("/api/incident/{incident_id}/update-status")
async def update_incident_status(incident_id: str, status: str = Body(..., embed=True)):
    """Updates the response status (Dispatched, On the way, etc.)."""
    if incident_id not in incident_states:
        raise HTTPException(status_code=404, detail="Incident not found")
    
    state = incident_states[incident_id]
    valid_statuses = ["Dispatched", "On the way", "Arrived", "Resolved"]
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Invalid status")

    state["status"] = status
    state["timeline"].append({
        "status": status,
        "time": datetime.now().strftime("%I:%M %p"),
        "message": f"Status updated to {status}"
    })

    if status == "Resolved":
        # Add to history if not exists
        if not any(h["incident_id"] == incident_id for h in incident_history):
            incident_history.append(state)

    await broadcast_status({
        "type": "incident_update",
        "incident_id": incident_id,
        "state": state
    })
    return {"success": True, "state": state}


@app.post("/api/analyze")
async def analyze_video(file: UploadFile = File(...)):
    """
    Frontend-facing upload route used by `frontend/js/app.js`.

    The UI expects a single JSON payload with:
    - accident_detected
    - message
    - preview_frame
    - stats
    - alerts
    """
    save_path = await _store_upload(file)

    try:
        result = await asyncio.to_thread(
            _analyze_video_file,
            save_path,
            file.filename or save_path.name,
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected upload analysis failure for %s", file.filename)
        raise HTTPException(status_code=500, detail=f"Video analysis failed: {exc}") from exc
    finally:
        try:
            save_path.unlink(missing_ok=True)
        except OSError:
            pass


@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    """
    Legacy compatibility route.
    Keeps the prior websocket-job flow available if something still uses it.
    """
    save_path = await _store_upload(file)
    job_id = uuid.uuid4().hex[:8]
    jobs[job_id] = {
        "status": "ready",
        "path": str(save_path),
        "alerts": [],
        "filename": file.filename,
    }
    return {"job_id": job_id, "filename": file.filename}


@app.get("/api/job/{job_id}")
async def get_job_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    return {
        "job_id": job_id,
        "status": job["status"],
        "filename": job.get("filename"),
        "alert_count": len(job["alerts"]),
        "alerts": job["alerts"],
    }


@app.websocket("/ws/camera")
async def websocket_camera(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)

    try:
        PipelineCls = _get_pipeline_cls()
        import cv2 as _cv2
        import numpy as _np
    except Exception as exc:
        await websocket.send_json({
            "type": "error",
            "message": f"ML dependencies not installed: {exc}. Run: pip install -r requirements.txt",
        })
        await websocket.close()
        return

    pipeline = PipelineCls()
    live_alerts = []
    frame_idx = 0

    await websocket.send_json({"type": "ready"})

    try:
        while True:
            msg = await websocket.receive_json()

            if msg.get("type") == "stop":
                break

            if msg.get("type") != "frame":
                continue

            frame_bytes = base64.b64decode(msg["frame"])
            nparr = _np.frombuffer(frame_bytes, _np.uint8)
            frame = _cv2.imdecode(nparr, _cv2.IMREAD_COLOR)
            if frame is None:
                continue

            frame_idx += 1
            if frame_idx % 2 != 0:
                continue

            frame = _resize_frame(frame, max_width=720)
            result = pipeline.process_frame(frame)

            response = {
                "type": "frame",
                "frame": _encode_frame(result["annotated_frame"], quality=72),
                "stats": result["stats"],
                "enhancement_mode": result["enhancement_mode"],
                "timestamp": round(frame_idx / 30, 2),
                "progress": -1,
            }

            if result["alert"]:
                incident = result["alert"]
                
                # Initialize Incident State if new
                iid = incident["incident_id"]
                if iid not in incident_states:
                    # Mocking Coimbatore-centric location if not provided
                    # Backend provides frame-relative center, we map it to Coimbatore bounds
                    lat = 11.0168 + (uuid.uuid4().int % 1000) / 50000 
                    lng = 76.9558 + (uuid.uuid4().int % 1000) / 50000
                    
                    nearby = find_nearby_hospitals(lat, lng)
                    incident_states[iid] = {
                        "incident_id": iid,
                        "base_data": incident,
                        "lat": lat,
                        "lng": lng,
                        "status": "Pending",
                        "accepted_by": None,
                        "hospitals": nearby,
                        "timeline": [{
                            "status": "Detected",
                            "time": datetime.now().strftime("%I:%M %p"),
                            "message": "AI System detected potential accident"
                        }]
                    }
                    incident["extended_state"] = incident_states[iid]

                live_alerts.append(incident)
                await broadcast_status({"type": "alert", "incident": incident})

            await websocket.send_json(response)

    except WebSocketDisconnect:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
    except Exception as exc:
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        try:
            await websocket.send_json({
                "type": "complete",
                "stats": pipeline.stats,
                "total_alerts": len(live_alerts),
            })
        except Exception:
            pass


@app.websocket("/ws/{job_id}")
async def websocket_stream(websocket: WebSocket, job_id: str):
    await websocket.accept()

    if job_id not in jobs:
        await websocket.send_json({"type": "error", "message": "Job not found"})
        await websocket.close()
        return

    job = jobs[job_id]
    job["status"] = "processing"

    try:
        PipelineCls = _get_pipeline_cls()
        import cv2 as _cv2
    except Exception as exc:
        await websocket.send_json({
            "type": "error",
            "message": f"ML dependencies not installed: {exc}. Run: pip install -r requirements.txt",
        })
        await websocket.close()
        return

    cap = _cv2.VideoCapture(job["path"])
    if not cap.isOpened():
        await websocket.send_json({"type": "error", "message": "Cannot open video file"})
        await websocket.close()
        return

    total_frames = int(cap.get(_cv2.CAP_PROP_FRAME_COUNT))
    src_fps = cap.get(_cv2.CAP_PROP_FPS) or 25.0
    target_fps = UPLOAD_STREAM_TARGET_FPS
    frame_skip = max(1, int(src_fps / target_fps))

    await websocket.send_json({
        "type": "start",
        "total_frames": total_frames,
        "fps": src_fps,
    })

    pipeline = _get_upload_pipeline()
    pipeline.reset_session()
    frame_idx = 0
    processed_frames = 0

    try:
        while cap.isOpened():
            grabbed = cap.grab()
            if not grabbed:
                break

            frame_idx += 1
            if frame_idx % frame_skip != 0:
                continue

            ret, frame = cap.retrieve()
            if not ret:
                continue

            processed_frames += 1

            frame = _resize_frame(frame, max_width=UPLOAD_MAX_WIDTH)
            result = pipeline.process_frame_fast(frame)
            progress = round(frame_idx / max(total_frames, 1) * 100, 1)

            msg = {
                "type": "frame",
                "frame": _encode_frame(result["annotated_frame"], quality=72),
                "stats": result["stats"],
                "enhancement_mode": result["enhancement_mode"],
                "timestamp": round(frame_idx / src_fps, 2),
                "progress": progress,
            }

            if result["alert"]:
                incident = result["alert"]
                job["alerts"].append(incident)
                await websocket.send_json({"type": "alert", "incident": incident})
                await websocket.send_json(msg)
                break

            await websocket.send_json(msg)
            await asyncio.sleep(0)

            if processed_frames >= UPLOAD_MAX_PROCESSED_FRAMES:
                break

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        cap.release()
        job["status"] = "done"
        try:
            await websocket.send_json({
                "type": "complete",
                "stats": pipeline.stats,
                "total_alerts": len(job["alerts"]),
            })
        except Exception:
            pass


async def _store_upload(file: UploadFile) -> Path:
    filename = file.filename or "upload.bin"
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 500 MB)")

    save_path = UPLOAD_DIR / f"{uuid.uuid4().hex[:12]}{ext}"
    save_path.write_bytes(content)
    return save_path


def _analyze_video_file(path: Path, original_name: str) -> dict:
    try:
        PipelineCls = _get_pipeline_cls()
        import cv2 as _cv2
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"ML dependencies not installed: {exc}. Run: pip install -r requirements.txt",
        ) from exc

    cap = _cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise HTTPException(status_code=400, detail="Unable to open uploaded video")

    try:
        pipeline = _get_upload_pipeline()
        pipeline.reset_session()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to initialize accident-detection pipeline: {exc}",
        ) from exc
    total_frames = int(cap.get(_cv2.CAP_PROP_FRAME_COUNT))
    src_fps = cap.get(_cv2.CAP_PROP_FPS) or 25.0
    frame_skip = max(1, int(src_fps / UPLOAD_TARGET_FPS))

    alerts = []
    preview_frame = None
    processed_frames = 0
    last_timestamp = 0.0

    try:
        frame_idx = 0
        while cap.isOpened():
            grabbed = cap.grab()
            if not grabbed:
                break

            frame_idx += 1
            if frame_idx % frame_skip != 0:
                continue

            ret, frame = cap.retrieve()
            if not ret:
                continue

            processed_frames += 1
            last_timestamp = round(frame_idx / src_fps, 2)
            frame = _resize_frame(frame, max_width=UPLOAD_MAX_WIDTH)
            result = pipeline.process_frame_fast(frame)

            preview_frame = result["annotated_frame"]
            if result["alert"]:
                alerts.append(result["alert"])
                break
            if processed_frames >= UPLOAD_MAX_PROCESSED_FRAMES:
                break
    finally:
        cap.release()

    stats = dict(pipeline.stats)
    stats["processed_frames"] = processed_frames
    stats["source_fps"] = round(src_fps, 2)
    stats["duration_seconds"] = round(total_frames / src_fps, 2) if total_frames and src_fps else last_timestamp

    accident_detected = bool(alerts)
    return {
        "job_id": uuid.uuid4().hex[:8],
        "filename": original_name,
        "accident_detected": accident_detected,
        "message": (
            f"Accident analysis complete. {len(alerts)} incident(s) detected."
            if accident_detected
            else "Analysis complete. No accident detected."
        ),
        "preview_frame": _encode_frame(preview_frame, quality=78) if preview_frame is not None else None,
        "stats": stats,
        "alerts": alerts,
        "analysis": {
            "total_frames": total_frames,
            "processed_frames": processed_frames,
            "sampling_stride": frame_skip,
            "last_timestamp": last_timestamp,
            "fast_scan": True,
            "max_processed_frames": UPLOAD_MAX_PROCESSED_FRAMES,
        },
    }


def _encode_frame(frame, quality: int = 72) -> str:
    import cv2 as _cv2

    ok, buf = _cv2.imencode(".jpg", frame, [_cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("Failed to encode processed frame")
    return base64.b64encode(buf).decode("utf-8")


def _resize_frame(frame, max_width: int = 960):
    import cv2 as _cv2

    h, w = frame.shape[:2]
    if w <= max_width:
        return frame
    new_h = int(h * max_width / w)
    return _cv2.resize(frame, (max_width, new_h), interpolation=_cv2.INTER_AREA)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
