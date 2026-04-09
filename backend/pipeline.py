"""
Main Processing Pipeline
Single unified pipeline used for both live camera and uploaded videos.
Accident detection uses four independent methods:
  1. Custom model collision class (trained detector)
  2. IoU + velocity tracker (physics-based)
  3. Proximity overlap between vehicle pairs (geometric)
  4. Motion spike detector (frame-difference burst)
"""

import time
import numpy as np
import cv2
from typing import Optional, Dict, Any, List, Tuple

from backend.detector import VehicleDetector, Detection
from backend.tracker import VehicleTracker, Track
from backend.accident import AccidentDetector, Incident, SEVERITY_COLORS
from backend.lpr import read_plates_for_incident
from backend.enhancer import enhance_frame

FONT = cv2.FONT_HERSHEY_SIMPLEX

_CLASS_SEVERITY_FLOOR = {
    "car-person_collision":          "Critical",
    "motorcycle-person_collision":   "Critical",
    "bus-collision":                 "Critical",
    "truck-collision":               "Critical",
    "bicycle-person_collision":      "Critical",
    "car-bicycle_collision":         "Critical",
    "motorcycle-car_collision":      "Major",
    "car-car_collision":             "Major",
    "bicycle-bicycle_collision":     "Major",
    "car-object_collision":          "Minor",
    "bicycle-object_collision":      "Minor",
}

_SEVERITY_RANK = {"Minor": 0, "Major": 1, "Critical": 2}
_RANK_SEVERITY  = {0: "Minor", 1: "Major", 2: "Critical"}

# Pairs checked by proximity detector
_PAIR_SEVERITY = {
    frozenset(["car",        "motorcycle"]):  ("Critical", "car-motorcycle collision"),
    frozenset(["car",        "bicycle"]):     ("Critical", "car-bicycle collision"),
    frozenset(["car",        "person"]):      ("Critical", "car-person collision"),
    frozenset(["motorcycle", "person"]):      ("Critical", "motorcycle-person collision"),
    frozenset(["motorcycle", "bicycle"]):     ("Critical", "motorcycle-bicycle collision"),
    frozenset(["motorcycle", "motorcycle"]): ("Major",    "motorcycle-motorcycle collision"),
    frozenset(["truck",      "motorcycle"]): ("Critical", "truck-motorcycle collision"),
    frozenset(["truck",      "person"]):     ("Critical", "truck-person collision"),
    frozenset(["bus",        "motorcycle"]): ("Critical", "bus-motorcycle collision"),
    frozenset(["bus",        "person"]):     ("Critical", "bus-person collision"),
    frozenset(["car",        "truck"]):      ("Major",    "car-truck collision"),
    frozenset(["car",        "bus"]):        ("Major",    "car-bus collision"),
    frozenset(["car",        "car"]):        ("Major",    "car-car collision"),
    frozenset(["auto-rickshaw", "motorcycle"]): ("Critical", "auto-rickshaw collision"),
    frozenset(["auto-rickshaw", "car"]):        ("Major",    "auto-rickshaw collision"),
    frozenset(["auto-rickshaw", "person"]):     ("Critical", "auto-rickshaw collision"),
}


def _is_collision_class(name: str) -> bool:
    return "collision" in name


def _is_trackable_class(name: str) -> bool:
    return not _is_collision_class(name)


def _filter_riders(dets: list, iou_fn) -> list:
    """
    Remove 'person' detections that significantly overlap a motorcycle bbox —
    those are riders, not independent pedestrians, and cause false
    'motorcycle-person collision' labels when the real event is car-vs-motorcycle.
    """
    motorcycles = [d for d in dets if d.class_name == "motorcycle"]
    if not motorcycles:
        return dets
    return [
        d for d in dets
        if d.class_name != "person"
        or not any(iou_fn(d.bbox, m.bbox) > 0.25 for m in motorcycles)
    ]


def _severity_from_detection(det: Detection) -> str:
    # Use only the collision class floor — confidence fluctuates frame-to-frame
    # and would cause different severity each run for the same video.
    return _CLASS_SEVERITY_FLOOR.get(det.class_name, "Major")


def _valid_collision_det(det: Detection, frame_area: float) -> bool:
    if det.confidence < 0.25:
        return False
    x1, y1, x2, y2 = det.bbox
    frac = max(0.0, (x2-x1)*(y2-y1)) / max(frame_area, 1.0)
    return 0.002 < frac < 0.75


class AccidentDetectionPipeline:
    def __init__(self):
        self.detector = VehicleDetector(model_size="n", conf=0.25)
        self.tracker  = VehicleTracker(max_lost=20, iou_threshold=0.2)
        self.accident_detector = AccidentDetector(
            iou_collision_threshold=0.40,
            speed_drop_ratio=0.55,
            min_speed_for_crash=5.0,
            cooldown_frames=90,
        )
        self.frame_number = 0
        self._incident_counter = 0
        self.reset_session()

    # ------------------------------------------------------------------ #
    def reset_session(self):
        self.frame_number = 0
        self._incident_counter = 0
        self.stats = {"total_vehicles": 0, "total_incidents": 0, "frame_count": 0}
        self.enhancement_mode = "Normal"

        # Method 1 — collision class streak
        self._best_collision   = None
        self._collision_streak = 0
        self._gap_frames       = 0
        self._post_alert_cooldown = 0
        self._STREAK_TO_FIRE   = 5      # 5 consecutive frames (~0.5s) before alerting
        self._MAX_GAP          = 3      # gap frames forgiven before streak reset
        self._ALERT_COOLDOWN   = 20     # frames suppressed after alert
        self._severity_votes: List[str] = []  # votes across streak window

        # Vehicle type memory — remembers what was in the scene recently
        # Used to identify hit-and-run vehicles that left the frame
        # Stores (frame_num, class_name, centre_x, centre_y) — position-aware
        self._recent_vehicle_memory: List[Tuple[int, str, float, float]] = []
        self._VEHICLE_MEMORY_FRAMES = 60  # ~2 seconds at 30fps

        # Method 3 — proximity
        self._proximity_streak:   Dict[frozenset, int] = {}
        self._proximity_cooldown: Dict[frozenset, int] = {}

        # Method 4 — motion spike
        self._prev_gray    = None
        self._motion_buf:  List[float] = []
        self._motion_cooldown = 0

        # Live IoU tracker state
        self._live_tracks:  Dict[int, Any] = {}
        self._live_next_id: int = 1

    # ------------------------------------------------------------------ #
    def process_frame(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Full pipeline: enhance → detect → track → accident (4 methods) → LPR → annotate.
        Used for both live camera and uploaded videos.
        """
        self.frame_number += 1
        self.stats["frame_count"] = self.frame_number

        enhanced, self.enhancement_mode = enhance_frame(frame)
        all_detections = self.detector.detect(enhanced)

        fh, fw = enhanced.shape[:2]
        frame_area = fw * fh

        from backend.tracker import iou as _iou
        vehicle_dets   = [d for d in all_detections if _is_trackable_class(d.class_name)]
        vehicle_dets   = _filter_riders(vehicle_dets, _iou)
        actual_vehicles = [d for d in vehicle_dets   if d.class_name != "person"]
        self._record_vehicle_types(vehicle_dets)

        # Filter collision detections: must overlap a real vehicle bbox
        raw_collision = [
            d for d in all_detections
            if _is_collision_class(d.class_name) and _valid_collision_det(d, frame_area)
        ]
        collision_dets = [
            d for d in raw_collision
            if actual_vehicles and any(_iou(d.bbox, v.bbox) > 0.05 for v in actual_vehicles)
        ]

        active_tracks = self.tracker.update(vehicle_dets, enhanced)
        self.stats["total_vehicles"] = len(active_tracks)

        incident: Optional[Incident] = None

        # ── Method 1: custom model collision class streak ──
        if self._post_alert_cooldown > 0:
            self._post_alert_cooldown -= 1
        else:
            if collision_dets:
                self._gap_frames = 0
                best = max(collision_dets, key=lambda d: d.confidence)
                if self._best_collision is None or best.confidence > self._best_collision.confidence:
                    self._best_collision = best
                self._severity_votes.append(_severity_from_detection(best))
                self._collision_streak += 1
                if self._collision_streak >= self._STREAK_TO_FIRE:
                    incident = self._incident_from_det(self._best_collision)
                    # Use voted severity (mode across streak) for consistency
                    from collections import Counter
                    voted_sev = Counter(self._severity_votes).most_common(1)[0][0]
                    incident.severity = voted_sev
                    incident.color = SEVERITY_COLORS[voted_sev]
                    self._reset_collision_streak()
            else:
                self._gap_frames += 1
                if self._gap_frames > self._MAX_GAP:
                    self._reset_collision_streak()

        # ── Method 2: IoU + velocity (tracker-based) ──
        if incident is None and self._post_alert_cooldown == 0:
            incident = self.accident_detector.detect(active_tracks, self.frame_number)

        # ── Method 3: proximity overlap ──
        if incident is None and self._post_alert_cooldown == 0:
            incident = self._proximity_check(vehicle_dets, self.frame_number)

        # ── Method 4: motion spike ──
        if incident is None and self._post_alert_cooldown == 0:
            incident = self._motion_spike_check(enhanced, actual_vehicles, self.frame_number)

        if incident:
            self._rederive_collision_type(incident, vehicle_dets, active_tracks)
            self.stats["total_incidents"] += 1
            self._post_alert_cooldown = self._ALERT_COOLDOWN
            involved = [t for t in active_tracks if t.track_id in incident.track_ids]
            bboxes = [t.bbox for t in involved] or [d.bbox for d in collision_dets] or [incident.bbox]
            incident.plates = read_plates_for_incident(enhanced, bboxes)
            incident.fire_detected = self._detect_fire(enhanced, incident.bbox)

        annotated = self._annotate(enhanced, active_tracks, collision_dets, incident)
        return {
            "annotated_frame":  annotated,
            "stats":            dict(self.stats),
            "alert":            incident.to_dict() if incident else None,
            "enhancement_mode": self.enhancement_mode,
        }

    # kept as alias so existing callers don't break
    def process_frame_fast(self, frame: np.ndarray) -> Dict[str, Any]:
        return self.process_frame(frame)

    # ------------------------------------------------------------------ #
    def process_frame_live(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Optimised path for live camera — targets ~15 fps on CPU.
        Skips: visual enhancement, custom model, DeepSORT appearance embedding.
        Uses: COCO model at imgsz=416, simple IoU tracker, proximity + motion detection.
        """
        self.frame_number += 1
        self.stats["frame_count"] = self.frame_number
        self.enhancement_mode = "Live"

        from backend.detector import Detection, VEHICLE_COLORS, DEFAULT_CLASS_COLORS, _COCO_VEHICLE_CLASSES

        # COCO model — lower conf + larger imgsz to catch small/distant vehicles
        coco_res = self.detector.coco_model(
            frame, conf=0.18, imgsz=640, verbose=False,
            classes=[0, 1, 2, 3, 5, 7],
        )[0]

        vehicle_dets: List[Detection] = []
        if coco_res.boxes is not None:
            for box in coco_res.boxes:
                cid  = int(box.cls[0])
                name = _COCO_VEHICLE_CLASSES.get(cid, f"class_{cid}")
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                vehicle_dets.append(Detection(
                    bbox=[x1, y1, x2, y2],
                    class_id=cid,
                    class_name=name,
                    confidence=float(box.conf[0]),
                    color=VEHICLE_COLORS.get(name, DEFAULT_CLASS_COLORS[cid % len(DEFAULT_CLASS_COLORS)]),
                ))

        # Custom model every frame at lower resolution for consistent detection
        collision_dets: List[Detection] = []
        fh, fw = frame.shape[:2]
        frame_area = fw * fh
        if self.detector.custom_model is not None:
            custom_res = self.detector.custom_model(
                frame, conf=0.25, imgsz=480, verbose=False,
            )[0]
            if custom_res.boxes is not None:
                for box in custom_res.boxes:
                    cid  = int(box.cls[0])
                    name = self.detector.class_names.get(cid, f"class_{cid}")
                    if "collision" not in name:
                        continue
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    det = Detection(
                        bbox=[x1, y1, x2, y2], class_id=cid, class_name=name,
                        confidence=float(box.conf[0]),
                        color=VEHICLE_COLORS.get(name, (200, 0, 200)),
                    )
                    if _valid_collision_det(det, frame_area):
                        collision_dets.append(det)

        from backend.tracker import iou as _iou_fn
        vehicle_dets   = _filter_riders(vehicle_dets, _iou_fn)
        actual_vehicles = [d for d in vehicle_dets if d.class_name != "person"]
        self._record_vehicle_types(vehicle_dets)
        self.stats["total_vehicles"] = len(vehicle_dets)

        # Filter collision dets: must overlap a real vehicle
        collision_dets = [
            d for d in collision_dets
            if actual_vehicles and any(_iou_fn(d.bbox, v.bbox) > 0.05 for v in actual_vehicles)
        ]

        # Simple IoU-based track update (no DeepSORT / no MobileNet)
        tracks = self._iou_track(vehicle_dets)

        incident: Optional[Incident] = None

        if self._post_alert_cooldown > 0:
            self._post_alert_cooldown -= 1
        else:
            # Method 1: collision class streak
            if collision_dets:
                self._gap_frames = 0
                best = max(collision_dets, key=lambda d: d.confidence)
                if self._best_collision is None or best.confidence > self._best_collision.confidence:
                    self._best_collision = best
                self._severity_votes.append(_severity_from_detection(best))
                self._collision_streak += 1
                if self._collision_streak >= self._STREAK_TO_FIRE:
                    incident = self._incident_from_det(self._best_collision)
                    from collections import Counter
                    voted_sev = Counter(self._severity_votes).most_common(1)[0][0]
                    incident.severity = voted_sev
                    incident.color = SEVERITY_COLORS[voted_sev]
                    self._reset_collision_streak()
            else:
                self._gap_frames += 1
                if self._gap_frames > self._MAX_GAP:
                    self._reset_collision_streak()

            # Method 2: IoU + velocity
            if incident is None:
                incident = self.accident_detector.detect(tracks, self.frame_number)
            # Method 3: proximity
            if incident is None:
                incident = self._proximity_check(vehicle_dets, self.frame_number)
            # Method 4: motion spike
            if incident is None:
                incident = self._motion_spike_check(frame, actual_vehicles, self.frame_number)

        if incident:
            self._rederive_collision_type(incident, vehicle_dets, tracks)
            self.stats["total_incidents"] += 1
            self._post_alert_cooldown = self._ALERT_COOLDOWN
            incident.fire_detected = self._detect_fire(frame, incident.bbox)

        annotated = self._annotate(frame, tracks, [], incident)
        return {
            "annotated_frame":  annotated,
            "stats":            dict(self.stats),
            "alert":            incident.to_dict() if incident else None,
            "enhancement_mode": self.enhancement_mode,
        }

    # ------------------------------------------------------------------ #
    def _iou_track(self, dets: List[Detection]) -> List[Track]:
        """
        Lightweight IoU-only tracker — no neural network, no embeddings.
        Runs in <1 ms. Sufficient for live cam accident detection.
        """
        from backend.tracker import Track, centroid, iou as _iou

        if not hasattr(self, "_live_tracks"):
            self._live_tracks: Dict[int, Track] = {}
            self._live_next_id = 1

        matched_det_ids = set()
        matched_trk_ids = set()

        # Match detections to existing tracks by IoU
        for tid, track in self._live_tracks.items():
            best_iou, best_det = 0.0, None
            for det in dets:
                if id(det) in matched_det_ids:
                    continue
                ov = _iou(track.bbox, det.bbox)
                if ov > best_iou:
                    best_iou, best_det = ov, det
            if best_det is not None and best_iou > 0.2:
                track.update(best_det.bbox, best_det.confidence)
                track.class_name  = best_det.class_name
                track.color       = best_det.color
                matched_det_ids.add(id(best_det))
                matched_trk_ids.add(tid)

        # Create new tracks for unmatched detections
        for det in dets:
            if id(det) in matched_det_ids:
                continue
            t = Track(
                track_id=self._live_next_id,
                bbox=det.bbox,
                class_name=det.class_name,
                color=det.color,
                confidence=det.confidence,
            )
            cx, cy = centroid(det.bbox)
            t.history.append((cx, cy))
            self._live_tracks[self._live_next_id] = t
            self._live_next_id += 1

        # Age out lost tracks
        for tid in list(self._live_tracks):
            if tid not in matched_trk_ids:
                self._live_tracks[tid].frames_since_seen += 1
                if self._live_tracks[tid].frames_since_seen > 10:
                    del self._live_tracks[tid]

        return [t for t in self._live_tracks.values() if t.frames_since_seen == 0]

    # ------------------------------------------------------------------ #
    def _detect_fire(self, frame: np.ndarray, bbox: list) -> bool:
        """
        HSV color-based fire detection inside (and around) the incident bounding box.
        Fire pixels are red-orange hues with high saturation and brightness.
        Returns True if >5% of the region matches fire colors.
        """
        fh, fw = frame.shape[:2]
        x1, y1, x2, y2 = [int(v) for v in bbox]
        # Expand region by 50% to catch flames outside the collision box
        pad_x = int((x2 - x1) * 0.5)
        pad_y = int((y2 - y1) * 0.5)
        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(fw, x2 + pad_x)
        y2 = min(fh, y2 + pad_y)
        if x2 <= x1 or y2 <= y1:
            return False
        roi = frame[y1:y2, x1:x2]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        # Red-orange hue (H: 0-20), high saturation and brightness
        lower1 = np.array([0,  120, 150])
        upper1 = np.array([20, 255, 255])
        # Wrap-around red (H: 160-180)
        lower2 = np.array([160, 120, 150])
        upper2 = np.array([180, 255, 255])
        mask = cv2.bitwise_or(
            cv2.inRange(hsv, lower1, upper1),
            cv2.inRange(hsv, lower2, upper2),
        )
        fire_ratio = float(np.sum(mask > 0)) / max(roi.shape[0] * roi.shape[1], 1)
        return fire_ratio > 0.05

    def _reset_collision_streak(self):
        self._collision_streak = 0
        self._best_collision   = None
        self._gap_frames       = 0
        self._severity_votes   = []

    def _record_vehicle_types(self, vehicle_dets: list) -> None:
        for d in vehicle_dets:
            if d.class_name != "person":
                cx = (d.bbox[0] + d.bbox[2]) / 2
                cy = (d.bbox[1] + d.bbox[3]) / 2
                self._recent_vehicle_memory.append(
                    (self.frame_number, d.class_name, cx, cy)
                )
        cutoff = self.frame_number - self._VEHICLE_MEMORY_FRAMES
        self._recent_vehicle_memory = [
            e for e in self._recent_vehicle_memory if e[0] >= cutoff
        ]

    # ------------------------------------------------------------------ #
    def _rederive_collision_type(
        self,
        incident: "Incident",
        vehicle_dets: list,
        active_tracks: list = None,
    ) -> None:
        """
        Corrects the collision type label using only vehicles visible in the
        current frame that physically overlap the incident bounding box.
        No memory fallback — stale vehicles from past frames must not
        influence the collision type label.
        """
        from backend.tracker import iou as _iou

        def _apply_pair(names):
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    pair_key = frozenset([names[i], names[j]])
                    if pair_key in _PAIR_SEVERITY:
                        type_sev, type_ct = _PAIR_SEVERITY[pair_key]
                        incident.collision_type = type_ct
                        if _SEVERITY_RANK[type_sev] >= _SEVERITY_RANK[incident.severity]:
                            incident.severity = type_sev
                            incident.color = SEVERITY_COLORS[type_sev]
                        return True
            return False

        # ── Priority 1: use track IDs from Method 2 (most accurate) ──
        # Method 2 records exactly which tracked vehicles were involved.
        # Using their class names avoids spectator-vehicle contamination.
        if incident.track_ids and active_tracks:
            track_map = {t.track_id: t.class_name for t in active_tracks}
            track_names = [
                track_map[tid] for tid in incident.track_ids if tid in track_map
            ]
            if len(track_names) >= 2 and _apply_pair(track_names):
                return

        # ── Priority 2: spatial search on current frame only ──
        # Only vehicles whose bbox actually overlaps the incident bbox are
        # considered involved — no distance radius, no memory fallback.
        involved = [
            d for d in vehicle_dets
            if d.class_name != "person" and _iou(d.bbox, incident.bbox) > 0.05
        ]

        if len(involved) >= 2:
            _apply_pair([d.class_name for d in involved])

    def _incident_from_det(self, det: Detection) -> Incident:
        severity = _severity_from_detection(det)
        x1, y1, x2, y2 = det.bbox
        self._incident_counter += 1
        return Incident(
            incident_id    = f"INC-{self._incident_counter:04d}",
            severity       = severity,
            color          = SEVERITY_COLORS[severity],
            collision_type = det.class_name.replace("_", " ").replace("-", " vs "),
            track_ids      = [],
            location       = ((x1+x2)/2, (y1+y2)/2),
            bbox           = list(det.bbox),
            timestamp      = time.time(),
            frame_number   = self.frame_number,
            score          = float(det.confidence),
        )

    def _make_incident(self, severity, collision_type, bbox, score, track_ids=None) -> Incident:
        x1, y1, x2, y2 = bbox
        self._incident_counter += 1
        return Incident(
            incident_id    = f"INC-{self._incident_counter:04d}",
            severity       = severity,
            color          = SEVERITY_COLORS[severity],
            collision_type = collision_type,
            track_ids      = track_ids or [],
            location       = ((x1+x2)/2, (y1+y2)/2),
            bbox           = list(bbox),
            timestamp      = time.time(),
            frame_number   = self.frame_number,
            score          = float(score),
        )

    # ------------------------------------------------------------------ #
    def _proximity_check(
        self,
        vehicle_dets: List[Detection],
        frame_number: int,
    ) -> Optional[Incident]:
        from backend.tracker import iou as _iou

        _IOU_LOW  = 0.32   # vehicles must substantially overlap — not just drive close
        _IOU_HIGH = 0.72   # above this = same object detected twice
        _STREAK   = 6      # 6 consecutive frames of overlap required
        _COOLDOWN = 90

        # Tick down cooldowns
        for k in list(self._proximity_cooldown):
            self._proximity_cooldown[k] -= 1
            if self._proximity_cooldown[k] <= 0:
                del self._proximity_cooldown[k]

        best_iou, best_pair, active_pairs = 0.0, None, set()

        # Large-vehicle pairs on busy roads generate many false positives
        # in the proximity check.  They are covered by Method 2 (IoU + velocity)
        # with stricter guards; skip them here entirely.
        _SKIP_PROXIMITY = {
            frozenset(["car",   "car"]),
            frozenset(["car",   "bus"]),
            frozenset(["car",   "truck"]),
            frozenset(["truck", "truck"]),
            frozenset(["bus",   "bus"]),
        }

        for i in range(len(vehicle_dets)):
            for j in range(i + 1, len(vehicle_dets)):
                a, b = vehicle_dets[i], vehicle_dets[j]
                pk = frozenset([a.class_name, b.class_name])
                if pk not in _PAIR_SEVERITY or pk in self._proximity_cooldown:
                    continue
                if pk in _SKIP_PROXIMITY:
                    continue
                # Skip tiny/distant vehicles (same false-positive guard as Method 2)
                area_a = (a.bbox[2]-a.bbox[0]) * (a.bbox[3]-a.bbox[1])
                area_b = (b.bbox[2]-b.bbox[0]) * (b.bbox[3]-b.bbox[1])
                if min(area_a, area_b) < 800:
                    continue
                overlap = _iou(a.bbox, b.bbox)
                if _IOU_LOW <= overlap <= _IOU_HIGH:
                    active_pairs.add(pk)
                    if overlap > best_iou:
                        best_iou, best_pair = overlap, (a, b, pk)

        # Reset streaks for pairs no longer overlapping
        for k in list(self._proximity_streak):
            if k not in active_pairs:
                del self._proximity_streak[k]

        if best_pair is None:
            return None

        a, b, pk = best_pair
        self._proximity_streak[pk] = self._proximity_streak.get(pk, 0) + 1
        if self._proximity_streak[pk] < _STREAK:
            return None

        del self._proximity_streak[pk]
        self._proximity_cooldown[pk] = _COOLDOWN

        severity, collision_type = _PAIR_SEVERITY[pk]
        merged = [
            min(a.bbox[0], b.bbox[0]), min(a.bbox[1], b.bbox[1]),
            max(a.bbox[2], b.bbox[2]), max(a.bbox[3], b.bbox[3]),
        ]
        return self._make_incident(severity, collision_type, merged, best_iou)

    # ------------------------------------------------------------------ #
    def _motion_spike_check(
        self,
        frame: np.ndarray,
        actual_vehicles: List[Detection],
        frame_number: int,
    ) -> Optional[Incident]:
        """
        Detects sudden large motion bursts in vehicle-occupied regions.
        A crash causes debris, skidding, and abrupt position changes that
        produce a spike well above the scene's rolling motion baseline.
        """
        if self._motion_cooldown > 0:
            self._motion_cooldown -= 1
            return None

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if self._prev_gray is None or self._prev_gray.shape != gray.shape:
            self._prev_gray = gray
            return None

        diff = cv2.absdiff(gray, self._prev_gray)
        self._prev_gray = gray

        # Only measure motion inside vehicle bounding boxes
        if not actual_vehicles:
            return None

        fh, fw = frame.shape[:2]
        mask = np.zeros((fh, fw), dtype=np.uint8)
        for v in actual_vehicles:
            x1, y1, x2, y2 = [int(c) for c in v.bbox]
            mask[max(0,y1):min(fh,y2), max(0,x1):min(fw,x2)] = 255

        roi = diff[mask > 0]
        if roi.size == 0:
            return None

        # Mean of high-motion pixels (>30/255)
        hot = roi[roi > 30]
        motion_score = float(np.mean(hot)) if hot.size > 0 else 0.0

        self._motion_buf.append(motion_score)
        if len(self._motion_buf) > 30:
            self._motion_buf.pop(0)

        if len(self._motion_buf) < 8:
            return None  # not enough history

        baseline = float(np.mean(self._motion_buf[:-3]))
        recent   = float(np.mean(self._motion_buf[-3:]))

        # Spike: recent motion is 3.0× above baseline AND above an absolute floor
        # The absolute floor (20) prevents triggering on a completely still scene.
        if recent < 20.0 or recent < baseline * 3.0:
            return None

        # Triggered — find the most active vehicle region
        best_v = max(actual_vehicles, key=lambda v: v.confidence)
        severity = "Major"
        collision_type = f"sudden impact ({best_v.class_name})"
        self._motion_cooldown = 150

        return self._make_incident(severity, collision_type, best_v.bbox, min(recent / 255.0, 1.0))

    # ------------------------------------------------------------------ #
    def _annotate(
        self,
        frame: np.ndarray,
        tracks: List[Track],
        collision_dets: List[Detection],
        incident: Optional[Incident],
    ) -> np.ndarray:
        out = frame.copy()

        # Tracked vehicles
        for track in tracks:
            x1, y1, x2, y2 = [int(v) for v in track.bbox]
            color = track.color
            label = f"#{track.track_id} {track.class_name} ({track.confidence:.0%})"
            cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
            (tw, th), _ = cv2.getTextSize(label, FONT, 0.45, 1)
            cv2.rectangle(out, (x1, y1-th-8), (x1+tw+4, y1), color, -1)
            cv2.putText(out, label, (x1+2, y1-4), FONT, 0.45, (0, 0, 0), 1)
            if len(track.history) > 2:
                pts = np.array(track.history[-20:], dtype=np.int32)
                for k in range(1, len(pts)):
                    alpha = k / len(pts)
                    c = tuple(int(v * alpha) for v in color)
                    cv2.line(out, tuple(pts[k-1]), tuple(pts[k]), c, 1)

        # Raw collision class boxes
        for det in collision_dets:
            x1, y1, x2, y2 = [int(v) for v in det.bbox]
            cv2.rectangle(out, (x1, y1), (x2, y2), (0, 0, 255), 2)
            cv2.putText(out, f"{det.class_name} ({det.confidence:.0%})",
                        (x1, y1-6), FONT, 0.4, (0, 0, 255), 1)

        # Accident overlay
        if incident:
            x1, y1, x2, y2 = [int(v) for v in incident.bbox]
            sev = incident.severity
            oc = (0, 0, 220) if sev == "Critical" else (0, 100, 220) if sev == "Major" else (0, 180, 220)
            cv2.rectangle(out, (x1, y1), (x2, y2), oc, 3)
            warn = f"ACCIDENT! {sev} [{incident.incident_id}]"
            (tw, th), _ = cv2.getTextSize(warn, FONT, 0.75, 2)
            lx = max(0, int((x1+x2)/2 - tw/2))
            ly = max(th+10, y1-10)
            cv2.rectangle(out, (lx-4, ly-th-6), (lx+tw+4, ly+4), oc, -1)
            cv2.putText(out, warn, (lx, ly), FONT, 0.75, (255, 255, 255), 2)
            if incident.plates:
                cv2.putText(out, "Plates: " + "  |  ".join(incident.plates),
                            (lx, ly+22), FONT, 0.5, (200, 255, 200), 1)

        _draw_hud(out, self.stats, self.enhancement_mode)
        return out


def _draw_hud(frame, stats, mode):
    lines = [
        f"RESCUE VISION  |  Frame: {stats['frame_count']}",
        f"Vehicles: {stats['total_vehicles']}   Incidents: {stats['total_incidents']}",
        f"Enhancement: {mode}",
    ]
    for i, line in enumerate(lines):
        y = 22 + i * 20
        cv2.putText(frame, line, (10, y), FONT, 0.5, (0, 0, 0), 3)
        cv2.putText(frame, line, (10, y), FONT, 0.5, (0, 255, 180), 1)
