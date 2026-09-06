"""db.py: schema, pure rules, rebuild from raw, precedence, chains, calendar, idempotency."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import db
import pytest
from conftest import FIXTURES, load_fixture_raw

CANONICAL = ("invoice", "invoice_line", "invoice_vat", "payment", "customer", "calendar")


def dump(conn: sqlite3.Connection) -> bytes:
    parts = []
    for table in CANONICAL:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        order = ", ".join(cols)
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()
        parts.append(table.encode() + b"\n" + b"\n".join(repr(tuple(r)).encode() for r in rows))
    return b"\n".join(parts)


def row(conn: sqlite3.Connection, number: str) -> sqlite3.Row:
    return conn.execute("SELECT * FROM invoice WHERE invoice_number = ?", (number,)).fetchone()


# --- schema ------------------------------------------------------------------


def test_create_schema_is_idempotent_and_versioned(tmp_path: Path):
    conn = db.connect(tmp_path / "x.db")
    assert db.create_schema(conn) == 1
    assert db.create_schema(conn) == 1
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "raw_documents",
        "invoice",
        "invoice_line",
        "invoice_vat",
        "payment",
        "customer",
        "calendar",
        "staging_fokonyvi",
        "staging_afalista",
        "sync_log",
    } <= tables
    views = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='view'")}
    assert "v_chain" in views
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()


def test_default_db_path_honours_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RIPORTOK_DIR", str(tmp_path))
    assert db.default_db_path() == tmp_path / "data" / "invoices.db"
    monkeypatch.delenv("RIPORTOK_DIR")
    assert db.default_db_path().parts[-3:] == ("Riportok", "data", "invoices.db")


def test_migration_pattern_applies_new_version(tmp_db, monkeypatch):
    monkeypatch.setitem(db.MIGRATIONS, 2, ["CREATE TABLE IF NOT EXISTS probe (x INTEGER)"])
    assert db.create_schema(tmp_db) == 2
    assert tmp_db.execute("SELECT COUNT(*) FROM probe").fetchone()[0] == 0


# --- pure rules --------------------------------------------------------------


@pytest.mark.parametrize(
    "code,expected",
    [
        ("27", 27.0),
        ("18", 18.0),
        ("5", 5.0),
        ("0", 0.0),
        (" 27 ", 27.0),
        ("27%", 27.0),
        ("AAM", None),
        ("TAM", None),
        ("EU", None),
        ("EUK", None),
        ("MAA", None),
        ("F.AFA", None),
        ("K.AFA", None),
        ("ÁKK", None),
        ("TEHK", None),
        ("HO", None),
        ("KBAET", None),
        ("KBAUK", None),
        ("EUFAD37", None),
        ("EUFADE", None),
        ("EUE", None),
        ("", None),
        (None, None),
    ],
)
def test_vat_rate_pct(code, expected):
    assert db.vat_rate_pct(code) == expected


@pytest.mark.parametrize(
    "raw,unified,expected",
    [
        ("Átutalás", None, "transfer"),
        ("átutalás", "transfer", "transfer"),
        ("Készpénz", None, "cash"),
        ("Bankkártya", None, "card"),
        ("bankkartya", "card", "card"),
        ("Csekk", None, "other"),
        ("Utánvét", None, "other"),
        (None, None, "other"),
        ("PayPal", None, "other"),
        ("Transfer", None, "transfer"),
    ],
)
def test_normalize_payment_method(raw, unified, expected):
    assert db.normalize_payment_method(raw, unified) == expected


@pytest.mark.parametrize(
    "doc_type,gross,paid,storno,expected",
    [
        ("storno", -148000, 0, True, "void"),
        ("invoice", 148000, 148000, True, "void"),
        ("modifier", 12700, 0, True, "void"),
        ("proforma", 1000, 1000, False, "unpaid"),
        ("invoice", 148000, 148000, False, "paid"),
        ("invoice", 148000, 147999, False, "paid"),
        ("invoice", 148000, 147998, False, "partial"),
        ("invoice", 148000, 1, False, "partial"),
        ("invoice", 148000, 0, False, "unpaid"),
        ("invoice", 0, 0, False, "paid"),
        ("modifier", -5000, -5000, False, "paid"),
        ("modifier", -5000, -2000, False, "partial"),
        ("modifier", 12700, 0, False, "unpaid"),
    ],
)
def test_derive_pay_status_matrix(doc_type, gross, paid, storno, expected):
    assert db.derive_pay_status(doc_type, gross, paid, storno) == expected


def test_customer_key_prefers_szamlazz_id_then_hash():
    assert db.customer_key("501", "x", "y") == "501"
    a = db.customer_key(None, "Alfa Ügyfél Zrt.", "23456789-2-41")
    b = db.customer_key("", "  alfa ügyfél zrt  ", "23456789241")
    c = db.customer_key("0", "ALFA ÜGYFÉL ZRT.", "23456789-2-41")
    assert a == b == c and len(a) == 16
    assert db.customer_key(None, "Alfa Ügyfél Zrt.", "99999999-2-41") != a
    assert db.customer_key(None, "Béta Bt.", None) != db.customer_key(None, "Béta Kft.", None)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1 234 567,89", 1234567.89),
        ("1234567.89", 1234567.89),
        ("1.234.567,89", 1234567.89),
        ("-12", -12.0),
        ("120 000,00", 120000.0),
        ("1,5", 1.5),
        ("12 345 Ft", 12345.0),
        ("", None),
        (None, None),
        ("abc", None),
        (5, 5.0),
        ("1 000", 1000.0),
    ],
)
def test_parse_amount(text, expected):
    assert db.parse_amount(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("2026-08-05", "2026-08-05"),
        ("2026.08.05.", "2026-08-05"),
        ("2026. 08. 05.", "2026-08-05"),
        ("2026.8.5", "2026-08-05"),
        ("05.08.2026", "2026-08-05"),
        ("2026-08-05T10:00:00Z", "2026-08-05"),
        ("", None),
        (None, None),
        ("nem dátum", None),
        ("2026-13-01", None),
    ],
)
def test_parse_date(text, expected):
    assert db.parse_date(text) == expected


# --- raw documents -----------------------------------------------------------


def test_insert_raw_dedupes_identical_bodies_and_latest_wins(tmp_db):
    assert db.insert_raw(tmp_db, "agent", "X-1", b"<a/>", fetched_at="2026-01-01T00:00:00Z") is True
    assert (
        db.insert_raw(tmp_db, "agent", "X-1", b"<a/>", fetched_at="2026-01-02T00:00:00Z") is False
    )
    assert db.insert_raw(tmp_db, "agent", "X-1", b"<b/>", fetched_at="2026-01-03T00:00:00Z") is True
    assert db.insert_raw(tmp_db, "agent", "X-1", b"<c/>", fetched_at="2025-12-31T00:00:00Z") is True
    assert db.latest_raw(tmp_db, "agent") == {"X-1": b"<b/>"}
    assert db.known_doc_keys(tmp_db, "agent") == {"X-1"}
    assert tmp_db.execute("SELECT COUNT(*) FROM raw_documents").fetchone()[0] == 3
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_raw(tmp_db, "bogus", "X-1", b"<a/>")


# --- fixture database --------------------------------------------------------


def test_fixture_invoice_headers(fixture_db):
    rows = {r["invoice_number"]: r for r in fixture_db.execute("SELECT * FROM invoice")}
    assert sorted(rows) == [
        "E-SZLA-2026-1",
        "SZLA-2026-1",
        "SZLA-2026-2",
        "SZLA-2026-3",
        "SZLA-2026-4",
        "SZLA-2026-5",
    ]
    r = rows["SZLA-2026-1"]
    assert (r["doc_type"], r["nav_operation"], r["chain_root"], r["modification_index"]) == (
        "invoice",
        "CREATE",
        "SZLA-2026-1",
        0,
    )
    assert (r["issue_date"], r["delivery_date"], r["due_date"]) == (
        "2026-08-05",
        "2026-08-05",
        "2026-08-20",
    )
    assert (r["payment_method"], r["payment_method_raw"], r["is_einvoice"]) == (
        "transfer",
        "Átutalás",
        0,
    )
    assert (r["customer_key"], r["currency"], r["fx_rate_invoice"]) == ("501", "HUF", 1.0)
    assert (r["net_amount"], r["vat_amount"], r["gross_amount"]) == (120000.0, 28000.0, 148000.0)
    assert (r["net_huf"], r["vat_huf"], r["gross_huf"], r["paid_huf"]) == (
        120000.0,
        28000.0,
        148000.0,
        100000.0,
    )
    assert r["pay_status"] == "void"
    assert (r["order_ref"], r["note"]) == ("PO-2026-11", "Augusztusi fejlesztés")
    assert r["source_flags"] == "agent,nav_digest"
    assert (r["period_kelt"], r["period_telj"]) == ("2026-08", "2026-08")

    s = rows["SZLA-2026-2"]
    assert (s["doc_type"], s["nav_operation"], s["chain_root"], s["modification_index"]) == (
        "storno",
        "STORNO",
        "SZLA-2026-1",
        1,
    )
    assert (s["net_amount"], s["vat_amount"], s["gross_amount"]) == (-120000.0, -28000.0, -148000.0)
    assert (s["gross_huf"], s["paid_huf"], s["pay_status"]) == (-148000.0, 0.0, "void")

    a = rows["SZLA-2026-3"]
    assert (a["doc_type"], a["payment_method"], a["pay_status"], a["paid_huf"]) == (
        "invoice",
        "cash",
        "paid",
        63500.0,
    )
    m = rows["SZLA-2026-4"]
    assert (m["doc_type"], m["nav_operation"], m["chain_root"], m["modification_index"]) == (
        "modifier",
        "MODIFY",
        "SZLA-2026-3",
        1,
    )
    assert (m["gross_huf"], m["paid_huf"], m["pay_status"], m["due_date"]) == (
        12700.0,
        0.0,
        "unpaid",
        "2026-09-06",
    )


def test_fixture_eur_invoice_nav_data_precedence(fixture_db):
    e = row(fixture_db, "E-SZLA-2026-1")
    assert e["source_flags"] == "agent,nav_data,nav_digest"
    assert (e["currency"], e["fx_rate_invoice"], e["is_einvoice"]) == ("EUR", 399.5, 1)
    assert (e["net_amount"], e["vat_amount"], e["gross_amount"]) == (1000.0, 0.0, 1000.0)
    assert (e["net_huf"], e["vat_huf"], e["gross_huf"]) == (399500.0, 0.0, 399500.0)
    assert e["paid_huf"] == 240000.0
    assert e["pay_status"] == "partial"
    assert (e["due_date"], e["payment_method"], e["customer_key"]) == (
        "2026-09-11",
        "transfer",
        "601",
    )
    vat = fixture_db.execute(
        "SELECT vat_rate, net, vat, gross, net_huf, vat_huf FROM invoice_vat "
        "WHERE invoice_number = ?",
        ("E-SZLA-2026-1",),
    ).fetchall()
    assert [tuple(v) for v in vat] == [("EU", 1000.0, 0.0, 1000.0, 399500.0, 0.0)]


def test_fixture_digest_only_invoice(fixture_db):
    d = row(fixture_db, "SZLA-2026-5")
    assert d["source_flags"] == "nav_digest"
    assert (d["doc_type"], d["nav_operation"], d["chain_root"]) == (
        "invoice",
        "CREATE",
        "SZLA-2026-5",
    )
    assert (d["issue_date"], d["delivery_date"], d["due_date"]) == (
        "2026-08-28",
        "2026-08-28",
        None,
    )
    assert (d["payment_method"], d["payment_method_raw"]) == ("other", None)
    assert (d["net_amount"], d["vat_amount"], d["gross_amount"]) == (30000.0, 8100.0, 38100.0)
    assert (d["net_huf"], d["gross_huf"], d["paid_huf"], d["pay_status"]) == (
        30000.0,
        38100.0,
        0.0,
        "unpaid",
    )
    assert d["customer_key"] == db.customer_key(None, "Digest Only Kft.", "45678901")
    assert (
        fixture_db.execute(
            "SELECT COUNT(*) FROM invoice_line WHERE invoice_number = 'SZLA-2026-5'"
        ).fetchone()[0]
        == 0
    )
    assert (
        fixture_db.execute(
            "SELECT COUNT(*) FROM invoice_vat WHERE invoice_number = 'SZLA-2026-5'"
        ).fetchone()[0]
        == 0
    )


def test_fixture_lines_vat_payments(fixture_db):
    lines = fixture_db.execute(
        "SELECT invoice_number, line_no, product_name, quantity, unit, unit_price, "
        "vat_rate, net, vat, "
        "gross, ledger_code FROM invoice_line ORDER BY invoice_number, line_no"
    ).fetchall()
    assert [tuple(ln) for ln in lines] == [
        (
            "E-SZLA-2026-1",
            1,
            "Consulting services",
            20.0,
            "óra",
            50.0,
            "EU",
            1000.0,
            0.0,
            1000.0,
            "914",
        ),
        (
            "SZLA-2026-1",
            1,
            "Szoftverfejlesztés (augusztus)",
            10.0,
            "óra",
            10000.0,
            "27",
            100000.0,
            27000.0,
            127000.0,
            "911",
        ),
        ("SZLA-2026-1", 2, "Szakkönyv", 4.0, "db", 5000.0, "5", 20000.0, 1000.0, 21000.0, "912"),
        (
            "SZLA-2026-2",
            1,
            "Szoftverfejlesztés (augusztus)",
            -10.0,
            "óra",
            10000.0,
            "27",
            -100000.0,
            -27000.0,
            -127000.0,
            "911",
        ),
        (
            "SZLA-2026-2",
            2,
            "Szakkönyv",
            -4.0,
            "db",
            5000.0,
            "5",
            -20000.0,
            -1000.0,
            -21000.0,
            "912",
        ),
        (
            "SZLA-2026-3",
            1,
            "Tanácsadás",
            5.0,
            "óra",
            10000.0,
            "27",
            50000.0,
            13500.0,
            63500.0,
            "913",
        ),
        (
            "SZLA-2026-4",
            1,
            "Kiegészítő tanácsadás",
            1.0,
            "óra",
            10000.0,
            "27",
            10000.0,
            2700.0,
            12700.0,
            "913",
        ),
    ]
    vat = fixture_db.execute(
        "SELECT invoice_number, vat_rate, net, vat, gross, net_huf, vat_huf FROM invoice_vat "
        "WHERE invoice_number = 'SZLA-2026-1' ORDER BY vat_rate"
    ).fetchall()
    assert [tuple(v) for v in vat] == [
        ("SZLA-2026-1", "27", 100000.0, 27000.0, 127000.0, 100000.0, 27000.0),
        ("SZLA-2026-1", "5", 20000.0, 1000.0, 21000.0, 20000.0, 1000.0),
    ]
    pays = fixture_db.execute(
        "SELECT payment_id, invoice_number, pay_date, pay_type, amount, bank_account, note "
        "FROM payment "
        "ORDER BY payment_id"
    ).fetchall()
    assert [tuple(p) for p in pays] == [
        (
            "E-SZLA-2026-1#1",
            "E-SZLA-2026-1",
            "2026-08-30",
            "átutalás",
            600.0,
            "HU11 1111 1111 2222 2222 3333 3333",
            None,
        ),
        (
            "SZLA-2026-1#1",
            "SZLA-2026-1",
            "2026-08-18",
            "átutalás",
            100000.0,
            "11111111-22222222-33333333",
            "részfizetés",
        ),
        ("SZLA-2026-3#1", "SZLA-2026-3", "2026-08-10", "készpénz", 63500.0, None, None),
    ]


def test_fixture_customers(fixture_db):
    rows = fixture_db.execute("SELECT * FROM customer ORDER BY customer_key").fetchall()
    by_key = {r["customer_key"]: r for r in rows}
    assert len(rows) == 4
    alfa = by_key["501"]
    assert (alfa["name"], alfa["tax_number"], alfa["country"], alfa["is_private"]) == (
        "Alfa Ügyfél Zrt.",
        "23456789-2-41",
        "Magyarország",
        0,
    )
    assert (alfa["first_invoice_date"], alfa["last_invoice_date"]) == ("2026-08-05", "2026-08-25")
    beta = by_key["502"]
    assert (beta["first_invoice_date"], beta["last_invoice_date"]) == ("2026-08-10", "2026-08-22")
    gamma = by_key["601"]
    assert (gamma["name"], gamma["tax_number"], gamma["country"]) == (
        "Gamma GmbH",
        "ATU12345678",
        "Ausztria",
    )
    digest = by_key[db.customer_key(None, "Digest Only Kft.", "45678901")]
    assert (digest["name"], digest["tax_number"], digest["is_private"]) == (
        "Digest Only Kft.",
        "45678901",
        0,
    )


def test_chain_view_statuses(fixture_db):
    chains = {r["chain_root"]: r for r in fixture_db.execute("SELECT * FROM v_chain")}
    assert sorted(chains) == ["E-SZLA-2026-1", "SZLA-2026-1", "SZLA-2026-3", "SZLA-2026-5"]
    s = chains["SZLA-2026-1"]
    assert (s["chain_status"], s["doc_count"], s["effective_gross_huf"], s["open_huf"]) == (
        "stornoed",
        2,
        0.0,
        -100000.0,
    )
    assert (s["effective_net_huf"], s["effective_vat_huf"]) == (0.0, 0.0)
    m = chains["SZLA-2026-3"]
    assert (m["chain_status"], m["doc_count"], m["effective_gross_huf"], m["open_huf"]) == (
        "modified",
        2,
        76200.0,
        12700.0,
    )
    e = chains["E-SZLA-2026-1"]
    assert (e["chain_status"], e["doc_count"], e["effective_gross_huf"], e["open_huf"]) == (
        "active",
        1,
        399500.0,
        159500.0,
    )
    d = chains["SZLA-2026-5"]
    assert (d["chain_status"], d["open_huf"]) == ("active", 38100.0)


def test_calendar_range_and_fiscal_fields(fixture_db):
    first, last, n = fixture_db.execute(
        "SELECT MIN(date), MAX(date), COUNT(*) FROM calendar"
    ).fetchone()
    assert (first, last) == ("2025-07-01", "2026-09-30")
    assert n == 457
    r = fixture_db.execute("SELECT * FROM calendar WHERE date = '2026-08-31'").fetchone()
    assert (
        r["period_month"],
        r["quarter"],
        r["fiscal_year"],
        r["fiscal_period_no"],
        r["is_month_end"],
    ) == ("2026-08", "2026-Q3", 2026, 8, 1)
    r = fixture_db.execute("SELECT * FROM calendar WHERE date = '2026-02-28'").fetchone()
    assert (r["is_month_end"], r["quarter"]) == (1, "2026-Q1")
    assert (
        fixture_db.execute("SELECT COUNT(*) FROM calendar WHERE is_month_end = 1").fetchone()[0]
        == 15
    )


def test_rebuild_with_fiscal_year_start_month(loaded_tmp_db):
    db.rebuild(loaded_tmp_db, fiscal_year_start_month=7)
    r = loaded_tmp_db.execute("SELECT * FROM calendar WHERE date = '2026-08-05'").fetchone()
    assert (r["fiscal_year"], r["fiscal_period_no"]) == (2026, 2)
    r = loaded_tmp_db.execute("SELECT * FROM calendar WHERE date = '2026-06-15'").fetchone()
    assert (r["fiscal_year"], r["fiscal_period_no"]) == (2025, 12)
    with pytest.raises(ValueError):
        db.rebuild(loaded_tmp_db, fiscal_year_start_month=13)


def test_proforma_excluded_from_chain_view(tmp_db):
    body = (FIXTURES / "agent_szamla_active.xml").read_bytes()
    body = body.replace(b"<tipus>SZ</tipus>", b"<tipus>DB</tipus>").replace(
        b"SZLA-2026-3", b"DBK-2026-1"
    )
    db.insert_raw(tmp_db, "agent", "DBK-2026-1", body, fetched_at="2026-09-01T00:00:00Z")
    db.rebuild(tmp_db)
    r = row(tmp_db, "DBK-2026-1")
    assert (r["doc_type"], r["pay_status"]) == ("proforma", "unpaid")
    assert tmp_db.execute("SELECT COUNT(*) FROM v_chain").fetchone()[0] == 0


# --- rebuild semantics -------------------------------------------------------


def test_rebuild_is_idempotent_byte_identical(loaded_tmp_db):
    first = dump(loaded_tmp_db)
    counts = db.rebuild(loaded_tmp_db)
    assert counts == {
        "invoice": 6,
        "invoice_line": 7,
        "invoice_vat": 7,
        "payment": 3,
        "customer": 4,
        "calendar": 457,
    }
    second = dump(loaded_tmp_db)
    assert first == second
    assert len(first) > 1000


def test_rebuild_uses_latest_fetched_body_per_source(loaded_tmp_db):
    body = (FIXTURES / "agent_szamla_active.xml").read_bytes()
    newer = body.replace(
        b"<megjegyzes></megjegyzes>", "<megjegyzes>frissítve</megjegyzes>".encode()
    )
    db.insert_raw(loaded_tmp_db, "agent", "SZLA-2026-3", newer, fetched_at="2026-09-02T00:00:00Z")
    db.rebuild(loaded_tmp_db)
    assert row(loaded_tmp_db, "SZLA-2026-3")["note"] == "frissítve"
    older = body.replace(b"<megjegyzes></megjegyzes>", "<megjegyzes>régi</megjegyzes>".encode())
    db.insert_raw(loaded_tmp_db, "agent", "SZLA-2026-3", older, fetched_at="2026-08-01T00:00:00Z")
    db.rebuild(loaded_tmp_db)
    assert row(loaded_tmp_db, "SZLA-2026-3")["note"] == "frissítve"


def test_rebuild_agent_only_assigns_sequential_modification_index(tmp_db):
    for name in ("agent_szamla_active.xml", "agent_szamla_modifier.xml"):
        body = (FIXTURES / name).read_bytes()
        db.insert_raw(tmp_db, "agent", name, body, fetched_at="2026-09-01T00:00:00Z")
    db.rebuild(tmp_db)
    assert row(tmp_db, "SZLA-2026-3")["modification_index"] == 0
    assert row(tmp_db, "SZLA-2026-4")["modification_index"] == 1
    assert row(tmp_db, "SZLA-2026-4")["nav_operation"] is None
    assert row(tmp_db, "SZLA-2026-4")["source_flags"] == "agent"


def test_rebuild_empty_raw_yields_empty_tables(tmp_db):
    counts = db.rebuild(tmp_db)
    assert counts == {
        t: 0 for t in ("invoice", "invoice_line", "invoice_vat", "payment", "customer", "calendar")
    }


def test_load_fixture_raw_counts(tmp_db):
    load_fixture_raw(tmp_db)
    counts = {
        r[0]: r[1]
        for r in tmp_db.execute("SELECT source, COUNT(*) FROM raw_documents GROUP BY source")
    }
    assert counts == {"agent": 5, "nav_digest": 6, "nav_data": 1}
