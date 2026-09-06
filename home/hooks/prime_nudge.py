#!/usr/bin/env python3
"""SessionStart / PostToolUse hook: nudge Claude to run /prime after a context reset.

Port of the workstation prime-nudge.sh without jq. Emits a hookSpecificOutput
additionalContext payload. The Hungarian wording gates itself on whether /prime
exists in the current project, so the hook is a harmless no-op elsewhere.

Usage: python prime_nudge.py <HookEventName>   (SessionStart or PostToolUse)
Fail-open: any error is logged to <claude home>/hooks/.hook-errors.log, exit 0.
"""

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

HOOK_NAME = "prime_nudge"
NUDGE = (
    "A kontextus most újraindult vagy kiléptél a tervezési módból. "
    "Ha ebben a projektben elérhető a /prime parancs, futtasd most, hogy betöltsd "
    "a projekt kontextusát (riportok, adatállapot, legutóbbi munka), mielőtt bármi "
    "mást csinálnál. Ha a /prime itt nem elérhető, hagyd figyelmen kívül ezt az üzenetet."
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


def _run() -> None:
    try:
        sys.stdin.read()  # payload content is irrelevant, consume it so the pipe closes cleanly
    except Exception:
        pass
    event = "SessionStart"
    if len(sys.argv) > 1 and sys.argv[1].strip():
        event = sys.argv[1].strip()
    payload = {"hookSpecificOutput": {"hookEventName": event, "additionalContext": NUDGE}}
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
