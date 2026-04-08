"""
Vehicle Detector Module
Dual-model approach:
  - YOLOv8n COCO model  → reliable vehicle detection (car, bus, truck, person, bicycle, motorcycle)
  - Custom trained model → Indian road vehicles (auto-rickshaw) + collision class detection
"""

from dataclasses import dataclass, field
from typing import List
import numpy as np

VEHICLE_COLORS = {
    "bicycle":                   (0, 200, 255),
    "motorcycle":                (0, 220, 200),
    "auto-rickshaw":             (0, 255, 180),
    "car":                       (0, 165, 255),
    "bus":                       (255, 165, 0),
    "truck":                     (255, 140, 0),
    "person":                    (255, 80,  80),
    "bicycle-bicycle_collision": (0,   0, 255),
    "bicycle-person_collision":  (0,  50, 255),
    "bicycle-object_collision":  (0,   0, 200),
    "motorcycle-car_collision":  (200, 0, 180),
    "motorcycle-person_collision":(220,0, 100),
    "car-car_collision":         (255, 0,   0),
    "car-person_collision":      (180, 0,  50),
    "car-object_collision":      (200, 0,   0),
    "car-bicycle_collision":     (0,   0, 220),
    "bus-collision":             (255, 0,  80),
    "truck-collision":           (255, 0, 120),
}

DEFAULT_CLASS_COLORS = [
    (0, 200, 255), (0, 220, 200), (0, 255, 180), (0, 165, 255),
    (255, 165, 0), (255, 140, 0), (255, 80, 80),  (255, 0, 0),
    (200, 0, 180), (0, 0, 255),
]

# COCO class IDs → vehicle names
_COCO_VEHICLE_CLASSES = {
    0: "person",
    1: "bicycle",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}


@dataclass
class Detection:
    bbox: List[float]       # [x1, y1, x2, y2]
    class_id: int
    class_name: str
    confidence: float
    track_id: int = -1
    color: tuple = field(default_factory=lambda: (128, 128, 128))


def _iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    union = (ax2-ax1)*(ay2-ay1) + (bx2-bx1)*(by2-by1) - inter
    return inter / union if union > 0 else 0.0


class VehicleDetector:
    def __init__(self, model_size: str = "n", conf: float = 0.25):
        from ultralytics import YOLO
        import os
        from pathlib import Path

        base_dir = Path(__file__).parent.parent

        # Custom model — Indian road vehicles + collision classes
        trained_model = str(base_dir / "model" / "best (1).pt")
        fallback_model = str(base_dir / "accident_best.pt")
        if os.path.exists(trained_model):
            self.custom_model = YOLO(trained_model)
        elif os.path.exists(fallback_model):
            self.custom_model = YOLO(fallback_model)
        else:
            self.custom_model = None

        # COCO model — highly reliable for standard vehicle classes
        self.coco_model = YOLO(f"yolov8{model_size}.pt")

        self.conf = conf
        self.class_names = {
            int(k): str(v)
            for k, v in self.custom_model.names.items()
        } if self.custom_model else {}

    def detect(self, frame: np.ndarray) -> List[Detection]:
        detections: List[Detection] = []

        # ── Step 1: COCO model — primary vehicle detector ──
        # Reliable for cars, motorcycles, buses, trucks, persons, bicycles.
        coco_res = self.coco_model(
            frame, conf=0.15, imgsz=1280, verbose=False,
            classes=list(_COCO_VEHICLE_CLASSES.keys()),
        )[0]

        if coco_res.boxes is not None:
            for box in coco_res.boxes:
                cid  = int(box.cls[0])
                name = _COCO_VEHICLE_CLASSES.get(cid, f"class_{cid}")
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                detections.append(Detection(
                    bbox=[x1, y1, x2, y2],
                    class_id=cid,
                    class_name=name,
                    confidence=float(box.conf[0]),
                    color=VEHICLE_COLORS.get(name, DEFAULT_CLASS_COLORS[cid % len(DEFAULT_CLASS_COLORS)]),
                ))

        # ── Step 2: Custom model — collision classes + auto-rickshaw ──
        # Only adds:
        #   (a) collision class detections (not in COCO)
        #   (b) auto-rickshaw (not in COCO)
        # Everything else is skipped to avoid duplicates with COCO.
        if self.custom_model is not None:
            custom_res = self.custom_model(
                frame, conf=self.conf, imgsz=640, verbose=False,
            )[0]

            if custom_res.boxes is not None:
                for box in custom_res.boxes:
                    cid  = int(box.cls[0])
                    name = self.class_names.get(cid, f"class_{cid}")
                    x1, y1, x2, y2 = box.xyxy[0].tolist()

                    is_collision = "collision" in name
                    is_autorickshaw = name == "auto-rickshaw"

                    if not (is_collision or is_autorickshaw):
                        continue  # covered by COCO

                    # Skip if a COCO detection already covers this area
                    if not is_collision:
                        duplicate = any(
                            _iou([x1, y1, x2, y2], d.bbox) > 0.4
                            for d in detections
                        )
                        if duplicate:
                            continue

                    detections.append(Detection(
                        bbox=[x1, y1, x2, y2],
                        class_id=cid,
                        class_name=name,
                        confidence=float(box.conf[0]),
                        color=VEHICLE_COLORS.get(name, DEFAULT_CLASS_COLORS[cid % len(DEFAULT_CLASS_COLORS)]),
                    ))

        return detections
