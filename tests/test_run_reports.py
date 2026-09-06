"""Tests for run_reports: --list and --slug on a temporary Riportok tree."""

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


def test_slug_failed_build_exits_1(project, capsys):
    bad = project / "reports" / "ugyfel_koncentracio_churn" / "spec.yaml"
    bad.write_text(
        bad.read_text(encoding="utf-8").replace("overwrite: same_version", "overwrite: sometimes"),
        encoding="utf-8",
    )
    rc = rr.main(
        ["--slug", "ugyfel_koncentracio_churn", "--period", "2026-08", "--riportok", str(project)]
    )
    out = capsys.readouterr().out
    assert rc == 1
    ugy = next(line for line in out.splitlines() if line.startswith("ugyfel_koncentracio_churn"))
    assert "hiba" in ugy and "SPEC HIBA" in ugy and "delivery.overwrite" in ugy
    assert "a riport sikertelen" in out
    assert not (project / "reports" / "ugyfel_koncentracio_churn" / "runlog.jsonl").exists()


def test_all_flag_is_rejected(project, capsys):
    with pytest.raises(SystemExit) as excinfo:
        rr.main(["--all", "--riportok", str(project)])
    assert excinfo.value.code == 2
    assert "--slug" in capsys.readouterr().err  # the required group, not a batch mode
    with pytest.raises(SystemExit) as excinfo:
        rr.main(["--slug", "havi_arbev_kintlev", "--all", "--riportok", str(project)])
    assert excinfo.value.code == 2
    assert "--all" in capsys.readouterr().err
    assert not (project / "exports").exists()


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


def _set_status(project, slug: str, status: str) -> None:
    spec = project / "reports" / slug / "spec.yaml"
    spec.write_text(
        spec.read_text(encoding="utf-8").replace("status: active", f"status: {status}", 1),
        encoding="utf-8",
    )


def test_draft_slug_is_refused(project, capsys):
    _set_status(project, "havi_arbev_kintlev", "draft")
    rc = rr.main(
        ["--slug", "havi_arbev_kintlev", "--period", "2026-08", "--riportok", str(project)]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert (
        "A(z) havi_arbev_kintlev riport állapota draft, csak active riport futtatható."
        in captured.err
    )
    assert "/report-new vagy /report-edit" in captured.err
    assert captured.out == ""
    assert not (project / "exports").exists()
    assert not (project / "reports" / "havi_arbev_kintlev" / "runlog.jsonl").exists()
    # --dry-run of a draft is refused too (build.py --dry-run is the path for drafts)
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
    captured = capsys.readouterr()
    assert rc == 2
    assert json.loads(captured.out) == {
        "slug": "havi_arbev_kintlev",
        "outcome": "not_active",
        "status": "draft",
        "exit_code": 2,
    }
    assert "állapota draft" in captured.err
    assert not (project / "reports" / "havi_arbev_kintlev" / "_dryrun").exists()


def test_retired_slug_is_refused_but_listed(project, capsys):
    _set_status(project, "ugyfel_koncentracio_churn", "retired")
    rc = rr.main(["--slug", "ugyfel_koncentracio_churn", "--riportok", str(project), "--json"])
    captured = capsys.readouterr()
    assert rc == 2
    assert json.loads(captured.out)["outcome"] == "not_active"
    assert json.loads(captured.out)["status"] == "retired"
    assert "állapota retired" in captured.err
    assert not (project / "exports").exists()
    assert rr.main(["--list", "--riportok", str(project), "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert {r["slug"]: r["status"] for r in rows} == {
        "havi_arbev_kintlev": "active",
        "ugyfel_koncentracio_churn": "retired",
    }
