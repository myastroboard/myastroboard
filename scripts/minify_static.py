"""Minify static CSS and JS assets during Docker image build."""

from __future__ import annotations

import shutil
import sys
from importlib import import_module
from pathlib import Path


def should_skip(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".min.js") or name.endswith(".min.css")


def minify_file(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")

    if path.suffix.lower() == ".js":
        jsmin = import_module("rjsmin").jsmin
        minified = jsmin(source)
    elif path.suffix.lower() == ".css":
        compress = import_module("csscompressor").compress
        minified = compress(source)
    else:
        return False

    minified = minified.strip()
    if not minified or minified == source.strip():
        return False

    path.write_text(f"{minified}\n", encoding="utf-8")
    return True


def minify_tree(static_dir: Path) -> tuple[int, int]:
    processed = 0
    changed = 0

    for pattern in ("*.js", "*.css"):
        for path in static_dir.rglob(pattern):
            if should_skip(path):
                continue

            processed += 1
            if minify_file(path):
                changed += 1

    return processed, changed


def main() -> int:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("static")
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else source

    if not source.exists():
        print(f"[ERROR] Static directory not found: {source}")
        return 1

    if source != target:
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)

    processed, changed = minify_tree(target)
    print(
        f"[INFO] Build-time static minification complete: source={source}, target={target}, "
        f"processed={processed}, changed={changed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
