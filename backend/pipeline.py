"""
Main Processing Pipeline
Orchestrates detection, tracking, accident analysis, LPR, and annotation.
"""

import time
import numpy as np
import cv2
from typing import Optional, Dict, Any, List

from backend.detector import VehicleDetector, Detection
from backend.tracker import VehicleTracker, Track
from backend.accident import AccidentDetector, Incident, SEVERITY_COLORS
from backend.lpr import read_plates_for_incident
from backend.enhancer import enhance_frame

FONT = cv2.FONT_HERSHEY_SIMPLEX

# Classes that are just vehicles (tracked normally)
# 0:bicycle  1:motorcycle  2:auto-rickshaw  3:car  4:bus  5:truck  6:person
NORMAL_CLASS_IDS = {0, 1, 2, 3, 4, 5, 6}

# Classes the model directly labels as a collision event
# 7-17 are all collision types
COLLISION_CLASS_IDS = {7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17}

# Inherent severity floor per collision class.
# Heavy vehicles (bus/truck) and person-involved = Critical.
_CLASS_SEVERITY_FLOOR = {
    # Critical — person involved or heavy vehicle
    "car-person_collision":         "Critical",
    "motorcycle-person_collision":  "Critical",
    "bus-collision":                "Critical",
    "truck-collision":              "Critical",
    "bicycle-person_collision":     "Critical",
    # Major — vehicle vs vehicle
    "car-car_collision":            "Major",
    "motorcycle-car_collision":     "Major",
    "car-bicycle_collision":        "Major",
    "bicycle-bicycle_collision":    "Major",
    # Minor — object/low speed
    "car-object_collision":         "Minor",
    "bicycle-object_collision":     "Minor",
}

_SEVERITY_RANK = {"Minor": 0, "Major": 1, "Critical": 2}
_RANK_SEVERITY  = {0: "Minor", 1: "Major", 2: "Critical"}


def _severity_from_detection(det) -> str:
    """
    Combines the collision class (inherent danger) with model confidence
    (certainty of detection) and takes the higher of the two tiers.
    This prevents a car-person_collision from ever being labelled 'Minor'.
    """
    # Class-based floor
    floor = _CLASS_SEVERITY_FLOOR.get(det.class_name, "Minor")
    floor_rank = _SEVERITY_RANK[floor]

    # Confidence-based tier (model certainty)
    if det.confidence >= 0.50:
        conf_rank = _SEVERITY_RANK["Critical"]
    elif det.confidence >= 0.28:
        conf_rank = _SEVERITY_RANK["Major"]
    else:
        conf_rank = _SEVERITY_RANK["Minor"]

    return _RANK_SEVERITY[max(floor_rank, conf_rank)]


class AccidentDetectionPipeline:
    def __init__(self):
        self.detector  = VehicleDetector(model_size="n", conf=0.20)
        self.tracker   = VehicleTracker(max_lost=15, iou_threshold=0.2)
        self.accident_detector = AccidentDetector(
            iou_collision_threshold=0.15,   # raised — vehicles must actually overlap
            speed_drop_ratio=0.55,
            min_speed_for_crash=3.0,        # raised — require real movement before impact
            cooldown_frames=60,
        )
        self.frame_number      = 0
        self._incident_counter = 0

        # Peak-detection buffer — waits for N confirmed collision frames,
        # then fires exactly ONE alert using the highest-confidence detection.
        self._best_collision       = None        # best Detection seen in current cluster
        self._collision_streak     = 0           # consecutive frames WITH collision
        self._gap_frames           = 0           # consecutive frames WITHOUT collision (forgiveness)
        self._STREAK_TO_FIRE       = 8           # need 8 consistent frames before firing (was 5)
        self._MAX_GAP              = 1           # only 1 gap frame tolerated (was 2)
        self._post_alert_cooldown  = 0           # frames remaining in post-alert silence
        self._ALERT_COOLDOWN       = 90          # suppress 9s after alert to avoid spam (was 60)

        self.stats = {
            "total_vehicles":  0,
            "total_incidents": 0,
            "frame_count":     0,
        }
        self.enhancement_mode = "Normal"

    # ------------------------------------------------------------------ #
    def process_frame(self, frame: np.ndarray) -> Dict[str, Any]:
        self.frame_number += 1
        self.stats["frame_count"] = self.frame_number

        # Enhance visibility
        enhanced, self.enhancement_mode = enhance_frame(frame)

        # Detect everything
        all_detections = self.detector.detect(enhanced)

        fh, fw = enhanced.shape[:2]
        frame_area = fw * fh

        # Split: normal vehicles vs model-detected collisions
        vehicle_dets = [d for d in all_detections if d.class_id in NORMAL_CLASS_IDS]

        # Filter collision detections with sanity checks to kill false positives:
        #   1. Confidence ≥ 0.45  (much higher floor than normal vehicles)
        #   2. BBox area < 70% of frame  (a face/object filling the whole frame = not a collision)
        #   3. BBox area > 0.3% of frame (tiny noise boxes discarded)
        def _valid_collision(d: Detection) -> bool:
            if d.confidence < 0.45:
                return False
            x1, y1, x2, y2 = d.bbox
            area = (x2 - x1) * (y2 - y1)
            frac = area / frame_area
            return 0.003 < frac < 0.70

        collision_dets = [d for d in all_detections
                          if d.class_id in COLLISION_CLASS_IDS and _valid_collision(d)]

        # Track only normal vehicles — pass frame for DeepSORT appearance embedding
        active_tracks = self.tracker.update(vehicle_dets, enhanced)
        self.stats["total_vehicles"] = len(active_tracks)

        # ── Method 1: sustained collision detection ──
        incident: Optional[Incident] = None

        if self._post_alert_cooldown > 0:
            self._post_alert_cooldown -= 1
            if not collision_dets:
                self._collision_streak = 0
                self._gap_frames = 0
                self._best_collision = None
        else:
            if collision_dets:
                self._gap_frames = 0
                best = max(collision_dets, key=lambda d: d.confidence)
                # Track the single best detection seen in this cluster
                if self._best_collision is None or best.confidence > self._best_collision.confidence:
                    self._best_collision = best
                self._collision_streak += 1
                # Fire once we have enough confirmed frames
                if self._collision_streak >= self._STREAK_TO_FIRE:
                    incident = self._incident_from_collision_dets([self._best_collision])
                    self._best_collision = None
                    self._collision_streak = 0
                    self._gap_frames = 0
                    self._post_alert_cooldown = self._ALERT_COOLDOWN
            else:
                # Allow short gaps (motion blur / occlusion) without resetting the streak
                self._gap_frames += 1
                if self._gap_frames > self._MAX_GAP:
                    self._collision_streak = 0
                    self._best_collision = None
                    self._gap_frames = 0

        # ── Method 2: IoU + velocity fallback (only if no model collision) ──
        if incident is None and self._collision_streak == 0:
            incident = self.accident_detector.detect(active_tracks, self.frame_number)

        # Run LPR only when accident detected
        if incident:
            self.stats["total_incidents"] += 1
            involved_tracks = [t for t in active_tracks if t.track_id in incident.track_ids]
            # Also include bboxes from collision detections if no tracks matched
            bboxes = [t.bbox for t in involved_tracks] or [d.bbox for d in collision_dets]
            plates = read_plates_for_incident(enhanced, bboxes)
            incident.plates = plates

        # Annotate frame
        annotated = self._annotate(enhanced, active_tracks, collision_dets, incident)

        return {
            "annotated_frame":   annotated,
            "stats":             dict(self.stats),
            "alert":             incident.to_dict() if incident else None,
            "enhancement_mode":  self.enhancement_mode,
        }

    # ------------------------------------------------------------------ #
    def _incident_from_collision_dets(self, dets: List[Detection]) -> Optional[Incident]:
        """Create an Incident directly from model-detected collision classes."""
        best = max(dets, key=lambda d: d.confidence)
        severity = _severity_from_detection(best)
        x1, y1, x2, y2 = best.bbox
        self._incident_counter += 1
        collision_type = best.class_name.replace("_", " ").replace("-", " vs ")
        return Incident(
            incident_id    = f"INC-{self._incident_counter:04d}",
            severity       = severity,
            color          = SEVERITY_COLORS[severity],
            collision_type = collision_type,
            track_ids      = [],
            location       = ((x1 + x2) / 2, (y1 + y2) / 2),
            bbox           = list(best.bbox),
            timestamp      = time.time(),
            frame_number   = self.frame_number,
            score          = float(best.confidence),
        )

    # ------------------------------------------------------------------ #
    def _annotate(
        self,
        frame: np.ndarray,
        tracks: List[Track],
        collision_dets: List[Detection],
        incident: Optional[Incident],
    ) -> np.ndarray:
        out = frame.copy()

        # Draw tracked vehicles
        for track in tracks:
            x1, y1, x2, y2 = [int(v) for v in track.bbox]
            color = track.color
            label = f"#{track.track_id} {track.class_name} ({track.confidence:.0%})"

            cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
            (tw, th), _ = cv2.getTextSize(label, FONT, 0.45, 1)
            cv2.rectangle(out, (x1, y1 - th - 8), (x1 + tw + 4, y1), color, -1)
            cv2.putText(out, label, (x1 + 2, y1 - 4), FONT, 0.45, (0, 0, 0), 1)

            if len(track.history) > 2:
                pts = np.array(track.history[-20:], dtype=np.int32)
                for k in range(1, len(pts)):
                    alpha = k / len(pts)
                    c = tuple(int(v * alpha) for v in color)
                    cv2.line(out, tuple(pts[k - 1]), tuple(pts[k]), c, 1)

        # Draw raw collision detections from model (red dashed box)
        for det in collision_dets:
            x1, y1, x2, y2 = [int(v) for v in det.bbox]
            cv2.rectangle(out, (x1, y1), (x2, y2), (0, 0, 255), 2)
            label = f"{det.class_name} ({det.confidence:.0%})"
            cv2.putText(out, label, (x1, y1 - 6), FONT, 0.4, (0, 0, 255), 1)

        # Draw accident overlay
        if incident:
            x1, y1, x2, y2 = [int(v) for v in incident.bbox]
            sev = incident.severity
            overlay_color = (0, 0, 220) if sev == "Critical" else \
                            (0, 100, 220) if sev == "Major" else \
                            (0, 180, 220)

            cv2.rectangle(out, (x1, y1), (x2, y2), overlay_color, 3)

            warn = f"ACCIDENT! {sev} [{incident.incident_id}]"
            (tw, th), _ = cv2.getTextSize(warn, FONT, 0.75, 2)
            lx = max(0, int((x1 + x2) / 2 - tw / 2))
            ly = max(th + 10, y1 - 10)
            cv2.rectangle(out, (lx - 4, ly - th - 6), (lx + tw + 4, ly + 4), overlay_color, -1)
            cv2.putText(out, warn, (lx, ly), FONT, 0.75, (255, 255, 255), 2)

            if incident.plates:
                plate_txt = "Plates: " + "  |  ".join(incident.plates)
                cv2.putText(out, plate_txt, (lx, ly + 22), FONT, 0.5, (200, 255, 200), 1)

        _draw_hud(out, self.stats, self.enhancement_mode)
        return out


def _draw_hud(frame: np.ndarray, stats: dict, mode: str):
    lines = [
        f"RESCUE VISION  |  Frame: {stats['frame_count']}",
        f"Vehicles: {stats['total_vehicles']}   Incidents: {stats['total_incidents']}",
        f"Enhancement: {mode}",
    ]
    for i, line in enumerate(lines):
        y = 22 + i * 20
        cv2.putText(frame, line, (10, y), FONT, 0.5, (0, 0, 0), 3)
        cv2.putText(frame, line, (10, y), FONT, 0.5, (0, 255, 180), 1)
