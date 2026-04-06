"""
Vehicle Tracker Module — DeepSORT
Replaces the IoU centroid tracker with DeepSORT which uses appearance
features (re-identification embeddings) to keep consistent IDs even
through occlusion, overlap, and brief disappearances.
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from backend.detector import Detection

_deepsort = None


def _get_deepsort():
    """Lazy-load DeepSORT so the server starts without ML packages."""
    global _deepsort
    if _deepsort is None:
        from deep_sort_realtime.deepsort_tracker import DeepSort
        _deepsort = DeepSort(
            max_age=30,           # frames to keep a lost track alive
            n_init=3,             # detections before a track is confirmed
            nms_max_overlap=0.7,
            max_cosine_distance=0.3,   # re-ID embedding similarity threshold
            nn_budget=100,             # max stored embeddings per track
            embedder="mobilenet",      # lightweight CNN for appearance features
            half=False,                # FP32 for CPU compatibility
            bgr=True,                  # our frames are BGR (OpenCV)
        )
    return _deepsort


def iou(a: List[float], b: List[float]) -> float:
    """Intersection-over-Union between two [x1,y1,x2,y2] boxes."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1); iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2); iy2 = min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    union = (ax2-ax1)*(ay2-ay1) + (bx2-bx1)*(by2-by1) - inter
    return inter / union if union > 0 else 0.0


def centroid(bbox: List[float]) -> Tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


@dataclass
class Track:
    """
    Unified track object compatible with the rest of the pipeline.
    Wraps a DeepSORT track and maintains the velocity / history data
    that the accident detector uses for severity scoring.
    """
    track_id: int
    bbox: List[float]              # [x1, y1, x2, y2]
    class_name: str
    color: tuple
    confidence: float
    frames_since_seen: int = 0
    history: List[Tuple[float, float]] = field(default_factory=list)
    velocity: Tuple[float, float] = (0.0, 0.0)
    speed_history: List[float] = field(default_factory=list)

    def update(self, bbox: List[float], confidence: float):
        self.bbox = bbox
        self.confidence = confidence
        self.frames_since_seen = 0
        cx, cy = centroid(bbox)
        if self.history:
            px, py = self.history[-1]
            self.velocity = (cx - px, cy - py)
            speed = float(np.sqrt((cx - px) ** 2 + (cy - py) ** 2))
            self.speed_history.append(speed)
            if len(self.speed_history) > 30:
                self.speed_history.pop(0)
        self.history.append((cx, cy))
        if len(self.history) > 60:
            self.history.pop(0)

    @property
    def speed(self) -> float:
        if not self.speed_history:
            return 0.0
        return float(np.mean(self.speed_history[-5:]))

    @property
    def avg_speed(self) -> float:
        if not self.speed_history:
            return 0.0
        return float(np.mean(self.speed_history))


class VehicleTracker:
    """
    DeepSORT-based tracker.

    DeepSORT combines:
      1. Kalman filter  — predicts next position between frames
      2. Hungarian algorithm — optimal assignment of detections to tracks
      3. Appearance embedding (MobileNet) — re-identifies vehicles by look,
         allowing consistent IDs through occlusion and long disappearances

    This is a major upgrade over pure IoU tracking:
      - Vehicles that overlap no longer swap IDs
      - Partial occlusion (another car passing in front) no longer kills a track
      - Re-entering vehicles are re-identified correctly
    """

    def __init__(self, max_lost: int = 30, iou_threshold: float = 0.2):
        self.max_lost       = max_lost
        self.iou_threshold  = iou_threshold
        self._tracks: Dict[int, Track] = {}   # track_id → Track
        self._class_map: Dict[int, str] = {}  # deepsort_id → class_name
        self._color_map: Dict[int, tuple] = {}

    def update(self, detections: List[Detection], frame: np.ndarray) -> List[Track]:
        """
        Run DeepSORT on this frame's detections.

        Args:
            detections: List of Detection objects from VehicleDetector
            frame:      The current BGR frame (needed for appearance embedding)

        Returns:
            List of active confirmed Track objects (frames_since_seen == 0)
        """
        ds = _get_deepsort()

        # Convert Detection → DeepSORT input format:
        # [([x, y, w, h], confidence, class_name), ...]
        ds_inputs = []
        for det in detections:
            x1, y1, x2, y2 = det.bbox
            w = x2 - x1
            h = y2 - y1
            ds_inputs.append(([x1, y1, w, h], det.confidence, det.class_name))

        # Run tracker
        ds_tracks = ds.update_tracks(ds_inputs, frame=frame)

        active_ids = set()

        for dst in ds_tracks:
            if not dst.is_confirmed():
                continue

            tid = dst.track_id
            ltrb = dst.to_ltrb()   # [x1, y1, x2, y2]
            bbox = [float(v) for v in ltrb]

            # Class/colour from the detection that initialised this track
            cls_name = dst.det_class or "car"
            conf     = float(dst.det_conf) if dst.det_conf is not None else 0.5

            # Resolve color from the detection class map
            from backend.detector import VEHICLE_COLORS
            color = VEHICLE_COLORS.get(cls_name, (128, 128, 128))

            if tid in self._tracks:
                self._tracks[tid].update(bbox, conf)
            else:
                t = Track(
                    track_id=tid,
                    bbox=bbox,
                    class_name=cls_name,
                    color=color,
                    confidence=conf,
                )
                cx, cy = centroid(bbox)
                t.history.append((cx, cy))
                self._tracks[tid] = t

            active_ids.add(tid)

        # Age / prune lost tracks
        for tid in list(self._tracks.keys()):
            if tid not in active_ids:
                self._tracks[tid].frames_since_seen += 1
                if self._tracks[tid].frames_since_seen > self.max_lost:
                    del self._tracks[tid]

        return [t for t in self._tracks.values() if t.frames_since_seen == 0]
