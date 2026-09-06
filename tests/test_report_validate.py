"""Tests for report_validate: V01..V16 on the fixture, delivery modes, runlog."""

from __future__ import annotations

import copy
import json
import shutil
import sqlite3
from datetime import date
from pathlib import Path

import pytest
import report_engine as re_
import report_spec as rs
import report_validate as rv
from engine_fixture import EXAMPLES_DIR, PLANTED, RUN_DATE, make_engine_db, set_afalista_delta
from report_excel import write_workbook

CLEAN_EXPECTED = {
    "V01": "ok",
    "V02": "ok",
    "V03": "skipped",
    "V04": "ok",
    "V05": "ok",
    "V06": "skipped",
    "V07": "warn",
    "V08": "ok",
    "V09": "ok",
    "V10": "ok",
    "V11": "ok",
    "V12": "ok",
    "V13": "ok",
    "V14": "ok",
    "V15": "ok",
    "V16": "ok",
}


class Build:
    """One spec + fixture DB in a tmp project. `run()` recomputes after DB edits."""

    def __init__(self, root: Path, slug: str = "havi_arbev_kintlev", raw_override=None):
        self.root = root
        spec_dir = root / "reports" / slug
        spec_dir.mkdir(parents=True, exist_ok=True)
        raw = rs.load_spec(EXAMPLES_DIR / slug / "spec.yaml").raw
        raw = copy.deepcopy(raw)
        if raw_override:
            raw_override(raw)
        self.spec_path = spec_dir / "spec.yaml"
        self.spec_path.write_text(rs.dump_yaml(raw), encoding="utf-8")
        self.spec = rs.load_spec(self.spec_path)
        assert rs.validate(self.spec) == []
        self.db = root / "data" / "invoices.db"
        self.db.parent.mkdir(exist_ok=True)
        self.db.unlink(missing_ok=True)
        make_engine_db(self.db).close()
        self.conn = sqlite3.connect(self.db)
        self.period = re_.resolve_period(self.spec, run_date=RUN_DATE)

    def run(
        self, run_date: date | None = None, override: str | None = None, workbook: bool = False
    ):
        if run_date or override:
            self.period = re_.resolve_period(
                self.spec, run_date=run_date or RUN_DATE, override=override
            )
        self.frames = re_.load_frames(self.conn, self.spec, self.period)
        self.result = re_.compute(self.frames, self.spec, self.period)
        path = None
        if workbook:
            checks = rv.run_checks(self.conn, self.frames, self.result, self.spec, self.period)
            info = rv.build_run_info(
                self.spec, self.period, self.frames, self.result, checks, run_ts="2026-09-03 08:12"
            )
            path = self.spec_path.parent / ".staging" / rv.output_filename(self.spec, self.period)
            write_workbook(self.result, self.spec, self.period, path, info, frames=self.frames)
        self.checks = rv.run_checks(
            self.conn, self.frames, self.result, self.spec, self.period, workbook_path=path
        )
        self.staging = path
        return {c.id: c for c in self.checks}


@pytest.fixture
def build(tmp_path) -> Build:
    return Build(tmp_path)


def test_clean_fixture_statuses(build):
    checks = build.run(workbook=True)
    assert [c.id for c in build.checks] == list(rs.CHECK_IDS)
    assert {cid: c.status for cid, c in checks.items()} == CLEAN_EXPECTED
    assert {cid for cid, c in checks.items() if c.blocking} == {
        "V01",
        "V04",
        "V05",
        "V11",
        "V15",
        "V16",
    }
    assert all(c.title_hu and c.detail_hu for c in checks.values())
    assert rv.blocking_failures(build.checks) == []
    delta_doc = PLANTED["afalista_delta"].number
    assert delta_doc in checks["V07"].detail_hu and "ÁFA +1" in checks["V07"].detail_hu
    without_wb = rv.run_checks(build.conn, build.frames, build.result, build.spec, build.period)
    assert without_wb[-1].id == "V16" and without_wb[-1].status == "skipped"


def test_afalista_delta_toggle(build):
    set_afalista_delta(build.conn, False)
    assert build.run()["V07"].status == "ok"
    set_afalista_delta(build.conn, True)
    assert build.run()["V07"].status == "warn"


def test_v05_injected_delta_fails_and_rejects(build):
    doc = PLANTED["afalista_delta"].number
    build.conn.execute(
        "UPDATE invoice_vat SET vat = vat + 1 WHERE invoice_number = ? AND vat_rate = '27'", (doc,)
    )
    build.conn.commit()
    checks = build.run(workbook=True)
    assert (
        checks["V05"].status == "fail" and checks["V05"].blocking and doc in checks["V05"].detail_hu
    )
    assert checks["V04"].status == "ok"
    info = rv.build_run_info(
        build.spec,
        build.period,
        build.frames,
        build.result,
        build.checks,
        run_ts="2026-09-03 08:12",
    )
    outcome = rv.deliver(build.staging, build.spec, build.period, build.checks, info)
    assert outcome.exit_code == 1 and outcome.outcome == "rejected"
    rejected = (
        build.root / "exports" / "_rejected" / "havi_arbev_kintlev_2026-08_v1.0.0_FAILED.xlsx"
    )
    assert outcome.delivered_path == rejected and rejected.exists() and not build.staging.exists()
    assert "ELUTASÍTVA" in outcome.message_hu and "V05" in outcome.message_hu
    assert not (build.root / "exports" / "havi_arbev_kintlev_2026-08_v1.0.0.xlsx").exists()
    entries = rv.read_runlog(rv.runlog_path(build.spec))
    assert (
        len(entries) == 1
        and entries[0]["outcome"] == "rejected"
        and entries[0]["delivered_path"] == str(rejected)
    )
    assert entries[0]["checks"][4]["id"] == "V05" and entries[0]["checks"][4]["status"] == "fail"


def test_v04_line_delta_fails(build):
    doc = PLANTED["afalista_delta"].number
    build.conn.execute(
        "UPDATE invoice_line SET net = net + 1.5 WHERE invoice_number = ? AND line_no = 1", (doc,)
    )
    build.conn.commit()
    checks = build.run()
    assert checks["V04"].status == "fail" and doc in checks["V04"].detail_hu
    assert checks["V05"].status == "ok"


def test_v04_tolerance_from_spec(tmp_path):
    def loosen(raw):
        raw["validation"]["checks"] = [
            {"id": "V04", "tolerance": 5, "severity": "warn", "blocks_delivery": False}
        ]

    b = Build(tmp_path, raw_override=loosen)
    doc = PLANTED["afalista_delta"].number
    b.conn.execute(
        "UPDATE invoice_line SET net = net + 1.5 WHERE invoice_number = ? AND line_no = 1", (doc,)
    )
    b.conn.commit()
    checks = b.run()
    assert checks["V04"].status == "ok"
    b.conn.execute(
        "UPDATE invoice_line SET net = net + 10 WHERE invoice_number = ? AND line_no = 1", (doc,)
    )
    b.conn.commit()
    checks = b.run()
    assert checks["V04"].status == "warn" and checks["V04"].blocking is False


def test_v02_freshness(build):
    assert build.run(run_date=date(2026, 9, 5))["V02"].status == "ok"  # 3 days old
    c = build.run(run_date=date(2026, 9, 6))["V02"]
    assert c.status == "fail" and "napos" in c.detail_hu and not c.blocking
    c = build.run(run_date=RUN_DATE, override="2026-07")["V02"]
    assert c.status == "fail" and "2026-07" in c.detail_hu  # only a failed sync covers July
    build.conn.execute("DELETE FROM sync_log")
    build.conn.commit()
    assert "nincs sikeres szinkron" in build.run(override="2026-08")["V02"].detail_hu


def test_v03_and_v06_with_nav_required(tmp_path):
    def nav(raw):
        raw["sources"]["nav_digest"] = {"required": True}

    b = Build(tmp_path, raw_override=nav)
    checks = b.run()
    assert checks["V02"].status == "fail" and "nav_digest" in checks["V02"].detail_hu
    assert checks["V03"].status == "fail" and "NAV digest: 0" in checks["V03"].detail_hu
    assert (
        checks["V06"].status == "warn" and PLANTED["fx_deviation"].number in checks["V06"].detail_hu
    )
    for num in b.frames.invoice[b.frames.invoice["period_month"] == "2026-08"]["invoice_number"]:
        b.conn.execute(
            "INSERT INTO raw_documents (source, doc_key, fetched_at, source_hash, body) VALUES "
            "('nav_digest', ?, '2026-09-02', ?, X'00')",
            (num, num),
        )
    b.conn.commit()
    assert b.run()["V03"].status == "ok"


def test_v08_status_mismatch(build):
    doc = PLANTED["afalista_delta"].number
    build.conn.execute(
        "UPDATE staging_fokonyvi SET pay_status_raw = 'Nem fizetve' WHERE invoice_number = ?",
        (doc,),
    )
    build.conn.commit()
    c = build.run()["V08"]
    assert c.status == "warn" and doc in c.detail_hu
    assert build.run(override="2026-07")["V08"].status == "skipped"


def test_v09_missing_customer(build):
    build.conn.execute("DELETE FROM customer WHERE customer_key = 'C12'")
    build.conn.commit()
    c = build.run()["V09"]
    assert c.status == "fail" and "SZ-" in c.detail_hu


def test_v10_closed_period_stability(build):
    build.run()
    info = rv.build_run_info(
        build.spec, build.period, build.frames, build.result, build.checks, run_ts="x"
    )
    info["totals"]["rev_net"] -= 1000
    rv.append_runlog(build.spec, build.period, info, "delivered", None)
    c = build.run()["V10"]
    assert c.status == "warn" and "rev_net" in c.detail_hu
    info = rv.build_run_info(
        build.spec, build.period, build.frames, build.result, build.checks, run_ts="y"
    )
    rv.append_runlog(build.spec, build.period, info, "delivered", None)
    assert build.run()["V10"].status == "ok"
    assert rv.last_runlog_entry(build.spec, "2026-08")["run_ts"] == "y"
    assert rv.last_runlog_entry(build.spec, "2026-01") is None


def test_v11_chain_integrity(build):
    build.conn.execute(
        "INSERT INTO invoice (invoice_number, doc_type, chain_root, modification_index, "
        "issue_date, customer_key, net_amount, vat_amount, gross_amount, net_huf, vat_huf, "
        "gross_huf, pay_status, period_kelt) "
        "VALUES ('SZ-2026-9999', 'storno', 'SZ-2026-0000', 1, '2026-08-30', 'C01', -1, 0, -1, -1, "
        "0, -1, 'void', '2026-08')"
    )
    build.conn.commit()
    c = build.run()["V11"]
    assert c.status == "fail" and c.blocking and "SZ-2026-9999" in c.detail_hu


def test_v12_fx_sanity(build):
    doc = PLANTED["fx_deviation"].number
    build.conn.execute(
        "UPDATE invoice SET fx_rate_invoice = 3955.0 WHERE invoice_number = ?", (doc,)
    )
    build.conn.commit()
    c = build.run()["V12"]
    assert c.status == "warn" and doc in c.detail_hu
    assert build.run(override="2026-08-01..2026-08-01")["V12"].status == "skipped"


def test_v13_duplicates(build):
    doc = PLANTED["afalista_delta"].number
    row = build.conn.execute(
        "SELECT customer_key, gross_huf, issue_date FROM invoice WHERE invoice_number = ?", (doc,)
    ).fetchone()
    build.conn.execute(
        "INSERT INTO invoice (invoice_number, doc_type, chain_root, issue_date, customer_key, "
        "net_amount, vat_amount, gross_amount, net_huf, vat_huf, gross_huf, pay_status, "
        "period_kelt) "
        "VALUES ('SZ-2026-9998', 'invoice', 'SZ-2026-9998', ?, ?, 1, 0, ?, 1, 0, ?, 'unpaid', "
        "'2026-08')",
        (row[2], row[0], row[1], row[1]),
    )
    build.conn.commit()
    c = build.run()["V13"]
    assert c.status == "warn" and doc in c.detail_hu and "SZ-2026-9998" in c.detail_hu


def test_v14_min_rows(tmp_path):
    b = Build(tmp_path, raw_override=lambda r: r["validation"].__setitem__("min_rows", 1000))
    c = b.run()["V14"]
    assert c.status == "fail" and "minimum 1000" in c.detail_hu


def test_v15_tie_out_breaks_on_vat_delta(build):
    doc = PLANTED["afalista_delta"].number
    build.conn.execute(
        "UPDATE invoice_vat SET net_huf = net_huf + 5 WHERE invoice_number = ? AND vat_rate = '27'",
        (doc,),
    )
    build.conn.commit()
    c = build.run()["V15"]
    assert c.status == "fail" and c.blocking


def test_v16_output_integrity(build, tmp_path):
    checks = build.run(workbook=True)
    assert checks["V16"].status == "ok"
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(b"not a workbook")
    c = rv.check_output(build.spec, bad)
    assert c.status == "fail" and "nem nyitható" in c.detail_hu
    raw = copy.deepcopy(build.spec.raw)
    raw["output"]["sheets"].append("payment")
    other = rs.spec_from_dict(raw, build.spec.path)
    c = rv.check_output(other, build.staging)
    assert (
        c.status == "fail"
        and "Kifizetések" in c.detail_hu
        and "tbl_havi_arbev_kintlev_payment" in c.detail_hu
    )


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


def deliver_ok(b: Build, override_mode: str | None = None, keep: int | None = None):
    if override_mode or keep:
        raw = copy.deepcopy(b.spec.raw)
        if override_mode:
            raw["delivery"]["overwrite"] = override_mode
        if keep:
            raw["delivery"]["keep_n_versions"] = keep
        b.spec_path.write_text(rs.dump_yaml(raw), encoding="utf-8")
        b.spec = rs.load_spec(b.spec_path)
    b.run(workbook=True)
    info = rv.build_run_info(
        b.spec, b.period, b.frames, b.result, b.checks, run_ts="2026-09-03 08:12"
    )
    return rv.deliver(b.staging, b.spec, b.period, b.checks, info)


def test_deliver_clean_and_runlog(build):
    out = deliver_ok(build)
    target = build.root / "exports" / "havi_arbev_kintlev_2026-08_v1.0.0.xlsx"
    assert (
        out.exit_code == 0
        and out.outcome == "delivered"
        and out.delivered_path == target
        and target.exists()
    )
    assert "Kézbesítve" in out.message_hu and not build.staging.exists()
    log = rv.runlog_path(build.spec)
    assert log == build.spec_path.parent / "runlog.jsonl"
    entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 1
    e = entries[0]
    assert (
        e["period"] == "2026-08"
        and e["outcome"] == "delivered"
        and e["delivered_path"] == str(target)
    )
    assert e["spec_version"] == "1.0.0" and e["kit_version"] and len(e["spec_hash"]) == 64
    assert e["row_counts"]["invoice"] > 0 and e["totals"]["inv_count"] == 28
    assert [c["id"] for c in e["checks"]] == list(rs.CHECK_IDS)
    out2 = deliver_ok(build)
    assert out2.exit_code == 0  # same_version overwrites the same version
    assert len(rv.read_runlog(log)) == 2


def test_deliver_overwrite_never(build):
    assert deliver_ok(build).exit_code == 0
    out = deliver_ok(build, override_mode="never")
    assert out.exit_code == 1 and out.outcome == "exists" and "never" in out.message_hu
    assert build.staging.exists()
    assert rv.read_runlog(rv.runlog_path(build.spec))[-1]["outcome"] == "exists"


def test_deliver_same_version_keeps_other_versions(build):
    raw = copy.deepcopy(build.spec.raw)
    raw["output"]["file_pattern"] = "{slug}_{period}.xlsx"
    build.spec_path.write_text(rs.dump_yaml(raw), encoding="utf-8")
    build.spec = rs.load_spec(build.spec_path)
    assert deliver_ok(build).exit_code == 0
    plain = build.root / "exports" / "havi_arbev_kintlev_2026-08.xlsx"
    assert plain.exists()
    out = deliver_ok(build)
    assert (
        out.exit_code == 0
        and out.delivered_path == build.root / "exports" / "havi_arbev_kintlev_2026-08_v1.0.0.xlsx"
    )
    assert plain.exists() and out.delivered_path.exists()
    out = deliver_ok(build, override_mode="always")
    assert out.exit_code == 0 and out.delivered_path == plain


def test_keep_n_versions_pruning(build):
    exports = build.root / "exports"
    exports.mkdir()
    (exports / "_rejected").mkdir()
    (exports / "_rejected" / "havi_arbev_kintlev_2026-01_v1.0.0_FAILED.xlsx").write_bytes(b"x")
    (exports / "masik_riport_2026-05_v1.0.0.xlsx").write_bytes(b"x")
    import os
    import time

    for i, month in enumerate(["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"]):
        p = exports / f"havi_arbev_kintlev_{month}_v1.0.0.xlsx"
        p.write_bytes(b"x")
        ts = time.time() - (10 - i) * 86400
        os.utime(p, (ts, ts))
    out = deliver_ok(build, keep=3)
    assert out.exit_code == 0 and "törölt régi verziók" in out.message_hu
    names = sorted(p.name for p in exports.glob("havi_arbev_kintlev_*.xlsx"))
    assert names == [
        "havi_arbev_kintlev_2026-04_v1.0.0.xlsx",
        "havi_arbev_kintlev_2026-05_v1.0.0.xlsx",
        "havi_arbev_kintlev_2026-08_v1.0.0.xlsx",
    ]
    assert (exports / "masik_riport_2026-05_v1.0.0.xlsx").exists()
    assert (exports / "_rejected" / "havi_arbev_kintlev_2026-01_v1.0.0_FAILED.xlsx").exists()


def test_permission_error_writes_pending(build, monkeypatch):
    build.run(workbook=True)
    info = rv.build_run_info(
        build.spec, build.period, build.frames, build.result, build.checks, run_ts="x"
    )
    real_move = shutil.move

    def locked(src, dst):
        if "_rejected" not in str(dst):
            raise PermissionError("locked by Excel")
        return real_move(src, dst)

    monkeypatch.setattr(rv.shutil, "move", locked)
    out = rv.deliver(build.staging, build.spec, build.period, build.checks, info)
    pending = build.root / "exports" / "havi_arbev_kintlev_2026-08_v1.0.0.pending.xlsx"
    assert out.exit_code == 1 and out.outcome == "pending" and out.delivered_path == pending
    assert pending.exists() and pending.name in out.message_hu and "zárolva" in out.message_hu
    assert rv.read_runlog(rv.runlog_path(build.spec))[-1]["outcome"] == "pending"


def test_output_filename_tokens(build):
    assert rv.output_filename(build.spec, build.period) == "havi_arbev_kintlev_2026-08_v1.0.0.xlsx"
    raw = copy.deepcopy(build.spec.raw)
    raw["output"]["file_pattern"] = "{slug}_{run_date}.xlsx"
    spec = rs.spec_from_dict(raw, build.spec.path)
    assert rv.output_filename(spec, build.period) == "havi_arbev_kintlev_2026-09-03.xlsx"


def test_preview_lines_are_hungarian(build):
    build.run()
    lines = rv.preview_lines(
        build.spec, build.period, build.frames, build.result, build.checks, None
    )
    text = "\n".join(lines)
    assert "Nettó árbevétel" in text and "Kintlévőség" in text and "Előző futtatás: nincs" in text
    assert "V07 [FIGY]" in text and "blokkoló hiba" in text
    prev = {"run_ts": "2026-08-03 07:00", "totals": {"rev_net": 1.0, "inv_count": 1}}
    lines = rv.preview_lines(
        build.spec, build.period, build.frames, build.result, build.checks, prev
    )
    assert any("Előző futtatás (2026-08-03 07:00)" in line and "eltérés" in line for line in lines)


def test_spec_project_root_and_paths(build):
    assert build.spec.project_root == build.root
    assert build.spec.resolve_path("exports") == build.root / "exports"
    assert build.spec.resolve_path("/abs/path") == Path("/abs/path")
