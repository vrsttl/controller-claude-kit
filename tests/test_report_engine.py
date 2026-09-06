"""Tests for report_engine: periods, frames, measures (SQL-verified), exceptions, thresholds."""

from __future__ import annotations

import copy
import importlib.util
import os
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
import report_engine as re_
import report_spec as rs
import yaml
from engine_fixture import AS_OF, EXAMPLES_DIR, PLANTED, RUN_DATE, make_engine_db

P_START, P_END = "2026-08-01", "2026-08-31"
DOC_FILTER = "doc_type IN ('invoice','modifier','storno')"


@pytest.fixture(scope="module")
def conn() -> sqlite3.Connection:
    return make_engine_db(":memory:")


@pytest.fixture(scope="module")
def base_raw() -> dict:
    return yaml.safe_load(
        (EXAMPLES_DIR / "havi_arbev_kintlev" / "spec.yaml").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="module")
def spec(base_raw) -> rs.Spec:
    return rs.spec_from_dict(base_raw)


def full_spec(base_raw: dict, **overrides) -> rs.Spec:
    raw = copy.deepcopy(base_raw)
    raw["dimensions"] = list(rs.DIMENSIONS)
    raw["measures"] = [
        {"id": mid, "params": {"n": 5}} if mid == "top_n_share" else {"id": mid}
        for mid in re_.MEASURES
    ]
    raw["thresholds"] = {}
    raw["output"]["executive"]["variance_rows"] = ["rev_net"]
    for k, v in overrides.items():
        node = raw
        parts = k.split(".")
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = v
    spec = rs.spec_from_dict(raw)
    assert rs.validate(spec) == [], rs.validate(spec)
    return spec


@pytest.fixture(scope="module")
def period(spec) -> re_.Period:
    return re_.resolve_period(spec, run_date=RUN_DATE)


@pytest.fixture(scope="module")
def full(conn, base_raw, period):
    spec = full_spec(base_raw)
    frames = re_.load_frames(conn, spec, period)
    return spec, frames, re_.compute(frames, spec, period)


def q1(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()[0]


# ---------------------------------------------------------------------------
# Period resolution
# ---------------------------------------------------------------------------

PERIOD_CASES = [
    # (period section, run_date, override, expected)
    (
        {"grain": "month", "offset": "previous_full_month"},
        date(2026, 9, 3),
        None,
        dict(
            start=date(2026, 8, 1),
            end=date(2026, 8, 31),
            label="2026-08",
            prior_label="2026-07",
            py_label="2025-08",
            ytd_start=date(2026, 1, 1),
        ),
    ),
    (
        {"grain": "month", "offset": "current_month_to_date"},
        date(2026, 9, 6),
        None,
        dict(
            start=date(2026, 9, 1),
            end=date(2026, 9, 6),
            to_date=True,
            prior_start=date(2026, 8, 1),
            prior_end=date(2026, 8, 6),
        ),
    ),
    (
        {"grain": "quarter", "offset": "previous_full_quarter"},
        date(2026, 9, 3),
        None,
        dict(
            start=date(2026, 4, 1),
            end=date(2026, 6, 30),
            label="2026-Q2",
            prior_label="2026-Q1",
            prior_start=date(2026, 1, 1),
            py_label="2025-Q2",
        ),
    ),
    (
        {"grain": "quarter", "offset": "previous_full_quarter", "fiscal_year_start_month": 4},
        date(2026, 9, 3),
        None,
        dict(
            start=date(2026, 4, 1),
            end=date(2026, 6, 30),
            label="2026-Q1",
            ytd_start=date(2026, 4, 1),
        ),
    ),
    (
        {"grain": "quarter", "offset": "previous_full_quarter", "fiscal_year_start_month": 4},
        date(2026, 5, 10),
        None,
        dict(
            start=date(2026, 1, 1),
            end=date(2026, 3, 31),
            label="2025-Q4",
            ytd_start=date(2025, 4, 1),
        ),
    ),
    (
        {"grain": "quarter", "offset": "previous_full_month"},
        date(2026, 9, 3),
        None,
        dict(start=date(2026, 7, 1), end=date(2026, 8, 31), label="2026-Q3"),
    ),
    (
        {"grain": "ytd", "offset": "previous_full_month"},
        date(2026, 9, 3),
        None,
        dict(
            start=date(2026, 1, 1),
            end=date(2026, 8, 31),
            label="2026-YTD08",
            prior_start=date(2025, 1, 1),
            prior_end=date(2025, 8, 31),
        ),
    ),
    (
        {"grain": "ytd", "offset": "previous_full_month", "fiscal_year_start_month": 4},
        date(2026, 9, 3),
        None,
        dict(start=date(2026, 4, 1), end=date(2026, 8, 31), label="2026-YTD08"),
    ),
    (
        {"grain": "ytd", "offset": "previous_full_month", "fiscal_year_start_month": 4},
        date(2026, 2, 3),
        None,
        dict(start=date(2025, 4, 1), end=date(2026, 1, 31), label="2025-YTD01"),
    ),
    (
        {"grain": "week", "offset": "previous_full_week"},
        date(2026, 9, 3),
        None,
        dict(
            start=date(2026, 8, 24),
            end=date(2026, 8, 30),
            label="2026-W35",
            prior_start=date(2026, 8, 17),
            py_start=date(2025, 8, 25),
        ),
    ),
    (
        {"grain": "week", "offset": "current_week_to_date"},
        date(2026, 9, 3),
        None,
        dict(start=date(2026, 8, 31), end=date(2026, 9, 3), label="2026-W36", to_date=True),
    ),
    (
        {"grain": "custom", "offset": {"start": "2026-05-15", "end": "2026-06-14"}},
        date(2026, 9, 3),
        None,
        dict(
            start=date(2026, 5, 15),
            end=date(2026, 6, 14),
            label="2026-05-15_2026-06-14",
            prior_start=date(2025, 5, 15),
        ),
    ),
    (
        {"grain": "month"},
        date(2026, 9, 3),
        "2026-05",
        dict(start=date(2026, 5, 1), end=date(2026, 5, 31), label="2026-05", grain="month"),
    ),
    (
        {"grain": "month"},
        date(2026, 9, 3),
        "2026-Q2",
        dict(start=date(2026, 4, 1), end=date(2026, 6, 30), label="2026-Q2", grain="quarter"),
    ),
    (
        {"grain": "month", "fiscal_year_start_month": 4},
        date(2026, 9, 3),
        "2026-Q1",
        dict(start=date(2026, 4, 1), end=date(2026, 6, 30), label="2026-Q1"),
    ),
    (
        {"grain": "month"},
        date(2026, 9, 3),
        "2026-W35",
        dict(start=date(2026, 8, 24), end=date(2026, 8, 30), label="2026-W35", grain="week"),
    ),
    (
        {"grain": "month"},
        date(2026, 9, 3),
        "previous_month",
        dict(start=date(2026, 8, 1), end=date(2026, 8, 31), label="2026-08"),
    ),
    (
        {"grain": "month"},
        date(2026, 9, 3),
        "2026-05-15..2026-06-14",
        dict(start=date(2026, 5, 15), end=date(2026, 6, 14), grain="custom"),
    ),
    (
        {"grain": "ytd"},
        date(2026, 9, 3),
        "2026-08",
        dict(start=date(2026, 1, 1), end=date(2026, 8, 31), label="2026-YTD08", grain="ytd"),
    ),
    ({"grain": "month", "as_of": "run_date"}, date(2026, 9, 3), None, dict(as_of=date(2026, 9, 3))),
    (
        {"grain": "month", "as_of": "period_end"},
        date(2026, 9, 3),
        None,
        dict(as_of=date(2026, 8, 31)),
    ),
]


@pytest.mark.parametrize("section,run_date,override,expected", PERIOD_CASES)
def test_resolve_period_matrix(base_raw, section, run_date, override, expected):
    raw = copy.deepcopy(base_raw)
    raw["period"].update(section)
    p = re_.resolve_period(rs.spec_from_dict(raw), run_date=run_date, override=override)
    for k, v in expected.items():
        assert getattr(p, k) == v, f"{k}: {getattr(p, k)} != {v}"
    assert p.run_date == run_date
    assert len(p.history()) == raw["period"].get("history_months", 13)
    assert p.history()[-1][1] == re_.month_end(p.end)


@pytest.mark.parametrize(
    "token", ["2026", "2026-13", "yesterday", "2026-06-14..2026-05-15", "2026-Q5"]
)
def test_resolve_period_rejects_bad_override(spec, token):
    with pytest.raises(re_.PeriodError) as exc:
        re_.resolve_period(spec, run_date=RUN_DATE, override=token)
    assert exc.value.message_hu


def test_date_helpers():
    assert re_.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert re_.add_months(date(2026, 3, 15), -3) == date(2025, 12, 15)
    assert re_.fiscal_year_of(date(2026, 2, 1), 4) == 2025
    assert re_.fiscal_quarter_of(date(2026, 2, 1), 4) == 4
    assert re_.fiscal_quarter_start(date(2026, 2, 1), 4) == date(2026, 1, 1)


# ---------------------------------------------------------------------------
# Frames and filters
# ---------------------------------------------------------------------------


def test_load_frames_applies_filters(conn, base_raw, period):
    def frames_with(**filters):
        raw = copy.deepcopy(base_raw)
        raw["filters"].update(filters)
        return re_.load_frames(conn, rs.spec_from_dict(raw), period)

    base = frames_with()
    assert len(base.invoice) == q1(conn, f"SELECT COUNT(*) FROM invoice WHERE {DOC_FILTER}")
    assert set(base.invoice["pay_status_raw"]) >= {"unpaid", "paid"}

    f = frames_with(invoice_prefixes=["SZ-2026"])
    assert f.invoice["invoice_number"].str.startswith("SZ-2026").all()
    assert len(f.invoice) == q1(
        conn, "SELECT COUNT(*) FROM invoice WHERE invoice_number LIKE 'SZ-2026%'"
    )
    assert set(f.line["invoice_number"]) <= set(f.invoice["invoice_number"])

    f = frames_with(currencies=["EUR"])
    assert set(f.invoice["currency"]) == {"EUR"} and set(f.customer["customer_key"]) == {"C05"}

    f = frames_with(customers={"include": ["*"], "exclude": ["acme*"]})
    assert not (set(f.invoice["customer_key"]) & {"C01", "C02"})
    f = frames_with(customers={"include": ["Beta*", "C04"], "exclude": []})
    assert set(f.invoice["customer_key"]) == {"C03", "C04"}

    f = frames_with(doc_types=["invoice"])
    assert set(f.invoice["doc_type"]) == {"invoice"}

    f = frames_with(min_net_huf=1_000_000)
    assert (f.invoice["net_huf"].abs() >= 1_000_000).all()

    f = frames_with(vat_rates=["27"])
    assert set(f.vat["vat_rate"]) == {"27"} and set(f.line["vat_rate"]) == {"27"}
    assert "ÁFA-kulcs: 27" in f.filters_hu


def test_cash_card_autopaid_both_modes(conn, base_raw, period):
    raw = copy.deepcopy(base_raw)
    on = re_.load_frames(conn, rs.spec_from_dict(raw), period)
    raw["sources"]["cash_card_autopaid"] = False
    off = re_.load_frames(conn, rs.spec_from_dict(raw), period)
    cash = [PLANTED["cash_unpaid_0"].number, PLANTED["cash_unpaid_1"].number]
    on_rows = on.invoice.set_index("invoice_number").loc[cash]
    off_rows = off.invoice.set_index("invoice_number").loc[cash]
    assert list(on_rows["pay_status"]) == ["paid", "paid"] and list(on_rows["pay_status_raw"]) == [
        "unpaid",
        "unpaid",
    ]
    assert (on_rows["paid_huf"] == on_rows["gross_huf"]).all()
    assert (
        list(off_rows["pay_status"]) == ["unpaid", "unpaid"] and (off_rows["paid_huf"] == 0).all()
    )
    ar_on = re_.ar_frame(on, AS_OF)["open_huf"].sum()
    ar_off = re_.ar_frame(off, AS_OF)["open_huf"].sum()
    assert ar_off - ar_on == pytest.approx(float(off_rows["gross_huf"].sum()), abs=0.01)


def test_storno_attribution_both_modes(conn, base_raw):
    storno = PLANTED["storno_2026_07"]
    assert (
        storno.issue.strftime("%Y-%m") == "2026-08"
        and storno.chain_root_doc.issue.strftime("%Y-%m") == "2026-07"
    )
    storno_net = q1(conn, "SELECT net_huf FROM invoice WHERE invoice_number = ?", (storno.number,))

    def rev(mode, label):
        raw = copy.deepcopy(base_raw)
        raw["period"]["storno_attribution"] = mode
        spec = rs.spec_from_dict(raw)
        p = re_.resolve_period(spec, run_date=RUN_DATE, override=label)
        fr = re_.load_frames(conn, spec, p)
        return re_.compute(fr, spec, p).value("rev_net"), fr

    aug_issue, fr_issue = rev("issue_month", "2026-08")
    aug_orig, fr_orig = rev("original_month", "2026-08")
    jul_issue, _ = rev("issue_month", "2026-07")
    jul_orig, _ = rev("original_month", "2026-07")
    assert aug_issue - aug_orig == pytest.approx(storno_net, abs=0.01)
    assert jul_orig - jul_issue == pytest.approx(storno_net, abs=0.01)
    row = fr_orig.invoice.set_index("invoice_number").loc[storno.number]
    assert (
        row["period_kelt"] == "2026-07" and row["issue_date"].date() == storno.chain_root_doc.issue
    )
    assert (
        fr_issue.invoice.set_index("invoice_number").loc[storno.number, "period_kelt"] == "2026-08"
    )


# ---------------------------------------------------------------------------
# Measures with SQL-computed expectations
# ---------------------------------------------------------------------------


def ar_sql(conn, as_of: str, autopaid: bool = True):
    paid_eff = (
        "CASE WHEN i.payment_method IN ('cash','card') AND i.pay_status IN ('unpaid','partial') "
        "THEN i.gross_huf ELSE i.paid_huf END"
        if autopaid
        else "i.paid_huf"
    )
    sql = f"""
    WITH docs AS (
        SELECT i.*, {paid_eff} AS paid_eff FROM invoice i
        WHERE i.doc_type != 'proforma' AND i.issue_date <= :as_of
    ), paid AS (
        SELECT d.invoice_number,
               CASE WHEN EXISTS (SELECT 1 FROM payment p WHERE p.invoice_number = d.invoice_number)
                    THEN COALESCE((SELECT SUM(p.amount) FROM payment p
                                   WHERE p.invoice_number = d.invoice_number
                                     AND p.pay_date <= :as_of), 0) * d.fx_rate_invoice
                    ELSE d.paid_eff END AS paid_asof
        FROM docs d
    ), chains AS (
        SELECT d.chain_root, SUM(d.gross_huf) - SUM(p.paid_asof) AS open
        FROM docs d JOIN paid p ON p.invoice_number = d.invoice_number GROUP BY d.chain_root
    )
    SELECT c.chain_root, ROUND(c.open, 2) AS open, r.due_date, r.currency,
           CAST(julianday(:as_of) - julianday(r.due_date) AS INTEGER) AS days
    FROM chains c JOIN invoice r ON r.invoice_number = c.chain_root WHERE ABS(c.open) >= 0.5
    """
    return conn.execute(sql, {"as_of": as_of}).fetchall()


def bucket_of(open_, days):
    if open_ <= 0 or days <= 0:
        return "not_due"
    if days <= 30:
        return "1_30"
    if days <= 60:
        return "31_60"
    if days <= 90:
        return "61_90"
    return "90_plus"


def test_flow_measures_match_sql(conn, full):
    _spec, _frames, res = full
    v = res.values
    where = f"{DOC_FILTER} AND issue_date BETWEEN '{P_START}' AND '{P_END}'"
    assert v["rev_net"] == pytest.approx(
        q1(conn, f"SELECT SUM(net_huf) FROM invoice WHERE {where}")
    )
    assert v["rev_gross"] == pytest.approx(
        q1(conn, f"SELECT SUM(gross_huf) FROM invoice WHERE {where}")
    )
    assert v["vat_total"] == pytest.approx(
        q1(conn, f"SELECT SUM(vat_huf) FROM invoice WHERE {where}")
    )
    inv_count = q1(
        conn,
        "SELECT COUNT(*) FROM invoice WHERE doc_type = 'invoice' AND issue_date BETWEEN "
        f"'{P_START}' AND '{P_END}'",
    )
    assert v["inv_count"] == inv_count
    assert v["avg_inv"] == pytest.approx(v["rev_net"] / inv_count)
    stornos = q1(
        conn,
        "SELECT COUNT(*) FROM invoice WHERE doc_type = 'storno' AND issue_date BETWEEN "
        f"'{P_START}' AND '{P_END}'",
    )
    assert stornos == 1 and v["storno_rate"] == pytest.approx(stornos / inv_count)
    modifiers = q1(
        conn,
        "SELECT COUNT(*) FROM invoice WHERE doc_type = 'modifier' AND issue_date BETWEEN "
        f"'{P_START}' AND '{P_END}'",
    )
    assert modifiers == 1 and v["modifier_rate"] == pytest.approx(modifiers / inv_count)
    cash_in = q1(
        conn,
        "SELECT SUM(p.amount * i.fx_rate_invoice) FROM payment p JOIN invoice i USING "
        f"(invoice_number) WHERE p.pay_date BETWEEN '{P_START}' AND '{P_END}'",
    )
    assert v["cash_in"] == pytest.approx(cash_in)
    assert v["coll_rate"] == pytest.approx(cash_in / v["rev_gross"])
    einv = q1(
        conn,
        "SELECT COUNT(*) FROM invoice WHERE doc_type = 'invoice' AND is_einvoice = 1 AND "
        f"issue_date BETWEEN '{P_START}' AND '{P_END}'",
    )
    assert v["einv_share"] == pytest.approx(einv / inv_count)
    eur_net = q1(conn, f"SELECT SUM(net_huf) FROM invoice WHERE currency <> 'HUF' AND {where}")
    assert v["eur_share"] == pytest.approx(eur_net / v["rev_net"])
    assert v["fx_dev"] == pytest.approx(0.01, abs=1e-6)  # planted 1 % deviation
    assert v["cust_active"] == q1(
        conn,
        f"SELECT COUNT(*) FROM (SELECT customer_key FROM invoice WHERE {where} GROUP BY "
        "customer_key HAVING SUM(net_huf) > 0)",
    )
    assert (
        v["cust_new"]
        == q1(
            conn,
            f"SELECT COUNT(*) FROM customer WHERE first_invoice_date BETWEEN '{P_START}' AND "
            f"'{P_END}'",
        )
        == 1
    )
    assert v["cust_returning"] == v["cust_active"] - v["cust_new"]
    churned = q1(
        conn,
        f"""SELECT COUNT(*) FROM (
            SELECT customer_key FROM invoice WHERE {DOC_FILTER}
              AND issue_date BETWEEN '2025-06-01' AND '2026-05-31'
              GROUP BY customer_key HAVING SUM(net_huf) > 0
            EXCEPT
            SELECT customer_key FROM invoice WHERE {DOC_FILTER}
              AND issue_date BETWEEN '2026-06-01' AND '2026-08-31'
              GROUP BY customer_key HAVING SUM(net_huf) > 0)""",
    )
    assert churned == 1 and v["cust_churned"] == churned
    top5 = q1(
        conn,
        f"""WITH by_c AS (SELECT customer_key, SUM(net_huf) AS net FROM invoice
                       WHERE {where} GROUP BY customer_key)
            SELECT (SELECT SUM(net)
                    FROM (SELECT net FROM by_c WHERE net > 0 ORDER BY net DESC LIMIT 5))
                   / (SELECT SUM(net) FROM by_c)""",
    )
    assert v["top_n_share[n=5]"] == pytest.approx(top5)
    assert 0 < v["ontime_rate"] <= 1


def test_snapshot_measures_match_sql(conn, full):
    _spec, _frames, res = full
    v = res.values
    rows = ar_sql(conn, AS_OF.isoformat())
    ar_balance = sum(r[1] for r in rows)
    assert v["ar_balance"] == pytest.approx(ar_balance, abs=0.01)
    overdue = [r for r in rows if r[1] > 0 and r[4] > 0]
    assert v["overdue_amt"] == pytest.approx(sum(r[1] for r in overdue), abs=0.01)
    assert v["overdue_cnt"] == len(overdue)
    assert v["eur_open"] == pytest.approx(sum(r[1] for r in rows if r[3] == "EUR"), abs=0.01)
    buckets = {b: 0.0 for b in re_.AGING_BUCKETS}
    counts = {b: 0 for b in re_.AGING_BUCKETS}
    for _root, open_, _due, _cur, days in rows:
        b = bucket_of(open_, days)
        buckets[b] += open_
        counts[b] += 1
    ag = res.ar_aging.set_index("bucket")
    for b in re_.AGING_BUCKETS:
        assert ag.at[b, "amount"] == pytest.approx(buckets[b], abs=0.01), b
        assert ag.at[b, "count"] == counts[b], b
        assert counts[b] >= 1, f"fixture must populate bucket {b}"
    for key in ("overdue_1_30", "overdue_31_60", "overdue_61_90", "overdue_90_plus"):
        num = PLANTED[key].number
        hit = res.ar[res.ar["invoice_number"] == num]
        assert len(hit) == 1 and hit["bucket"].iloc[0] == key.removeprefix("overdue_")
    rev3 = q1(
        conn,
        f"SELECT SUM(net_huf) FROM invoice WHERE {DOC_FILTER} AND issue_date BETWEEN '2026-06-01' "
        "AND '2026-08-31'",
    )
    assert v["dso"] == pytest.approx(ar_balance / (rev3 / 92), abs=0.01)


def test_every_catalogue_measure_returns_a_number(full):
    spec, _frames, res = full
    assert len(re_.MEASURES) == 30
    for m in spec.measures:
        rows = res.measures[res.measures["measure_id"] == m.key]
        assert len(rows) >= 1, m.key
        assert rows["value"].notna().any(), m.key
        mdef = re_.MEASURES[m.id]
        assert (
            mdef.label_hu
            and mdef.label_en
            and mdef.formula_words.endswith(".")
            and mdef.source in ("D", "A")
        )
        assert mdef.default_format in rs.FORMATS
        if mdef.dim:
            assert set(rows["dim_name"]) == {mdef.dim}
        else:
            assert list(rows["dim_name"]) == ["total"]
    assert set(res.measures.columns) == set(re_.MEASURE_COLUMNS)
    total = res.measures[res.measures["dim_name"] == "total"].set_index("measure_id")
    assert total.at["rev_net", "mom_pct"] == pytest.approx(
        total.at["rev_net", "value"] / total.at["rev_net", "prior"] - 1
    )
    assert total.at["rev_net", "yoy_pct"] == pytest.approx(
        total.at["rev_net", "value"] / total.at["rev_net", "prior_year"] - 1
    )
    assert total.at["rev_net", "ytd"] > total.at["rev_net", "value"]
    assert pytest_isnan(total.at["ar_balance", "ytd"])  # snapshots have no YTD
    assert total.at["inv_count", "avg3m"] > 0


def pytest_isnan(v) -> bool:
    return v != v


def test_dimensioned_measures_sum_to_totals(conn, full):
    _spec, _frames, res = full
    m = res.measures
    by_cust = m[m["measure_id"] == "rev_net_cust"]["value"].sum()
    by_vat = m[m["measure_id"] == "rev_net_vat"]["value"].sum()
    by_cur = m[m["measure_id"] == "rev_net_cur"]["value"].sum()
    assert (
        by_cust
        == pytest.approx(res.value("rev_net"))
        == pytest.approx(by_vat)
        == pytest.approx(by_cur)
    )
    pm = m[m["measure_id"] == "pm_mix"]["value"].sum()
    assert pm == pytest.approx(1.0)
    vat = m[m["measure_id"] == "vat_by_rate"].set_index("dim_value")["value"]
    assert vat["27"] == pytest.approx(
        q1(
            conn,
            "SELECT SUM(v.vat_huf) FROM invoice_vat v JOIN invoice i USING (invoice_number) WHERE "
            f"v.vat_rate = '27' AND i.issue_date BETWEEN '{P_START}' AND '{P_END}'",
        )
    )
    assert set(res.vat_summary["vat_rate"]) == {"27", "5", "AAM", "EU"}
    assert list(res.vat_summary["vat_rate"])[:2] == ["27", "5"]


def test_series_and_top_customers(full):
    spec, _frames, res = full
    for tile in spec.output.executive.tiles:
        s = res.series[res.series["measure_id"] == tile]
        assert len(s) == 13 and s["month"].iloc[-1] == "2026-08" and s["month"].iloc[0] == "2025-08"
        assert s["value"].notna().all()
    tc = res.top_customers
    assert len(tc) <= spec.output.executive.top_n and (tc["net"] > 0).all()
    assert list(tc["net"]) == sorted(tc["net"], reverse=True)
    assert tc["cum_share"].iloc[-1] == pytest.approx(tc["share"].sum())
    assert tc["name"].iloc[0] == "Acme Kft."
    assert res.top_series.groupby("name").size().eq(6).all()


def test_custom_measure_and_prior(conn, base_raw, period):
    raw = copy.deepcopy(base_raw)
    raw["measures"].append(
        {"id": "custom:novekedes", "formula": "rev_net / prior(rev_net, 12) - 1", "format": "pct"}
    )
    raw["measures"].append(
        {"id": "custom:nulla", "formula": "rev_net / (inv_count - inv_count)", "format": "pct"}
    )
    spec = rs.spec_from_dict(raw)
    frames = re_.load_frames(conn, spec, period)
    res = re_.compute(frames, spec, period)
    total = res.measures[res.measures["dim_name"] == "total"].set_index("measure_id")
    assert res.value("custom:novekedes") == pytest.approx(total.at["rev_net", "yoy_pct"])
    assert res.value("custom:nulla") is None


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------


def test_threshold_levels_on_example(conn, spec, period):
    frames = re_.load_frames(conn, spec, period)
    res = re_.compute(frames, spec, period)
    assert res.value("overdue_amt") > 5_000_000 and res.level("overdue_amt") == "critical"
    assert res.value("dso") < 45 and res.level("dso") == "none"
    assert 0.03 <= res.value("storno_rate") < 0.05 and res.level("storno_rate") == "warn"
    assert res.level("rev_net") == "none"  # no threshold defined
    t = res.thresholds.set_index("measure_id")
    assert list(t.columns) == ["value", "ratio", "warn", "critical", "direction", "unit", "level"]


def test_threshold_pct_of_and_below(conn, base_raw, period):
    raw = copy.deepcopy(base_raw)
    raw["thresholds"] = {
        "overdue_amt": {
            "warn": 0.15,
            "critical": 0.30,
            "direction": "above",
            "unit": "pct_of:ar_balance",
        },
        "coll_rate": {"warn": 0.9, "critical": 0.5, "direction": "below", "unit": "pct"},
        "inv_count": {"warn": 100, "direction": "below", "unit": "abs"},
    }
    spec = rs.spec_from_dict(raw)
    res = re_.compute(re_.load_frames(conn, spec, period), spec, period)
    t = res.thresholds.set_index("measure_id")
    assert t.at["overdue_amt", "ratio"] == pytest.approx(
        res.value("overdue_amt") / res.value("ar_balance")
    )
    assert t.at["overdue_amt", "level"] == "critical"
    assert 0.5 < res.value("coll_rate") < 0.9 and t.at["coll_rate", "level"] == "warn"
    assert t.at["inv_count", "level"] == "warn"
    assert re_._threshold_level(None, 1, 2, "above") == "none"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


def exceptions_spec(base_raw, rules, **period_overrides):
    raw = copy.deepcopy(base_raw)
    raw["period"].update(period_overrides)
    raw["exceptions"] = rules
    return rs.spec_from_dict(raw)


def run_exceptions(conn, spec, period):
    frames = re_.load_frames(conn, spec, period)
    return re_.compute(frames, spec, period)


def test_each_exception_rule_fires_on_planted_rows(conn, base_raw, period):
    spec = exceptions_spec(
        base_raw,
        [
            {"id": "o30", "rule": "overdue_gt_days", "params": {"days": 30}, "severity": "warn"},
            {
                "id": "big",
                "rule": "overdue_gt_amount",
                "params": {"amount_huf": 900000},
                "severity": "critical",
            },
            {"id": "sto", "rule": "storno_in_period", "severity": "info"},
            {"id": "mod", "rule": "modifier_in_period", "severity": "info"},
            {
                "id": "out",
                "rule": "amount_outlier_zscore",
                "params": {"z": 3.0, "window_months": 12},
                "severity": "info",
            },
            {"id": "tax", "rule": "missing_customer_taxno", "severity": "warn"},
            {
                "id": "fx",
                "rule": "fx_deviation",
                "params": {"tolerance": 0.005},
                "severity": "warn",
            },
            {"id": "dup", "rule": "duplicate_customer_name", "severity": "warn"},
            {"id": "cash", "rule": "unpaid_cash_invoice", "severity": "warn"},
        ],
    )
    assert rs.validate(spec) == []
    res = run_exceptions(conn, spec, period)
    ex = res.exceptions
    assert list(ex.columns) == re_.EXCEPTION_COLUMNS
    by_rule = {
        rid: set(ex[ex["rule_id"] == rid]["invoice_number"]) for rid in ex["rule_id"].unique()
    }

    planted_overdue = {
        PLANTED[k].number for k in ("overdue_31_60", "overdue_61_90", "overdue_90_plus")
    }
    assert planted_overdue <= by_rule["o30"]
    assert PLANTED["overdue_1_30"].number not in by_rule["o30"]
    days = ex[ex["rule_id"] == "o30"].set_index("invoice_number")["days"]
    assert (
        days[PLANTED["overdue_90_plus"].number]
        == (AS_OF - PLANTED["overdue_90_plus"].due).days
        > 90
    )
    assert PLANTED["overdue_90_plus"].number in by_rule["big"]
    assert (ex[ex["rule_id"] == "big"]["amount"] > 900000).all()
    assert by_rule["sto"] == {PLANTED["storno_2026_07"].number}
    assert (
        ex[ex["rule_id"] == "sto"]["note"].iloc[0]
        == f"eredeti: {PLANTED['storno_2026_07'].chain_root_doc.number}"
    )
    assert by_rule["mod"] == {PLANTED["modifier_2026_08"].number}
    assert by_rule["out"] == {PLANTED["outlier"].number}
    assert by_rule["tax"] and all(n.startswith("SZ-") for n in by_rule["tax"])
    tax_customers = set(ex[ex["rule_id"] == "tax"]["customer"])
    assert tax_customers == {"Lambda Startup Kft."}  # private person C11 is exempt
    assert by_rule["fx"] == {PLANTED["fx_deviation"].number}
    dup = ex[ex["rule_id"] == "dup"]
    assert (
        len(dup) == 1
        and "Acme Kft. (C01)" in dup["note"].iloc[0]
        and "ACME KFT. (C02)" in dup["note"].iloc[0]
    )
    assert by_rule["cash"] == {PLANTED["cash_unpaid_0"].number, PLANTED["cash_unpaid_1"].number}
    sev = list(ex["severity"])
    order = [re_.SEVERITY_ORDER[s] for s in sev]
    assert order == sorted(order)
    assert res.exception_totals["o30"] == len(by_rule["o30"])


def test_exception_max_rows_and_totals(conn, base_raw, period):
    spec = exceptions_spec(
        base_raw,
        [
            {
                "id": "all",
                "rule": "overdue_gt_days",
                "params": {"days": 0},
                "severity": "warn",
                "max_rows": 2,
            }
        ],
    )
    res = run_exceptions(conn, spec, period)
    assert len(res.exceptions) == 2 and res.exception_totals["all"] > 2
    amounts = list(res.exceptions["amount"])
    assert amounts == sorted(amounts, reverse=True)


def test_missing_taxno_only_domestic_and_normalize_names(conn, base_raw, period):
    spec = exceptions_spec(
        base_raw,
        [
            {
                "id": "tax",
                "rule": "missing_customer_taxno",
                "params": {"only_domestic_companies": True},
                "severity": "warn",
            }
        ],
    )
    res = run_exceptions(conn, spec, period)
    assert set(res.exceptions["customer"]) == {"Lambda Startup Kft."}
    assert (
        re_.normalize_customer_name("ACME KFT.")
        == re_.normalize_customer_name("Acme Kft.")
        == "acme"
    )
    assert re_.normalize_customer_name("Beta Zrt.") != re_.normalize_customer_name("Béta Zrt.")


def test_calendar_frame():
    cal = re_.calendar_frame(date(2026, 3, 30), date(2026, 4, 2), fiscal_start_month=4)
    assert list(cal["date"]) == ["2026-03-30", "2026-03-31", "2026-04-01", "2026-04-02"]
    assert list(cal["fiscal_year"]) == [2025, 2025, 2026, 2026]
    assert list(cal["is_month_end"]) == [0, 1, 0, 0]
    assert list(cal["quarter"]) == ["2025-Q4", "2025-Q4", "2026-Q1", "2026-Q1"]
    assert list(cal["is_business_day"]) == [1, 1, 1, 1]


# ---------------------------------------------------------------------------
# Fixture schema source and the optional measures_local.py extension
# ---------------------------------------------------------------------------

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
TESTS_DIR = Path(__file__).resolve().parent
LOCAL_ID = "local_gross_per_invoice"
LOCAL_MODULE = f'''
from report_engine import MeasureDef


def m_gross_per_invoice(ctx, start, end, params):
    docs = ctx.invoices(start, end)
    return float(docs["gross_huf"].sum() / len(docs)) if len(docs) else None


MEASURES = {{
    "{LOCAL_ID}": MeasureDef(
        id="{LOCAL_ID}",
        label_hu="Bruttó érték számlánként (helyi)",
        label_en="Gross value per invoice (local)",
        formula_words="Bruttó árbevétel osztva a számlák számával.",
        source="D",
        default_format="huf_k",
        fn=m_gross_per_invoice,
    )
}}
'''


def test_engine_fixture_uses_the_data_layer_schema():
    import db
    import engine_fixture

    assert engine_fixture.DB_SCHEMA_AVAILABLE is True
    assert engine_fixture._db_create_schema is db.create_schema
    assert importlib.util.find_spec("measures_local") is None  # the kit ships no local module


@pytest.fixture
def local_dir(tmp_path, monkeypatch):
    (tmp_path / "measures_local.py").write_text(LOCAL_MODULE, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("measures_local", None)
    importlib.invalidate_caches()
    yield tmp_path
    sys.modules.pop("measures_local", None)
    importlib.invalidate_caches()


def _rewrite_local(local_dir: Path, text: str) -> None:
    (local_dir / "measures_local.py").write_text(text, encoding="utf-8")
    sys.modules.pop("measures_local", None)
    importlib.invalidate_caches()


def test_merge_local_measures_adds_without_touching_the_catalogue(local_dir):
    cat = dict(re_.MEASURES)
    assert re_.merge_local_measures(cat) is cat
    assert LOCAL_ID in cat and len(cat) == len(re_.MEASURES) + 1
    assert LOCAL_ID not in re_.MEASURES
    assert cat[LOCAL_ID].label_hu == "Bruttó érték számlánként (helyi)"


def test_merge_local_measures_refuses_collision_and_bad_entries(local_dir):
    _rewrite_local(local_dir, LOCAL_MODULE.replace(LOCAL_ID, "rev_net"))
    with pytest.raises(re_.LocalMeasureError) as info:
        re_.merge_local_measures(dict(re_.MEASURES))
    assert "rev_net" in info.value.message_hu and "ütközik" in info.value.message_hu
    _rewrite_local(local_dir, 'MEASURES = {"x_local": "nem MeasureDef"}\n')
    with pytest.raises(re_.LocalMeasureError) as info:
        re_.merge_local_measures(dict(re_.MEASURES))
    assert "x_local" in info.value.message_hu and "MeasureDef" in info.value.message_hu
    _rewrite_local(local_dir, "MEASURES = 5\n")
    assert re_.merge_local_measures({"a": 1}) == {"a": 1}


def test_merge_local_measures_without_module_is_a_no_op():
    assert importlib.util.find_spec("measures_local") is None
    assert re_.merge_local_measures({}) == {}


def test_local_measure_appears_in_catalogue_and_cli(local_dir):
    env = dict(
        os.environ,
        PYTHONPATH=os.pathsep.join([str(local_dir), str(SCRIPTS_DIR), str(TESTS_DIR)]),
    )
    code = f"""
import report_engine as e, report_spec as rs, yaml
from engine_fixture import EXAMPLES_DIR, RUN_DATE, make_engine_db
print("{LOCAL_ID}" in e.MEASURES, len(e.MEASURES))
raw = yaml.safe_load((EXAMPLES_DIR / "havi_arbev_kintlev" / "spec.yaml").read_text("utf-8"))
raw["measures"].append({{"id": "{LOCAL_ID}", "comparisons": ["mom"]}})
spec = rs.spec_from_dict(raw)
print(rs.validate(spec))
period = e.resolve_period(spec, run_date=RUN_DATE)
res = e.compute(e.load_frames(make_engine_db(":memory:"), spec, period), spec, period)
print(round(res.value("{LOCAL_ID}")))
"""
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True
    )
    first, errors, value = proc.stdout.strip().splitlines()
    assert first.split() == ["True", str(len(re_.MEASURES) + 1)] and errors == "[]"
    assert int(value) > 0
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "report_spec.py"), "--catalogue"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    row = next(line for line in proc.stdout.splitlines() if line.startswith(LOCAL_ID))
    assert "Bruttó érték számlánként (helyi)" in row and row.split()[-2:] == ["D", "huf_k"]
