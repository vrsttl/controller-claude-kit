# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "xlsxwriter>=3.2", "openpyxl>=3.1", "pyyaml>=6"]
# ///
"""Riport build: spec.yaml -> Excel (+ Power BI CSV) -> ellenőrzés -> kézbesítés.

A /report-new ezt a fájlt másolja reports/<slug>/build.py néven. Minden logika a
scripts/ modulokban van; ez a fájl csak összefűzi a lépéseket.

Kilépési kódok: 0 kézbesítve vagy próbafuttatás rendben, 1 elutasítva vagy a
kézbesítés nem sikerült, 2 használati vagy spec hiba.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

SPEC_PATH = Path(__file__).resolve().parent / "spec.yaml"
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import kit_meta  # noqa: E402
import report_validate as rv  # noqa: E402
from report_engine import PeriodError, compute, load_frames, resolve_period  # noqa: E402
from report_excel import write_powerbi_csvs, write_workbook  # noqa: E402
from report_spec import SpecLoadError, load_spec, validate  # noqa: E402


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Riport build (spec.yaml alapján)")
    ap.add_argument("--period", help="previous_month | ÉÉÉÉ-HH | ÉÉÉÉ-Qn | ÉÉÉÉ-Whh | tól..ig")
    ap.add_argument("--out", help="kimeneti mappa (alapból .staging/ a spec mellett)")
    ap.add_argument("--db", help="SQLite adatbázis (alapból data/invoices.db)")
    ap.add_argument("--dry-run", action="store_true", help="_dryrun/ mappába ír, nem kézbesít")
    ap.add_argument("--no-deliver", action="store_true", help="a staging fájl marad")
    ap.add_argument("--powerbi", dest="powerbi", action="store_true", default=None)
    ap.add_argument("--no-powerbi", dest="powerbi", action="store_false")
    ap.add_argument("--run-date", help="ÉÉÉÉ-HH-NN (teszteléshez)")
    ap.add_argument("--json", action="store_true", help="gépi összefoglaló a kimeneten")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        spec = load_spec(SPEC_PATH)
    except SpecLoadError as exc:
        print(f"SPEC HIBA: {exc.message_hu}")
        return 2
    if errors := validate(spec):
        for e in errors:
            print(f"SPEC HIBA: {e.path}: {e.message_hu}")
        return 2
    run_date = date.fromisoformat(args.run_date) if args.run_date else None
    try:
        period = resolve_period(spec, run_date=run_date, override=args.period)
    except PeriodError as exc:
        print(f"IDŐSZAK HIBA: {exc.message_hu}")
        return 2
    db_path = Path(args.db) if args.db else kit_meta.default_db_path()
    if not db_path.exists():
        print(f"ADATBÁZIS HIBA: nem található: {db_path} (uv run scripts/szamlazz_sync.py init)")
        return 2
    sub = "_dryrun" if args.dry_run else ".staging"
    out_dir = Path(args.out) if args.out else SPEC_PATH.parent / sub
    out_dir.mkdir(parents=True, exist_ok=True)
    staging = out_dir / rv.output_filename(spec, period)

    conn = sqlite3.connect(str(db_path))
    frames = load_frames(conn, spec, period)
    result = compute(frames, spec, period)
    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    # first pass without V16 so the workbook carries the check table, second pass with it
    for wb_path in (None, staging):
        checks = rv.run_checks(conn, frames, result, spec, period, workbook_path=wb_path)
        run_info = rv.build_run_info(spec, period, frames, result, checks, run_ts=run_ts)
        write_workbook(result, spec, period, staging, run_info, frames=frames)
    powerbi_files: list[str] = []
    if args.powerbi if args.powerbi is not None else spec.powerbi.enabled:
        folder = out_dir / "powerbi" if args.dry_run else spec.resolve_path(spec.powerbi.folder)
        powerbi_files = [str(p) for p in write_powerbi_csvs(result, frames, spec, folder)]

    previous = rv.last_runlog_entry(spec, period.label)
    for line in rv.preview_lines(spec, period, frames, result, checks, previous):
        print(line)
    outcome, delivered, message = "dry_run", None, f"Próbafuttatás: {staging}"
    code = 1 if rv.blocking_failures(checks) else 0
    if not args.dry_run and not args.no_deliver:
        d = rv.deliver(staging, spec, period, checks, run_info)
        outcome, delivered, message, code = d.outcome, d.delivered_path, d.message_hu, d.exit_code
    elif args.no_deliver:
        outcome, message = "not_delivered", f"Nem kézbesítve, a fájl itt van: {staging}"
    print(message)
    if args.json:
        summary = {
            "slug": spec.report.slug,
            "period": period.label,
            "version": spec.report.version,
            "outcome": outcome,
            "outcome_hu": rv.OUTCOME_HU.get(outcome, outcome),
            "delivered_path": str(delivered) if delivered else None,
            "staging_path": str(staging),
            "checks": [c.to_dict() for c in checks],
            "row_counts": run_info["row_counts"],
            "totals": run_info["totals"],
            "previous_totals": (previous or {}).get("totals"),
            "powerbi_files": powerbi_files,
            "exit_code": code,
        }
        print(json.dumps(summary, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
