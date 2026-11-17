@echo off
setlocal

REM Resolve project root from script location and move there.
cd /d "%~dp0"

if not defined PORT set PORT=8001

echo Starting backend in APP_ENV=go mode...
echo.

set APP_ENV=go

if exist ".venv\Scripts\python.exe" (
    set PYTHON=.venv\Scripts\python.exe
    echo Using project virtual environment ^(.venv^)
) else (
    set PYTHON=python
    echo No .venv found, using system Python
)

echo APP_ENV=%APP_ENV%
echo Starting uvicorn server on http://localhost:%PORT%
echo.

"%PYTHON%" -m uvicorn backend.main:app --host 0.0.0.0 --port %PORT%
