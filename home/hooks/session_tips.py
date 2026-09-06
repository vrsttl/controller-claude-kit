#!/usr/bin/env python3
"""SessionStart hook: one rotating Hungarian tip for the user's current kit level.

Reads level, tips_seen and flags from <claude home>/kit-state.json, picks a tip
from session_tips.json (fallbacks: session_tips.example.json, then a built-in
tip), bumps tips_seen (best effort, atomic replace) and prints an
additionalContext payload. Tips for level N pool levels 1..N so old tips keep
rotating. KIT_TODAY=YYYY-MM-DD overrides today's date (tests only).
Fail-open: any error is logged to <claude home>/hooks/.hook-errors.log, exit 0.
"""

import json
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

HOOK_NAME = "session_tips"
TIP_FILES = ("session_tips.json", "session_tips.example.json")
BUILTIN_TIP = (
    "A /report-list parancs megmutatja az összes riportot és az utolsó futtatásuk eredményét."
)
SCHEDULE_REMINDER = (
    "Emlékeztető: a hónap 5-én futó ütemezett havi riportnak mostanra el kellett készülnie. "
    "Ellenőrizd a kézbesítési mappát, és ha hiányzik a fájl, futtasd a /report-run parancsot."
)


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


def _load_state() -> tuple[dict, Path, bool]:
    """Return (state, path, readable). Missing or broken file -> ({}, path, False)."""
    path = _claude_home() / "kit-state.json"
    try:
        with open(path, encoding="utf-8") as fh:
            state = json.load(fh)
        if isinstance(state, dict):
            return state, path, True
    except Exception:
        pass
    return {}, path, False


def _load_tips() -> dict:
    dirs = [_claude_home() / "hooks"]
    script_dir = Path(__file__).resolve().parent
    if script_dir not in dirs:
        dirs.append(script_dir)
    for name in TIP_FILES:
        for directory in dirs:
            candidate = directory / name
            if not candidate.is_file():
                continue
            try:
                with open(candidate, encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception as exc:
                _log_error(f"cannot read {candidate}: {exc!r}")
                continue
            if isinstance(data, dict) and data:
                return data
    return {}


def _tip_pool(tips: dict, level: int) -> list[str]:
    pool: list[str] = []
    for lvl in range(1, level + 1):
        entries = tips.get(str(lvl), [])
        if isinstance(entries, list):
            pool.extend(t for t in entries if isinstance(t, str) and t.strip())
    return pool or [BUILTIN_TIP]


def _save_state(state: dict, path: Path, tips_seen: int) -> None:
    state["tips_seen"] = tips_seen
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def _today() -> date:
    raw = os.environ.get("KIT_TODAY", "").strip()
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return date.today()


def _run() -> None:
    try:
        sys.stdin.read()  # payload content is irrelevant
    except Exception:
        pass
    state, state_path, readable = _load_state()
    level = state.get("level")
    level = level if isinstance(level, int) and level >= 1 else 1
    seen = state.get("tips_seen")
    seen = seen if isinstance(seen, int) and seen >= 0 else 0
    pool = _tip_pool(_load_tips(), level)
    tip = pool[seen % len(pool)]
    if readable:  # never create kit-state.json, the installer owns it
        try:
            _save_state(state, state_path, seen + 1)
        except Exception as exc:
            _log_error(f"cannot update tips_seen: {exc!r}")
    text = f"Tipp ({level}. szint): {tip}"
    flags = state.get("flags")
    if isinstance(flags, dict) and flags.get("schedule") is True and 5 <= _today().day <= 7:
        text += " " + SCHEDULE_REMINDER
    payload = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main() -> None:
    try:
        _run()
    except Exception as exc:
        _log_error(repr(exc))
    sys.exit(0)


if __name__ == "__main__":
    main()
