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
# Remove legacy flat SkyTonight JSON files left at the top level by pre-v1.2 runs;
# per-location results now live in subdirectories and must survive restarts.
find /app/data/skytonight/calculations -maxdepth 1 -type f -name "*.json" -delete 2>/dev/null || true
find /app/data/skytonight/outputs -maxdepth 1 -type f -name "*.json" -delete 2>/dev/null || true

echo "[INFO] Starting application as non-root user"
exec su appuser -c "$*"
