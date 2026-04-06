FROM python:3.11-slim

WORKDIR /app

# System dependencies for OpenCV and EasyOCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch first (avoids pulling the 2GB CUDA build)
RUN pip install --no-cache-dir \
    torch==2.2.2 torchvision==0.17.2 \
    --index-url https://download.pytorch.org/whl/cpu

# Install remaining dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    python-multipart \
    aiofiles \
    websockets \
    numpy \
    Pillow \
    scipy \
    opencv-python-headless \
    ultralytics \
    easyocr \
    deep-sort-realtime

# Copy application code
COPY main.py .
COPY core/ core/
COPY static/ static/

# Create uploads directory
RUN mkdir -p uploads

# HF Spaces runs as non-root; ensure uploads is writable
RUN chmod 777 uploads

EXPOSE 7860

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
