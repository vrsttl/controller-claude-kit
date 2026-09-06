# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6"]
# ///
"""Runner for every report under reports/<slug>/ (Task Scheduler entry point).

    uv run scripts/run_reports.py --all --period previous_month
    uv run scripts/run_reports.py --slug havi_arbev_kintlev [--period 2026-08]
    uv run scripts/run_reports.py --list
    --riportok DIR overrides the project root (default: RIPORTOK_DIR or ~/Riportok)

Each build runs as a subprocess (`uv run build.py ...` when uv is on PATH, else
the current interpreter). --all continues after failures and exits 1 if any
report failed. Only pandas-free imports here, so `--list` stays fast.
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
    ap = argparse.ArgumentParser(description="Riportok futtatása")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true", help="minden aktív riport (abc sorrendben)")
    g.add_argument("--slug", help="egy riport")
    g.add_argument("--list", action="store_true", help="riportok táblázata")
    ap.add_argument("--period", help="időszak (pl. previous_month, 2026-08)")
    ap.add_argument("--riportok", help="Riportok mappa (tesztekhez)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
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

    specs = list_specs(root)
    if args.slug:
        specs = [p for p in specs if p.parent.name == args.slug]
        if not specs:
            print(f"nincs ilyen riport: {args.slug} ({root / 'reports'})")
            return 2
    else:
        specs = [p for p in specs if _read_spec_meta(p)["status"] == "active"]
        if not specs:
            print(f"nincs aktív riport itt: {root / 'reports'}")
            return 0

    extra = ["--dry-run"] if args.dry_run else []
    results = [run_one(p, args.period, root, extra) for p in specs]
    if args.json:
        print(
            json.dumps(
                [{k: v for k, v in r.items() if k not in ("stdout", "stderr")} for r in results],
                ensure_ascii=False,
            )
        )
    else:
        for r in results:
            r["outcome_hu"] = OUTCOME_HU.get(r["outcome"], r["outcome"])
        print(
            format_table(
                results,
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
    failed = [r for r in results if r["exit_code"] != 0]
    if not args.json:
        if failed:
            print(f"{len(failed)} riport sikertelen, {len(results) - len(failed)} sikeres")
        else:
            print(f"{len(results)} riport sikeres")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
