#!/usr/bin/env bash
export GOOGLE_GENAI_USE_VERTEXAI=True
export GOOGLE_CLOUD_PROJECT=${PROJECT:-demo-project}
export GOOGLE_CLOUD_LOCATION=global

cd ..
uvicorn main:app --port 8080 &
BACKEND_PID=$!

cd frontend
npm run dev &
FRONTEND_PID=$!

echo "Backend: http://localhost:8080"
echo "Frontend: http://localhost:3000"
echo "Press Ctrl+C to stop"

trap "kill $BACKEND_PID $FRONTEND_PID" EXIT
wait
