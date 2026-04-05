"""
Rescue Vision — YOLOv8 Training Pipeline
=========================================
Trains or fine-tunes the accident detection model with:
  - Your existing labelled data  (data/train + data/val)
  - Optional extra datasets from Roboflow / custom sources
  - Strong augmentation (mosaic, mixup, copy-paste, colour jitter)
  - Cosine LR schedule + early stopping
  - Automatic export to ONNX after training

Usage
-----
  # Fine-tune from the existing checkpoint (recommended):
  python train.py

  # Train from pretrained YOLOv8n (if you have no checkpoint yet):
  python train.py --base yolov8n.pt

  # More epochs, larger batch:
  python train.py --epochs 150 --batch 16

  # Resume an interrupted run:
  python train.py --resume

  # Train then export to ONNX:
  python train.py --export
"""

import argparse
import shutil
from pathlib import Path

CHECKPOINT   = r"C:\Users\Sushanthi\Desktop\accident\accident_best.pt"
DATASET_YAML = r"C:\Users\Sushanthi\Desktop\accident\dataset.yaml"
PROJECT_DIR  = r"C:\Users\Sushanthi\Desktop\accident\runs\train"


def parse_args():
    p = argparse.ArgumentParser(description="Rescue Vision — YOLOv8 Training")
    p.add_argument("--base",    default=CHECKPOINT,    help="Starting weights (.pt)")
    p.add_argument("--data",    default=DATASET_YAML,  help="dataset.yaml path")
    p.add_argument("--epochs",  type=int, default=100, help="Training epochs")
    p.add_argument("--batch",   type=int, default=8,   help="Batch size (-1 = auto)")
    p.add_argument("--imgsz",   type=int, default=640, help="Input image size")
    p.add_argument("--device",  default="cpu",         help="cpu | 0 | 0,1 (GPU ids)")
    p.add_argument("--workers", type=int, default=2,   help="Dataloader workers")
    p.add_argument("--resume",  action="store_true",   help="Resume last run")
    p.add_argument("--export",  action="store_true",   help="Export to ONNX after training")
    return p.parse_args()


def verify_dataset(yaml_path: str) -> bool:
    """Check that train/val image dirs exist and have content."""
    import yaml
    with open(yaml_path) as f:
        cfg = yaml.safe_load(f)

    root = Path(yaml_path).parent / cfg.get("path", "data")
    ok = True
    for split in ["train", "val"]:
        img_dir = root / cfg.get(split, f"{split}/images")
        if not img_dir.exists():
            print(f"  [!] Missing: {img_dir}")
            ok = False
        else:
            n = len(list(img_dir.glob("*.jpg")) + list(img_dir.glob("*.png")))
            print(f"  [OK] {split}: {n} images  ({img_dir})")
    return ok


def train(args):
    from ultralytics import YOLO

    print("\n" + "=" * 62)
    print("   RESCUE VISION — YOLOv8 ACCIDENT DETECTION TRAINING")
    print("=" * 62)

    base = args.base
    if not Path(base).exists():
        print(f"  [!] Checkpoint not found: {base}")
        print("      Falling back to pretrained yolov8n.pt")
        base = "yolov8n.pt"

    print(f"\n  Weights : {base}")
    print(f"  Dataset : {args.data}")
    print(f"  Epochs  : {args.epochs}  |  Batch: {args.batch}  |  ImgSz: {args.imgsz}")
    print(f"  Device  : {args.device}\n")

    model = YOLO(base)

    model.train(
        data     = args.data,
        epochs   = args.epochs,
        batch    = args.batch,
        imgsz    = args.imgsz,
        device   = args.device,
        workers  = args.workers,
        project  = PROJECT_DIR,
        name     = "rescue_vision",
        resume   = args.resume,

        # -- Early stopping --
        patience = 20,

        # -- Checkpointing --
        save        = True,
        save_period = 10,

        # -- Augmentation ------------------------------------------
        # These transforms massively improve generalisation to new
        # camera angles, lighting, weather, and occlusion scenarios.
        hsv_h       = 0.015,   # hue shift ±1.5%
        hsv_s       = 0.7,     # saturation jitter
        hsv_v       = 0.4,     # brightness jitter
        degrees     = 5.0,     # rotation ±5°
        translate   = 0.1,     # translation ±10%
        scale       = 0.5,     # zoom 50–150%
        shear       = 2.0,     # shear ±2°
        perspective = 0.0005,  # slight perspective warp
        flipud      = 0.0,     # vertical flip OFF (cars not upside-down)
        fliplr      = 0.5,     # horizontal flip 50%
        mosaic      = 1.0,     # mosaic 4-image collage — best for small objects
        mixup       = 0.15,    # alpha-blend two images
        copy_paste  = 0.1,     # copy-paste object instances across images

        # -- Optimiser --
        optimizer    = "AdamW",
        lr0          = 0.001,
        lrf          = 0.01,   # final LR = lr0 * lrf
        momentum     = 0.937,
        weight_decay = 0.0005,
        warmup_epochs    = 3,
        warmup_momentum  = 0.8,
        cos_lr       = True,   # cosine annealing schedule

        # -- Loss weights ------------------------------------------
        # Raise cls weight: correctly classifying collision severity
        # (car-car vs car-person) is as important as localisation.
        cls = 0.7,   # default 0.5
        box = 7.5,
        dfl = 1.5,

        # -- Output --
        plots   = True,   # PR curve, confusion matrix, F1 curve
        verbose = True,
    )

    # Save best weights to project root
    best_pt = Path(PROJECT_DIR) / "rescue_vision" / "weights" / "best.pt"
    if best_pt.exists():
        shutil.copy(best_pt, CHECKPOINT)
        print(f"\n  [OK] Best weights -> {CHECKPOINT}")
    else:
        print("\n  [!] best.pt not found — check runs/train/rescue_vision/weights/")

    if args.export:
        export_onnx(str(best_pt) if best_pt.exists() else CHECKPOINT)


def export_onnx(weights: str):
    """
    Export to ONNX for ~2x faster CPU inference.
    DeepSORT appearance embeddings still run in PyTorch;
    only the YOLOv8 detector benefits from this.
    """
    from ultralytics import YOLO
    print("\n  [->] Exporting to ONNX...")
    model = YOLO(weights)
    model.export(format="onnx", imgsz=640, simplify=True, opset=17)
    onnx = weights.replace(".pt", ".onnx")
    print(f"  [OK] ONNX model saved: {onnx}")


def print_data_guide():
    print("\n" + "=" * 63)
    print("   HOW TO GET MORE TRAINING DATA")
    print("=" * 63)
    print("  1. ROBOFLOW  (free tier - easiest)")
    print("     Search 'accident detection' or 'vehicle collision'")
    print("     Export as YOLOv8 format, unzip into data/")
    print()
    print("  2. KAGGLE DATASETS")
    print("     - Road Accident Detection Dataset")
    print("     - CADP: Car Accident Detection & Prediction")
    print("     - UA-DETRAC Vehicle Detection")
    print()
    print("  3. AUGMENT EXISTING DATA (multiply dataset size)")
    print("     python augment.py --input data/train --factor 5")
    print()
    print("  REQUIRED LAYOUT:")
    print("     data/train/images/*.jpg    data/train/labels/*.txt")
    print("     data/val/images/*.jpg      data/val/labels/*.txt")
    print("=" * 63 + "\n")


if __name__ == "__main__":
    args = parse_args()
    print_data_guide()

    print("Verifying dataset...")
    if not verify_dataset(args.data):
        print("\n[!] Fix dataset layout then re-run train.py\n")
        raise SystemExit(1)

    train(args)
