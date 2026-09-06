#!/usr/bin/env python3
"""PreToolUse hook: protect delivered report folders and locked report specs.

Protected set (rebuilt per call from <project_dir>/reports/*/spec.yaml, _examples
skipped): every top-level delivery.folder and powerbi.folder, plus any spec whose
report block says locked: true. Blocks (Hungarian reason on stderr, exit 2) a
Write/Edit/MultiEdit into them and a Bash command that mentions them together with
a destructive verb, a redirect into them, or Copy-Item -Force. Reads are never
blocked. Fail-open: errors go to <claude home>/hooks/.hook-errors.log, exit 0.
"""

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

HOOK_NAME = "protect_delivery"
EDIT_TOOLS = {"Write", "Edit", "MultiEdit"}
_VERB_RE = re.compile(
    r"(?<![\w-])(remove-item|move-item|clear-content|set-content|out-file"
    r"|rmdir|erase|move|rm|rd|del|mv|ri|mi)(?![\w-])"
)
# Git Bash drive form (/c/Users) to C:/Users, at string start or after whitespace/operators.
_DRIVE_RE = re.compile(r"(?<![\w:./])/([A-Za-z])(?=/|$)")
_WIN_ENV_RE = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)%")
_HOME_RE = re.compile(r"(\$env:USERPROFILE|%USERPROFILE%|\$\{HOME\}|\$HOME|~)(?=/|$)", re.I)
_TRUE = {"true", "yes", "on", "1"}


def _base_home() -> Path:
    return Path(os.environ.get("CLAUDE_KIT_HOME") or Path.home())


def _log_error(msg: str) -> None:
    try:
        hooks_dir = _base_home() / ".claude" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        with open(hooks_dir / ".hook-errors.log", "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now(UTC).isoformat()} {HOOK_NAME}: {msg}\n")
    except Exception:
        pass


def _slash(p: str) -> str:
    return p.replace("\\", "/")


def normalize_path(path: str, base: str | None = None) -> str:
    """Canonical lowercase forward-slash form; accepts Windows, POSIX and Git Bash spellings."""
    p = str(path).strip().strip("'\"").strip()
    p = _WIN_ENV_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), p)
    p = _slash(os.path.expandvars(os.path.expanduser(p)))
    p = _DRIVE_RE.sub(lambda m: m.group(1).upper() + ":", p)
    if base and not p.startswith("/") and not re.match(r"^[A-Za-z]:", p):
        p = _slash(str(base)).rstrip("/") + "/" + p
    return _slash(os.path.normpath(p)).lower().rstrip("/") or "/"


def _clean_value(raw: str) -> str:
    v = raw.strip()
    if v[:1] in ("'", '"'):
        end = v.find(v[0], 1)
        return v[1:end] if end > 0 else v[1:]
    return re.split(r"\s+#", v, maxsplit=1)[0].strip()


def _parse_spec(text: str) -> dict:
    """Line-based reader for top-level delivery.folder, powerbi.folder and report.locked."""
    found: dict = {}
    section = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.strip().partition(":")
        if not sep:
            continue
        key = key.strip()
        if not line[:1].isspace():
            section = key
        elif section in ("delivery", "powerbi") and key == "folder":
            found[section] = _clean_value(value)
        elif section == "report" and key == "locked":
            found["locked"] = _clean_value(value).lower() in _TRUE
    return found


def _project_dir() -> str:
    try:
        with open(_base_home() / ".claude" / "kit-state.json", encoding="utf-8") as fh:
            value = json.load(fh).get("project_dir")
        if isinstance(value, str) and value.strip():
            return os.path.expanduser(os.path.expandvars(value.strip()))
    except Exception:
        pass
    return str(_base_home() / "Riportok")


def _protected(project_dir: str) -> list[tuple[str, str, str]]:
    """[(normalized path, slug, kind)] with kind 'folder' or 'locked'."""
    entries: list[tuple[str, str, str]] = []
    for spec in sorted((Path(project_dir) / "reports").glob("*/spec.yaml")):
        slug = spec.parent.name
        if slug == "_examples":
            continue
        try:
            found = _parse_spec(spec.read_text(encoding="utf-8"))
        except Exception as exc:
            _log_error(f"cannot read {spec}: {exc!r}")
            continue
        for key in ("delivery", "powerbi"):
            if found.get(key):
                entries.append((normalize_path(found[key], project_dir), slug, "folder"))
        if found.get("locked"):
            entries.append((normalize_path(str(spec)), slug, "locked"))
    return entries


def _message(kind: str, path: str, slug: str) -> str:
    if kind == "folder":
        return (
            f"Tiltott művelet: a(z) {path} útvonal a(z) '{slug}' riport kézbesített "
            "riportmappájában van (delivery vagy Power BI mappa). A kézbesített fájlokat nem "
            "szabad kézzel írni, módosítani vagy törölni. A helyes út: futtasd a "
            f"/report-run {slug} parancsot, amely újraépíti és kézbesíti a riportot."
        )
    return (
        f"Tiltott művelet: a(z) {path} zárolt riportspecifikáció ('{slug}', report.locked: true). "
        "Zárolt spec.yaml fájlt nem szabad közvetlenül szerkeszteni vagy törölni. "
        f"A helyes út: futtasd a /report-edit {slug} parancsot."
    )


def _check_edit(file_path: str, base: str, entries: list) -> str | None:
    target = normalize_path(file_path, base)
    for path, slug, kind in entries:
        inside = target == path or (kind == "folder" and target.startswith(path + "/"))
        if inside:
            return _message(kind, file_path, slug)
    return None


def _mention_re(path: str, cwd: str | None) -> re.Pattern:
    forms = [re.escape(path)]
    if cwd and path.startswith(cwd + "/"):
        forms.append(r"(?<![\w./-])(?:\./)?" + re.escape(path[len(cwd) + 1 :]))
    return re.compile("(?:" + "|".join(forms) + r")(?![\w-])")


def _check_bash(command: str, cwd: str | None, entries: list) -> str | None:
    cmd = re.sub(r"[\"']", "", _slash(command))
    cmd = _HOME_RE.sub(lambda m: _slash(str(_base_home())), cmd)
    cmd = _DRIVE_RE.sub(lambda m: m.group(1).upper() + ":", cmd).lower()
    cwd_norm = normalize_path(cwd) if cwd else None
    for path, slug, kind in entries:
        mention = _mention_re(path, cwd_norm)
        hit = mention.search(cmd)
        if hit and (
            _VERB_RE.search(cmd)
            or re.search(r">>?\s*" + mention.pattern, cmd)
            or ("copy-item" in cmd and "-force" in cmd)
        ):
            return _message(kind, hit.group(0), slug)
    return None


def _run() -> str | None:
    raw = sys.stdin.read()
    if not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except Exception as exc:
        _log_error(f"malformed stdin: {exc!r}")
        return None
    if not isinstance(data, dict):
        return None
    tool_input = data.get("tool_input") or {}
    if isinstance(tool_input, str):
        tool_input = json.loads(tool_input)
    tool = data.get("tool_name", "")
    if not isinstance(tool_input, dict) or (tool not in EDIT_TOOLS and tool != "Bash"):
        return None
    project_dir = _project_dir()
    entries = _protected(project_dir)
    cwd = data.get("cwd") if isinstance(data.get("cwd"), str) and data.get("cwd") else None
    field = "file_path" if tool in EDIT_TOOLS else "command"
    value = tool_input.get(field)
    if not entries or not isinstance(value, str) or not value:
        return None
    if tool in EDIT_TOOLS:
        return _check_edit(value, cwd or project_dir, entries)
    return _check_bash(value, cwd, entries)


def main() -> None:
    try:
        reason = _run()
    except Exception as exc:
        _log_error(repr(exc))
        reason = None
    if reason:
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        sys.stderr.write(reason + "\n")
        sys.stderr.flush()
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
