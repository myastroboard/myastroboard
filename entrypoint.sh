#!/bin/sh
set -e

echo "[INFO] Fixing permissions on mounted volumes..."
chown -R appuser:appuser /app/data || true

echo "[INFO] Cleaning temporary files in /app/data..."
# Keep persisted caches/status across restarts.
# Only remove transient lock/trigger files.
find /app/data -type f \( \
  -name "*.lock" -o \
  -name "scheduler_trigger" \
\) -delete || true

# Migration for v1.2.x.
# Remove legacy SkyTonight JSON files that are regenerated in subdirectories.
find /app/data/skytonight/calculations -type f -name "*.json" -delete 2>/dev/null || true
find /app/data/skytonight/outputs -type f -name "*.json" -delete 2>/dev/null || true

echo "[INFO] Starting application as non-root user"
exec su appuser -c "$*"
