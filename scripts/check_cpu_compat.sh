#!/bin/sh
# Check that a MyAstroBoard amd64 image runs on an x86-64 CPU without x86-64-v2
# (no SSE4.2/POPCNT) - e.g. a Proxmox VM with the generic "kvm64" CPU model, the
# default of the Home Assistant OS VM scripts.
#
#   sh scripts/check_cpu_compat.sh <image>          # CPU_MODEL=kvm64 by default
#
# Runs scripts/cpu_compat_smoke.py inside the image under QEMU user-mode emulation
# of that CPU. On failure, imports each compiled top-level package one by one and
# names those killed by SIGILL. What to do then: CONTRIBUTING.md "CPU compatibility".
set -eu

IMAGE="${1:?usage: check_cpu_compat.sh <image>}"
CPU_MODEL="${CPU_MODEL:-kvm64}"
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"

# MSYS_NO_PATHCONV: keep Git Bash on Windows from rewriting the container paths.
MSYS_NO_PATHCONV=1 docker run --rm --user root --entrypoint sh \
  -e CPU_MODEL="$CPU_MODEL" -e DATA_DIR=/tmp/cpu-compat-data -e DEBIAN_FRONTEND=noninteractive \
  -v "$SCRIPTS_DIR:/checks:ro" -w /app \
  "$IMAGE" -c '
set -u
echo "Installing QEMU user-mode emulation..."
apt-get update -qq >/dev/null && apt-get install -y -qq --no-install-recommends qemu-user >/dev/null \
  || { echo "::error::could not install qemu-user"; exit 2; }
mkdir -p "$DATA_DIR"
emulated() { qemu-x86_64 -cpu "$CPU_MODEL" /usr/local/bin/python3 "$@"; }

if ! emulated -c "pass"; then
  echo "::error::Python itself does not start under -cpu $CPU_MODEL - the emulation setup is broken"
  exit 2
fi
if ! python3 /checks/cpu_compat_smoke.py; then
  echo "::error::the smoke test fails on the native CPU too - not a CPU compatibility problem"
  exit 2
fi

echo "Running the smoke test on an emulated $CPU_MODEL CPU..."
if emulated /checks/cpu_compat_smoke.py; then
  echo "CPU compatibility ($CPU_MODEL): OK"
  exit 0
fi

echo "Looking for the packages that need a newer CPU..."
site=$(python3 -c "import sysconfig; print(sysconfig.get_paths()[\"purelib\"])")
offenders=""
for mod in $(cd "$site" && find . -name "*.so" | cut -d/ -f2 | grep -v "\.libs$" \
             | sed "s/\..*//" | sort -u); do
  emulated -c "import $mod" >/dev/null 2>&1 && continue
  status=$?
  # 132 = 128 + SIGILL; anything else is an unrelated import error.
  [ "$status" -eq 132 ] && offenders="$offenders $mod"
done
if [ -n "$offenders" ]; then
  # A package that merely imports a crashing one crashes too; the root causes are
  # the offenders that load no other offender (checked on the native CPU).
  roots=""
  for mod in $offenders; do
    loads=$(python3 -c "import sys, $mod; print(\" \".join(m for m in sys.argv[1:] if m != \"$mod\" and m in sys.modules))" $offenders 2>/dev/null)
    [ -z "$loads" ] && roots="$roots $mod"
  done
  echo "::error::root cause - packages built for a newer CPU than $CPU_MODEL:${roots:-$offenders}"
  echo "Crashing on import (including packages that only depend on the above):$offenders"
else
  echo "::error::the smoke test crashes on a $CPU_MODEL CPU, but no single package import does - see the log above"
fi
echo "See CONTRIBUTING.md \"CPU compatibility\"."
exit 1
'
