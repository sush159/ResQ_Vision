# ResQ Vision Backend Workflow

## Frontend analysis

The current frontend is a control-room dashboard with two backend entry paths:

1. Upload flow
   `frontend/js/app.js` sends a video file to `POST /api/analyze`.
   The frontend expects one final JSON response, not a websocket stream.

2. Live camera flow
   `frontend/js/app.js` opens `WS /ws/camera`.
   The browser captures webcam frames, sends them as base64 JPEG payloads, and expects realtime processed frames and alert events back.

The UI then renders:

- `preview_frame` into the main canvas
- `stats.total_vehicles` and `stats.frame_count` into the live stats
- `alerts[]` into alert, map, and history panels
- `message` into the live ticker
- `accident_detected` into status and toast behavior

## Backend workflow

### 1. Dashboard delivery

- `GET /` serves `frontend/index.html`
- `/static` exposes the rest of the frontend folder
- `GET /api/health` gives a quick readiness check

### 2. Uploaded video workflow

1. Browser selects a file in the upload modal.
2. Frontend sends multipart form data to `POST /api/analyze`.
3. Backend validates extension and file size.
4. Backend stores the file temporarily in `uploads/`.
5. Backend opens the video with OpenCV.
6. Backend samples frames at a controlled rate to reduce CPU load.
7. Every sampled frame goes through `backend.pipeline.AccidentDetectionPipeline`.
8. The pipeline performs:
   - frame enhancement
   - YOLO-based detection
   - DeepSORT tracking
   - accident inference
   - license plate extraction on confirmed incidents
   - annotated-frame generation
9. Backend collects all detected incidents and keeps the last annotated frame as `preview_frame`.
10. Backend returns one final JSON response and removes the temp upload.

### 3. Live camera workflow

1. Browser requests webcam permission.
2. Frontend opens `WS /ws/camera`.
3. Backend replies with `{ "type": "ready" }`.
4. Frontend captures browser video frames and sends them as base64 JPEG.
5. Backend decodes each frame, resizes it, and runs the same detection pipeline.
6. Backend sends:
   - `type: "frame"` with the annotated frame and stats
   - `type: "alert"` when an incident is confirmed
   - `type: "complete"` when the session ends
   - `type: "error"` on failures

## Response contract

### `POST /api/analyze`

```json
{
  "job_id": "a1b2c3d4",
  "filename": "traffic.mp4",
  "accident_detected": true,
  "message": "Accident analysis complete. 1 incident(s) detected.",
  "preview_frame": "<base64-jpeg>",
  "stats": {
    "total_vehicles": 4,
    "total_incidents": 1,
    "frame_count": 87,
    "processed_frames": 87,
    "source_fps": 29.97,
    "duration_seconds": 31.2
  },
  "alerts": [],
  "analysis": {
    "total_frames": 936,
    "processed_frames": 87,
    "sampling_stride": 10,
    "last_timestamp": 31.2
  }
}
```

### `WS /ws/camera`

Incoming messages from browser:

```json
{ "type": "frame", "frame": "<base64-jpeg>" }
```

Outgoing messages from backend:

```json
{ "type": "ready" }
```

```json
{
  "type": "frame",
  "frame": "<base64-jpeg>",
  "stats": {},
  "enhancement_mode": "Normal",
  "timestamp": 4.2,
  "progress": -1
}
```

```json
{
  "type": "alert",
  "incident": {
    "incident_id": "INC-0001",
    "severity": "Critical",
    "collision_type": "car vs person collision",
    "track_ids": [],
    "location": [320, 220],
    "bbox": [120, 80, 520, 360],
    "plates": ["TN37AB1234"],
    "timestamp": 1710000000.0,
    "frame_number": 64,
    "score": 0.81
  }
}
```

## File responsibilities

- `app.py`
  Owns API routes, upload handling, websocket transport, and payload shaping for the frontend.

- `backend/pipeline.py`
  Owns orchestration of the full AI workflow for each frame.

- `backend/detector.py`
  Owns YOLO inference and detection normalization.

- `backend/tracker.py`
  Owns DeepSORT-based persistent vehicle tracking.

- `backend/accident.py`
  Owns accident scoring, severity selection, and incident object creation.

- `backend/lpr.py`
  Owns OCR-based plate extraction for confirmed incidents.

- `backend/enhancer.py`
  Owns low-light and fog enhancement before inference.

## Why this now matches the frontend

- `app.js` uploads to `/api/analyze`, and that route now exists.
- The upload route now returns the exact fields the UI reads.
- The live websocket route already matched the UI and remains intact.
- CORS is enabled so opening the frontend separately still works against `http://127.0.0.1:8000`.
