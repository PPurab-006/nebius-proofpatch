#!/bin/bash

echo "Starting ProofPatch Backend..."
cd backend
# Run in background
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
cd ..

echo "Starting ProofPatch Frontend..."
cd frontend
# Run in background
npm run dev &
FRONTEND_PID=$!
cd ..

echo "ProofPatch is running!"
echo "Backend: http://localhost:8000"
echo "Frontend: http://localhost:5173"
echo "Press Ctrl+C to stop both."

trap "kill $BACKEND_PID $FRONTEND_PID" SIGINT

wait
