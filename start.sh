#!/bin/bash

# Boomerang Startup Script
# Runs from the repository root: the backend is imported as the `backend` package
# (`backend.main:app`), matching render.yaml's startCommand.

cd "$(dirname "$0")" || exit 1

echo "🚀 Starting Boomerang Financial Analytics Platform..."
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PORT="${PORT:-8001}"

# Check if backend directory exists
if [ ! -d "backend" ]; then
    echo -e "${YELLOW}⚠️  Backend directory not found. Please run this script from the project root.${NC}"
    exit 1
fi

# Use the project virtual environment if it exists; otherwise create it.
if [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
else
    if ! command -v python3 &> /dev/null; then
        echo -e "${YELLOW}⚠️  Python3 is not installed. Please install Python 3.11 (see .python-version).${NC}"
        exit 1
    fi
    echo -e "${YELLOW}Creating virtual environment (.venv)...${NC}"
    python3 -m venv .venv || exit 1
    PYTHON=".venv/bin/python"
fi

# Install dependencies if needed
if [ ! -f ".venv/.installed" ]; then
    echo -e "${YELLOW}Installing dependencies...${NC}"
    "$PYTHON" -m pip install -r backend/requirements.txt || exit 1
    touch .venv/.installed
fi

# Next.js must run the frontend source and proxy /api requests to this backend.
if ! command -v npm &> /dev/null; then
    echo "Node.js and npm are required to start the frontend."
    exit 1
fi
if [ ! -d frontend/node_modules ]; then
    (cd frontend && npm ci) || exit 1
fi
export BACKEND_URL="http://127.0.0.1:${PORT}"
export NEXT_PUBLIC_BACKEND_URL="$BACKEND_URL"

# Start Backend
echo -e "${BLUE}📡 Starting Backend Server...${NC}"
echo -e "${GREEN}✓ Starting FastAPI server on http://localhost:${PORT}${NC}"
"$PYTHON" -m uvicorn backend.main:app --host 0.0.0.0 --port "$PORT" &
BACKEND_PID=$!

# Start Frontend
echo ""
echo -e "${BLUE}🌐 Starting Frontend Server...${NC}"
echo -e "${GREEN}✓ Starting frontend on http://localhost:3000${NC}"
(cd frontend && exec npm run dev -- --port 3000) &
FRONTEND_PID=$!

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✓ Boomerang is now running!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "📊 Frontend:  ${BLUE}http://localhost:3000${NC}"
echo -e "📡 Backend:   ${BLUE}http://localhost:${PORT}${NC}"
echo -e "📚 API Docs:  ${BLUE}http://localhost:${PORT}/docs${NC}"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all servers${NC}"
echo ""

# Stop both servers on Ctrl+C or SIGTERM
cleanup() {
    echo ""
    echo -e "${YELLOW}Stopping servers...${NC}"
    kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
    exit 0
}
trap cleanup INT TERM

wait
