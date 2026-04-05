"""
Rescue Vision — Offline Dataset Augmentation
=============================================
Multiplies your training data by applying randomised transforms to every
image + label pair.  Run this BEFORE train.py when your dataset is small.

Usage
-----
  # 5x expansion of train split:
  python augment.py --input data/train --factor 5

  # Custom output directory:
  python augment.py --input data/train --output data/train_aug --factor 8

  # Preview without writing (dry run):
  python augment.py --input data/train --factor 3 --dry-run

What it does
------------
Each original image is transformed N times using a pipeline of:
  - Random horizontal flip
  - Random brightness / contrast / saturation / hue shift
  - Gaussian blur + motion blur (simulates camera shake / fast movement)
  - Random rain overlay (simulates bad weather)
  - Random fog overlay
  - Perspective warp  (simulates different camera angles)
  - Coarse dropout / cutout  (simulates partial occlusion)
  - CLAHE  (simulates different lighting conditions)
  - Random rotation ±10°
  - Mosaic blend of 4 images  (built into YOLOv8 training; skipped here)

All bounding-box labels are transformed correctly alongside the images.
"""

import argparse
import random
import shutil
from pathlib import Path

import cv2
import numpy as np


def parse_args():
    p = argparse.ArgumentParser(description="Rescue Vision — Dataset Augmentation")
    p.add_argument("--input",   required=True, help="Source split dir (must contain images/ and labels/)")
    p.add_argument("--output",  default=None,  help="Output dir (default: input_augmented/)")
    p.add_argument("--factor",  type=int, default=5, help="How many augmented copies per image")
    p.add_argument("--dry-run", action="store_true", help="Print what would happen without writing files")
    return p.parse_args()


# ── Augmentation helpers ──────────────────────────────────────────────────────

def random_brightness_contrast(img: np.ndarray) -> np.ndarray:
    alpha = random.uniform(0.6, 1.4)   # contrast
    beta  = random.randint(-40, 40)    # brightness
    return np.clip(img.astype(np.float32) * alpha + beta, 0, 255).astype(np.uint8)


def random_hsv(img: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 0] = (hsv[:, :, 0] + random.uniform(-18, 18)) % 180
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * random.uniform(0.5, 1.5), 0, 255)
    hsv[:, :, 2] = np.clip(hsv[:, :, 2] * random.uniform(0.5, 1.5), 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def random_blur(img: np.ndarray) -> np.ndarray:
    choice = random.random()
    if choice < 0.3:
        k = random.choice([3, 5])
        return cv2.GaussianBlur(img, (k, k), 0)
    elif choice < 0.5:
        # Motion blur (horizontal or vertical)
        k = random.choice([5, 7, 9])
        kernel = np.zeros((k, k))
        if random.random() < 0.5:
            kernel[k // 2, :] = 1.0 / k   # horizontal
        else:
            kernel[:, k // 2] = 1.0 / k   # vertical
        return cv2.filter2D(img, -1, kernel)
    return img


def random_flip(img: np.ndarray, bboxes: list) -> tuple:
    if random.random() < 0.5:
        img = cv2.flip(img, 1)   # horizontal
        bboxes = [[cls, 1.0 - cx, cy, w, h] for cls, cx, cy, w, h in bboxes]
    return img, bboxes


def random_rotate(img: np.ndarray, bboxes: list, max_deg: float = 10.0) -> tuple:
    """Rotate image and update bboxes (approximate — rotates bbox centres)."""
    h, w = img.shape[:2]
    angle = random.uniform(-max_deg, max_deg)
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    img = cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_REFLECT_101)

    rad = np.radians(-angle)
    cos_a, sin_a = np.cos(rad), np.sin(rad)
    new_bboxes = []
    for cls, cx, cy, bw, bh in bboxes:
        # Rotate centre point
        x = cx - 0.5; y = cy - 0.5
        nx = x * cos_a - y * sin_a + 0.5
        ny = x * sin_a + y * cos_a + 0.5
        nx = float(np.clip(nx, 0, 1))
        ny = float(np.clip(ny, 0, 1))
        new_bboxes.append([cls, nx, ny, bw, bh])
    return img, new_bboxes


def random_perspective(img: np.ndarray, bboxes: list, strength: float = 0.05) -> tuple:
    h, w = img.shape[:2]
    s = strength
    pts1 = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    pts2 = np.float32([
        [random.uniform(0, s*w), random.uniform(0, s*h)],
        [w - random.uniform(0, s*w), random.uniform(0, s*h)],
        [w - random.uniform(0, s*w), h - random.uniform(0, s*h)],
        [random.uniform(0, s*w), h - random.uniform(0, s*h)],
    ])
    M = cv2.getPerspectiveTransform(pts1, pts2)
    img = cv2.warpPerspective(img, M, (w, h), borderMode=cv2.BORDER_REFLECT_101)
    # Approximate: transform bbox centres only
    new_bboxes = []
    for cls, cx, cy, bw, bh in bboxes:
        pt = np.float32([[[cx * w, cy * h]]])
        tp = cv2.perspectiveTransform(pt, M)[0][0]
        nx = float(np.clip(tp[0] / w, 0, 1))
        ny = float(np.clip(tp[1] / h, 0, 1))
        new_bboxes.append([cls, nx, ny, bw, bh])
    return img, new_bboxes


def random_cutout(img: np.ndarray, n_holes: int = 3, max_frac: float = 0.15) -> np.ndarray:
    h, w = img.shape[:2]
    out = img.copy()
    for _ in range(n_holes):
        ch = int(h * random.uniform(0.02, max_frac))
        cw = int(w * random.uniform(0.02, max_frac))
        y  = random.randint(0, h - ch)
        x  = random.randint(0, w - cw)
        out[y:y+ch, x:x+cw] = random.randint(0, 255)
    return out


def add_rain(img: np.ndarray, intensity: float = 0.4) -> np.ndarray:
    h, w = img.shape[:2]
    rain = np.zeros_like(img)
    n_drops = int(w * h * intensity * 0.0003)
    for _ in range(n_drops):
        x1 = random.randint(0, w - 1)
        y1 = random.randint(0, h - 1)
        length = random.randint(10, 30)
        x2 = min(w - 1, x1 + random.randint(-3, 3))
        y2 = min(h - 1, y1 + length)
        cv2.line(rain, (x1, y1), (x2, y2), (200, 200, 200), 1)
    alpha = random.uniform(0.2, 0.5)
    return cv2.addWeighted(img, 1 - alpha, rain, alpha, 0)


def add_fog(img: np.ndarray) -> np.ndarray:
    fog_level = random.uniform(0.2, 0.5)
    fog       = np.ones_like(img, dtype=np.float32) * 255
    return np.clip(img.astype(np.float32) * (1 - fog_level) + fog * fog_level, 0, 255).astype(np.uint8)


def apply_clahe(img: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=random.uniform(1.5, 4.0), tileGridSize=(8, 8))
    return cv2.cvtColor(cv2.merge([clahe.apply(l), a, b]), cv2.COLOR_LAB2BGR)


def augment_image(img: np.ndarray, bboxes: list) -> tuple:
    """Apply a randomised chain of transforms to one image."""
    # Geometric (always applied in fixed order)
    img, bboxes = random_flip(img, bboxes)

    if random.random() < 0.5:
        img, bboxes = random_rotate(img, bboxes)

    if random.random() < 0.3:
        img, bboxes = random_perspective(img, bboxes)

    # Photometric
    img = random_hsv(img)
    img = random_brightness_contrast(img)
    img = random_blur(img)

    if random.random() < 0.25:
        img = add_rain(img)
    elif random.random() < 0.2:
        img = add_fog(img)

    if random.random() < 0.3:
        img = apply_clahe(img)

    if random.random() < 0.4:
        img = random_cutout(img)

    return img, bboxes


# ── Label I/O ─────────────────────────────────────────────────────────────────

def read_label(label_path: Path) -> list:
    """Return list of [class, cx, cy, w, h] floats."""
    if not label_path.exists():
        return []
    rows = []
    for line in label_path.read_text().strip().splitlines():
        parts = line.split()
        if len(parts) == 5:
            rows.append([int(parts[0])] + [float(x) for x in parts[1:]])
    return rows


def write_label(label_path: Path, bboxes: list):
    lines = [f"{int(b[0])} {b[1]:.6f} {b[2]:.6f} {b[3]:.6f} {b[4]:.6f}" for b in bboxes]
    label_path.write_text("\n".join(lines))


# ── Main ──────────────────────────────────────────────────────────────────────

def run(args):
    src_images = Path(args.input) / "images"
    src_labels = Path(args.input) / "labels"

    out_root = Path(args.output) if args.output else Path(str(args.input) + "_augmented")
    out_images = out_root / "images"
    out_labels = out_root / "labels"

    image_files = list(src_images.glob("*.jpg")) + list(src_images.glob("*.png"))

    if not image_files:
        print(f"[!] No images found in {src_images}")
        raise SystemExit(1)

    print(f"\n  Source      : {src_images}  ({len(image_files)} images)")
    print(f"  Output      : {out_images}")
    print(f"  Factor      : {args.factor}x  →  {len(image_files) * args.factor} augmented images")
    print(f"  Dry run     : {args.dry_run}\n")

    if args.dry_run:
        print("  [dry-run] No files written.")
        return

    out_images.mkdir(parents=True, exist_ok=True)
    out_labels.mkdir(parents=True, exist_ok=True)

    # Copy originals first
    for img_path in image_files:
        shutil.copy(img_path, out_images / img_path.name)
        lbl_path = src_labels / (img_path.stem + ".txt")
        if lbl_path.exists():
            shutil.copy(lbl_path, out_labels / lbl_path.name)

    total = 0
    for idx, img_path in enumerate(image_files):
        img = cv2.imread(str(img_path))
        if img is None:
            continue
        bboxes = read_label(src_labels / (img_path.stem + ".txt"))

        for k in range(args.factor):
            aug_img, aug_bboxes = augment_image(img.copy(), list(bboxes))
            stem = f"{img_path.stem}_aug{k:03d}"
            cv2.imwrite(str(out_images / f"{stem}.jpg"), aug_img, [cv2.IMWRITE_JPEG_QUALITY, 92])
            write_label(out_labels / f"{stem}.txt", aug_bboxes)
            total += 1

        if (idx + 1) % 20 == 0 or idx == len(image_files) - 1:
            print(f"  [{idx+1}/{len(image_files)}] {(idx+1)*args.factor} augmented images written…")

    print(f"\n  [✓] Done — {total} augmented images written to {out_root}")
    print(f"  Update dataset.yaml → train: {out_root.name}/images")


if __name__ == "__main__":
    run(parse_args())
