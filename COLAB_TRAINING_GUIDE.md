# Rescue Vision - Google Colab Training Guide

---

## CURRENT PROJECT STATUS (as of April 2026)

### What is done:
- Full pipeline built: FastAPI + YOLOv8 + DeepSORT + EasyOCR + OpenCV
- Professional dashboard frontend (dark theme, 3-column layout, real-time WebSocket streaming)
- False-positive suppression: confidence filtering, bbox area checks, streak-based firing
- Severity classification: Critical / Major / Minor with per-class floor logic
- Dataset downloaded: 7,125 training images + 254 validation images (same 10-class layout)

### Current model file:
- `accident_best.pt` in the project root
- Architecture: YOLOv8n (nano), 10 classes
- Trained on a small dataset, needs retraining on the 7,125 image dataset

### Dataset (already downloaded and ready):
- Location: `C:\Users\Sushanthi\Desktop\accident\datasets\archive\`
- Colab zip: `C:\Users\Sushanthi\Desktop\accident\dataset_for_colab.zip` (278 MB)
- Structure inside zip:
  ```
  datasets/archive/
    data.yaml
    train/
      images/   (7125 .jpg files)
      labels/   (7125 .txt files in YOLO format)
    valid/
      images/   (254 .jpg files)
      labels/   (254 .txt files)
  ```
- Classes (10 total, same as current model):
  ```
  0: bicycle
  1: bicycle-bicycle_collision
  2: bicycle-object_collision
  3: bicycle-person_collision
  4: car
  5: car-bicycle_collision
  6: car-car_collision
  7: car-object_collision
  8: car-person_collision
  9: person
  ```

---

## HOW TO TRAIN ON GOOGLE COLAB (step by step)

### Step 1 - Upload files to Google Drive

Upload these two files to your Google Drive:
1. `dataset_for_colab.zip` (278 MB) - the training dataset
2. `accident_best.pt` - the current model weights (to fine-tune from)

### Step 2 - Open Google Colab

Go to https://colab.research.google.com and create a New Notebook.

**IMPORTANT: Change runtime to GPU**
- Click Runtime > Change runtime type > Hardware accelerator: **GPU** (T4 is free)
- This makes training 10x faster than CPU

### Step 3 - Paste this code into Colab cells

#### Cell 1: Mount Google Drive
```python
from google.colab import drive
drive.mount('/content/drive')
```

#### Cell 2: Install dependencies
```python
!pip install ultralytics -q
```

#### Cell 3: Extract dataset
```python
import zipfile
import os

# Update this path to where you uploaded the zip in Drive
zip_path = '/content/drive/MyDrive/dataset_for_colab.zip'

print("Extracting dataset...")
with zipfile.ZipFile(zip_path, 'r') as z:
    z.extractall('/content/')
print("Done!")

# Verify
train_imgs = len(os.listdir('/content/datasets/archive/train/images'))
val_imgs   = len(os.listdir('/content/datasets/archive/valid/images'))
print(f"Train images: {train_imgs}")
print(f"Val   images: {val_imgs}")
```

#### Cell 4: Copy current model weights
```python
import shutil

# Copy accident_best.pt from Drive to Colab
shutil.copy(
    '/content/drive/MyDrive/accident_best.pt',
    '/content/accident_best.pt'
)
print("Model weights copied!")
```

#### Cell 5: Create dataset.yaml
```python
yaml_content = """path: /content/datasets/archive
train: train/images
val:   valid/images

nc: 10

names:
  0: bicycle
  1: bicycle-bicycle_collision
  2: bicycle-object_collision
  3: bicycle-person_collision
  4: car
  5: car-bicycle_collision
  6: car-car_collision
  7: car-object_collision
  8: car-person_collision
  9: person
"""

with open('/content/dataset.yaml', 'w') as f:
    f.write(yaml_content)
print("dataset.yaml created!")
```

#### Cell 6: Train the model
```python
from ultralytics import YOLO

model = YOLO('/content/accident_best.pt')  # fine-tune from existing weights

model.train(
    data     = '/content/dataset.yaml',
    epochs   = 150,
    batch    = 16,      # GPU can handle larger batches
    imgsz    = 640,
    device   = 0,       # GPU
    workers  = 2,

    # Augmentation
    hsv_h       = 0.015,
    hsv_s       = 0.7,
    hsv_v       = 0.4,
    degrees     = 5.0,
    translate   = 0.1,
    scale       = 0.5,
    shear       = 2.0,
    perspective = 0.0005,
    flipud      = 0.0,
    fliplr      = 0.5,
    mosaic      = 1.0,
    mixup       = 0.15,
    copy_paste  = 0.1,

    # Optimizer
    optimizer    = 'AdamW',
    lr0          = 0.001,
    lrf          = 0.01,
    cos_lr       = True,
    warmup_epochs = 3,
    patience     = 20,   # early stopping

    # Loss weights
    cls = 0.7,
    box = 7.5,
    dfl = 1.5,

    # Output
    project = '/content/runs',
    name    = 'rescue_vision',
    plots   = True,
    verbose = True,
    save    = True,
    save_period = 10,
)

print("\nTraining complete!")
```

#### Cell 7: Save best model back to Google Drive
```python
import shutil

# Copy the best weights back to Google Drive
shutil.copy(
    '/content/runs/rescue_vision/weights/best.pt',
    '/content/drive/MyDrive/accident_best_retrained.pt'
)
print("Best model saved to Google Drive as accident_best_retrained.pt")
```

#### Cell 8: Check accuracy (mAP scores)
```python
from ultralytics import YOLO

model = YOLO('/content/runs/rescue_vision/weights/best.pt')
results = model.val(data='/content/dataset.yaml')

print("\n--- ACCURACY RESULTS ---")
print(f"mAP50:    {results.box.map50:.4f}")
print(f"mAP50-95: {results.box.map:.4f}")
print("\nTarget: mAP50 > 0.70 = good, > 0.85 = excellent")
```

---

## AFTER TRAINING - WHAT TO DO

1. Download `accident_best_retrained.pt` from Google Drive to your PC
2. Copy it to `C:\Users\Sushanthi\Desktop\accident\accident_best.pt` (replace the old file)
3. Restart the server: `python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload`
4. Open http://localhost:8000 and test with a video

No code changes needed — the server automatically loads `accident_best.pt` on startup.

---

## EXPECTED TRAINING TIME ON COLAB GPU

- GPU T4 (free): ~1-2 hours for 100 epochs on 7,125 images
- GPU A100 (Colab Pro): ~30-40 minutes
- CPU (your laptop): 8-24 hours — not recommended

---

## IF COLAB DISCONNECTS

Colab free tier disconnects after ~90 minutes of inactivity. To avoid losing progress:

Option A - Use Colab Pro (paid, ~$10/month)

Option B - Save checkpoints more often. Change `save_period = 5` in the train cell.
Then if it disconnects, the last checkpoint will be in `/content/runs/rescue_vision/weights/epoch_XX.pt`
You can resume from there.

Option C - Train in segments. After 50 epochs, save to Drive, then resume:
```python
model = YOLO('/content/drive/MyDrive/accident_best_retrained.pt')
model.train(..., resume=True)
```

---

## SEVERITY LOGIC REFERENCE (already in code, no changes needed)

The pipeline code (core/pipeline.py) already has these rules:

| Collision Type           | Minimum Severity |
|--------------------------|-----------------|
| car-person_collision     | Critical always |
| car-car_collision        | Major or higher |
| car-bicycle_collision    | Major or higher |
| bicycle-person_collision | Major or higher |
| car-object_collision     | Minor or higher |
| bicycle-bicycle_collision| Minor           |
| bicycle-object_collision | Minor           |

An alert only fires after 8 consecutive detection frames (prevents false positives).
After an alert fires, 90 frames (9 seconds) of silence before next alert.

---

## KEY FILES TO KNOW

```
accident/
  accident_best.pt         <- THE MODEL - replace this after retraining
  dataset.yaml             <- dataset config (updated to point at datasets/archive)
  dataset_for_colab.zip    <- upload this to Google Drive for Colab training
  train.py                 <- local training script (use on CPU/GPU locally)
  core/
    detector.py            <- VEHICLE_CLASSES dict (matches 10 classes)
    pipeline.py            <- thresholds, streak logic, severity rules
    accident.py            <- IoU + velocity fallback collision detection
```

---

*Generated April 2026 - Rescue Vision Project*
