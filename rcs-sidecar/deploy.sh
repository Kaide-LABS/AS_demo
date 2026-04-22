#!/usr/bin/env bash
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"

gcloud run deploy rcs-sidecar \
  --source=. \
  --region=us-central1 \
  --service-account=rcs-sa@${PROJECT}.iam.gserviceaccount.com \
  --cpu=2 --memory=2Gi \
  --min-instances=1 \
  --max-instances=50 \
  --concurrency=40 \
  --cpu-boost \
  --timeout=300 \
  --set-env-vars="GOOGLE_GENAI_USE_VERTEXAI=True,GOOGLE_CLOUD_PROJECT=${PROJECT},GOOGLE_CLOUD_LOCATION=global" \
  --no-allow-unauthenticated
