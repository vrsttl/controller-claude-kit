"""Deterministic synthetic invoice database for the report engine tests.

`make_engine_db(path)` builds the schema through `db.create_schema` (the data
layer, always present in the kit; `SCHEMA_SQL` below is a verbatim copy kept
only as a documented safety net, and the test suite asserts it is not used)
and fills it with a
seeded dataset: 14 months ending 2026-08, 12 customers, ~25 invoices a month,
storno and modifier chains, planted overdue buckets, partial payments, unpaid
cash invoices, an FX deviation, a duplicate customer name, and staging rows for
2026-08 that tie out except one deliberate 1 HUF VAT delta (toggle with
`set_afalista_delta`).

Every planted row is recorded in the module-level `PLANTED` dict so tests can
assert on exact invoice numbers.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

try:
    from db import create_schema as _db_create_schema
except ImportError:  # pragma: no cover - safety net only, see DB_SCHEMA_AVAILABLE
    _db_create_schema = None
DB_SCHEMA_AVAILABLE = _db_create_schema is not None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS raw_documents (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL CHECK (source IN ('agent','nav_digest','nav_data','csv')), doc_key TEXT NOT NULL, fetched_at TEXT NOT NULL, source_hash TEXT NOT NULL, body BLOB NOT NULL, UNIQUE (source, doc_key, source_hash));
CREATE TABLE IF NOT EXISTS invoice (invoice_number TEXT PRIMARY KEY, doc_type TEXT NOT NULL CHECK (doc_type IN ('invoice','modifier','storno','proforma')), nav_operation TEXT, chain_root TEXT NOT NULL, modification_index INTEGER NOT NULL DEFAULT 0, issue_date TEXT NOT NULL, delivery_date TEXT, due_date TEXT, payment_method TEXT NOT NULL DEFAULT 'other', payment_method_raw TEXT, is_einvoice INTEGER NOT NULL DEFAULT 0, customer_key TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'HUF', fx_rate_invoice REAL NOT NULL DEFAULT 1.0, net_amount REAL NOT NULL, vat_amount REAL NOT NULL, gross_amount REAL NOT NULL, net_huf REAL NOT NULL, vat_huf REAL NOT NULL, gross_huf REAL NOT NULL, paid_huf REAL NOT NULL DEFAULT 0, pay_status TEXT NOT NULL CHECK (pay_status IN ('unpaid','partial','paid','void')), order_ref TEXT, note TEXT, source_flags TEXT NOT NULL DEFAULT '', period_kelt TEXT NOT NULL, period_telj TEXT);
CREATE TABLE IF NOT EXISTS invoice_line (invoice_number TEXT NOT NULL REFERENCES invoice(invoice_number), line_no INTEGER NOT NULL, product_name TEXT NOT NULL, quantity REAL NOT NULL, unit TEXT, unit_price REAL NOT NULL, vat_rate TEXT NOT NULL, net REAL NOT NULL, vat REAL NOT NULL, gross REAL NOT NULL, ledger_code TEXT, PRIMARY KEY (invoice_number, line_no));
CREATE TABLE IF NOT EXISTS invoice_vat (invoice_number TEXT NOT NULL REFERENCES invoice(invoice_number), vat_rate TEXT NOT NULL, net REAL NOT NULL, vat REAL NOT NULL, gross REAL NOT NULL, net_huf REAL NOT NULL, vat_huf REAL NOT NULL, PRIMARY KEY (invoice_number, vat_rate));
CREATE TABLE IF NOT EXISTS payment (payment_id TEXT PRIMARY KEY, invoice_number TEXT NOT NULL REFERENCES invoice(invoice_number), pay_date TEXT NOT NULL, pay_type TEXT, amount REAL NOT NULL, bank_account TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS customer (customer_key TEXT PRIMARY KEY, name TEXT NOT NULL, tax_number TEXT, country TEXT, is_private INTEGER NOT NULL DEFAULT 0, first_invoice_date TEXT, last_invoice_date TEXT);
CREATE TABLE IF NOT EXISTS calendar (date TEXT PRIMARY KEY, period_month TEXT NOT NULL, quarter TEXT NOT NULL, fiscal_year INTEGER NOT NULL, fiscal_period_no INTEGER NOT NULL, is_month_end INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS staging_fokonyvi (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_number TEXT NOT NULL, line_no INTEGER, issue_date TEXT, delivery_date TEXT, due_date TEXT, customer_name TEXT, customer_taxno TEXT, product_name TEXT, ledger_code TEXT, vat_rate TEXT, net REAL, vat REAL, gross REAL, currency TEXT, pay_status_raw TEXT, paid_date TEXT, raw_json TEXT NOT NULL, imported_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS staging_afalista (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_number TEXT NOT NULL, issue_date TEXT, customer_name TEXT, vat_rate TEXT, net REAL, vat REAL, gross REAL, raw_json TEXT NOT NULL, imported_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sync_log (id INTEGER PRIMARY KEY AUTOINCREMENT, started TEXT NOT NULL, finished TEXT, source TEXT NOT NULL, window_from TEXT, window_to TEXT, fetched INTEGER NOT NULL DEFAULT 0, inserted INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0, note TEXT);
CREATE VIEW IF NOT EXISTS v_chain AS SELECT chain_root, SUM(net_huf) AS effective_net_huf, SUM(vat_huf) AS effective_vat_huf, SUM(gross_huf) AS effective_gross_huf, COUNT(*) AS doc_count, CASE WHEN SUM(CASE WHEN doc_type = 'storno' THEN 1 ELSE 0 END) > 0 THEN 'stornoed' WHEN SUM(CASE WHEN doc_type = 'modifier' THEN 1 ELSE 0 END) > 0 THEN 'modified' ELSE 'active' END AS chain_status, SUM(gross_huf) - SUM(paid_huf) AS open_huf FROM invoice WHERE doc_type != 'proforma' GROUP BY chain_root;
"""  # noqa: E501

SEED = 20260906
FIRST_MONTH = (2025, 7)
LAST_MONTH = (2026, 8)
AS_OF = date(2026, 8, 31)
RUN_DATE = date(2026, 9, 3)
SYNC_FINISHED = "2026-09-02T06:03:10"
EUR_FX = 395.5
INVOICES_PER_MONTH = 25

CUSTOMERS = [
    # key, name, tax_number, country, is_private, currency, weight
    ("C01", "Acme Kft.", "12345678-2-41", "HU", 0, "HUF", 9),
    ("C02", "ACME KFT.", "12345679-2-41", "HU", 0, "HUF", 3),
    ("C03", "Beta Zrt.", "23456789-2-13", "HU", 0, "HUF", 6),
    ("C04", "Gamma Bt.", "34567890-1-42", "HU", 0, "HUF", 4),
    ("C05", "Delta Systems GmbH", "ATU12345678", "AT", 0, "EUR", 0),
    ("C06", "Epszilon Kft.", "45678901-2-43", "HU", 0, "HUF", 4),
    ("C07", "Zéta Nonprofit Kft.", "56789012-2-01", "HU", 0, "HUF", 2),
    ("C08", "Éta Szolgáltató Kft.", "67890123-2-19", "HU", 0, "HUF", 3),
    ("C09", "Théta Kereskedőház Zrt.", "78901234-2-44", "HU", 0, "HUF", 5),
    ("C10", "Ióta Kft.", "89012345-2-02", "HU", 0, "HUF", 2),
    ("C11", "Kovács Péter", None, "HU", 1, "HUF", 1),
    ("C12", "Lambda Startup Kft.", None, "HU", 0, "HUF", 2),
]
CHURNED_CUSTOMER = "C10"  # invoices only until 2026-03
NEW_CUSTOMER = "C12"  # first invoice in 2026-08
EUR_CUSTOMER = "C05"

PRODUCTS = [
    # name, unit_price_huf, vat_rate, unit
    ("Szoftverfejlesztés", 25000, "27", "óra"),
    ("Rendszerüzemeltetés", 180000, "27", "hó"),
    ("Tanácsadás", 30000, "27", "óra"),
    ("Licenc", 120000, "27", "db"),
    ("Szakkönyv", 8000, "5", "db"),
    ("Oktatás", 45000, "AAM", "nap"),
    ("Támogatás", 60000, "27", "hó"),
    ("Hosting", 15000, "27", "hó"),
]

PAY_METHODS = ["transfer"] * 14 + ["card"] * 3 + ["cash"] * 2 + ["other"]

# Planted overdue invoices as of AS_OF: (month, due_date, expected bucket)
OVERDUE_PLAN = [
    ((2026, 8), date(2026, 8, 20), "1_30"),
    ((2026, 7), date(2026, 7, 20), "31_60"),
    ((2026, 6), date(2026, 6, 20), "61_90"),
    ((2026, 4), date(2026, 4, 20), "90_plus"),
]

PLANTED: dict[str, object] = {}


def _months() -> list[tuple[int, int]]:
    out = []
    y, m = FIRST_MONTH
    while (y, m) <= LAST_MONTH:
        out.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def _quarter_of(y: int, m: int) -> tuple[int, int]:
    return y, (m - 1) // 3 + 1


def _vat_of(net: float, rate: str) -> float:
    if rate.isdigit():
        return round(net * int(rate) / 100, 2)
    return 0.0


class _Doc:
    """Mutable holder for one document while the dataset is generated."""

    def __init__(self, **kw):
        self.lines: list[dict] = []
        self.payments: list[tuple[date, float]] = []
        self.number: str | None = None
        self.chain_root_doc: _Doc | None = None
        self.doc_type = "invoice"
        self.pay_status = "unpaid"
        self.paid_amount = 0.0
        self.fx_deviation = 1.0
        self.planted: str | None = None
        for k, v in kw.items():
            setattr(self, k, v)

    @property
    def net(self) -> float:
        return round(sum(ln["net"] for ln in self.lines), 2)

    @property
    def vat(self) -> float:
        return round(sum(ln["vat"] for ln in self.lines), 2)

    @property
    def gross(self) -> float:
        return round(self.net + self.vat, 2)


def _build_docs(rng: random.Random) -> list[_Doc]:
    docs: list[_Doc] = []
    cust_by_key = {c[0]: c for c in CUSTOMERS}
    months = _months()

    for y, m in months:
        weighted = []
        for c in CUSTOMERS:
            key = c[0]
            if key == EUR_CUSTOMER:
                continue
            if key == CHURNED_CUSTOMER and (y, m) > (2026, 3):
                continue
            if key == NEW_CUSTOMER and (y, m) < (2026, 8):
                continue
            weighted.extend([key] * c[6])

        month_docs: list[_Doc] = []
        for _ in range(INVOICES_PER_MONTH):
            key = rng.choice(weighted)
            month_docs.append(_new_invoice(rng, y, m, cust_by_key[key]))
        # two EUR invoices per month
        for _ in range(2):
            month_docs.append(_new_invoice(rng, y, m, cust_by_key[EUR_CUSTOMER]))
        # force the payment methods the planted rows need (not left to the RNG)
        for d in month_docs[:2]:
            d.method = "cash" if (y, m) == (2026, 8) else "transfer"
            d.due = d.issue if d.method == "cash" else d.issue + timedelta(days=15)
        month_docs[2].method = "transfer"
        month_docs[2].due = month_docs[2].issue + timedelta(days=15)
        if (y, m) == LAST_MONTH:
            # z-score outlier: one 8 000 000 HUF invoice
            big = month_docs[3]
            big.lines = [
                {
                    "product_name": "Licenc",
                    "quantity": 10,
                    "unit": "db",
                    "unit_price": 800000,
                    "vat_rate": "27",
                    "net": 8000000.0,
                    "vat": 2160000.0,
                    "gross": 10160000.0,
                }
            ]
            big.planted = "outlier"

        # chains: one storno + one modifier per quarter. The last quarter is
        # split so the storno crosses a month boundary (2026-07 -> 2026-08) and
        # the modifier lands inside 2026-08.
        q = _quarter_of(y, m)
        if q == (2026, 3):
            if m == 7:
                _plant_storno(rng, month_docs, y, m, cust_by_key)
            if m == 8:
                _plant_modifier(rng, month_docs, y, m, cust_by_key)
        elif m % 3 == 2:
            _plant_storno(rng, month_docs, y, m, cust_by_key)
            _plant_modifier(rng, month_docs, y, m, cust_by_key)
        docs.extend(month_docs)
    return docs


def _new_invoice(rng: random.Random, y: int, m: int, cust: tuple) -> _Doc:
    key, _name, _tax, _country, _priv, currency, _w = cust
    issue = date(y, m, rng.randint(1, 28))
    delivery = issue - timedelta(days=rng.choice([0, 0, 0, 3, 7]))
    method = "transfer" if currency == "EUR" else rng.choice(PAY_METHODS)
    if method in ("cash", "card"):
        due = issue
    else:
        due = issue + timedelta(days=rng.choice([8, 15, 30]))
    fx = EUR_FX if currency == "EUR" else 1.0
    doc = _Doc(
        customer_key=key,
        currency=currency,
        fx=fx,
        issue=issue,
        delivery=delivery,
        due=due,
        method=method,
        is_einvoice=1 if rng.random() < 0.6 else 0,
    )
    for _ in range(rng.randint(1, 3)):
        name, price, rate, unit = rng.choice(PRODUCTS)
        if currency == "EUR":
            rate = "EU"
            price = round(price / EUR_FX, 2)
        qty = rng.randint(1, 10)
        net = round(qty * price, 2)
        vat = _vat_of(net, rate)
        doc.lines.append(
            {
                "product_name": name,
                "quantity": qty,
                "unit": unit,
                "unit_price": price,
                "vat_rate": rate,
                "net": net,
                "vat": vat,
                "gross": round(net + vat, 2),
            }
        )
    return doc


def _plant_storno(rng: random.Random, month_docs: list[_Doc], y: int, m: int, cust_by_key):
    # storno chain: original plus storno 10 days later (crosses month for 2026-07)
    orig = _new_invoice(rng, y, m, cust_by_key["C03"])
    orig.issue = date(y, m, 25) if (y, m) == (2026, 7) else date(y, m, 12)
    orig.delivery = orig.issue
    orig.due = orig.issue + timedelta(days=15)
    orig.method = "transfer"
    storno = _Doc(
        customer_key=orig.customer_key,
        currency=orig.currency,
        fx=orig.fx,
        issue=orig.issue + timedelta(days=10),
        delivery=orig.issue + timedelta(days=10),
        due=orig.issue + timedelta(days=10),
        method="transfer",
        is_einvoice=orig.is_einvoice,
    )
    storno.doc_type = "storno"
    storno.chain_root_doc = orig
    storno.lines = [
        {
            **ln,
            "quantity": -ln["quantity"],
            "net": -ln["net"],
            "vat": -ln["vat"],
            "gross": -ln["gross"],
        }
        for ln in orig.lines
    ]
    storno.delivery = orig.delivery
    orig.pay_status = "void"
    storno.pay_status = "void"
    orig.planted = f"storno_original_{y}_{m:02d}"
    storno.planted = f"storno_{y}_{m:02d}"
    month_docs.extend([orig, storno])


def _plant_modifier(rng: random.Random, month_docs: list[_Doc], y: int, m: int, cust_by_key):
    # modifier chain: original plus a -20% correction of the first line
    orig2 = _new_invoice(rng, y, m, cust_by_key["C09"])
    orig2.issue = date(y, m, 10)
    orig2.delivery = orig2.issue
    orig2.due = orig2.issue + timedelta(days=15)
    orig2.method = "transfer"
    mod = _Doc(
        customer_key=orig2.customer_key,
        currency=orig2.currency,
        fx=orig2.fx,
        issue=orig2.issue + timedelta(days=10),
        delivery=orig2.delivery,
        due=orig2.issue + timedelta(days=10),
        method="transfer",
        is_einvoice=orig2.is_einvoice,
    )
    mod.doc_type = "modifier"
    mod.chain_root_doc = orig2
    first = orig2.lines[0]
    net = -round(first["net"] * 0.2, 2)
    vat = _vat_of(net, first["vat_rate"])
    mod.lines = [
        {
            **first,
            "quantity": -round(first["quantity"] * 0.2, 2),
            "net": net,
            "vat": vat,
            "gross": round(net + vat, 2),
        }
    ]
    orig2.planted = f"modifier_original_{y}_{m:02d}"
    mod.planted = f"modifier_{y}_{m:02d}"
    month_docs.extend([orig2, mod])


def _assign_status_and_payments(rng: random.Random, docs: list[_Doc]) -> None:
    cutoff_paid = date(2026, 8, 20)
    sync_date = date(2026, 9, 2)
    overdue_todo = {plan[0]: plan for plan in OVERDUE_PLAN}
    partial_left = 2
    cash_unpaid_left = 2
    fx_dev_done = False
    for doc in docs:
        if doc.pay_status == "void":
            continue
        ym = (doc.issue.year, doc.issue.month)
        if doc.doc_type == "modifier":
            pay = doc.issue + timedelta(days=3)
            doc.pay_status = "paid"
            doc.payments.append((pay, doc.gross))
            doc.paid_amount = doc.gross
            continue
        if ym in overdue_todo and doc.method == "transfer" and doc.planted is None:
            _month, due, bucket = overdue_todo.pop(ym)
            doc.due = due
            doc.issue = min(doc.issue, due - timedelta(days=5))
            doc.delivery = min(doc.delivery, doc.issue)
            doc.pay_status = "unpaid"
            doc.planted = f"overdue_{bucket}"
            PLANTED[f"overdue_{bucket}"] = doc
            continue
        if (
            doc.method == "cash"
            and ym == (2026, 8)
            and cash_unpaid_left > 0
            and doc.planted is None
        ):
            cash_unpaid_left -= 1
            doc.pay_status = "unpaid"
            doc.planted = f"cash_unpaid_{cash_unpaid_left}"
            PLANTED[doc.planted] = doc
            continue
        if (
            doc.method == "transfer"
            and ym == (2026, 7)
            and partial_left > 0
            and doc.planted is None
        ):
            partial_left -= 1
            doc.pay_status = "partial"
            doc.paid_amount = round(doc.gross * 0.5, 2)
            doc.payments.append((doc.due, doc.paid_amount))
            doc.planted = f"partial_{partial_left}"
            PLANTED[doc.planted] = doc
            continue
        if doc.currency == "EUR" and ym == (2026, 8) and not fx_dev_done and doc.planted is None:
            fx_dev_done = True
            doc.fx_deviation = 1.01
            doc.planted = "fx_deviation"
            PLANTED["fx_deviation"] = doc
        if doc.method in ("cash", "card"):
            doc.pay_status = "paid"
            doc.paid_amount = doc.gross
            doc.payments.append((doc.issue, doc.gross))
            continue
        if doc.due <= cutoff_paid:
            if rng.random() < 0.8:
                pay = doc.due - timedelta(days=rng.randint(0, 7))
            else:
                pay = doc.due + timedelta(days=rng.randint(1, 20))
            pay = min(pay, sync_date)
            doc.pay_status = "paid"
            doc.paid_amount = doc.gross
            doc.payments.append((pay, doc.gross))
        else:
            doc.pay_status = "unpaid"
    assert not overdue_todo, f"overdue plan not fully planted: {overdue_todo}"
    assert cash_unpaid_left == 0 and partial_left == 0 and fx_dev_done


def _number_docs(docs: list[_Doc]) -> None:
    order = sorted(docs, key=lambda d: (d.issue, d.doc_type != "invoice", d.customer_key))
    seq: dict[int, int] = {}
    for doc in order:
        y = doc.issue.year
        seq[y] = seq.get(y, 0) + 1
        doc.number = f"SZ-{y}-{seq[y]:04d}"
    for doc in docs:
        if doc.planted:
            PLANTED[doc.planted] = doc


def _insert(conn: sqlite3.Connection, docs: list[_Doc]) -> None:
    cur = conn.cursor()
    for key, name, tax, country, priv, _cur, _w in CUSTOMERS:
        dates = sorted(d.issue for d in docs if d.customer_key == key)
        cur.execute(
            "INSERT INTO customer VALUES (?,?,?,?,?,?,?)",
            (
                key,
                name,
                tax,
                country,
                priv,
                dates[0].isoformat() if dates else None,
                dates[-1].isoformat() if dates else None,
            ),
        )
    pay_seq = 0
    for doc in docs:
        root = doc.chain_root_doc.number if doc.chain_root_doc else doc.number
        fx = doc.fx
        net_huf = round(doc.net * fx * doc.fx_deviation, 2)
        vat_huf = round(doc.vat * fx * doc.fx_deviation, 2)
        gross_huf = round(net_huf + vat_huf, 2)
        paid_huf = round(doc.paid_amount * fx, 2)
        nav_op = {"invoice": "CREATE", "modifier": "MODIFY", "storno": "STORNO"}[doc.doc_type]
        cur.execute(
            "INSERT INTO invoice VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                doc.number,
                doc.doc_type,
                nav_op,
                root,
                1 if doc.chain_root_doc else 0,
                doc.issue.isoformat(),
                doc.delivery.isoformat(),
                doc.due.isoformat(),
                doc.method,
                {
                    "transfer": "átutalás",
                    "cash": "készpénz",
                    "card": "bankkártya",
                    "other": "egyéb",
                }[doc.method],
                doc.is_einvoice,
                doc.customer_key,
                doc.currency,
                fx,
                doc.net,
                doc.vat,
                doc.gross,
                net_huf,
                vat_huf,
                gross_huf,
                paid_huf,
                doc.pay_status,
                None,
                doc.planted,
                "",
                doc.issue.strftime("%Y-%m"),
                doc.delivery.strftime("%Y-%m"),
            ),
        )
        for i, ln in enumerate(doc.lines, start=1):
            cur.execute(
                "INSERT INTO invoice_line VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    doc.number,
                    i,
                    ln["product_name"],
                    ln["quantity"],
                    ln["unit"],
                    ln["unit_price"],
                    ln["vat_rate"],
                    ln["net"],
                    ln["vat"],
                    ln["gross"],
                    "911",
                ),
            )
        by_rate: dict[str, list[float]] = {}
        for ln in doc.lines:
            acc = by_rate.setdefault(ln["vat_rate"], [0.0, 0.0])
            acc[0] = round(acc[0] + ln["net"], 2)
            acc[1] = round(acc[1] + ln["vat"], 2)
        for rate, (n, v) in by_rate.items():
            cur.execute(
                "INSERT INTO invoice_vat VALUES (?,?,?,?,?,?,?)",
                (
                    doc.number,
                    rate,
                    n,
                    v,
                    round(n + v, 2),
                    round(n * fx * doc.fx_deviation, 2),
                    round(v * fx * doc.fx_deviation, 2),
                ),
            )
        for pay_date, amount in doc.payments:
            pay_seq += 1
            cur.execute(
                "INSERT INTO payment VALUES (?,?,?,?,?,?,?)",
                (
                    f"P{pay_seq:05d}",
                    doc.number,
                    pay_date.isoformat(),
                    doc.method,
                    amount,
                    None,
                    None,
                ),
            )
    conn.commit()


def _insert_staging(conn: sqlite3.Connection, docs: list[_Doc]) -> None:
    cur = conn.cursor()
    status_text = {
        "paid": "Fizetve",
        "unpaid": "Nem fizetve",
        "partial": "Részben fizetve",
        "void": "",
    }
    names = {c[0]: (c[1], c[2]) for c in CUSTOMERS}
    delta_done = False
    for doc in sorted(docs, key=lambda d: d.number or ""):
        if (doc.issue.year, doc.issue.month) != LAST_MONTH:
            continue
        name, tax = names[doc.customer_key]
        paid_date = max((p[0] for p in doc.payments), default=None)
        for i, ln in enumerate(doc.lines, start=1):
            cur.execute(
                "INSERT INTO staging_fokonyvi (invoice_number, line_no, issue_date, delivery_date, "
                "due_date, customer_name, customer_taxno, product_name, ledger_code, vat_rate, "
                "net, "
                "vat, gross, currency, pay_status_raw, paid_date, raw_json, imported_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    doc.number,
                    i,
                    doc.issue.isoformat(),
                    doc.delivery.isoformat(),
                    doc.due.isoformat(),
                    name,
                    tax,
                    ln["product_name"],
                    "911",
                    ln["vat_rate"],
                    ln["net"],
                    ln["vat"],
                    ln["gross"],
                    doc.currency,
                    status_text[doc.pay_status],
                    paid_date.isoformat() if paid_date else None,
                    "{}",
                    SYNC_FINISHED,
                ),
            )
        by_rate: dict[str, list[float]] = {}
        for ln in doc.lines:
            acc = by_rate.setdefault(ln["vat_rate"], [0.0, 0.0])
            acc[0] = round(acc[0] + ln["net"], 2)
            acc[1] = round(acc[1] + ln["vat"], 2)
        for rate, (n, v) in by_rate.items():
            net_huf = round(n * doc.fx * doc.fx_deviation, 2)
            vat_huf = round(v * doc.fx * doc.fx_deviation, 2)
            note = "{}"
            if not delta_done and rate == "27" and doc.doc_type == "invoice":
                delta_done = True
                note = '{"planted": "afalista_delta"}'
                PLANTED["afalista_delta"] = doc
                PLANTED["afalista_delta_rate"] = rate
                PLANTED["afalista_delta_vat_huf"] = vat_huf
                vat_huf = vat_huf + 1
            cur.execute(
                "INSERT INTO staging_afalista (invoice_number, issue_date, customer_name, "
                "vat_rate, "
                "net, vat, gross, raw_json, imported_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    doc.number,
                    doc.issue.isoformat(),
                    name,
                    rate,
                    net_huf,
                    vat_huf,
                    round(net_huf + vat_huf, 2),
                    note,
                    SYNC_FINISHED,
                ),
            )
    cur.execute(
        "INSERT INTO sync_log (started, finished, source, window_from, window_to, fetched, "
        "inserted, errors, note) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "2026-08-02T06:00:00",
            "2026-08-02T06:00:40",
            "agent",
            "2026-07-01",
            "2026-07-31",
            0,
            0,
            1,
            "HTTP 500",
        ),
    )
    cur.execute(
        "INSERT INTO sync_log (started, finished, source, window_from, window_to, fetched, "
        "inserted, errors, note) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "2026-09-02T06:00:00",
            SYNC_FINISHED,
            "agent",
            "2026-08-01",
            "2026-08-31",
            31,
            31,
            0,
            None,
        ),
    )
    conn.commit()


def set_afalista_delta(conn: sqlite3.Connection, on: bool) -> None:
    """Toggle the deliberate 1 HUF VAT delta on the planted Áfalista row."""
    doc = PLANTED["afalista_delta"]
    exact = PLANTED["afalista_delta_vat_huf"]
    vat = exact + 1 if on else exact
    conn.execute(
        "UPDATE staging_afalista SET vat = ?, gross = net + ? WHERE invoice_number = ? AND "
        "vat_rate = ?",
        (vat, vat, doc.number, PLANTED["afalista_delta_rate"]),
    )
    conn.commit()


def create_schema(conn: sqlite3.Connection) -> None:
    """Apply the kit schema via db.create_schema; SCHEMA_SQL only when db.py is absent."""
    if _db_create_schema is None:  # pragma: no cover - documented safety net
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        return
    _db_create_schema(conn)


def make_engine_db(path: Path | str) -> sqlite3.Connection:
    """Create and populate the fixture database at `path` (":memory:" allowed)."""
    PLANTED.clear()
    conn = sqlite3.connect(str(path))
    create_schema(conn)
    rng = random.Random(SEED)
    docs = _build_docs(rng)
    _assign_status_and_payments(rng, docs)
    _number_docs(docs)
    _insert(conn, docs)
    _insert_staging(conn, docs)
    return conn


if __name__ == "__main__":  # pragma: no cover
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "fixture_engine.db"
    Path(target).unlink(missing_ok=True)
    c = make_engine_db(target)
    n = c.execute("SELECT COUNT(*) FROM invoice").fetchone()[0]
    print(f"{target}: {n} invoices, planted: {sorted(k for k in PLANTED)}")


# ---------------------------------------------------------------------------
# Project scaffolding helpers for tests
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "templates" / "project" / "reports" / "_examples"


def make_project(root: Path, slugs: list[str], with_build: bool = True) -> Path:
    """Create a Riportok-like tree under `root` with the given example specs.

    Copies scripts/, the example spec.yaml files (and build.py from the
    template), builds the fixture database at data/invoices.db, and returns
    the root. Callers set RIPORTOK_DIR=root when they run build.py.
    """
    import shutil

    root = Path(root)
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    for py in (REPO_ROOT / "scripts").glob("*.py"):
        shutil.copy(py, root / "scripts" / py.name)
    for slug in slugs:
        dst = root / "reports" / slug
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy(EXAMPLES_DIR / slug / "spec.yaml", dst / "spec.yaml")
        if with_build:
            shutil.copy(REPO_ROOT / "scripts" / "build_template.py", dst / "build.py")
    (root / "data").mkdir(exist_ok=True)
    db = root / "data" / "invoices.db"
    db.unlink(missing_ok=True)
    make_engine_db(db).close()
    return root
