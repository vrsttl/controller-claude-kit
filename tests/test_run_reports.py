"""Tests for run_reports: --list and --all on a temporary Riportok tree."""

from __future__ import annotations

import json
import sys

import pytest
import run_reports as rr
from engine_fixture import make_project


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = make_project(tmp_path / "Riportok", ["havi_arbev_kintlev", "ugyfel_koncentracio_churn"])
    monkeypatch.setattr(rr.shutil, "which", lambda name: None)  # force sys.executable
    return root


def test_runner_command_prefers_uv_then_python(tmp_path, monkeypatch):
    monkeypatch.setattr(rr.shutil, "which", lambda name: "/usr/local/bin/uv")
    assert rr.runner_command(tmp_path / "build.py")[:2] == ["/usr/local/bin/uv", "run"]
    monkeypatch.setattr(rr.shutil, "which", lambda name: None)
    assert rr.runner_command(tmp_path / "build.py") == [sys.executable, str(tmp_path / "build.py")]


def test_list_shows_specs_and_last_run(project, capsys):
    log = project / "reports" / "havi_arbev_kintlev" / "runlog.jsonl"
    log.write_text(
        json.dumps(
            {
                "period": "2026-07",
                "run_ts": "2026-08-05 07:00",
                "outcome": "delivered",
                "delivered_path": "C:/x/havi_2026-07.xlsx",
            }
        )
        + "\n"
        + json.dumps(
            {
                "period": "2026-08",
                "run_ts": "2026-09-05 07:00",
                "outcome": "rejected",
                "delivered_path": "C:/x/_rejected/havi_FAILED.xlsx",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert rr.main(["--list", "--riportok", str(project)]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0].split()[:3] == ["slug", "cím", "verzió"]
    havi = next(line for line in lines if line.startswith("havi_arbev_kintlev"))
    assert (
        "Havi árbevétel és kintlévőség" in havi
        and "1.0.0" in havi
        and "active" in havi
        and "month" in havi
    )
    assert "2026-09-05 07:00" in havi and "elutasítva" in havi and "havi_FAILED.xlsx" in havi
    ugy = next(line for line in lines if line.startswith("ugyfel_koncentracio_churn"))
    assert "Ügyfél-koncentráció" in ugy and "2026-09-05" not in ugy
    rows = rr.list_rows(project)
    assert [r["slug"] for r in rows] == ["havi_arbev_kintlev", "ugyfel_koncentracio_churn"]
    assert (
        rows[0]["last_outcome"] == "rejected"
        and rows[1]["last_outcome"] == ""
        and rows[0]["has_build"]
    )
    assert rr.main(["--list", "--riportok", str(project), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["slug"] == "havi_arbev_kintlev"


def test_all_continues_after_failure_and_exits_1(project, capsys):
    bad = project / "reports" / "ugyfel_koncentracio_churn" / "spec.yaml"
    bad.write_text(
        bad.read_text(encoding="utf-8").replace("overwrite: same_version", "overwrite: sometimes"),
        encoding="utf-8",
    )
    rc = rr.main(["--all", "--period", "2026-08", "--riportok", str(project)])
    out = capsys.readouterr().out
    assert rc == 1
    havi = next(line for line in out.splitlines() if line.startswith("havi_arbev_kintlev"))
    ugy = next(line for line in out.splitlines() if line.startswith("ugyfel_koncentracio_churn"))
    assert (
        "kézbesítve" in havi
        and "2026-08" in havi
        and "havi_arbev_kintlev_2026-08_v1.0.0.xlsx" in havi
    )
    assert "hiba" in ugy and "SPEC HIBA" in ugy and "delivery.overwrite" in ugy
    assert "1 riport sikertelen, 1 sikeres" in out
    assert (project / "exports" / "havi_arbev_kintlev_2026-08_v1.0.0.xlsx").exists()
    assert (project / "reports" / "havi_arbev_kintlev" / "runlog.jsonl").exists()
    assert not (project / "reports" / "ugyfel_koncentracio_churn" / "runlog.jsonl").exists()


def test_slug_runs_one_and_reports_missing(project, capsys):
    rc = rr.main(
        [
            "--slug",
            "ugyfel_koncentracio_churn",
            "--period",
            "2026-08",
            "--riportok",
            str(project),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0 and payload[0]["outcome"] == "delivered" and payload[0]["exit_code"] == 0
    assert (
        project / "exports" / "powerbi" / "fact_measure.csv"
    ).exists()  # powerbi enabled in that spec
    assert rr.main(["--slug", "nincs_ilyen", "--riportok", str(project)]) == 2
    assert "nincs ilyen riport" in capsys.readouterr().out


def test_all_skips_inactive_specs(project, capsys):
    for slug in ("havi_arbev_kintlev", "ugyfel_koncentracio_churn"):
        p = project / "reports" / slug / "spec.yaml"
        p.write_text(
            p.read_text(encoding="utf-8").replace("status: active", "status: draft"),
            encoding="utf-8",
        )
    assert rr.main(["--all", "--riportok", str(project)]) == 0
    assert "nincs aktív riport" in capsys.readouterr().out


def test_dry_run_flag_passes_through(project, capsys):
    rc = rr.main(
        [
            "--slug",
            "havi_arbev_kintlev",
            "--period",
            "2026-08",
            "--riportok",
            str(project),
            "--dry-run",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0 and payload[0]["outcome"] == "dry_run"
    assert not (project / "exports").exists()
    assert (project / "reports" / "havi_arbev_kintlev" / "_dryrun").exists()
