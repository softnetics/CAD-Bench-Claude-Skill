#!/usr/bin/env python3
"""build_skill_bundle.py -- rebuild cad-bench.skill, the one-file install.

The bundle is a zip whose entries all sit under `cad-bench/`. It holds what
the skill needs at run time and nothing else:

    SKILL.md README.md HOWTO.md LICENSE
    scripts/*.py   assets/*   references/*.md
    docs/screenshots/*.png         (HOWTO.md shows them)
    models/*.py (worked examples, not _-prefixed fixtures)
    models/rules/wheel-hub.rules   (the example's confirmed rules)

Never tests/, docs/ (beyond the screenshots), library/, .superpowers/,
exports, __pycache__ or *.stl. Text files are stored with LF line endings
and every entry gets the same timestamp, so the same tree gives the same
bytes on any machine.

    python scripts/build_skill_bundle.py [--out cad-bench.skill]
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREFIX = "cad-bench/"
STAMP = (2026, 1, 1, 0, 0, 0)
TEXT = {".md", ".py", ".html", ".js", ".rules", ".txt", ""}

TOP = ["SKILL.md", "README.md", "HOWTO.md", "LICENSE"]
GLOBS = ["scripts/*.py", "assets/*", "references/*.md", "docs/screenshots/*.png",
         "models/*.py"]
EXTRA = ["models/rules/wheel-hub.rules"]
EXCLUDED = ("tests/", "docs/superpowers/", "library/", ".superpowers/", "exports/",
            "__pycache__/", "node_modules/")


class BundleError(RuntimeError):
    pass


def excluded(rel):
    """Why `rel` must never ship, or None."""
    for d in EXCLUDED:
        if rel.startswith(d) or f"/{d}" in rel:
            return d
    if rel.lower().endswith(".stl"):
        return "*.stl"
    if rel.startswith("models/") and Path(rel).name.startswith("_"):
        return "models/_* (test fixture)"
    return None


def files(root=ROOT):
    """Sorted relative paths that go into the bundle."""
    out = set(TOP) | set(EXTRA)
    for g in GLOBS:
        out |= {p.relative_to(root).as_posix() for p in root.glob(g) if p.is_file()}
    out = {r for r in out if not excluded(r)}
    missing = [r for r in out if not (root / r).is_file()]
    if missing:
        raise BundleError(f"missing: {', '.join(sorted(missing))}")
    return sorted(out)


def _data(path):
    data = path.read_bytes()
    if path.suffix in TEXT:
        data = data.replace(b"\r\n", b"\n")
    return data


def build(out, root=ROOT):
    names = files(root)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in names:
            info = zipfile.ZipInfo(PREFIX + rel, STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, _data(root / rel))
    check(out)
    return names


def check(out):
    """Every entry under cad-bench/, none excluded, SKILL.md present."""
    with zipfile.ZipFile(out) as z:
        entries = z.namelist()
    bad = [e for e in entries if not e.startswith(PREFIX)]
    bad += [e for e in entries if excluded(e[len(PREFIX):])]
    if bad:
        raise BundleError(f"{out}: should not contain {', '.join(bad)}")
    if PREFIX + "SKILL.md" not in entries:
        raise BundleError(f"{out}: no SKILL.md")
    return entries


def main(argv=None):
    ap = argparse.ArgumentParser(description="rebuild cad-bench.skill")
    ap.add_argument("--out", default=str(ROOT / "cad-bench.skill"))
    a = ap.parse_args(argv)
    try:
        names = build(a.out)
    except BundleError as e:
        print(f"bundle: {e}", file=sys.stderr)
        return 1
    size = Path(a.out).stat().st_size
    print(f"{Path(a.out).name}: {len(names)} files, {size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
