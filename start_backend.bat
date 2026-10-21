@echo off
REM Backend-only launcher for Windows. Runs from the repository root so backend.main:app resolves.

cd /d "%~dp0"

if not defined PORT set PORT=8001

echo Starting AI Advisor Backend Server...
echo.

if exist ".venv\Scripts\python.exe" (
    set PYTHON=.venv\Scripts\python.exe
    echo Using project virtual environment ^(.venv^)
) else (
    set PYTHON=python
    echo No .venv found, using system Python
)

echo Starting uvicorn server on http://localhost:%PORT%
echo.

"%PYTHON%" -m uvicorn backend.main:app --host 0.0.0.0 --port %PORT%
