"""
Accident Detection & Severity Classification Module
Analyzes tracked vehicles to detect collisions and sudden stops.
"""

import time
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from backend.tracker import Track, iou


SEVERITY_THRESHOLDS = {
    "Critical": 0.65,
    "Major":    0.35,
    "Minor":    0.10,
}

SEVERITY_COLORS = {
    "Critical": "#e74c3c",
    "Major":    "#e67e22",
    "Minor":    "#f1c40f",
}


@dataclass
class Incident:
    incident_id: str
    severity: str
    color: str
    track_ids: List[int]
    location: Tuple[float, float]  # bounding box center (x, y) of the collision
    bbox: List[float]              # merged bbox of involved vehicles
    collision_type: str = ""
    plates: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    frame_number: int = 0
    score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "incident_id": self.incident_id,
            "severity": self.severity,
            "color": self.color,
            "collision_type": self.collision_type,
            "track_ids": self.track_ids,
            "location": list(self.location),
            "bbox": self.bbox,
            "plates": self.plates,
            "timestamp": self.timestamp,
            "frame_number": self.frame_number,
            "score": round(self.score, 3),
        }


class AccidentDetector:
    def __init__(
        self,
        iou_collision_threshold: float = 0.08,
        speed_drop_ratio: float = 0.55,
        min_speed_for_crash: float = 2.5,
        cooldown_frames: int = 60,
    ):
        self.iou_threshold = iou_collision_threshold
        self.speed_drop_ratio = speed_drop_ratio
        self.min_speed_for_crash = min_speed_for_crash
        self.cooldown_frames = cooldown_frames

        self._incident_counter = 0
        self._last_incident_frames: Dict[frozenset, int] = {}
        self._current_frame = 0

    def _merge_bbox(self, a: List[float], b: List[float]) -> List[float]:
        return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]

    def _center(self, bbox: List[float]) -> Tuple[float, float]:
        return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)

    def _classify_severity(self, score: float) -> str:
        for label, threshold in SEVERITY_THRESHOLDS.items():
            if score >= threshold:
                return label
        return "Minor"

    def _approach_velocity(self, ta: "Track", tb: "Track") -> float:
        """
        Measures how fast the two vehicles are closing on each other along
        the line connecting their centres.  Positive = approaching, 0 = stationary.
        Normalised to [0, 1] where 1 = closing at ≥ 12 px/frame (fast approach).
        """
        if not ta.history or not tb.history:
            return 0.0
        cx_a = (ta.bbox[0] + ta.bbox[2]) / 2
        cy_a = (ta.bbox[1] + ta.bbox[3]) / 2
        cx_b = (tb.bbox[0] + tb.bbox[2]) / 2
        cy_b = (tb.bbox[1] + tb.bbox[3]) / 2
        dx = cx_a - cx_b
        dy = cy_a - cy_b
        dist = max(1.0, float(np.sqrt(dx * dx + dy * dy)))
        vax, vay = ta.velocity
        vbx, vby = tb.velocity
        rel_vx = vax - vbx
        rel_vy = vay - vby
        # Dot product of relative velocity with the unit vector from b→a
        # Positive means they are moving toward each other
        approach = -(rel_vx * dx + rel_vy * dy) / dist
        return float(np.clip(approach / 12.0, 0.0, 1.0))

    def _compute_score(
        self,
        overlap: float,
        speed_a: float,
        speed_b: float,
        avg_speed_a: float,
        avg_speed_b: float,
        approach_vel: float = 0.0,
    ) -> float:
        """
        Combines three signals into a severity score [0, 1]:
          - overlap_signal  : how much the bounding boxes overlap (IoU normalised)
          - speed_signal    : sudden deceleration of either vehicle
          - approach_signal : how fast the vehicles were closing before impact
        """
        # Speed drop: current speed much lower than historical avg → severe impact
        drop_a = 1.0 - (speed_a / avg_speed_a) if avg_speed_a > self.min_speed_for_crash else 0.0
        drop_b = 1.0 - (speed_b / avg_speed_b) if avg_speed_b > self.min_speed_for_crash else 0.0
        drop_a = max(0.0, min(1.0, drop_a))
        drop_b = max(0.0, min(1.0, drop_b))
        speed_signal = max(drop_a, drop_b)

        overlap_signal = min(1.0, overlap / 0.35)   # 0.35 IoU → full score

        # Weighted combination: approach velocity is the strongest physical indicator
        score = 0.30 * speed_signal + 0.35 * overlap_signal + 0.35 * approach_vel
        return float(np.clip(score, 0.0, 1.0))

    def detect(
        self,
        tracks: List[Track],
        frame_number: int,
    ) -> Optional[Incident]:
        self._current_frame = frame_number

        # Only consider non-person vehicles with movement history
        vehicles = [
            t for t in tracks
            if t.class_name != "person" and len(t.history) >= 5
        ]

        best_incident: Optional[Incident] = None
        best_score = 0.0

        for i in range(len(vehicles)):
            for j in range(i + 1, len(vehicles)):
                ta, tb = vehicles[i], vehicles[j]
                pair_key = frozenset([ta.track_id, tb.track_id])

                # Enforce cooldown
                last_frame = self._last_incident_frames.get(pair_key, -999)
                if frame_number - last_frame < self.cooldown_frames:
                    continue

                overlap = iou(ta.bbox, tb.bbox)
                if overlap < self.iou_threshold:
                    continue

                approach_vel = self._approach_velocity(ta, tb)
                score = self._compute_score(
                    overlap,
                    ta.speed, tb.speed,
                    ta.avg_speed, tb.avg_speed,
                    approach_vel,
                )

                if score < SEVERITY_THRESHOLDS["Minor"]:
                    continue

                if score > best_score:
                    best_score = score
                    merged = self._merge_bbox(ta.bbox, tb.bbox)
                    severity = self._classify_severity(score)
                    self._incident_counter += 1
                    incident_id = f"INC-{self._incident_counter:04d}"

                    collision_type = f"{ta.class_name} vs {tb.class_name}"
                    best_incident = Incident(
                        incident_id=incident_id,
                        severity=severity,
                        color=SEVERITY_COLORS[severity],
                        collision_type=collision_type,
                        track_ids=[ta.track_id, tb.track_id],
                        location=self._center(merged),
                        bbox=merged,
                        timestamp=time.time(),
                        frame_number=frame_number,
                        score=score,
                    )
                    self._last_incident_frames[pair_key] = frame_number

        return best_incident
