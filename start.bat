@echo off
echo ╔══════════════════════════════════════════════╗
echo ║         RESCUE VISION — Starting Up          ║
echo ╚══════════════════════════════════════════════╝

echo.
echo [1/3] Stopping any existing server on port 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING 2^>nul') do (
    taskkill /f /pid %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

echo [2/3] Installing dependencies...
pip install -r requirements.txt -q

echo.
echo [3/3] Starting server at http://localhost:8000
echo       Open your browser and go to: http://localhost:8000
echo.
python -m uvicorn app:app --host 0.0.0.0 --port 8000
