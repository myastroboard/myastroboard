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
# Keep SkyTonight logs for production diagnostics.

# Various migration/cleaning tasks
# v1.2.x: Remove old SkyTonight night table files (no longer used)
# now stored in location subdirectories
echo "[INFO] Cleaning json files from old SkyTonight night table (v1.2.x)"
find /app/data/skytonight/calculations -type f -name "*.json" -delete || true
find /app/data/skytonight/outputs -type f -name "*.json" -delete || true

echo "[INFO] Starting application as non-root user"
exec su appuser -c "$*"
