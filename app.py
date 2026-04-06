"""
Rescue Vision - FastAPI Application Entry Point
AI-Powered Smart Accident Detection & Autonomous Emergency Response System
"""

import asyncio
import base64
import uuid
from pathlib import Path
from typing import Dict

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Heavy ML imports are done lazily inside the WebSocket handler so the server
# can start and serve the dashboard even before all packages are installed.
_pipeline_cls = None

def _get_pipeline_cls():
    global _pipeline_cls
    if _pipeline_cls is None:
        import cv2  # noqa: F401 — ensure opencv is available
        from backend.pipeline import AccidentDetectionPipeline
        _pipeline_cls = AccidentDetectionPipeline
    return _pipeline_cls

# ─────────────────────────────────────────────────
# App Setup
# ─────────────────────────────────────────────────

app = FastAPI(
    title="Rescue Vision",
    description="AI-Powered Smart Accident Detection & Emergency Response",
    version="1.0.0",
)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Active job registry: job_id → { status, path, alerts }
jobs: Dict[str, dict] = {}

# Mount static files
app.mount("/static", StaticFiles(directory="frontend"), name="static")


# ─────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    html_path = Path("frontend/index.html")
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    """Receive a video file and return a job_id for WebSocket processing."""
    allowed_ext = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed_ext:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    job_id = uuid.uuid4().hex[:8]
    save_path = UPLOAD_DIR / f"{job_id}{ext}"

    content = await file.read()
    if len(content) > 500 * 1024 * 1024:  # 500 MB limit
        raise HTTPException(status_code=413, detail="File too large (max 500 MB)")

    save_path.write_bytes(content)
    jobs[job_id] = {
        "status": "ready",
        "path": str(save_path),
        "alerts": [],
        "filename": file.filename,
    }
    return {"job_id": job_id, "filename": file.filename}


@app.get("/api/job/{job_id}")
async def get_job_status(job_id: str):
    """Return current job status and incident list."""
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
    """
    Browser-camera pipeline endpoint.
    The browser captures the webcam via getUserMedia, sends raw JPEG frames here
    as base64, and this endpoint runs each frame through the accident-detection
    pipeline and streams annotated frames back.
    """
    await websocket.accept()

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
    live_alerts: list = []
    frame_idx = 0

    # Tell the browser the backend is ready to receive frames
    await websocket.send_json({"type": "ready"})

    try:
        while True:
            msg = await websocket.receive_json()

            if msg.get("type") == "stop":
                break

            if msg.get("type") != "frame":
                continue

            # Decode the base64 JPEG frame sent by the browser
            frame_bytes = base64.b64decode(msg["frame"])
            nparr = _np.frombuffer(frame_bytes, _np.uint8)
            frame = _cv2.imdecode(nparr, _cv2.IMREAD_COLOR)
            if frame is None:
                continue

            frame_idx += 1
            # Process every other frame for speed on CPU
            if frame_idx % 2 != 0:
                continue
            frame = _resize_frame(frame, max_width=720)
            result = pipeline.process_frame(frame)

            _, buf = _cv2.imencode(
                ".jpg", result["annotated_frame"],
                [_cv2.IMWRITE_JPEG_QUALITY, 72],
            )
            frame_b64 = base64.b64encode(buf).decode("utf-8")

            response: dict = {
                "type": "frame",
                "frame": frame_b64,
                "stats": result["stats"],
                "enhancement_mode": result["enhancement_mode"],
                "timestamp": round(frame_idx / 30, 2),
                "progress": -1,
            }

            if result["alert"]:
                incident = result["alert"]
                live_alerts.append(incident)
                response["alert"] = incident
                await websocket.send_json({"type": "alert", "incident": incident})

            await websocket.send_json(response)

    except WebSocketDisconnect:
        pass
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
    """
    Stream processed video frames and incidents back to the browser in real time.
    Message types sent:
      - { type: "start",    total_frames, fps }
      - { type: "frame",    frame (base64 JPEG), stats, enhancement_mode, timestamp }
      - { type: "alert",    incident dict }
      - { type: "complete", stats }
      - { type: "error",    message }
    """
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
    target_fps = 10  # process 10 frames per second
    frame_skip = max(1, int(src_fps / target_fps))

    await websocket.send_json({
        "type": "start",
        "total_frames": total_frames,
        "fps": src_fps,
    })

    pipeline = PipelineCls()
    frame_idx = 0

    try:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            frame_idx += 1
            if frame_idx % frame_skip != 0:
                continue

            # Resize for faster processing
            frame = _resize_frame(frame, max_width=720)

            # Run the pipeline
            result = pipeline.process_frame(frame)

            # Encode annotated frame → JPEG → base64
            _, buf = _cv2.imencode(
                ".jpg", result["annotated_frame"],
                [_cv2.IMWRITE_JPEG_QUALITY, 72],
            )
            frame_b64 = base64.b64encode(buf).decode("utf-8")

            progress = round(frame_idx / max(total_frames, 1) * 100, 1)

            msg: dict = {
                "type": "frame",
                "frame": frame_b64,
                "stats": result["stats"],
                "enhancement_mode": result["enhancement_mode"],
                "timestamp": round(frame_idx / src_fps, 2),
                "progress": progress,
            }

            if result["alert"]:
                incident = result["alert"]
                job["alerts"].append(incident)
                msg["alert"] = incident
                # Also send as a separate alert message for the incident panel
                await websocket.send_json({"type": "alert", "incident": incident})

            await websocket.send_json(msg)
            # Small yield so other tasks can run
            await asyncio.sleep(0)

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


# ─────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────

def _resize_frame(frame, max_width: int = 960):
    import cv2 as _cv2
    import numpy as _np
    h, w = frame.shape[:2]
    if w <= max_width:
        return frame
    new_h = int(h * max_width / w)
    return _cv2.resize(frame, (max_width, new_h), interpolation=_cv2.INTER_AREA)


# ─────────────────────────────────────────────────
# Dev entry point
# ─────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
