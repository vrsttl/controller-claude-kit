#!/usr/bin/env python3
"""PreToolUse snapshot hook for Claude auto-memory directories (Level 2+).

Before Write/Edit/MultiEdit touches a file under
<claude home>/projects/<slug>/memory/, copy MEMORY.md and the target file's
pre-image into memory/backups/ so a clobbering rewrite can be recovered.
Keeps the newest KEEP snapshots per file. Port of the workstation hook with
Windows-safe path handling (both slash styles, case-insensitive drive letters,
Git Bash /c/Users form). Any other path is a silent no-op.
Fail-open: never blocks, never exits non-zero; errors are logged to
<claude home>/hooks/.hook-errors.log.
"""

import json
import os
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

HOOK_NAME = "memory_backup"
KEEP = 20
MEMORY_RE = re.compile(
    r"^(.*[\\/]\.claude[\\/]projects[\\/][^\\/]+[\\/]memory)(?:[\\/]|$)", re.IGNORECASE
)
_TS_FRAGMENT = r"\d{8}T\d{6}_\d{6}Z"
MEMORY_SNAP_RE = re.compile(r"^MEMORY\." + _TS_FRAGMENT + r"\.md$")
BAK_RE = re.compile(r"^(.*)\." + _TS_FRAGMENT + r"\.bak$")
_GIT_BASH_DRIVE_RE = re.compile(r"^/([A-Za-z])(?=/|$)")


def _claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_KIT_HOME") or Path.home()) / ".claude"


def _log_error(msg: str) -> None:
    try:
        hooks_dir = _claude_home() / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        with open(hooks_dir / ".hook-errors.log", "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now(UTC).isoformat()} {HOOK_NAME}: {msg}\n")
    except Exception:
        pass


def _norm(path: object) -> str:
    """Case-insensitive, forward-slash comparison form."""
    return os.path.normcase(os.path.normpath(str(path))).replace("\\", "/").lower().rstrip("/")


def _utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")


def _prune(backups: Path) -> None:
    """Keep only the newest KEEP snapshots per logical group."""
    groups: dict[str, list[str]] = {}
    for name in os.listdir(backups):
        if MEMORY_SNAP_RE.match(name):
            groups.setdefault("MEMORY.md", []).append(name)
            continue
        m = BAK_RE.match(name)
        if m:
            groups.setdefault(m.group(1), []).append(name)
    for files in groups.values():
        if len(files) <= KEEP:
            continue
        paths = sorted((backups / f for f in files), key=lambda p: p.stat().st_mtime, reverse=True)
        for stale in paths[KEEP:]:
            try:
                stale.unlink()
            except Exception:
                pass


def _target_path(data: dict) -> str | None:
    tool_input = data.get("tool_input") or {}
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except Exception:
            return None
    if not isinstance(tool_input, dict):
        return None
    file_path = tool_input.get("file_path")
    return file_path if isinstance(file_path, str) and file_path else None


def _memory_dir(file_path: str) -> tuple[Path, Path] | None:
    """(memory dir, absolute target) when file_path is under <claude home>/projects/*/memory."""
    p = _GIT_BASH_DRIVE_RE.sub(lambda m: m.group(1).upper() + ":", file_path.replace("\\", "/"))
    absolute = os.path.normpath(os.path.abspath(os.path.expanduser(p)))
    m = MEMORY_RE.match(absolute)
    if not m:
        return None
    memdir = m.group(1)
    if not _norm(memdir).startswith(_norm(_claude_home() / "projects") + "/"):
        return None
    return Path(memdir), Path(absolute)


def _run() -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        return
    try:
        data = json.loads(raw)
    except Exception as exc:
        _log_error(f"malformed stdin: {exc!r}")
        return
    if not isinstance(data, dict):
        return
    file_path = _target_path(data)
    if not file_path:
        return
    found = _memory_dir(file_path)
    if not found:
        return
    memdir, target = found
    backups = memdir / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    ts = _utc_stamp()
    memory_md = memdir / "MEMORY.md"
    if memory_md.is_file():
        shutil.copy2(memory_md, backups / f"MEMORY.{ts}.md")
    if target.name != "MEMORY.md" and target.is_file():
        shutil.copy2(target, backups / f"{target.name}.{ts}.bak")
    _prune(backups)


def main() -> None:
    try:
        _run()
    except Exception as exc:
        _log_error(repr(exc))
    sys.exit(0)


if __name__ == "__main__":
    main()
