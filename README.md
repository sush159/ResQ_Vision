---
title: ResQ Vision
emoji: 🚨
colorFrom: red
colorTo: orange
sdk: docker
app_port: 7860
pinned: false
---

# ResQ Vision — AI-Powered Accident Detection

Real-time accident detection and emergency response system using YOLOv8 + FastAPI.

## Features
- 18-class YOLOv8 model detecting vehicles and collision types
- Real-time WebSocket streaming with annotated video frames
- Severity classification: Minor / Major / Critical
- License plate reading (EasyOCR) on accident detection
- Live camera and uploaded video support
