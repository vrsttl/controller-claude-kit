# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6"]
# ///
"""Run one report under reports/<slug>/ by hand, or list every report.

    uv run scripts/run_reports.py --slug havi_arbev_kintlev [--period previous_month] [--dry-run]
    uv run scripts/run_reports.py --list [--json]
    --riportok DIR overrides the project root (default: RIPORTOK_DIR or ~/Riportok)

The build runs as a subprocess (`uv run build.py ...` when uv is on PATH, else
the current interpreter). Exit codes: 0 ok, 1 the build failed, 2 unknown slug
or the report is not `active` (draft and retired reports are refused, also with
`--dry-run`; a draft is dry-run via `build.py --dry-run` directly).
Only pandas-free imports here, so `--list` stays fast.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import kit_meta
import yaml

OUTCOME_HU = {
    "delivered": "kézbesítve",
    "rejected": "elutasítva",
    "pending": "függőben",
    "exists": "nem írható felül",
    "dry_run": "próbafuttatás",
    "not_delivered": "nem kézbesítve",
    "error": "hiba",
}


def riportok_root(override: str | None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    return kit_meta.riportok_dir()


def list_specs(root: Path) -> list[Path]:
    reports = root / "reports"
    if not reports.exists():
        return []
    return sorted(p for p in reports.glob("*/spec.yaml") if not p.parent.name.startswith("_"))


def _read_spec_meta(path: Path) -> dict:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {
            "slug": path.parent.name,
            "title_hu": "(hibás YAML)",
            "version": "",
            "status": "",
            "grain": "",
        }
    report = raw.get("report") or {}
    period = raw.get("period") or {}
    return {
        "slug": str(report.get("slug") or path.parent.name),
        "title_hu": str(report.get("title_hu") or ""),
        "version": str(report.get("version") or ""),
        "status": str(report.get("status") or ""),
        "grain": str(period.get("grain") or "month"),
    }


def _last_runlog(path: Path) -> dict | None:
    log = path.parent / "runlog.jsonl"
    if not log.exists():
        return None
    last = None
    for line in log.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            last = json.loads(line)
        except json.JSONDecodeError:
            continue
    return last


def list_rows(root: Path) -> list[dict]:
    rows = []
    for spec_path in list_specs(root):
        meta = _read_spec_meta(spec_path)
        last = _last_runlog(spec_path) or {}
        meta.update(
            {
                "last_run_ts": last.get("run_ts") or "",
                "last_outcome": last.get("outcome") or "",
                "last_outcome_hu": OUTCOME_HU.get(
                    last.get("outcome") or "", last.get("outcome") or ""
                ),
                "last_period": last.get("period") or "",
                "delivered_path": last.get("delivered_path") or "",
                "has_build": (spec_path.parent / "build.py").exists(),
            }
        )
        rows.append(meta)
    return rows


def format_table(rows: list[dict], columns: list[tuple[str, str]]) -> str:
    widths = [
        max(len(title), *(len(str(r.get(key, ""))) for r in rows)) if rows else len(title)
        for key, title in columns
    ]
    lines = ["  ".join(title.ljust(w) for (_, title), w in zip(columns, widths, strict=False))]
    lines.append("  ".join("-" * w for w in widths))
    for r in rows:
        lines.append(
            "  ".join(
                str(r.get(key, "")).ljust(w) for (key, _), w in zip(columns, widths, strict=False)
            )
        )
    return "\n".join(lines)


def runner_command(build_py: Path) -> list[str]:
    uv = shutil.which("uv")
    if uv:
        return [uv, "run", str(build_py)]
    return [sys.executable, str(build_py)]


def run_one(
    spec_path: Path, period: str | None, root: Path, extra: list[str] | None = None
) -> dict:
    build_py = spec_path.parent / "build.py"
    meta = _read_spec_meta(spec_path)
    if not build_py.exists():
        return {**meta, "outcome": "error", "exit_code": 2, "message": f"hiányzik: {build_py}"}
    cmd = runner_command(build_py) + ["--json"]
    if period:
        cmd += ["--period", period]
    cmd += extra or []
    env = dict(os.environ, RIPORTOK_DIR=str(root))
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(spec_path.parent))
    summary: dict = {}
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                summary = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    tail = (proc.stdout.strip().splitlines() or [""])[-1] if not summary else ""
    err_tail = (proc.stderr.strip().splitlines() or [""])[-1]
    return {
        **meta,
        "outcome": summary.get("outcome") or ("error" if proc.returncode else "delivered"),
        "exit_code": proc.returncode,
        "period": summary.get("period") or period or "",
        "delivered_path": summary.get("delivered_path") or "",
        "message": tail or err_tail,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Egy riport futtatása kézzel, vagy a riportok listázása"
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--slug", help="a futtatandó riport (a reports/ alatti mappa neve)")
    g.add_argument("--list", action="store_true", help="riportok táblázata")
    ap.add_argument("--period", help="időszak (pl. previous_month, 2026-08)")
    ap.add_argument("--riportok", help="Riportok mappa (tesztekhez)")
    ap.add_argument("--dry-run", action="store_true", help="próbafuttatás, nem kézbesít")
    ap.add_argument("--json", action="store_true", help="gépi kimenet")
    args = ap.parse_args(argv)
    root = riportok_root(args.riportok)

    if args.list:
        rows = list_rows(root)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False))
        else:
            print(
                format_table(
                    rows,
                    [
                        ("slug", "slug"),
                        ("title_hu", "cím"),
                        ("version", "verzió"),
                        ("status", "státusz"),
                        ("grain", "időszak"),
                        ("last_run_ts", "utolsó futás"),
                        ("last_outcome_hu", "eredmény"),
                        ("delivered_path", "kézbesített fájl"),
                    ],
                )
            )
        return 0

    specs = [p for p in list_specs(root) if p.parent.name == args.slug]
    if not specs:
        print(f"nincs ilyen riport: {args.slug} ({root / 'reports'})")
        return 2

    status = _read_spec_meta(specs[0])["status"]
    if status != "active":
        print(
            f"A(z) {args.slug} riport állapota {status}, csak active riport futtatható. "
            "Aktiváld a /report-new vagy /report-edit paranccsal.",
            file=sys.stderr,
        )
        if args.json:
            print(
                json.dumps(
                    {"slug": args.slug, "outcome": "not_active", "status": status, "exit_code": 2},
                    ensure_ascii=False,
                )
            )
        return 2

    extra = ["--dry-run"] if args.dry_run else []
    result = run_one(specs[0], args.period, root, extra)
    if args.json:
        print(
            json.dumps(
                [{k: v for k, v in result.items() if k not in ("stdout", "stderr")}],
                ensure_ascii=False,
            )
        )
    else:
        result["outcome_hu"] = OUTCOME_HU.get(result["outcome"], result["outcome"])
        print(
            format_table(
                [result],
                [
                    ("slug", "slug"),
                    ("period", "időszak"),
                    ("outcome_hu", "eredmény"),
                    ("exit_code", "kód"),
                    ("delivered_path", "fájl"),
                    ("message", "üzenet"),
                ],
            )
        )
        print("a riport sikertelen" if result["exit_code"] != 0 else "a riport sikeres")
    return 1 if result["exit_code"] != 0 else 0


if __name__ == "__main__":
    sys.exit(main())
