"""
Image Enhancement Module
Improves visibility under fog, rain, and low-light conditions.
"""

import cv2
import numpy as np


def enhance_frame(frame: np.ndarray):
    """
    Applies adaptive enhancement based on detected scene conditions.
    Returns (enhanced_frame, mode_string).
    """
    brightness = _estimate_brightness(frame)
    fog_score = _estimate_fog(frame)

    result = frame.copy()
    mode = "Normal"

    if brightness < 60:
        result = _enhance_low_light(result)
        mode = "Low-Light"

    if fog_score > 0.5:
        result = _dehaze(result)
        mode = "Dehaze"

    return result, mode


def _estimate_brightness(frame: np.ndarray) -> float:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(np.mean(gray))


def _estimate_fog(frame: np.ndarray) -> float:
    """
    Simple fog estimator: high brightness + low contrast = foggy.
    Returns a score from 0 (clear) to 1 (very foggy).
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mean = np.mean(gray)
    std = np.std(gray)
    if std < 1:
        return 0.0
    fog_score = max(0.0, min(1.0, (mean - 100) / 80 - std / 60))
    return fog_score


def _enhance_low_light(frame: np.ndarray) -> np.ndarray:
    """CLAHE on L channel of LAB colorspace."""
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    l_enhanced = clahe.apply(l)
    enhanced = cv2.merge([l_enhanced, a, b])
    return cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)


def _dehaze(frame: np.ndarray) -> np.ndarray:
    """
    Fast dehazing using Dark Channel Prior (simplified single-scale version).
    """
    frame_f = frame.astype(np.float64) / 255.0

    # Dark channel
    dark = np.min(frame_f, axis=2)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    dark_channel = cv2.erode(dark.astype(np.float32), kernel)

    # Atmospheric light estimation
    flat = dark_channel.flatten()
    top_idx = np.argsort(flat)[-max(1, int(len(flat) * 0.001)):]
    rows, cols = np.unravel_index(top_idx, dark_channel.shape)
    A = np.max(frame_f[rows, cols], axis=0)
    A = np.clip(A, 0.5, 1.0)

    # Transmission estimate
    omega = 0.85
    norm = frame_f / A
    dark_norm = np.min(norm, axis=2)
    dark_norm_ch = cv2.erode(dark_norm.astype(np.float32), kernel)
    t = 1.0 - omega * dark_norm_ch
    t = np.clip(t, 0.1, 1.0)[:, :, np.newaxis]

    # Scene radiance recovery
    t0 = 0.1
    J = (frame_f - A) / np.maximum(t, t0) + A
    J = np.clip(J, 0, 1)
    return (J * 255).astype(np.uint8)
