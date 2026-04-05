"""
License Plate Recognition Module
Uses EasyOCR to extract plate numbers from cropped vehicle regions.
"""

import re
import numpy as np
import cv2
from typing import List, Optional

_READER = None
PLATE_PATTERN = re.compile(r"[A-Z0-9]{4,10}")


def _get_reader():
    global _READER
    if _READER is None:
        import easyocr
        _READER = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _READER


def _crop_plate_region(frame: np.ndarray, bbox: List[float]) -> np.ndarray:
    """
    Crops the lower ~40% of the vehicle bounding box where plates are typically found.
    """
    x1, y1, x2, y2 = [int(v) for v in bbox]
    h = y2 - y1
    plate_y1 = max(0, y1 + int(h * 0.55))
    plate_y2 = min(frame.shape[0], y2)
    plate_x1 = max(0, x1)
    plate_x2 = min(frame.shape[1], x2)
    return frame[plate_y1:plate_y2, plate_x1:plate_x2]


def _preprocess(crop: np.ndarray) -> np.ndarray:
    """Sharpen and upscale the crop for better OCR accuracy."""
    if crop.size == 0:
        return crop
    scale = max(1, min(4, 120 // max(crop.shape[0], 1)))
    if scale > 1:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    # Sharpen
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    sharpened = cv2.filter2D(gray, -1, kernel)
    # Threshold
    _, thresh = cv2.threshold(sharpened, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return thresh


def read_plate(frame: np.ndarray, bbox: List[float]) -> Optional[str]:
    """
    Attempts to read a license plate from the vehicle bounding box.
    Returns the plate string if found, else None.
    """
    crop = _crop_plate_region(frame, bbox)
    if crop.size == 0 or crop.shape[0] < 5 or crop.shape[1] < 10:
        return None

    processed = _preprocess(crop)

    try:
        reader = _get_reader()
        results = reader.readtext(processed, detail=1, paragraph=False)
    except Exception:
        return None

    candidates = []
    for _, text, conf in results:
        cleaned = re.sub(r"[^A-Z0-9]", "", text.upper())
        if conf > 0.4 and PLATE_PATTERN.match(cleaned):
            candidates.append((conf, cleaned))

    if not candidates:
        return None

    candidates.sort(reverse=True)
    return candidates[0][1]


def read_plates_for_incident(
    frame: np.ndarray,
    bboxes: List[List[float]],
) -> List[str]:
    """Read plates for all vehicle bounding boxes in an incident."""
    plates = []
    for bbox in bboxes:
        plate = read_plate(frame, bbox)
        if plate:
            plates.append(plate)
    return plates
