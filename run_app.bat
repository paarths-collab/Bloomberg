@echo off
echo ===================================================
echo 🚀 Starting Autonomous Wealth Manager
echo ===================================================

echo [1/3] Activating Virtual Environment...
call venv\Scripts\activate

echo [2/3] Checking Dependencies...
python -m pip install -r requirements.txt

echo [3/3] Starting Backend Server...
echo.
echo    Backend running at: http://localhost:8000
echo    Frontend: Double click 'frontend/index.html' to launch UI.
echo.
echo Press Ctrl+C to stop the server.
echo.

uvicorn api:app --reload --host 0.0.0.0 --port 8000
