# Rescue Vision — AI Model Training Report
# For Claude (New Session) — Read This First

---

## PROJECT OVERVIEW

**Project:** Rescue Vision — AI-Powered Accident Detection & Emergency Response
**Location:** `C:\Users\Sushanthi\Desktop\accident\`
**Stack:** FastAPI + YOLOv8 (custom trained) + DeepSORT tracker + EasyOCR + OpenCV
**Server:** `python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload`
**Dashboard:** http://localhost:8000

---

## CURRENT MODEL STATE

- **Model file:** `C:\Users\Sushanthi\Desktop\accident\accident_best.pt`
- **Architecture:** YOLOv8n (nano) — smallest/fastest variant
- **Current classes (10 total):**

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

### CRITICAL PROBLEMS WITH CURRENT MODEL

1. **Missing vehicle classes** — Bus, truck, auto-rickshaw, motorcycle/two-wheeler are NOT in the class list. They get misclassified as "car" or not detected at all.

2. **Human false positives** — The model detects human faces and bodies as vehicles or collision events, especially in live camera mode. Partial fix applied via confidence thresholds in `core/pipeline.py` but the root fix must be in the training data.

3. **Collision severity unreliable** — The model was trained on a small dataset. Severity (Critical/Major/Minor) is partially rule-based rather than truly learned.

4. **Small dataset** — Original training likely had < 500 images. YOLOv8 needs 1000-5000+ images per class for good accuracy.

---

## WHAT NEEDS TO BE DONE (IN ORDER)

---

### STEP 1 — EXPAND THE CLASS LIST

The current 10 classes need to be expanded to properly cover Indian/global traffic. The new target class list should be:

```
0:  bicycle
1:  motorcycle          ← NEW (two-wheeler)
2:  auto-rickshaw       ← NEW (tuk-tuk)
3:  car
4:  bus                 ← NEW
5:  truck               ← NEW
6:  person
7:  bicycle-bicycle_collision
8:  bicycle-person_collision
9:  bicycle-object_collision
10: motorcycle-car_collision    ← NEW
11: motorcycle-person_collision ← NEW
12: car-car_collision
13: car-person_collision
14: car-object_collision
15: car-bicycle_collision
16: bus-collision               ← NEW
17: truck-collision             ← NEW
```

**Update `dataset.yaml`** with the new class list before training.

---

### STEP 2 — GATHER DATASETS

You need labelled images for training. Use ALL of these sources:

#### A. Roboflow Universe (FREE — most important)
Go to: https://universe.roboflow.com

Search and download these datasets (format: **YOLOv8**):

| Search Term | Why |
|---|---|
| "vehicle detection" | Cars, buses, trucks, motorcycles |
| "accident detection" | Collision events |
| "indian traffic" | Auto-rickshaws, two-wheelers, Indian roads |
| "road accident" | Crash footage |
| "car crash detection" | Collision bounding boxes |
| "traffic monitoring" | Multi-vehicle scenes |

For each dataset: Click **Download** → Format: **YOLOv8** → **Download zip to computer**

#### B. Kaggle (FREE)
Go to: https://www.kaggle.com/datasets

Download these:
- "Road Accident Detection Dataset"
- "Vehicle Detection Dataset"
- "COCO subset — vehicles only"

#### C. Your own CCTV/dashcam footage
- Extract frames using: `python -c "import cv2; ..."`  (guide below)
- Label using **labelImg** (free tool)

---

### STEP 3 — DATASET SETUP

After downloading, organise into this structure:

```
C:\Users\Sushanthi\Desktop\accident\data\
  train\
    images\   ← all training .jpg/.png files
    labels\   ← matching .txt files (YOLO format)
  val\
    images\   ← validation images (20% of total)
    labels\
```

**YOLO label format** (one .txt per image):
```
<class_id> <center_x> <center_y> <width> <height>
```
All values normalised 0-1. Example:
```
3 0.512 0.441 0.230 0.180
```
This means: class 3 (car), centered at 51.2% x 44.1%, width 23%, height 18%.

**If datasets have different class names**, you must remap their class IDs to match your `dataset.yaml`. Ask Claude to write a remapping script.

---

### STEP 4 — LABELLING YOUR OWN DATA (if needed)

Install labelImg:
```bash
pip install labelImg
labelImg
```

In labelImg:
- Open image folder
- Set save format to **YOLO**
- Draw boxes around every vehicle and collision
- **Do NOT label individual people** — only label person when they are part of a collision event (class `car-person_collision`)
- Save labels alongside images

---

### STEP 5 — AUGMENT THE DATASET

Once data is in `data/train/`, run the augmentation script to multiply it 5x:

```bash
cd C:\Users\Sushanthi\Desktop\accident
python augment.py --input data/train --factor 5
```

This generates: rain, fog, blur, brightness changes, flips, perspective warps — all with correct label transforms.

Then update `dataset.yaml`:
```yaml
train: train_augmented/images   # ← changed from train/images
val:   val/images
```

---

### STEP 6 — TRAIN THE MODEL

#### Option A: Fine-tune from existing model (if new classes match old ones)
```bash
python train.py --base accident_best.pt --epochs 150 --batch 8 --device cpu
```

#### Option B: Train from scratch with new classes (recommended if class list changed)
```bash
python train.py --base yolov8s.pt --epochs 150 --batch 8 --device cpu
```
Note: Use `yolov8s.pt` (small) instead of `yolov8n.pt` (nano) for better accuracy.

#### Option C: If you have a GPU (NVIDIA):
```bash
python train.py --base yolov8s.pt --epochs 200 --batch 16 --device 0
```

**Training output:** Best weights auto-save to `accident_best.pt` when done.

---

### STEP 7 — FIX HUMAN FALSE POSITIVES (Training data level)

This is the most important fix. In your training data:

1. **Do NOT draw boxes around standalone people** — the model should ignore pedestrians
2. **Only label people when part of a collision** — draw one merged box and label it `car-person_collision`
3. **Add negative samples** — images with people but no vehicles, labelled with empty .txt files (no boxes). This teaches the model "person alone = not a vehicle"

Ask Claude to help you create a negative sample script that:
- Takes random frames from dashcam footage with no accidents
- Saves them with empty label files
- Adds them to `data/train/`

---

### STEP 8 — UPDATE THE DETECTOR CODE

After training with new classes, update `core/detector.py`:

```python
# Update VEHICLE_CLASSES dict to match your new dataset.yaml classes
VEHICLE_CLASSES = {
    0: "bicycle",
    1: "motorcycle",
    2: "auto-rickshaw",
    3: "car",
    4: "bus",
    5: "truck",
    6: "person",
    7: "bicycle-bicycle_collision",
    # ... etc matching your new class list
}
```

Also update `core/pipeline.py`:
```python
# Update which class IDs are normal vehicles vs collision events
NORMAL_CLASS_IDS    = {0, 1, 2, 3, 4, 5, 6}   # all vehicle + person classes
COLLISION_CLASS_IDS = {7, 8, 9, 10, 11, ...}   # all collision classes
```

---

### STEP 9 — VALIDATE THE MODEL

After training completes, test it:

```bash
python -c "
from ultralytics import YOLO
model = YOLO('accident_best.pt')
results = model.val(data='dataset.yaml')
print('mAP50:', results.box.map50)
print('mAP50-95:', results.box.map)
"
```

**Target metrics:**
- mAP50 > 0.70 = good
- mAP50 > 0.85 = excellent
- Per-class AP > 0.65 for each vehicle type

---

### STEP 10 — EXPORT TO ONNX (for faster inference)

```bash
python train.py --export
```

Or manually:
```bash
python -c "
from ultralytics import YOLO
model = YOLO('accident_best.pt')
model.export(format='onnx', imgsz=640, simplify=True)
"
```

---

## KEY FILES IN THE PROJECT

```
accident/
├── main.py              # FastAPI server — do not change unless adding API endpoints
├── train.py             # Training script — run this to train
├── augment.py           # Data augmentation — run before training
├── dataset.yaml         # Class definitions — update when adding new classes
├── requirements.txt     # Python dependencies
├── accident_best.pt     # THE MODEL — this gets replaced after training
├── core/
│   ├── detector.py      # VEHICLE_CLASSES dict — update after changing classes
│   ├── tracker.py       # DeepSORT tracker — no changes needed
│   ├── accident.py      # Severity scoring — tunable thresholds
│   ├── pipeline.py      # Main logic — NORMAL_CLASS_IDS / COLLISION_CLASS_IDS
│   ├── lpr.py           # License plate reader
│   └── enhancer.py      # Low-light / fog enhancement
└── static/              # Frontend (HTML/CSS/JS) — dashboard UI
```

---

## CURRENT PIPELINE THRESHOLDS (in core/pipeline.py)

These were tuned to reduce false positives. Do not change without testing:

```python
conf = 0.20               # minimum confidence for ALL detections
collision confidence = 0.45   # minimum confidence for COLLISION detections (higher = fewer false positives)
bbox area < 70% of frame       # rejects detections covering most of frame (face close to camera)
STREAK_TO_FIRE = 8             # need 8 consecutive collision frames before alert fires
ALERT_COOLDOWN = 90            # 9 seconds silence after each alert
iou_collision_threshold = 0.15 # vehicles must overlap 15% to trigger IoU-based alert
min_speed_for_crash = 3.0      # vehicle must be moving before impact counts
```

---

## SEVERITY LOGIC (in core/pipeline.py + core/accident.py)

Two detection methods work in parallel:

**Method 1 — Model-based:** YOLOv8 directly detects collision classes (car-car_collision etc.)
- Severity = max(class floor, confidence tier)
- car-person_collision → always Critical
- car-car_collision → always at least Major

**Method 2 — Physics-based fallback:** IoU overlap + velocity drop + approach speed
- Score = 0.30 × speed_drop + 0.35 × overlap + 0.35 × approach_velocity
- Score ≥ 0.65 → Critical, ≥ 0.35 → Major, ≥ 0.10 → Minor

---

## SUMMARY — PRIORITY ORDER

| Priority | Task | Effort |
|---|---|---|
| 1 | Download vehicle datasets from Roboflow | 30 min |
| 2 | Add bus/truck/motorcycle/auto to class list | 15 min |
| 3 | Reorganise data into data/train and data/val | 30 min |
| 4 | Run augment.py to multiply dataset | 10 min |
| 5 | Run train.py with yolov8s.pt | 2-8 hours (CPU) |
| 6 | Update VEHICLE_CLASSES in detector.py | 15 min |
| 7 | Update NORMAL_CLASS_IDS in pipeline.py | 5 min |
| 8 | Validate mAP scores | 10 min |
| 9 | Restart server and test | 5 min |

---

## WHAT THE NEW CLAUDE SESSION SHOULD KNOW

- The user is building a **hackathon project** for real-time accident detection
- Everything runs on **CPU** (no GPU confirmed)
- Python version is **3.14** — some older packages break (pkg_resources is gone, use importlib.resources)
- DeepSORT is already integrated but uses **mobilenet embedder**
- The frontend is a professional dark-theme dashboard at http://localhost:8000
- Severity categories are **Critical / Major / Minor** (NOT Serious)
- The main goal: detect cars, buses, trucks, motorcycles, auto-rickshaws accurately WITHOUT flagging humans as vehicles

---
*Generated by Claude — Rescue Vision Project — April 2026*
