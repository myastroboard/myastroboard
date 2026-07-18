"""Build the normalized SkyTonight target dataset."""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, 'backend')

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from skytonight.skytonight_catalogue_builder import build_and_save_default_dataset  # noqa: E402


def main() -> int:
    result = build_and_save_default_dataset()
    metadata = result['metadata']
    counts = metadata.get('counts', {})

    print('SkyTonight dataset generated successfully')
    print(f"Generated at: {metadata.get('generated_at', 'unknown')}")
    print(f"Deep sky targets: {counts.get('deep_sky', 0)}")
    print(f"Bodies: {counts.get('bodies', 0)}")
    print(f"Comets: {counts.get('comets', 0)}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
