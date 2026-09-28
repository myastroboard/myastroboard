#!/bin/sh
set -e

# Honour DATA_DIR (e.g. /data when run as a Home Assistant app); default unchanged.
DATA_DIR="${DATA_DIR:-/app/data}"

echo "[INFO] Fixing permissions on mounted volumes..."
chown -R appuser:appuser "$DATA_DIR" || true

echo "[INFO] Cleaning temporary files in $DATA_DIR..."
# Keep persisted caches/status across restarts.
# Only remove transient lock/trigger files.
find "$DATA_DIR" -type f \( \
  -name "*.lock" -o \
  -name "scheduler_trigger" \
\) -delete || true

# Migration for v1.2.x.
# Remove legacy flat SkyTonight JSON files left at the top level by pre-v1.2 runs;
# per-location results now live in subdirectories and must survive restarts.
find "$DATA_DIR/skytonight/calculations" -maxdepth 1 -type f -name "*.json" -delete 2>/dev/null || true
find "$DATA_DIR/skytonight/outputs" -maxdepth 1 -type f -name "*.json" -delete 2>/dev/null || true

echo "[INFO] Starting application as non-root user"
exec su appuser -c "$*"
