@echo off
REM Boomerang Startup Script for Windows
REM Runs from the repository root: the backend is imported as backend.main:app.

cd /d "%~dp0"

if not defined PORT set PORT=8001

echo ========================================
echo 🚀 Starting Boomerang Platform
echo ========================================
echo.

REM Use the project virtual environment if it exists; otherwise create it.
if exist ".venv\Scripts\python.exe" (
    set PYTHON=.venv\Scripts\python.exe
) else (
    REM Check if Python is installed
    python --version >nul 2>&1
    if errorlevel 1 (
        echo ⚠️  Python is not installed or not in PATH
        echo Please install Python 3.11 (see .python-version^)
        pause
        exit /b 1
    )
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ⚠️  Failed to create virtual environment
        pause
        exit /b 1
    )
    set PYTHON=.venv\Scripts\python.exe
)

REM Check if backend directory exists
if not exist "backend" (
    echo ⚠️  Backend directory not found
    echo Please run this script from the project root
    pause
    exit /b 1
)

REM Install dependencies if needed
if not exist ".venv\.installed" (
    echo Installing dependencies...
    "%PYTHON%" -m pip install -r backend\requirements.txt
    if errorlevel 1 (
        echo ⚠️  Dependency installation failed
        pause
        exit /b 1
    )
    echo. > ".venv\.installed"
)

REM Start Backend
echo 📡 Starting Backend Server...
echo ✓ Starting FastAPI server on http://localhost:%PORT%
start "Boomerang Backend" cmd /k ""%PYTHON%" -m uvicorn backend.main:app --host 0.0.0.0 --port %PORT%"

REM Wait for backend to start
timeout /t 3 /nobreak >nul

REM Start Frontend
echo.
echo 🌐 Starting Frontend Server...
cd frontend

REM Start frontend server in a new window
echo ✓ Starting frontend on http://localhost:8080
start "Boomerang Frontend" cmd /k "python -m http.server 8080"

cd ..

REM Open browser
timeout /t 2 /nobreak >nul
start http://localhost:8080

echo.
echo ========================================
echo ✓ Boomerang is now running!
echo ========================================
echo.
echo 📊 Frontend:  http://localhost:8080
echo 📡 Backend:   http://localhost:%PORT%
echo 📚 API Docs:  http://localhost:%PORT%/docs
echo.
echo Two command windows have been opened:
echo   - Backend Server (FastAPI)
echo   - Frontend Server (HTTP)
echo.
echo Close those windows to stop the servers.
echo.
pause
