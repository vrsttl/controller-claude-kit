"""Contract tests for the kit hooks in home/hooks.

Every hook runs as a subprocess with CLAUDE_KIT_HOME pointing at a temporary
home, exactly the way Claude Code launches it (event JSON on stdin, JSON or
nothing on stdout, exit code carries the decision).
"""

import ast
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import protect_delivery
import pytest
import session_tips

HOOKS_DIR = Path(__file__).resolve().parents[1] / "home" / "hooks"
HOOKS = ["prime_nudge.py", "session_tips.py", "protect_delivery.py", "memory_backup.py"]
TIPS = {
    "1": ["Elso tipp", "Masodik tipp"],
    "2": ["Kontroll tipp"],
    "3": ["Automatizalas tipp"],
}


def run_hook(name, home, stdin="", args=(), env=None, devnull=False):
    full_env = {k: v for k, v in os.environ.items() if k != "KIT_TODAY"}
    full_env["CLAUDE_KIT_HOME"] = str(home)
    full_env.update(env or {})
    kwargs = {"stdin": subprocess.DEVNULL} if devnull else {"input": stdin}
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / name), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=full_env,
        timeout=60,
        **kwargs,
    )


def hook_context(proc):
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)["hookSpecificOutput"]
    return out["hookEventName"], out["additionalContext"]


def write_state(home, **overrides):
    state = {
        "kit_version": "0.1.0",
        "level": 1,
        "installed_at": "2026-09-06T10:00:00",
        "updated_at": "2026-09-06T10:00:00",
        "kit_path": "C:\\Users\\fanni\\claude-kit",
        "project_dir": str(home / "Riportok"),
        "tips_seen": 0,
        "flags": {"gmail": True, "nav": False, "schedule": False},
    }
    state.update(overrides)
    claude = home / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    (claude / "kit-state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def read_state(home):
    return json.loads((home / ".claude" / "kit-state.json").read_text(encoding="utf-8"))


def error_log(home):
    path = home / ".claude" / "hooks" / ".hook-errors.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def pre_tool_use(tool_name, tool_input, cwd):
    return json.dumps(
        {
            "session_id": "abc123",
            "transcript_path": str(cwd / "transcript.jsonl"),
            "cwd": str(cwd),
            "permission_mode": "default",
            "hook_event_name": "PreToolUse",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_use_id": "toolu_01",
        }
    )


@pytest.fixture
def home(tmp_path):
    (tmp_path / ".claude" / "hooks").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def tips(home):
    (home / ".claude" / "hooks" / "session_tips.json").write_text(
        json.dumps(TIPS, ensure_ascii=False), encoding="utf-8"
    )
    return TIPS


# ---------------------------------------------------------------- every hook


@pytest.mark.parametrize("hook", HOOKS)
def test_every_hook_survives_devnull_stdin(hook, home):
    proc = run_hook(hook, home, devnull=True)
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""


@pytest.mark.parametrize("hook", HOOKS)
def test_every_hook_has_no_third_party_imports(hook):
    text = (HOOKS_DIR / hook).read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env python3\n")
    assert "\u2014" not in text  # no em dashes in code or messages
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            assert name.split(".")[0] in sys.stdlib_module_names, f"{hook}: {name}"


# --------------------------------------------------------------- prime_nudge


@pytest.mark.parametrize("event", ["SessionStart", "PostToolUse"])
def test_prime_nudge_emits_hungarian_context(home, event):
    payload = json.dumps({"hook_event_name": event, "cwd": str(home), "source": "clear"})
    name, ctx = hook_context(run_hook("prime_nudge.py", home, payload, args=[event]))
    assert name == event
    assert "/prime" in ctx
    assert "kontextus" in ctx.lower()
    assert "hagyd figyelmen kívül" in ctx


def test_prime_nudge_empty_stdin_and_default_event(home):
    name, ctx = hook_context(run_hook("prime_nudge.py", home, ""))
    assert name == "SessionStart"
    assert "/prime" in ctx


# -------------------------------------------------------------- session_tips


def test_session_tips_rotates_and_counts(home, tips):
    write_state(home, level=1, tips_seen=0)
    seen = [hook_context(run_hook("session_tips.py", home, "{}"))[1] for _ in range(3)]
    assert seen == [
        "Tipp (1. szint): Elso tipp",
        "Tipp (1. szint): Masodik tipp",
        "Tipp (1. szint): Elso tipp",
    ]
    state = read_state(home)
    assert state["tips_seen"] == 3
    assert state["kit_path"] == "C:\\Users\\fanni\\claude-kit"  # other keys preserved
    assert not (home / ".claude" / "kit-state.json.tmp").exists()


def test_session_tips_level2_pools_level1(home, tips):
    write_state(home, level=2, tips_seen=0)
    seen = [hook_context(run_hook("session_tips.py", home, "{}"))[1] for _ in range(4)]
    assert seen == [
        "Tipp (2. szint): Elso tipp",
        "Tipp (2. szint): Masodik tipp",
        "Tipp (2. szint): Kontroll tipp",
        "Tipp (2. szint): Elso tipp",
    ]


def test_session_tips_missing_state_is_level1(home):
    name, ctx = hook_context(run_hook("session_tips.py", home, "{}"))
    assert name == "SessionStart"
    assert ctx.startswith("Tipp (1. szint): ")
    assert len(ctx) > len("Tipp (1. szint): ")
    assert not (home / ".claude" / "kit-state.json").exists()  # hook never creates it


def test_session_tips_unwritable_state_still_prints(home, tips):
    (home / ".claude" / "kit-state.json").mkdir()
    proc = run_hook("session_tips.py", home, "{}")
    _, ctx = hook_context(proc)
    assert ctx.startswith("Tipp (1. szint): ")


def test_session_tips_corrupt_state_is_not_overwritten(home, tips):
    path = home / ".claude" / "kit-state.json"
    path.write_text("{not json", encoding="utf-8")
    _, ctx = hook_context(run_hook("session_tips.py", home, "{}"))
    assert ctx.startswith("Tipp (1. szint): ")
    assert path.read_text(encoding="utf-8") == "{not json"


@pytest.mark.parametrize(
    ("schedule", "today", "expected"),
    [
        (True, "2026-09-05", True),
        (True, "2026-09-07", True),
        (True, "2026-09-10", False),
        (False, "2026-09-05", False),
    ],
)
def test_session_tips_schedule_reminder(home, tips, schedule, today, expected):
    write_state(home, flags={"gmail": True, "nav": False, "schedule": schedule})
    _, ctx = hook_context(run_hook("session_tips.py", home, "{}", env={"KIT_TODAY": today}))
    assert ("Emlékeztető" in ctx) is expected
    assert ("/report-run" in ctx) is expected


def test_session_tips_example_file_shape():
    data = json.loads((HOOKS_DIR / "session_tips.example.json").read_text(encoding="utf-8"))
    assert set(data) == {"1", "2", "3"}
    for level, entries in data.items():
        assert len(entries) >= 2, level
        for tip in entries:
            assert isinstance(tip, str) and tip.strip()
            assert "\u2014" not in tip


def test_session_tips_builtin_fallback_when_no_tips():
    assert session_tips._tip_pool({}, 3) == [session_tips.BUILTIN_TIP]
    assert session_tips._tip_pool({"1": "not a list", "2": [""]}, 2) == [session_tips.BUILTIN_TIP]


# ---------------------------------------------------------- protect_delivery

SPEC_TEMPLATE = """\
report:
  id: rpt_{id}
  slug: {slug}
  title_hu: "Teszt riport"
  locked: {locked}
period:
  grain: month
output:
  file_pattern: "{{slug}}_{{period}}.xlsx"
  folder: not_protected_here
powerbi:
  enabled: true
  folder: {powerbi}
delivery:
  folder: {delivery}   # comment after value
  overwrite: same_version
"""


@pytest.fixture
def project(home):
    """Riportok with three real specs plus an _examples spec that must be ignored."""
    root = home / "Riportok"
    absolute = home / "delivered"
    absolute.mkdir()
    specs = {
        "havi": dict(id="1", locked="false", delivery="exports", powerbi="exports/powerbi"),
        "abs": dict(id="2", locked="false", delivery=f'"{absolute}"', powerbi=f"'{absolute}/pbi'"),
        "locked": dict(id="3", locked="true", delivery="exports_locked", powerbi="exports_locked"),
        "_examples/demo": dict(
            id="4",
            locked="true",
            delivery=str(home / "examples_out"),
            powerbi=str(home / "examples_out"),
        ),
    }
    for slug, values in specs.items():
        spec_dir = root / "reports" / slug
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.yaml").write_text(
            SPEC_TEMPLATE.format(slug=slug.split("/")[-1], **values), encoding="utf-8"
        )
    (root / "exports" / "powerbi").mkdir(parents=True)
    (root / "exports" / "havi_2026-08_v1.0.0.xlsx").write_bytes(b"xlsx")
    write_state(home, project_dir=str(root))
    return root


def protect(home, project, tool, tool_input, cwd=None):
    return run_hook("protect_delivery.py", home, pre_tool_use(tool, tool_input, cwd or project))


def assert_blocked(proc, *needles):
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert "Tiltott" in proc.stderr
    for needle in needles:
        assert needle in proc.stderr, proc.stderr


def assert_allowed(proc):
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "" and proc.stderr == ""


def test_write_into_delivery_folder_blocked(home, project):
    target = project / "exports" / "havi_2026-08_v1.0.0.xlsx"
    proc = protect(home, project, "Write", {"file_path": str(target), "content": "x"})
    assert_blocked(proc, str(target), "/report-run havi", "kézbesített")


def test_write_into_powerbi_folder_blocked(home, project):
    target = project / "exports" / "powerbi" / "fact_invoice.csv"
    assert_blocked(protect(home, project, "Write", {"file_path": str(target)}), "/report-run havi")


def test_write_into_absolute_delivery_folder_blocked(home, project):
    target = home / "delivered" / "abs_2026-08.xlsx"
    assert_blocked(protect(home, project, "Write", {"file_path": str(target)}), "/report-run abs")
    target = home / "delivered" / "pbi" / "dim_customer.csv"
    assert_blocked(protect(home, project, "Write", {"file_path": str(target)}), "/report-run abs")


def test_edit_of_locked_spec_blocked(home, project):
    target = project / "reports" / "locked" / "spec.yaml"
    proc = protect(
        home, project, "Edit", {"file_path": str(target), "old_string": "a", "new_string": "b"}
    )
    assert_blocked(proc, str(target), "/report-edit locked", "zárolt")


def test_multiedit_of_locked_spec_blocked(home, project):
    target = project / "reports" / "locked" / "spec.yaml"
    proc = protect(home, project, "MultiEdit", {"file_path": str(target), "edits": []})
    assert_blocked(proc, "/report-edit locked")


def test_edit_of_unlocked_spec_and_other_files_allowed(home, project):
    assert_allowed(
        protect(
            home, project, "Edit", {"file_path": str(project / "reports" / "havi" / "spec.yaml")}
        )
    )
    assert_allowed(
        protect(
            home, project, "Write", {"file_path": str(project / "reports" / "havi" / "build.py")}
        )
    )
    assert_allowed(
        protect(home, project, "Write", {"file_path": str(project / "exports_other" / "x.xlsx")})
    )


def test_examples_spec_is_ignored(home, project):
    target = home / "examples_out" / "demo.xlsx"
    assert_allowed(protect(home, project, "Write", {"file_path": str(target)}))
    spec = project / "reports" / "_examples" / "demo" / "spec.yaml"
    assert_allowed(protect(home, project, "Edit", {"file_path": str(spec)}))


def test_relative_file_path_resolves_against_cwd(home, project):
    assert_blocked(
        protect(home, project, "Write", {"file_path": "exports/x.xlsx"}, cwd=project),
        "/report-run havi",
    )
    assert_allowed(protect(home, project, "Write", {"file_path": "exports/x.xlsx"}, cwd=home))


def test_backslash_file_path_recognized(home, project):
    target = str(project / "exports" / "x.xlsx").replace("/", "\\")
    assert_blocked(protect(home, project, "Write", {"file_path": target}), "/report-run havi")


def test_read_and_other_tools_never_blocked(home, project):
    target = project / "exports" / "havi_2026-08_v1.0.0.xlsx"
    assert_allowed(protect(home, project, "Read", {"file_path": str(target)}))
    assert_allowed(protect(home, project, "Grep", {"pattern": "x", "path": str(target)}))


@pytest.mark.parametrize(
    ("command", "blocked"),
    [
        ("rm -rf {d}", True),
        ("rm -rf {d}/", True),
        ("Remove-Item '{dw}\\x.xlsx'", True),
        ('Remove-Item -Recurse -Force "{dw}"', True),
        ("mv {d}/a.xlsx {d}/b.xlsx", True),
        ("Move-Item {dw}\\a.xlsx C:\\tmp", True),
        ("del {dw}\\a.xlsx", True),
        ("echo hi > {d}/x.txt", True),
        ("echo hi >>{d}/x.txt", True),
        ("Get-Content a.csv | Out-File {dw}\\x.csv", True),
        ("Set-Content -Path {dw}\\x.csv -Value 1", True),
        ("Copy-Item a.xlsx {dw}\\a.xlsx -Force", True),
        ("ls {d}", False),
        ("ls -la '{dw}'", False),
        ("cat {d}/file.xlsx > /tmp/out", False),
        ("Get-ChildItem {dw}", False),
        ("Copy-Item {dw}\\a.xlsx C:\\tmp", False),
        ("rm -rf /somewhere/else", False),
        ("rm -rf {d}_other", False),
        ("python build.py --out {d}", False),
    ],
)
def test_bash_destructive_patterns(home, project, command, blocked):
    delivery = project / "exports"
    cmd = command.format(d=str(delivery), dw=str(delivery).replace("/", "\\"))
    proc = protect(home, project, "Bash", {"command": cmd})
    if blocked:
        assert_blocked(proc, "/report-run havi")
    else:
        assert_allowed(proc)


def test_bash_relative_path_from_project_cwd(home, project):
    assert_blocked(
        protect(home, project, "Bash", {"command": "rm -rf exports"}, cwd=project),
        "/report-run havi",
    )
    assert_blocked(
        protect(home, project, "Bash", {"command": "rm -rf ./exports/x.xlsx"}, cwd=project),
        "/report-run havi",
    )
    assert_allowed(protect(home, project, "Bash", {"command": "rm -rf exports"}, cwd=home))
    assert_allowed(protect(home, project, "Bash", {"command": "ls exports"}, cwd=project))


def test_bash_home_tokens_expand(home, project):
    rel = str((project / "exports").relative_to(home))
    for token in ("~", "$HOME", "${HOME}", "%USERPROFILE%", "$env:USERPROFILE"):
        proc = protect(home, project, "Bash", {"command": f"rm -rf {token}/{rel}"})
        assert_blocked(proc, "/report-run havi")


def test_bash_against_locked_spec(home, project):
    spec = project / "reports" / "locked" / "spec.yaml"
    assert_blocked(protect(home, project, "Bash", {"command": f"rm {spec}"}), "/report-edit locked")
    assert_allowed(protect(home, project, "Bash", {"command": f"cat {spec}"}))


def test_no_specs_means_no_protection(home):
    write_state(home, project_dir=str(home / "Riportok"))
    proc = protect(home, home / "Riportok", "Write", {"file_path": str(home / "Riportok" / "x")})
    assert_allowed(proc)


def test_missing_state_defaults_project_dir(home):
    root = home / "Riportok"
    (root / "reports" / "havi").mkdir(parents=True)
    (root / "reports" / "havi" / "spec.yaml").write_text(
        SPEC_TEMPLATE.format(
            slug="havi", id="9", locked="false", delivery="exports", powerbi="exports"
        ),
        encoding="utf-8",
    )
    proc = protect(home, root, "Write", {"file_path": str(root / "exports" / "x.xlsx")})
    assert_blocked(proc, "/report-run havi")


def test_malformed_stdin_fails_open_and_logs(home, project):
    proc = run_hook("protect_delivery.py", home, "{not json")
    assert proc.returncode == 0
    assert proc.stdout == "" and proc.stderr == ""
    assert "protect_delivery" in error_log(home)
    assert "malformed" in error_log(home)


@pytest.mark.parametrize(
    "raw",
    [
        r"C:\Users\Fanni\Riportok\exports\x.xlsx",
        "C:/Users/Fanni/Riportok/exports/x.xlsx",
        "/c/Users/Fanni/Riportok/exports/x.xlsx",
        "c:\\users\\fanni\\riportok\\exports\\x.xlsx",
        "  'C:\\Users\\Fanni\\Riportok\\exports\\x.xlsx'  ",
        r"C:\Users\Fanni\Riportok\reports\..\exports\.\x.xlsx",
    ],
)
def test_normalize_path_windows_forms(raw):
    assert protect_delivery.normalize_path(raw) == "c:/users/fanni/riportok/exports/x.xlsx"


def test_normalize_path_relative_to_fake_windows_project(monkeypatch):
    base = r"C:\Users\Fanni\Riportok"
    normalize = protect_delivery.normalize_path
    assert normalize("exports", base) == "c:/users/fanni/riportok/exports"
    assert normalize("exports\\powerbi\\", base) == "c:/users/fanni/riportok/exports/powerbi"
    assert normalize("/c/Users/Fanni/Other", base) == "c:/users/fanni/other"
    assert normalize("D:\\Share\\out", base) == "d:/share/out"
    monkeypatch.setenv("USERPROFILE", r"C:\Users\Fanni")
    assert normalize(r"%USERPROFILE%\Riportok\exports") == "c:/users/fanni/riportok/exports"
    assert normalize("~/Riportok") == normalize(str(Path.home() / "Riportok"))
    spec = protect_delivery._parse_spec(
        SPEC_TEMPLATE.format(slug="x", id="1", locked="TRUE", delivery="exports", powerbi="pbi")
    )
    assert spec == {"delivery": "exports", "powerbi": "pbi", "locked": True}
    assert normalize(spec["delivery"], base) == "c:/users/fanni/riportok/exports"


def test_parse_spec_handles_quotes_comments_and_nesting():
    text = (
        "report:\n  slug: x\n  locked: false\noutput:\n  executive:\n    folder: deep\n"
        'delivery:\n  folder: "C:\\Users\\F\\Out # not a comment"\n'
        "powerbi:\n  folder: 'pbi'  # comment\n"
    )
    found = protect_delivery._parse_spec(text)
    assert found == {
        "locked": False,
        "delivery": "C:\\Users\\F\\Out # not a comment",
        "powerbi": "pbi",
    }
    assert protect_delivery._parse_spec("") == {}
    assert protect_delivery._parse_spec("delivery:\n  folder:\n") == {"delivery": ""}


# ------------------------------------------------------------- memory_backup


@pytest.fixture
def memory(home):
    memdir = home / ".claude" / "projects" / "C--Users-fanni-Riportok" / "memory"
    memdir.mkdir(parents=True)
    (memdir / "MEMORY.md").write_text("# index\n", encoding="utf-8")
    (memdir / "notes.md").write_text("notes v1\n", encoding="utf-8")
    return memdir


def backup(home, file_path, tool="Write"):
    return run_hook("memory_backup.py", home, pre_tool_use(tool, {"file_path": file_path}, home))


def test_memory_backup_snapshots_before_overwrite(home, memory):
    proc = backup(home, str(memory / "MEMORY.md"))
    assert proc.returncode == 0 and proc.stdout == "" and proc.stderr == ""
    snaps = sorted((memory / "backups").glob("MEMORY.*.md"))
    assert len(snaps) == 1
    assert snaps[0].read_text(encoding="utf-8") == "# index\n"
    assert not list((memory / "backups").glob("*.bak"))

    proc = backup(home, str(memory / "notes.md"), tool="Edit")
    assert proc.returncode == 0
    baks = list((memory / "backups").glob("notes.md.*.bak"))
    assert len(baks) == 1 and baks[0].read_text(encoding="utf-8") == "notes v1\n"
    assert len(list((memory / "backups").glob("MEMORY.*.md"))) == 2


def test_memory_backup_accepts_backslash_path(home, memory):
    proc = backup(home, str(memory / "notes.md").replace("/", "\\"))
    assert proc.returncode == 0
    assert len(list((memory / "backups").glob("notes.md.*.bak"))) == 1


def test_memory_backup_ignores_non_memory_paths(home, memory):
    other = home / "Riportok" / "reports" / "havi" / "spec.yaml"
    proc = backup(home, str(other))
    assert proc.returncode == 0 and proc.stdout == "" and proc.stderr == ""
    assert not (memory / "backups").exists()
    foreign = home / "elsewhere" / ".claude" / "projects" / "x" / "memory"
    foreign.mkdir(parents=True)
    (foreign / "MEMORY.md").write_text("x", encoding="utf-8")
    assert backup(home, str(foreign / "MEMORY.md")).returncode == 0
    assert not (foreign / "backups").exists()
    assert error_log(home) == ""


def test_memory_backup_prunes_to_keep(home, memory):
    backups = memory / "backups"
    backups.mkdir()
    base = time.time() - 10_000
    for i in range(21):
        snap = backups / f"MEMORY.20260101T000000_{i:06d}Z.md"
        snap.write_text(str(i), encoding="utf-8")
        os.utime(snap, (base + i, base + i))
    (backups / "notes.md.20260101T000000_000000Z.bak").write_text("keep", encoding="utf-8")
    assert backup(home, str(memory / "MEMORY.md")).returncode == 0
    remaining = sorted(backups.glob("MEMORY.*.md"))
    assert len(remaining) == 20
    names = {p.name for p in remaining}
    assert "MEMORY.20260101T000000_000000Z.md" not in names
    assert "MEMORY.20260101T000000_000001Z.md" not in names
    assert "MEMORY.20260101T000000_000020Z.md" in names
    assert (backups / "notes.md.20260101T000000_000000Z.bak").exists()


def test_memory_backup_malformed_stdin_fails_open(home, memory):
    proc = run_hook("memory_backup.py", home, "{not json")
    assert proc.returncode == 0 and proc.stdout == "" and proc.stderr == ""
    assert "memory_backup" in error_log(home)
