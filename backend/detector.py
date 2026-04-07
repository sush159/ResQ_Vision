"""
Vehicle Detector Module
Uses YOLOv8 to detect vehicles and collision classes in frames.
"""

from dataclasses import dataclass, field
from typing import List

import numpy as np

VEHICLE_COLORS = {
    "bicycle": (0, 200, 255),
    "motorcycle": (0, 220, 200),
    "auto-rickshaw": (0, 255, 180),
    "car": (0, 165, 255),
    "bus": (255, 165, 0),
    "truck": (255, 140, 0),
    "person": (255, 80, 80),
    "bicycle-bicycle_collision": (0, 0, 255),
    "bicycle-person_collision": (0, 50, 255),
    "bicycle-object_collision": (0, 0, 200),
    "motorcycle-car_collision": (200, 0, 180),
    "motorcycle-person_collision": (220, 0, 100),
    "car-car_collision": (255, 0, 0),
    "car-person_collision": (180, 0, 50),
    "car-object_collision": (200, 0, 0),
    "car-bicycle_collision": (0, 0, 220),
    "bus-collision": (255, 0, 80),
    "truck-collision": (255, 0, 120),
}

DEFAULT_CLASS_COLORS = [
    (0, 200, 255),
    (0, 220, 200),
    (0, 255, 180),
    (0, 165, 255),
    (255, 165, 0),
    (255, 140, 0),
    (255, 80, 80),
    (255, 0, 0),
    (200, 0, 180),
    (0, 0, 255),
]


@dataclass
class Detection:
    bbox: List[float]
    class_id: int
    class_name: str
    confidence: float
    track_id: int = -1
    color: tuple = field(default_factory=lambda: (128, 128, 128))


class VehicleDetector:
    def __init__(self, model_size: str = "n", conf: float = 0.20):
        from ultralytics import YOLO
        import os
        from pathlib import Path

        base_dir = Path(__file__).parent.parent
        trained_model = str(base_dir / "accident_best.pt")
        if os.path.exists(trained_model):
            self.model = YOLO(trained_model)
        else:
            self.model = YOLO(f"yolov8{model_size}.pt")
        self.conf = conf
        self.class_names = {
            int(class_id): str(class_name)
            for class_id, class_name in self.model.names.items()
        }

    def detect(self, frame: np.ndarray) -> List[Detection]:
        results = self.model(
            frame,
            conf=self.conf,
            imgsz=480,
            verbose=False,
        )[0]

        detections: List[Detection] = []
        if results.boxes is None:
            return detections

        for box in results.boxes:
            cls_id = int(box.cls[0])
            name = self.class_names.get(cls_id, f"class_{cls_id}")
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            det = Detection(
                bbox=[x1, y1, x2, y2],
                class_id=cls_id,
                class_name=name,
                confidence=float(box.conf[0]),
                color=VEHICLE_COLORS.get(name, DEFAULT_CLASS_COLORS[cls_id % len(DEFAULT_CLASS_COLORS)]),
            )
            detections.append(det)

        return detections
