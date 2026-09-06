# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Generate and verify `manifest.json`, the installer's copy contract.

The manifest lists every file the installer copies onto her laptop together with
its sha256, so `install.ps1` can tell three cases apart: the file is missing, the
file is untouched, or she edited it and the copy needs a backup first.

    uv run python tests/build_manifest.py --write
    uv run python tests/build_manifest.py --check

`--check` exits 1 and prints the differing paths when the manifest is stale.
Standard library only, Python 3.12.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "manifest.json"
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"

# Sections copied by install.ps1, in the order the installer walks them.
SECTIONS: tuple[str, ...] = ("home", "templates/project", "scripts")

EXCLUDED_DIRS = frozenset(
    {
        "__pycache__",
        ".git",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".venv",
        "node_modules",
    }
)
EXCLUDED_NAMES = frozenset({".DS_Store", "Thumbs.db"})
EXCLUDED_SUFFIXES = frozenset({".pyc", ".pyo", ".pyd", ".swp", ".orig", ".rej"})

FALLBACK_VERSION = "0.1.0"
VERSION_HEADING = re.compile(r"^##\s+\[(\d+\.\d+\.\d+)\]")


def is_excluded(path: Path, root: Path) -> bool:
    """True when the file must not be shipped (caches, editor and OS droppings)."""
    rel = path.relative_to(root)
    if any(part in EXCLUDED_DIRS for part in rel.parts):
        return True
    if path.name in EXCLUDED_NAMES:
        return True
    return path.suffix in EXCLUDED_SUFFIXES


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_managed_files(root: Path = REPO_ROOT) -> list[Path]:
    """Every shipped file under the managed sections, sorted by POSIX path."""
    found: list[Path] = []
    for section in SECTIONS:
        base = root / section
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if is_excluded(path, root):
                continue
            found.append(path)
    return sorted(found, key=lambda p: p.relative_to(root).as_posix())


def read_kit_version(changelog: Path = CHANGELOG_PATH) -> str:
    """First `## [x.y.z]` heading in the changelog, else the fallback version."""
    if not changelog.is_file():
        return FALLBACK_VERSION
    for line in changelog.read_text(encoding="utf-8").splitlines():
        match = VERSION_HEADING.match(line)
        if match:
            return match.group(1)
    return FALLBACK_VERSION


def build_files(root: Path = REPO_ROOT) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path) for path in iter_managed_files(root)
    }


def load_manifest(path: Path = MANIFEST_PATH) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def write_manifest(root: Path = REPO_ROOT, path: Path = MANIFEST_PATH) -> dict:
    """Regenerate the manifest, keeping `generated_at` stable when nothing moved."""
    files = build_files(root)
    version = read_kit_version(root / "CHANGELOG.md")
    previous = load_manifest(path)
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if (
        previous
        and previous.get("files") == files
        and previous.get("kit_version") == version
        and previous.get("generated_at")
    ):
        generated_at = str(previous["generated_at"])
    manifest = {"kit_version": version, "generated_at": generated_at, "files": files}
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def diff_files(current: dict[str, str], expected: dict[str, str]) -> tuple[list, list, list]:
    added = sorted(set(expected) - set(current))
    removed = sorted(set(current) - set(expected))
    changed = sorted(k for k in set(current) & set(expected) if current[k] != expected[k])
    return added, removed, changed


def check_manifest(root: Path = REPO_ROOT, path: Path = MANIFEST_PATH) -> int:
    manifest = load_manifest(path)
    if manifest is None:
        print(f"manifest missing or unreadable: {path}")
        print("run: uv run python tests/build_manifest.py --write")
        return 1

    expected_files = build_files(root)
    expected_version = read_kit_version(root / "CHANGELOG.md")
    current_files = dict(manifest.get("files") or {})
    problems = 0

    if manifest.get("kit_version") != expected_version:
        print(f"kit_version stale: {manifest.get('kit_version')!r} != {expected_version!r}")
        problems += 1

    added, removed, changed = diff_files(current_files, expected_files)
    for label, paths in (("missing from manifest", added), ("no longer on disk", removed)):
        for item in paths:
            print(f"{label}: {item}")
    for item in changed:
        print(f"hash changed: {item}")
    problems += len(added) + len(removed) + len(changed)

    if problems:
        print()
        print("run: uv run python tests/build_manifest.py --write")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build_manifest.py", description="Generate or verify manifest.json."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="Regenerate manifest.json.")
    group.add_argument("--check", action="store_true", help="Exit 1 when manifest.json is stale.")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="Repository root override.")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    manifest_path = root / "manifest.json"

    if args.write:
        manifest = write_manifest(root, manifest_path)
        print(f"manifest.json: {len(manifest['files'])} file(s), version {manifest['kit_version']}")
        return 0
    return check_manifest(root, manifest_path)


if __name__ == "__main__":
    sys.exit(main())
