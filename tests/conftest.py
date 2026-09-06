"""Shared pytest fixtures for the controller kit test suite.

`fixture_db` (session scope) rebuilds tests/fixtures/fixture.db on every session from the XML
fixtures through the real raw_documents -> db.rebuild() path. Other test modules (report
engine, Excel, validation) reuse it, so its content is stable. Contents (period 2026-08):

SZLA-2026-1    invoice   chain SZLA-2026-1   HUF  agent,nav_digest           pay_status void
    kelt 2026-08-05, telj 08-05, due 08-20, transfer, net 120000 vat 28000 gross 148000,
    lines 27% (100000) + 5% (20000), payment 100000 on 08-18, customer 501 Alfa Ügyfél Zrt.,
    order_ref PO-2026-11. Void because the chain is stornoed by SZLA-2026-2.
SZLA-2026-2    storno    chain SZLA-2026-1   HUF  agent,nav_digest           pay_status void
    kelt 08-25, storno of SZLA-2026-1, amounts -120000/-28000/-148000, modification_index 1.
SZLA-2026-3    invoice   chain SZLA-2026-3   HUF  agent,nav_digest           pay_status paid
    kelt 08-10, cash, 50000/13500/63500, one 27% line, payment 63500 on 08-10, customer 502.
SZLA-2026-4    modifier  chain SZLA-2026-3   HUF  agent,nav_digest           pay_status unpaid
    kelt 08-22, due 09-06, transfer, 10000/2700/12700 (one added 27% line), modification_index 1.
E-SZLA-2026-1  invoice   chain E-SZLA-2026-1 EUR  agent,nav_data,nav_digest  pay_status partial
    kelt 08-12, due 09-11, e-invoice, 1000/0/1000 EUR, VAT code EU (NAV: KBAET). Agent devizaarf
    is 400 but the NAV rate 399.5 wins: fx_rate_invoice 399.5, net_huf 399500. Payment 600 EUR
    at rate 400 = paid_huf 240000. Customer 601 Gamma GmbH (Ausztria, ATU12345678).
SZLA-2026-5    invoice   chain SZLA-2026-5   HUF  nav_digest                 pay_status unpaid
    digest only: kelt 08-28, 30000/8100/38100, no lines/payments, payment_method other,
    due NULL, customer Digest Only Kft. (sha1 key, tax number 45678901).

v_chain: SZLA-2026-1 stornoed (2 docs, gross 0, open -100000); SZLA-2026-3 modified (gross 76200,
open 12700); E-SZLA-2026-1 active (gross 399500, open 159500); SZLA-2026-5 active (open 38100).
customer: 4 rows (501, 502, 601, sha1 for Digest Only Kft.). calendar: 2025-07-01 .. 2026-09-30.
All raw rows carry fetched_at 2026-09-01T00:00:00Z so the build is deterministic.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import agent_client
import db
import nav_client
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
AGENT_FIXTURES = (
    "agent_szamla_normal.xml",
    "agent_szamla_storno.xml",
    "agent_szamla_active.xml",
    "agent_szamla_modifier.xml",
    "agent_szamla_eur.xml",
)
FETCHED_AT = "2026-09-01T00:00:00Z"


def load_fixture_raw(conn: sqlite3.Connection) -> None:
    """Insert every XML fixture into raw_documents (agent, nav_digest, nav_data)."""
    for name in AGENT_FIXTURES:
        body = (FIXTURES / name).read_bytes()
        number = agent_client.parse_invoice_xml(body).header.invoice_number
        db.insert_raw(conn, "agent", number, body, fetched_at=FETCHED_AT)
    for name in ("nav_digest_page1.xml", "nav_digest_page2.xml"):
        page = nav_client.parse_digest_response((FIXTURES / name).read_bytes())
        for digest in page.digests:
            db.insert_raw(
                conn, "nav_digest", digest.invoice_number, digest.xml, fetched_at=FETCHED_AT
            )
    body = (FIXTURES / "nav_invoicedata.xml").read_bytes()
    number = nav_client.parse_invoice_data(body).invoice_number
    db.insert_raw(conn, "nav_data", number, body, fetched_at=FETCHED_AT)


def build_fixture_db(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        extra = Path(str(path) + suffix)
        if extra.exists():
            extra.unlink()
    conn = db.connect(path)
    try:
        db.create_schema(conn)
        load_fixture_raw(conn)
        db.rebuild(conn)
    finally:
        conn.close()


@pytest.fixture(scope="session")
def fixture_db_path() -> Path:
    path = FIXTURES / "fixture.db"
    build_fixture_db(path)
    return path


@pytest.fixture(scope="session")
def fixture_db(fixture_db_path: Path):
    conn = db.connect(fixture_db_path)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def tmp_db(tmp_path: Path):
    """Empty database with the schema applied, in a temporary directory."""
    conn = db.connect(tmp_path / "test.db")
    db.create_schema(conn)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def loaded_tmp_db(tmp_db: sqlite3.Connection):
    """Temporary database with the fixture raw documents loaded and rebuilt (mutable)."""
    load_fixture_raw(tmp_db)
    db.rebuild(tmp_db)
    return tmp_db
