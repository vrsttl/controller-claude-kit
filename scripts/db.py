# /// script
# requires-python = ">=3.12"
# dependencies = ["requests>=2.32"]
# ///
"""SQLite invoice cache: append-only raw documents, rebuilt canonical tables.

Data flow (docs/PLAN.md section 1):

    raw_documents (agent / nav_digest / nav_data / csv bodies, gzip, append-only)
        -> rebuild()  drops and refills invoice, invoice_line, invoice_vat,
                      payment, customer, calendar in one transaction
        -> v_chain    per chain_root view

Field-name assumptions about the source XML are listed in docs/DATA-NOTES.md.
"""

from __future__ import annotations

import calendar as _calendar
import gzip
import hashlib
import os
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import agent_client
import nav_client

DEFAULT_DB_NAME = "invoices.db"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_V1 = [
    """
CREATE TABLE IF NOT EXISTS raw_documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL CHECK (source IN ('agent','nav_digest','nav_data','csv')),
  doc_key TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  source_hash TEXT NOT NULL,
  body BLOB NOT NULL,
  UNIQUE (source, doc_key, source_hash)
)""",
    """
CREATE TABLE IF NOT EXISTS invoice (
  invoice_number TEXT PRIMARY KEY,
  doc_type TEXT NOT NULL CHECK (doc_type IN ('invoice','modifier','storno','proforma')),
  nav_operation TEXT,
  chain_root TEXT NOT NULL,
  modification_index INTEGER NOT NULL DEFAULT 0,
  issue_date TEXT NOT NULL,
  delivery_date TEXT,
  due_date TEXT,
  payment_method TEXT NOT NULL DEFAULT 'other',
  payment_method_raw TEXT,
  is_einvoice INTEGER NOT NULL DEFAULT 0,
  customer_key TEXT NOT NULL,
  currency TEXT NOT NULL DEFAULT 'HUF',
  fx_rate_invoice REAL NOT NULL DEFAULT 1.0,
  net_amount REAL NOT NULL,
  vat_amount REAL NOT NULL,
  gross_amount REAL NOT NULL,
  net_huf REAL NOT NULL,
  vat_huf REAL NOT NULL,
  gross_huf REAL NOT NULL,
  paid_huf REAL NOT NULL DEFAULT 0,
  pay_status TEXT NOT NULL CHECK (pay_status IN ('unpaid','partial','paid','void')),
  order_ref TEXT,
  note TEXT,
  source_flags TEXT NOT NULL DEFAULT '',
  period_kelt TEXT NOT NULL,
  period_telj TEXT
)""",
    """
CREATE TABLE IF NOT EXISTS invoice_line (
  invoice_number TEXT NOT NULL REFERENCES invoice(invoice_number),
  line_no INTEGER NOT NULL,
  product_name TEXT NOT NULL,
  quantity REAL NOT NULL,
  unit TEXT,
  unit_price REAL NOT NULL,
  vat_rate TEXT NOT NULL,
  net REAL NOT NULL,
  vat REAL NOT NULL,
  gross REAL NOT NULL,
  ledger_code TEXT,
  PRIMARY KEY (invoice_number, line_no)
)""",
    """
CREATE TABLE IF NOT EXISTS invoice_vat (
  invoice_number TEXT NOT NULL REFERENCES invoice(invoice_number),
  vat_rate TEXT NOT NULL,
  net REAL NOT NULL,
  vat REAL NOT NULL,
  gross REAL NOT NULL,
  net_huf REAL NOT NULL,
  vat_huf REAL NOT NULL,
  PRIMARY KEY (invoice_number, vat_rate)
)""",
    """
CREATE TABLE IF NOT EXISTS payment (
  payment_id TEXT PRIMARY KEY,
  invoice_number TEXT NOT NULL REFERENCES invoice(invoice_number),
  pay_date TEXT NOT NULL,
  pay_type TEXT,
  amount REAL NOT NULL,
  bank_account TEXT,
  note TEXT
)""",
    """
CREATE TABLE IF NOT EXISTS customer (
  customer_key TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  tax_number TEXT,
  country TEXT,
  is_private INTEGER NOT NULL DEFAULT 0,
  first_invoice_date TEXT,
  last_invoice_date TEXT
)""",
    """
CREATE TABLE IF NOT EXISTS calendar (
  date TEXT PRIMARY KEY,
  period_month TEXT NOT NULL,
  quarter TEXT NOT NULL,
  fiscal_year INTEGER NOT NULL,
  fiscal_period_no INTEGER NOT NULL,
  is_month_end INTEGER NOT NULL DEFAULT 0
)""",
    """
CREATE TABLE IF NOT EXISTS staging_fokonyvi (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_number TEXT NOT NULL,
  line_no INTEGER,
  issue_date TEXT,
  delivery_date TEXT,
  due_date TEXT,
  customer_name TEXT,
  customer_taxno TEXT,
  product_name TEXT,
  ledger_code TEXT,
  vat_rate TEXT,
  net REAL,
  vat REAL,
  gross REAL,
  currency TEXT,
  pay_status_raw TEXT,
  paid_date TEXT,
  raw_json TEXT NOT NULL,
  imported_at TEXT NOT NULL
)""",
    """
CREATE TABLE IF NOT EXISTS staging_afalista (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_number TEXT NOT NULL,
  issue_date TEXT,
  customer_name TEXT,
  vat_rate TEXT,
  net REAL,
  vat REAL,
  gross REAL,
  raw_json TEXT NOT NULL,
  imported_at TEXT NOT NULL
)""",
    """
CREATE TABLE IF NOT EXISTS sync_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started TEXT NOT NULL,
  finished TEXT,
  source TEXT NOT NULL,
  window_from TEXT,
  window_to TEXT,
  fetched INTEGER NOT NULL DEFAULT 0,
  inserted INTEGER NOT NULL DEFAULT 0,
  errors INTEGER NOT NULL DEFAULT 0,
  note TEXT
)""",
    """
CREATE VIEW IF NOT EXISTS v_chain AS
SELECT chain_root,
       SUM(net_huf) AS effective_net_huf,
       SUM(vat_huf) AS effective_vat_huf,
       SUM(gross_huf) AS effective_gross_huf,
       COUNT(*) AS doc_count,
       CASE WHEN SUM(CASE WHEN doc_type = 'storno' THEN 1 ELSE 0 END) > 0 THEN 'stornoed'
            WHEN SUM(CASE WHEN doc_type = 'modifier' THEN 1 ELSE 0 END) > 0 THEN 'modified'
            ELSE 'active' END AS chain_status,
       SUM(gross_huf) - SUM(paid_huf) AS open_huf
FROM invoice
WHERE doc_type != 'proforma'
GROUP BY chain_root""",
]

# Adding a schema version is one dict entry: MIGRATIONS[2] = ["ALTER TABLE ...", ...]
MIGRATIONS: dict[int, list[str]] = {1: SCHEMA_V1}

CANONICAL_TABLES = ("payment", "invoice_line", "invoice_vat", "invoice", "customer", "calendar")


def default_db_path() -> Path:
    base = os.environ.get("RIPORTOK_DIR")
    root = Path(base) if base else Path.home() / "Riportok"
    return root / "data" / DEFAULT_DB_NAME


def connect(path: str | os.PathLike[str]) -> sqlite3.Connection:
    """Open (and create) the cache database with WAL and foreign keys on."""
    p = str(path)
    if p != ":memory:":
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> int:
    """Apply pending MIGRATIONS by PRAGMA user_version. Returns the final version."""
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    for version in sorted(MIGRATIONS):
        if version <= current:
            continue
        for stmt in MIGRATIONS[version]:
            conn.execute(stmt)
        conn.execute(f"PRAGMA user_version = {version}")
        current = version
    return current


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Pure helpers (spec-independent business rules)
# ---------------------------------------------------------------------------


def vat_rate_pct(code: str | None) -> float | None:
    """Numeric szamlazz.hu VAT codes ('27', '5', '0') to percent; symbolic codes to None."""
    if code is None:
        return None
    text = str(code).strip().replace("%", "").replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _fold(text: str) -> str:
    """Casefold and strip accents: 'Átutalás' -> 'atutalas'."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


_PAYMENT_METHOD_KEYWORDS = (
    ("transfer", ("atutal", "transfer", "utalas", "wire")),
    ("card", ("kartya", "card")),
    ("cash", ("keszpenz", "cash")),
)


def normalize_payment_method(raw: str | None, unified: str | None = None) -> str:
    """Map szamlazz.hu payment labels to transfer|cash|card|other.

    `unified` is the fizmodunified value when present, `raw` the free-text fizmod label.
    """
    for candidate in (unified, raw):
        if not candidate:
            continue
        folded = _fold(candidate)
        for target, keywords in _PAYMENT_METHOD_KEYWORDS:
            if any(k in folded for k in keywords):
                return target
    return "other"


def derive_pay_status(
    doc_type: str, gross_huf: float, paid_huf: float, chain_has_storno: bool
) -> str:
    """Pure pay-status rule with 1 HUF tolerance; cash/card auto-paid is a report option."""
    if doc_type == "storno" or chain_has_storno:
        return "void"
    if doc_type == "proforma":
        return "unpaid"
    target = abs(gross_huf)
    paid = abs(paid_huf)
    if paid >= target - 1:
        return "paid"
    if paid > 0:
        return "partial"
    return "unpaid"


def _norm_name(name: str | None) -> str:
    text = _fold(name or "")
    text = re.sub(r"[.,;:'\"()]", " ", text)
    return " ".join(text.split())


def _norm_taxno(taxno: str | None) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", taxno or "").upper()


def customer_key(szamlazz_id: str | None, name: str | None, tax_number: str | None) -> str:
    """szamlazz.hu customer id when present, else sha1(normalized name|taxno)[:16]."""
    ident = (szamlazz_id or "").strip()
    if ident and ident != "0":
        return ident
    payload = f"{_norm_name(name)}|{_norm_taxno(tax_number)}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


_SPACE_CHARS = " \u00a0\u2009\u202f"


def parse_amount(text: str | float | int | None) -> float | None:
    """Tolerant number parser: '1 234 567,89', '1234567.89', '1.234.567,89', '-12'."""
    if text is None:
        return None
    if isinstance(text, int | float):
        return float(text)
    s = str(text).strip()
    for ch in _SPACE_CHARS:
        s = s.replace(ch, "")
    s = s.replace("Ft", "").replace("HUF", "").strip()
    if not s:
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


_DATE_PATTERNS = (
    re.compile(r"^(\d{4})[-./ ]+(\d{1,2})[-./ ]+(\d{1,2})\.?"),
    re.compile(r"^(\d{1,2})[-./]+(\d{1,2})[-./]+(\d{4})\.?$"),
)


def parse_date(text: str | None) -> str | None:
    """Accepts 2026-08-05, 2026.08.05., 2026. 08. 05., 05.08.2026, ISO datetimes -> ISO date."""
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    m = _DATE_PATTERNS[0].match(s)
    if m:
        y, mo, d = (int(g) for g in m.groups())
    else:
        m = _DATE_PATTERNS[1].match(s)
        if not m:
            return None
        d, mo, y = (int(g) for g in m.groups())
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def period_of(iso_date: str | None) -> str | None:
    return iso_date[:7] if iso_date else None


# ---------------------------------------------------------------------------
# Raw documents
# ---------------------------------------------------------------------------


def insert_raw(
    conn: sqlite3.Connection,
    source: str,
    doc_key: str,
    body: bytes,
    fetched_at: str | None = None,
) -> bool:
    """Append a raw document. Returns False when the identical body is already stored."""
    digest = hashlib.sha256(body).hexdigest()
    packed = gzip.compress(body, mtime=0)
    cur = conn.execute(
        "INSERT INTO raw_documents (source, doc_key, fetched_at, source_hash, body) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(source, doc_key, source_hash) DO NOTHING",
        (source, doc_key, fetched_at or now_iso(), digest, packed),
    )
    return cur.rowcount == 1


def latest_raw(conn: sqlite3.Connection, source: str) -> dict[str, bytes]:
    """Latest body per doc_key for a source (latest fetched_at wins, then highest id)."""
    rows = conn.execute(
        "SELECT doc_key, body FROM raw_documents WHERE source = ? ORDER BY fetched_at, id",
        (source,),
    ).fetchall()
    out: dict[str, bytes] = {}
    for row in rows:
        out[row["doc_key"]] = gzip.decompress(row["body"])
    return out


def known_doc_keys(conn: sqlite3.Connection, source: str) -> set[str]:
    rows = conn.execute("SELECT DISTINCT doc_key FROM raw_documents WHERE source = ?", (source,))
    return {r["doc_key"] for r in rows}


def log_sync(
    conn: sqlite3.Connection,
    source: str,
    started: str,
    finished: str | None = None,
    window_from: str | None = None,
    window_to: str | None = None,
    fetched: int = 0,
    inserted: int = 0,
    errors: int = 0,
    note: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO sync_log (started, finished, source, window_from, window_to, fetched, "
        "inserted, errors, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            started,
            finished or now_iso(),
            source,
            window_from,
            window_to,
            fetched,
            inserted,
            errors,
            note,
        ),
    )
    return int(cur.lastrowid or 0)


# ---------------------------------------------------------------------------
# Rebuild
# ---------------------------------------------------------------------------

# ASSUMPTION: szamlazz.hu <alap><tipus> codes. SZ/SS/HS are named on the
# Financial Data Connection page; the pro forma code is a guess (docs/DATA-NOTES.md).
DOC_TYPE_BY_TIPUS = {
    "SZ": "invoice",
    "SS": "storno",
    "HS": "modifier",
    "DB": "proforma",
    "D": "proforma",
}

DOC_TYPE_BY_NAV_OPERATION = {"CREATE": "invoice", "MODIFY": "modifier", "STORNO": "storno"}


@dataclass
class _Rec:
    invoice_number: str
    doc_type: str = "invoice"
    nav_operation: str | None = None
    chain_root: str = ""
    modification_index: int | None = None
    issue_date: str = ""
    delivery_date: str | None = None
    due_date: str | None = None
    payment_method: str = "other"
    payment_method_raw: str | None = None
    is_einvoice: int = 0
    customer_key: str = ""
    customer_name: str = ""
    customer_taxno: str | None = None
    customer_country: str | None = None
    customer_private: int = 0
    currency: str = "HUF"
    fx_rate: float = 1.0
    net: float = 0.0
    vat: float = 0.0
    gross: float = 0.0
    net_huf: float | None = None
    vat_huf: float | None = None
    gross_huf: float | None = None
    paid_huf: float = 0.0
    order_ref: str | None = None
    note: str | None = None
    sources: set[str] = field(default_factory=set)
    lines: list[agent_client.Line] = field(default_factory=list)
    vat_rows: list[tuple[str, float, float, float, float | None, float | None]] = field(
        default_factory=list
    )
    payments: list[agent_client.Payment] = field(default_factory=list)
    pay_status: str = "unpaid"


@dataclass
class _Cust:
    name: str
    tax_number: str | None
    country: str | None
    is_private: int
    first: str
    last: str
    last_number: str


def _doc_type_from_agent(header: agent_client.Header) -> str:
    code = (header.doc_type_code or "").strip().upper()
    if code in DOC_TYPE_BY_TIPUS:
        return DOC_TYPE_BY_TIPUS[code]
    return "modifier" if header.reference else "invoice"


def _currency(code: str | None) -> str:
    c = (code or "").strip().upper()
    if c in ("", "FT", "HUF"):
        return "HUF"
    return c


def _fx(rate: float | None, currency: str) -> float:
    if currency == "HUF":
        return 1.0
    if rate is None or rate == 0:
        return 1.0
    return float(rate)


def _merge_agent(rec: _Rec, doc: agent_client.ParsedInvoice) -> None:
    h, c = doc.header, doc.customer
    rec.sources.add("agent")
    rec.doc_type = _doc_type_from_agent(h)
    rec.chain_root = h.reference or rec.invoice_number
    rec.issue_date = h.issue_date or rec.issue_date
    rec.delivery_date = h.delivery_date
    rec.due_date = h.due_date
    rec.payment_method = normalize_payment_method(h.payment_method_raw, h.payment_method_unified)
    rec.payment_method_raw = h.payment_method_raw
    rec.is_einvoice = 1 if h.is_einvoice else 0
    rec.customer_key = customer_key(c.szamlazz_id, c.name, c.tax_number)
    rec.customer_name = c.name or ""
    rec.customer_taxno = c.tax_number or c.eu_tax_number
    rec.customer_country = c.country
    if c.is_private is not None:
        rec.customer_private = 1 if c.is_private else 0
    else:
        rec.customer_private = 0 if (c.tax_number or c.eu_tax_number) else 1
    rec.currency = _currency(h.currency)
    rec.fx_rate = _fx(h.fx_rate, rec.currency)
    rec.net, rec.vat, rec.gross = doc.total_net, doc.total_vat, doc.total_gross
    rec.order_ref = h.order_ref
    rec.note = h.note
    rec.lines = list(doc.lines)
    rec.payments = list(doc.payments)
    rec.vat_rows = [(v.vat_rate, v.net, v.vat, v.gross, None, None) for v in doc.vat_totals]


def _merge_digest(rec: _Rec, d: nav_client.NavDigest) -> None:
    rec.sources.add("nav_digest")
    rec.nav_operation = d.operation
    if "agent" not in rec.sources:
        rec.doc_type = DOC_TYPE_BY_NAV_OPERATION.get(d.operation or "", "invoice")
        rec.chain_root = d.original_invoice_number or rec.invoice_number
        rec.issue_date = d.issue_date or rec.issue_date
        rec.delivery_date = d.delivery_date
        rec.is_einvoice = 1 if d.appearance == "ELECTRONIC" else 0
        rec.customer_key = customer_key(None, d.customer_name, d.customer_tax_number)
        rec.customer_name = d.customer_name or ""
        rec.customer_taxno = d.customer_tax_number
        rec.customer_private = 0 if d.customer_tax_number else 1
        rec.currency = _currency(d.currency)
        rec.net = d.net or 0.0
        rec.vat = d.vat or 0.0
        rec.gross = rec.net + rec.vat
    if d.modification_index is not None:
        rec.modification_index = d.modification_index
    if d.net_huf is not None:
        rec.net_huf = d.net_huf
        rec.vat_huf = d.vat_huf or 0.0
        rec.gross_huf = rec.net_huf + rec.vat_huf


def _merge_nav_data(rec: _Rec, n: nav_client.NavInvoiceData) -> None:
    rec.sources.add("nav_data")
    if "agent" not in rec.sources:
        if "nav_digest" not in rec.sources:
            rec.doc_type = "modifier" if n.original_invoice_number else "invoice"
        rec.chain_root = n.original_invoice_number or rec.invoice_number
        rec.customer_key = customer_key(None, n.customer_name, n.customer_tax_number)
        rec.customer_name = n.customer_name or ""
        rec.customer_taxno = n.customer_tax_number
        rec.customer_private = 0 if n.customer_tax_number else 1
        rec.is_einvoice = 1 if n.appearance == "ELECTRONIC" else 0
    rec.issue_date = n.issue_date or rec.issue_date
    rec.delivery_date = n.delivery_date or rec.delivery_date
    rec.currency = _currency(n.currency)
    rec.fx_rate = _fx(n.exchange_rate, rec.currency)
    rec.net, rec.vat, rec.gross = n.net, n.vat, n.gross
    if n.modification_index is not None:
        rec.modification_index = n.modification_index
    rec.net_huf, rec.vat_huf, rec.gross_huf = n.net_huf, n.vat_huf, n.gross_huf
    nav_by_rate = {r.vat_rate: r for r in n.vat_rows}
    if rec.vat_rows:
        rec.vat_rows = [
            (
                rate,
                net,
                vat,
                gross,
                nav_by_rate[rate].net_huf if rate in nav_by_rate else None,
                nav_by_rate[rate].vat_huf if rate in nav_by_rate else None,
            )
            for rate, net, vat, gross, _, _ in rec.vat_rows
        ]
    else:
        rec.vat_rows = [
            (r.vat_rate, r.net, r.vat, r.gross, r.net_huf, r.vat_huf) for r in n.vat_rows
        ]


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, 1)


def _calendar_rows(
    first: date, last: date, fiscal_year_start_month: int
) -> list[tuple[str, str, str, int, int, int]]:
    rows = []
    d = first
    while d <= last:
        month_end = _calendar.monthrange(d.year, d.month)[1]
        fiscal_year = d.year if d.month >= fiscal_year_start_month else d.year - 1
        if fiscal_year_start_month == 1:
            fiscal_year = d.year
        fiscal_period_no = (d.month - fiscal_year_start_month) % 12 + 1
        rows.append(
            (
                d.isoformat(),
                d.strftime("%Y-%m"),
                f"{d.year}-Q{(d.month - 1) // 3 + 1}",
                fiscal_year,
                fiscal_period_no,
                1 if d.day == month_end else 0,
            )
        )
        d += timedelta(days=1)
    return rows


def _load_records(conn: sqlite3.Connection) -> dict[str, _Rec]:
    recs: dict[str, _Rec] = {}

    def rec_for(number: str) -> _Rec:
        if number not in recs:
            recs[number] = _Rec(invoice_number=number, chain_root=number)
        return recs[number]

    for body in latest_raw(conn, "agent").values():
        doc = agent_client.parse_invoice_xml(body)
        _merge_agent(rec_for(doc.header.invoice_number), doc)
    digests = {}
    for body in latest_raw(conn, "nav_digest").values():
        d = nav_client.parse_digest_element(body)
        digests[d.invoice_number] = d
    for number in sorted(digests):
        _merge_digest(rec_for(number), digests[number])
    navdata = {}
    for body in latest_raw(conn, "nav_data").values():
        n = nav_client.parse_invoice_data(body)
        navdata[n.invoice_number] = n
    for number in sorted(navdata):
        _merge_nav_data(rec_for(number), navdata[number])
    return recs


def _finalize(recs: dict[str, _Rec]) -> None:
    # HUF fallback: amount x invoice rate when no NAV value is present.
    for rec in recs.values():
        if rec.net_huf is None:
            rec.net_huf = rec.net * rec.fx_rate
            rec.vat_huf = rec.vat * rec.fx_rate
            rec.gross_huf = rec.gross * rec.fx_rate
        rec.paid_huf = sum(p.amount * (p.fx_rate or rec.fx_rate) for p in rec.payments)
    # Sequential modification_index for chain members that NAV did not number.
    chains: dict[str, list[_Rec]] = {}
    for rec in recs.values():
        chains.setdefault(rec.chain_root, []).append(rec)
    for root, members in chains.items():
        used = [m.modification_index for m in members if m.modification_index is not None]
        next_index = max(used, default=0) + 1
        for m in sorted(members, key=lambda r: (r.issue_date, r.invoice_number)):
            if m.modification_index is None:
                if m.invoice_number == root:
                    m.modification_index = 0
                else:
                    m.modification_index = next_index
                    next_index += 1
    storno_roots = {r.chain_root for r in recs.values() if r.doc_type == "storno"}
    for rec in recs.values():
        rec.pay_status = derive_pay_status(
            rec.doc_type, rec.gross_huf or 0.0, rec.paid_huf, rec.chain_root in storno_roots
        )


def rebuild(conn: sqlite3.Connection, fiscal_year_start_month: int = 1) -> dict[str, int]:
    """Drop and refill every canonical table from raw_documents in one transaction."""
    if not 1 <= fiscal_year_start_month <= 12:
        raise ValueError("fiscal_year_start_month must be 1..12")
    recs = _load_records(conn)
    _finalize(recs)
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN")
    try:
        for table in CANONICAL_TABLES:
            conn.execute(f"DELETE FROM {table}")
        customers: dict[str, _Cust] = {}
        for number in sorted(recs):
            rec = recs[number]
            cust = customers.get(rec.customer_key)
            if cust is None:
                customers[rec.customer_key] = _Cust(
                    name=rec.customer_name,
                    tax_number=rec.customer_taxno,
                    country=rec.customer_country,
                    is_private=rec.customer_private,
                    first=rec.issue_date,
                    last=rec.issue_date,
                    last_number=number,
                )
                continue
            cust.first = min(cust.first, rec.issue_date)
            if (rec.issue_date, number) > (cust.last, cust.last_number):
                cust.name = rec.customer_name
                cust.tax_number = rec.customer_taxno
                cust.country = rec.customer_country
                cust.is_private = rec.customer_private
                cust.last = rec.issue_date
                cust.last_number = number
        for key in sorted(customers):
            c = customers[key]
            conn.execute(
                "INSERT INTO customer (customer_key, name, tax_number, country, is_private, "
                "first_invoice_date, last_invoice_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (key, c.name, c.tax_number, c.country, c.is_private, c.first, c.last),
            )
        for number in sorted(recs):
            rec = recs[number]
            conn.execute(
                "INSERT INTO invoice (invoice_number, doc_type, nav_operation, chain_root, "
                "modification_index, issue_date, delivery_date, due_date, payment_method, "
                "payment_method_raw, is_einvoice, customer_key, currency, fx_rate_invoice, "
                "net_amount, vat_amount, gross_amount, net_huf, vat_huf, gross_huf, paid_huf, "
                "pay_status, order_ref, note, source_flags, period_kelt, period_telj) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                "?, ?, ?)",
                (
                    number,
                    rec.doc_type,
                    rec.nav_operation,
                    rec.chain_root,
                    rec.modification_index or 0,
                    rec.issue_date,
                    rec.delivery_date,
                    rec.due_date,
                    rec.payment_method,
                    rec.payment_method_raw,
                    rec.is_einvoice,
                    rec.customer_key,
                    rec.currency,
                    rec.fx_rate,
                    rec.net,
                    rec.vat,
                    rec.gross,
                    rec.net_huf,
                    rec.vat_huf,
                    rec.gross_huf,
                    rec.paid_huf,
                    rec.pay_status,
                    rec.order_ref,
                    rec.note,
                    ",".join(sorted(rec.sources)),
                    period_of(rec.issue_date),
                    period_of(rec.delivery_date),
                ),
            )
            for line in rec.lines:
                conn.execute(
                    "INSERT INTO invoice_line (invoice_number, line_no, product_name, quantity, "
                    "unit, unit_price, vat_rate, net, vat, gross, ledger_code) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        number,
                        line.line_no,
                        line.name,
                        line.quantity,
                        line.unit,
                        line.unit_price,
                        line.vat_rate,
                        line.net,
                        line.vat,
                        line.gross,
                        line.ledger_code,
                    ),
                )
            for rate, net, vat, gross, net_huf, vat_huf in rec.vat_rows:
                conn.execute(
                    "INSERT OR REPLACE INTO invoice_vat (invoice_number, vat_rate, net, vat, "
                    "gross, net_huf, vat_huf) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        number,
                        rate,
                        net,
                        vat,
                        gross,
                        net * rec.fx_rate if net_huf is None else net_huf,
                        vat * rec.fx_rate if vat_huf is None else vat_huf,
                    ),
                )
            for p in rec.payments:
                conn.execute(
                    "INSERT INTO payment (payment_id, invoice_number, pay_date, pay_type, amount, "
                    "bank_account, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"{number}#{p.seq}",
                        number,
                        p.pay_date or rec.issue_date,
                        p.pay_type,
                        p.amount,
                        p.bank_account,
                        p.note,
                    ),
                )
        issue_dates = sorted(r.issue_date for r in recs.values() if r.issue_date)
        if issue_dates:
            first = _add_months(_month_start(date.fromisoformat(issue_dates[0])), -13)
            last = _add_months(_month_start(date.fromisoformat(issue_dates[-1])), 2) - timedelta(
                days=1
            )
            conn.executemany(
                "INSERT INTO calendar (date, period_month, quarter, fiscal_year, fiscal_period_no, "
                "is_month_end) VALUES (?, ?, ?, ?, ?, ?)",
                _calendar_rows(first, last, fiscal_year_start_month),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    counts = {}
    for table in ("invoice", "invoice_line", "invoice_vat", "payment", "customer", "calendar"):
        counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    return counts
