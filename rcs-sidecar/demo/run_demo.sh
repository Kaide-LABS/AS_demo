#!/usr/bin/env bash
set -euo pipefail

# Demo runner. Defaults to API-key mode (GEMINI_API_KEY). Set USE_VERTEXAI=1
# to switch to Vertex (requires gcloud auth + GOOGLE_CLOUD_PROJECT).

if [[ "${USE_VERTEXAI:-0}" == "1" ]]; then
    export GOOGLE_GENAI_USE_VERTEXAI=True
    export GOOGLE_CLOUD_PROJECT="${PROJECT:?Set PROJECT to your GCP project when USE_VERTEXAI=1}"
    export GOOGLE_CLOUD_LOCATION="${GOOGLE_CLOUD_LOCATION:-global}"
else
    export GOOGLE_GENAI_USE_VERTEXAI=False
    : "${GEMINI_API_KEY:?Set GEMINI_API_KEY (or USE_VERTEXAI=1)}"
fi

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
ROOT_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"

cd "$ROOT_DIR"
uvicorn main:app --port 8080 &
BACKEND_PID=$!

cd "$ROOT_DIR/frontend"
npm run dev &
FRONTEND_PID=$!

echo "Backend:  http://localhost:8080  (pid $BACKEND_PID)"
echo "Frontend: http://localhost:3000  (pid $FRONTEND_PID)"
echo "Press Ctrl+C to stop."

cleanup() {
    kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
wait
