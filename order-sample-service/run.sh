#!/usr/bin/env bash
set -euo pipefail

export OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-localhost:4317}"
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-8010}"
export PYTHONUNBUFFERED=1

python -m uvicorn app:app --host "${HOST}" --port "${PORT}"
