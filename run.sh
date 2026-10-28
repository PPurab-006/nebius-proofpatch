#!/bin/bash
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Activate virtual environment if present
if [ -d "$REPO_ROOT/.venv" ]; then
    echo "Activating virtual environment at $REPO_ROOT/.venv..."
    source "$REPO_ROOT/.venv/bin/activate"
elif [ -d "$REPO_ROOT/backend/.venv" ]; then
    echo "Activating virtual environment at $REPO_ROOT/backend/.venv..."
    source "$REPO_ROOT/backend/.venv/bin/activate"
fi

echo "Starting Patchworks Backend..."
cd "$REPO_ROOT/backend"
PYTHONPATH="$REPO_ROOT" uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

echo "Starting Patchworks Frontend..."
cd "$REPO_ROOT/frontend"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "Patchworks is running!"
echo "  Workbench: http://localhost:5173"
echo "  Backend:   http://localhost:8000"
echo "Press Ctrl+C to terminate both services."

cleanup() {
    echo ""
    echo "Stopping Patchworks services..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
    wait $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
}

trap cleanup SIGINT SIGTERM

wait
