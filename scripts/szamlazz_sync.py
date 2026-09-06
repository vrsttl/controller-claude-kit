# /// script
# requires-python = ">=3.12"
# dependencies = ["requests>=2.32", "keyring>=25", "openpyxl>=3.1"]
# ///
"""Számla-gyorsítótár szinkron: szamlazz.hu Számla Agent + NAV Online Számla -> SQLite.

    uv run scripts/szamlazz_sync.py init
    uv run scripts/szamlazz_sync.py pull --period 2026-08
    uv run scripts/szamlazz_sync.py pull --agent-only --prefix SZLA --year 2026
    uv run scripts/szamlazz_sync.py import-csv data/drops/fokonyvi.csv
    uv run scripts/szamlazz_sync.py import-afalista data/drops/afalista.xlsx
    uv run scripts/szamlazz_sync.py reconcile --period 2026-08 [--tolerance 1]
    uv run scripts/szamlazz_sync.py status

Kilépési kódok: 0 rendben, 1 adateltérés vagy nem jött adat, 2 használati hiba vagy hiányzó
titok, 3 hálózati hiba az újrapróbálkozások után.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import io
import json
import re
import sqlite3
import sys
import unicodedata
from collections.abc import Callable
from datetime import date
from pathlib import Path

import agent_client
import db
import get_secret
import nav_client

EXIT_OK = 0
EXIT_DATA = 1
EXIT_USAGE = 2
EXIT_NETWORK = 3

CONSECUTIVE_MISSES_TO_STOP = 3
DEFAULT_MAX_REQUESTS = 500

INVOICE_NUMBER_RE = re.compile(r"^(?P<prefix>.+)-(?P<year>\d{4})-(?P<seq>\d+)$")
PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# ASSUMPTION: Főkönyvi adatexport CSV header labels. The tudástár page lists the column
# meanings, not the literal header strings; confirm against a real export (DATA-NOTES.md).
HEADER_MAP_FOKONYVI: dict[str, tuple[str, ...]] = {
    "invoice_number": ("számlaszám", "bizonylatszám"),
    "issue_date": (
        "számla kiállítás dátuma",
        "számla kiállításának dátuma",
        "kelt",
        "kiállítás dátuma",
    ),
    "delivery_date": ("teljesítés időpontja", "teljesítés dátuma", "teljesítési dátum"),
    "due_date": ("fizetési határidő",),
    "customer_name": ("vevő neve", "vevő"),
    "customer_taxno": ("vevő adószáma", "adószám", "adószáma"),
    "product_name": ("termék neve", "tétel neve", "megnevezés"),
    "ledger_code": (
        "árbevétel főkönyvi szám",
        "főkönyvi szám",
        "főkönyv árbevétel",
        "árbevétel főkönyv",
    ),
    "vat_rate": ("áfakulcs", "áfa kulcs", "áfa %"),
    "net": ("tétel nettó érték", "tétel nettó", "nettó érték"),
    "vat": ("tétel áfaérték", "tétel áfa érték", "tétel áfa", "áfaérték"),
    "gross": ("tétel bruttó érték", "tétel bruttó", "bruttó érték"),
    "currency": ("devizanem", "pénznem"),
    "pay_status_raw": ("kifizetett összeg", "kifizetve", "fizetve", "kifizetettség"),
    "paid_date": ("kifizetés dátuma", "kifizetés napja"),
}

# ASSUMPTION: Áfalista XLSX header labels and the "<kulcs> alap" / "<kulcs> áfa" column pairs.
HEADER_MAP_AFALISTA: dict[str, tuple[str, ...]] = {
    "invoice_number": ("számlaszám", "bizonylatszám"),
    "issue_date": (
        "számla kiállításának dátuma",
        "számla kiállítás dátuma",
        "kelt",
        "kiállítás dátuma",
    ),
    "customer_name": ("vevő neve", "vevő"),
    "net": ("nettó ár", "nettó", "nettó összesen"),
    "vat": ("áfa", "áfa összesen"),
    "gross": ("bruttó ár", "bruttó", "bruttó összesen"),
}
AFALISTA_RATE_COLUMN_RE = re.compile(
    r"^(?P<rate>.+?)\s*%?\s+(?P<kind>áfa alap|alap|nettó|áfa érték|áfa összeg|áfa)$", re.IGNORECASE
)

AgentFactory = Callable[[], agent_client.AgentClient]
NavFactory = Callable[[], nav_client.NavClient]


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.casefold().split())


def _map_headers(headers: list[str], header_map: dict[str, tuple[str, ...]]) -> dict[str, int]:
    """canonical field -> column index, exact match on accent-folded, casefolded labels."""
    folded = [_fold(h) for h in headers]
    out: dict[str, int] = {}
    for field_name, candidates in header_map.items():
        for cand in candidates:
            key = _fold(cand)
            if key in folded:
                out[field_name] = folded.index(key)
                break
    return out


def _period_bounds(period: str) -> tuple[date, date]:
    year, month = int(period[:4]), int(period[5:7])
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _default_agent_factory() -> agent_client.AgentClient:
    return agent_client.AgentClient(get_secret.get_secret("szamlazz.hu", "agent-key"))


def _default_nav_factory(base_url: str) -> NavFactory:
    def factory() -> nav_client.NavClient:
        return nav_client.NavClient(
            login=get_secret.get_secret("nav.gov.hu", "tech-login"),
            password=get_secret.get_secret("nav.gov.hu", "tech-password"),
            signing_key=get_secret.get_secret("nav.gov.hu", "signing-key"),
            tax_number=get_secret.get_secret("nav.gov.hu", "tax-number"),
            base_url=base_url,
        )

    return factory


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_init(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    started = db.now_iso()
    version = db.create_schema(conn)
    db.log_sync(conn, "init", started, note=f"schema v{version}")
    print(f"Adatbázis kész: {args.db} (séma v{version})")
    return EXIT_OK


def _last_known_seq(conn: sqlite3.Connection, prefix: str, year: int) -> int:
    last = 0
    for key in db.known_doc_keys(conn, "agent"):
        m = INVOICE_NUMBER_RE.match(key)
        if m and m.group("prefix") == prefix and int(m.group("year")) == year:
            last = max(last, int(m.group("seq")))
    return last


def _count_prefix_year(conn: sqlite3.Connection, prefix: str, year: int) -> int:
    rows = conn.execute("SELECT invoice_number FROM invoice").fetchall()
    total = 0
    for row in rows:
        m = INVOICE_NUMBER_RE.match(row["invoice_number"])
        if m and m.group("prefix") == prefix and int(m.group("year")) == year:
            total += 1
    return total


def cmd_pull_agent_only(
    conn: sqlite3.Connection, args: argparse.Namespace, agent_factory: AgentFactory
) -> int:
    try:
        client = agent_factory()
    except get_secret.SecretMissing as exc:
        print(str(exc))
        return EXIT_USAGE
    exit_code = EXIT_OK
    for prefix in args.prefix:
        started = db.now_iso()
        last = _last_known_seq(conn, prefix, args.year)
        start = max(last + 1, args.start_seq or 1)
        seq = start
        misses = fetched = inserted = errors = requests_made = 0
        while requests_made < args.max:
            number = f"{prefix}-{args.year}-{seq}"
            try:
                result = client.fetch_invoice(number)
            except agent_client.AgentNetworkError as exc:
                print(f"Hálózati hiba: {exc}")
                db.log_sync(
                    conn,
                    "agent",
                    started,
                    window_from=f"{prefix}-{args.year}-{start}",
                    window_to=number,
                    fetched=fetched,
                    inserted=inserted,
                    errors=errors + 1,
                    note="hálózati hiba, megszakítva",
                )
                db.rebuild(conn)
                return EXIT_NETWORK
            requests_made += 1
            if result.ok:
                fetched += 1
                if db.insert_raw(conn, "agent", number, result.xml):
                    inserted += 1
                misses = 0
            elif result.error_code == agent_client.ERROR_LOGIN:
                print(
                    f"Belépési hiba a Számla Agentnél ({result.error_message}). "
                    "Ellenőrizd a kulcsot: "
                    "uv run scripts/get_secret.py set szamlazz.hu agent-key"
                )
                db.log_sync(
                    conn,
                    "agent",
                    started,
                    window_from=number,
                    window_to=number,
                    errors=1,
                    note="belépési hiba",
                )
                return EXIT_USAGE
            else:
                misses += 1
                if not result.not_found:
                    errors += 1
                    print(f"{number}: hiba {result.error_code}: {result.error_message}")
                if misses >= CONSECUTIVE_MISSES_TO_STOP:
                    break
            seq += 1
        last_tried = seq if misses else seq - 1
        note = (
            "3 egymást követő ismeretlen szám után megállt"
            if misses >= 3
            else "elérte a --max korlátot"
        )
        db.log_sync(
            conn,
            "agent",
            started,
            window_from=f"{prefix}-{args.year}-{start}",
            window_to=f"{prefix}-{args.year}-{max(last_tried, start)}",
            fetched=fetched,
            inserted=inserted,
            errors=errors,
            note=note,
        )
        print(
            f"{prefix}-{args.year}: {fetched} számla letöltve, {inserted} új, "
            f"{errors} hiba ({note})."
        )
        db.rebuild(conn)
        if fetched == 0 and _count_prefix_year(conn, prefix, args.year) == 0:
            print(
                f"Nincs egyetlen {prefix}-{args.year}-N számla sem. "
                "Ellenőrizd az előtagot és az évet."
            )
            exit_code = EXIT_DATA
    return exit_code


def cmd_pull_period(
    conn: sqlite3.Connection,
    args: argparse.Namespace,
    agent_factory: AgentFactory,
    nav_factory: NavFactory,
) -> int:
    date_from, date_to = _period_bounds(args.period)
    started = db.now_iso()
    try:
        nav = nav_factory()
    except get_secret.SecretMissing as exc:
        print(str(exc))
        return EXIT_USAGE
    numbers: list[str] = []
    inserted = 0
    try:
        for digest in nav.iter_digests(date_from, date_to):
            numbers.append(digest.invoice_number)
            if db.insert_raw(conn, "nav_digest", digest.invoice_number, digest.xml):
                inserted += 1
    except nav_client.NavNetworkError as exc:
        print(f"NAV hálózati hiba: {exc}")
        db.log_sync(
            conn,
            "nav_digest",
            started,
            window_from=date_from.isoformat(),
            window_to=date_to.isoformat(),
            fetched=len(numbers),
            inserted=inserted,
            errors=1,
            note="hálózati hiba",
        )
        return EXIT_NETWORK
    except nav_client.NavError as exc:
        print(f"NAV hiba: {exc}")
        db.log_sync(
            conn,
            "nav_digest",
            started,
            window_from=date_from.isoformat(),
            window_to=date_to.isoformat(),
            fetched=len(numbers),
            inserted=inserted,
            errors=1,
            note=str(exc)[:200],
        )
        return EXIT_USAGE if (exc.error_code or "").startswith("INVALID_") else EXIT_NETWORK
    db.log_sync(
        conn,
        "nav_digest",
        started,
        window_from=date_from.isoformat(),
        window_to=date_to.isoformat(),
        fetched=len(numbers),
        inserted=inserted,
        note="queryInvoiceDigest",
    )
    print(f"NAV: {len(numbers)} számla az időszakban ({args.period}), {inserted} új kivonat.")
    if not numbers:
        print("A NAV nem adott vissza számlát erre az időszakra.")
        db.rebuild(conn)
        return EXIT_DATA

    known = db.known_doc_keys(conn, "agent")
    todo = [n for n in dict.fromkeys(numbers) if n not in known]
    agent_started = db.now_iso()
    fetched = agent_inserted = errors = 0
    if todo:
        try:
            client = agent_factory()
        except get_secret.SecretMissing as exc:
            print(str(exc))
            db.rebuild(conn)
            return EXIT_USAGE
        for number in todo:
            try:
                result = client.fetch_invoice(number)
            except agent_client.AgentNetworkError as exc:
                print(f"Hálózati hiba: {exc}")
                db.log_sync(
                    conn,
                    "agent",
                    agent_started,
                    window_from=todo[0],
                    window_to=number,
                    fetched=fetched,
                    inserted=agent_inserted,
                    errors=errors + 1,
                    note="hálózati hiba, megszakítva",
                )
                db.rebuild(conn)
                return EXIT_NETWORK
            if result.ok:
                fetched += 1
                if db.insert_raw(conn, "agent", number, result.xml):
                    agent_inserted += 1
            elif result.error_code == agent_client.ERROR_LOGIN:
                print(
                    "Belépési hiba a Számla Agentnél. Ellenőrizd a kulcsot: "
                    "uv run scripts/get_secret.py set szamlazz.hu agent-key"
                )
                db.rebuild(conn)
                return EXIT_USAGE
            else:
                errors += 1
                print(f"{number}: Agent hiba {result.error_code}: {result.error_message}")
        db.log_sync(
            conn,
            "agent",
            agent_started,
            window_from=todo[0],
            window_to=todo[-1],
            fetched=fetched,
            inserted=agent_inserted,
            errors=errors,
            note="NAV kivonat alapján",
        )
    print(f"Agent: {len(todo)} új szám, {fetched} letöltve, {errors} hiba.")

    if args.with_nav_data:
        known_data = db.known_doc_keys(conn, "nav_data")
        data_started = db.now_iso()
        data_fetched = data_inserted = data_errors = 0
        for number in dict.fromkeys(numbers):
            if number in known_data:
                continue
            try:
                body = nav.query_invoice_data(number)
            except nav_client.NavNetworkError as exc:
                print(f"NAV hálózati hiba: {exc}")
                db.rebuild(conn)
                return EXIT_NETWORK
            except nav_client.NavError as exc:
                data_errors += 1
                print(f"{number}: NAV adat hiba: {exc}")
                continue
            data_fetched += 1
            if db.insert_raw(conn, "nav_data", number, body):
                data_inserted += 1
        db.log_sync(
            conn,
            "nav_data",
            data_started,
            window_from=date_from.isoformat(),
            window_to=date_to.isoformat(),
            fetched=data_fetched,
            inserted=data_inserted,
            errors=data_errors,
            note="queryInvoiceData",
        )
        print(f"NAV adat: {data_fetched} letöltve, {data_errors} hiba.")
    counts = db.rebuild(conn)
    print(f"Újraépítve: {counts['invoice']} számla, {counts['invoice_line']} tétel.")
    return EXIT_OK


def _read_text_tolerant(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1250", "iso-8859-2"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _sniff_delimiter(sample: str) -> str:
    first_line = sample.splitlines()[0] if sample else ""
    counts = {d: first_line.count(d) for d in (";", "\t", ",")}
    return max(counts, key=lambda d: counts[d]) if any(counts.values()) else ";"


def cmd_import_csv(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    path = Path(args.path)
    if not path.is_file():
        print(f"Nincs ilyen fájl: {path}")
        return EXIT_USAGE
    started = db.now_iso()
    text = _read_text_tolerant(path)
    reader = csv.reader(io.StringIO(text), delimiter=_sniff_delimiter(text))
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        print("Üres CSV.")
        return EXIT_DATA
    headers = [h.strip() for h in rows[0]]
    colmap = _map_headers(headers, HEADER_MAP_FOKONYVI)
    if "invoice_number" not in colmap:
        print("Nem találom a számlaszám oszlopot. Fejlécek: " + ", ".join(headers))
        print("Bővítsd a HEADER_MAP_FOKONYVI listát a szamlazz_sync.py elején.")
        return EXIT_USAGE
    missing = [f for f in HEADER_MAP_FOKONYVI if f not in colmap]
    if missing:
        print("Nem talált oszlopok (NULL marad): " + ", ".join(missing))

    def cell(row: list[str], field_name: str) -> str | None:
        idx = colmap.get(field_name)
        if idx is None or idx >= len(row):
            return None
        value = row[idx].strip()
        return value or None

    records = []
    line_counter: dict[str, int] = {}
    for row in rows[1:]:
        number = cell(row, "invoice_number")
        if not number:
            continue
        line_counter[number] = line_counter.get(number, 0) + 1
        raw = {headers[i]: row[i] for i in range(min(len(headers), len(row)))}
        records.append(
            (
                number,
                line_counter[number],
                db.parse_date(cell(row, "issue_date")),
                db.parse_date(cell(row, "delivery_date")),
                db.parse_date(cell(row, "due_date")),
                cell(row, "customer_name"),
                cell(row, "customer_taxno"),
                cell(row, "product_name"),
                cell(row, "ledger_code"),
                cell(row, "vat_rate"),
                db.parse_amount(cell(row, "net")),
                db.parse_amount(cell(row, "vat")),
                db.parse_amount(cell(row, "gross")),
                cell(row, "currency"),
                cell(row, "pay_status_raw"),
                db.parse_date(cell(row, "paid_date")),
                json.dumps(raw, ensure_ascii=False),
                started,
            )
        )
    if not records:
        print("A CSV nem tartalmaz számlasort.")
        return EXIT_DATA
    numbers = sorted({r[0] for r in records})
    conn.execute("BEGIN")
    conn.executemany(
        "DELETE FROM staging_fokonyvi WHERE invoice_number = ?", [(n,) for n in numbers]
    )
    conn.executemany(
        "INSERT INTO staging_fokonyvi (invoice_number, line_no, issue_date, delivery_date, "
        "due_date, customer_name, customer_taxno, product_name, ledger_code, vat_rate, net, vat, "
        "gross, currency, pay_status_raw, paid_date, raw_json, imported_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        records,
    )
    conn.execute("COMMIT")
    db.insert_raw(conn, "csv", path.name, path.read_bytes())
    db.log_sync(
        conn,
        "csv",
        started,
        window_from=numbers[0],
        window_to=numbers[-1],
        fetched=len(records),
        inserted=len(records),
        note=path.name,
    )
    print(f"Főkönyvi export betöltve: {len(records)} sor, {len(numbers)} számla ({path.name}).")
    return EXIT_OK


def _cell_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return text or None


def cmd_import_afalista(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    path = Path(args.path)
    if not path.is_file():
        print(f"Nincs ilyen fájl: {path}")
        return EXIT_USAGE
    import openpyxl  # lazy: only this command needs it

    started = db.now_iso()
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    all_rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    header_idx = next(
        (i for i, r in enumerate(all_rows) if sum(1 for c in r if c not in (None, "")) >= 3), None
    )
    if header_idx is None:
        print("Nem találok fejlécsort az Áfalista munkalapon.")
        return EXIT_DATA
    headers = [_cell_text(c) or "" for c in all_rows[header_idx]]
    colmap = _map_headers(headers, HEADER_MAP_AFALISTA)
    if "invoice_number" not in colmap:
        print("Nem találom a számlaszám oszlopot. Fejlécek: " + ", ".join(h for h in headers if h))
        print("Bővítsd a HEADER_MAP_AFALISTA listát a szamlazz_sync.py elején.")
        return EXIT_USAGE
    rate_cols: dict[str, dict[str, int]] = {}
    for idx, header in enumerate(headers):
        m = AFALISTA_RATE_COLUMN_RE.match(header.strip())
        if not m or idx in colmap.values():
            continue
        rate = m.group("rate").replace("%", "").strip()
        rate = rate if rate.isdigit() else rate.upper()
        kind = "net" if _fold(m.group("kind")) in ("alap", "afa alap", "netto") else "vat"
        rate_cols.setdefault(rate, {})[kind] = idx
    if not rate_cols:
        print("Nem találtam áfakulcsonkénti oszlopokat, csak számlaszintű összegek kerülnek be.")

    def cell(row: list[object], field_name: str) -> object:
        idx = colmap.get(field_name)
        return row[idx] if idx is not None and idx < len(row) else None

    records = []
    for row in all_rows[header_idx + 1 :]:
        number = _cell_text(cell(row, "invoice_number"))
        if not number:
            continue
        raw = {
            headers[i]: _cell_text(row[i]) for i in range(min(len(headers), len(row))) if headers[i]
        }
        raw_json = json.dumps(raw, ensure_ascii=False)
        issue = db.parse_date(_cell_text(cell(row, "issue_date")))
        customer = _cell_text(cell(row, "customer_name"))
        net = db.parse_amount(_cell_text(cell(row, "net")))
        vat = db.parse_amount(_cell_text(cell(row, "vat")))
        gross = db.parse_amount(_cell_text(cell(row, "gross")))
        if gross is None and net is not None:
            gross = net + (vat or 0.0)
        records.append((number, issue, customer, "*", net, vat, gross, raw_json, started))
        for rate, cols in sorted(rate_cols.items()):
            r_net = db.parse_amount(_cell_text(row[cols["net"]])) if "net" in cols else None
            r_vat = db.parse_amount(_cell_text(row[cols["vat"]])) if "vat" in cols else None
            if not r_net and not r_vat:
                continue
            r_net = r_net or 0.0
            r_vat = r_vat or 0.0
            records.append(
                (number, issue, customer, rate, r_net, r_vat, r_net + r_vat, raw_json, started)
            )
    if not records:
        print("Az Áfalista nem tartalmaz számlasort.")
        return EXIT_DATA
    numbers = sorted({r[0] for r in records})
    conn.execute("BEGIN")
    conn.executemany(
        "DELETE FROM staging_afalista WHERE invoice_number = ?", [(n,) for n in numbers]
    )
    conn.executemany(
        "INSERT INTO staging_afalista (invoice_number, issue_date, customer_name, vat_rate, net, "
        "vat, gross, raw_json, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        records,
    )
    conn.execute("COMMIT")
    db.insert_raw(conn, "csv", path.name, path.read_bytes())
    db.log_sync(
        conn,
        "afalista",
        started,
        window_from=numbers[0],
        window_to=numbers[-1],
        fetched=len(records),
        inserted=len(records),
        note=path.name,
    )
    print(f"Áfalista betöltve: {len(numbers)} számla, {len(records)} sor ({path.name}).")
    return EXIT_OK


def _delta_rows(
    source: str,
    cache_inv: dict[str, dict[str, float]],
    cache_vat: dict[tuple[str, str], dict[str, float]],
    staging_inv: dict[str, dict[str, float]],
    staging_vat: dict[tuple[str, str], dict[str, float]],
) -> list[tuple[str, str, str, str, str, float]]:
    rows: list[tuple[str, str, str, str, str, float]] = []

    def fmt(value: float | None) -> str:
        return "" if value is None else f"{value:.2f}"

    for number in sorted(staging_inv):
        if number not in cache_inv:
            value = staging_inv[number].get("gross") or 0.0
            rows.append((number, "", f"{source}.missing_in_cache", "", fmt(value), value))
            continue
        for field_name in ("net", "vat", "gross"):
            c = cache_inv[number].get(field_name)
            s = staging_inv[number].get(field_name)
            if s is None:
                continue
            delta = (s or 0.0) - (c or 0.0)
            if abs(delta) > 1e-9:
                rows.append((number, "", f"{source}.{field_name}", fmt(c), fmt(s), delta))
    numbers = set(staging_inv) & set(cache_inv)
    keys = {k for k in staging_vat if k[0] in numbers} | {k for k in cache_vat if k[0] in numbers}
    for number, rate in sorted(keys):
        c_row = cache_vat.get((number, rate))
        s_row = staging_vat.get((number, rate))
        for field_name in ("net", "vat"):
            c = c_row.get(field_name) if c_row else None
            s = s_row.get(field_name) if s_row else None
            if c is None and s is None:
                continue
            delta = (s or 0.0) - (c or 0.0)
            if abs(delta) > 1e-9:
                rows.append((number, rate, f"{source}.{field_name}", fmt(c), fmt(s), delta))
    return rows


def cmd_reconcile(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    started = db.now_iso()
    period = args.period
    cache_inv: dict[str, dict[str, float]] = {}
    for r in conn.execute(
        "SELECT invoice_number, net_amount, vat_amount, gross_amount FROM invoice "
        "WHERE period_kelt = ?",
        (period,),
    ):
        cache_inv[r["invoice_number"]] = {
            "net": r["net_amount"],
            "vat": r["vat_amount"],
            "gross": r["gross_amount"],
        }
    cache_vat: dict[tuple[str, str], dict[str, float]] = {}
    for r in conn.execute(
        "SELECT v.invoice_number, v.vat_rate, v.net, v.vat FROM invoice_vat v JOIN invoice i "
        "ON i.invoice_number = v.invoice_number WHERE i.period_kelt = ?",
        (period,),
    ):
        cache_vat[(r["invoice_number"], r["vat_rate"])] = {"net": r["net"], "vat": r["vat"]}

    fok_inv: dict[str, dict[str, float]] = {}
    fok_vat: dict[tuple[str, str], dict[str, float]] = {}
    for r in conn.execute(
        "SELECT invoice_number, vat_rate, SUM(net) AS net, SUM(vat) AS vat, SUM(gross) AS gross "
        "FROM staging_fokonyvi WHERE substr(issue_date, 1, 7) = ? OR invoice_number IN "
        "(SELECT invoice_number FROM invoice WHERE period_kelt = ?) "
        "GROUP BY invoice_number, vat_rate",
        (period, period),
    ):
        number, rate = r["invoice_number"], r["vat_rate"] or ""
        inv = fok_inv.setdefault(number, {"net": 0.0, "vat": 0.0, "gross": 0.0})
        for f in ("net", "vat", "gross"):
            inv[f] += r[f] or 0.0
        fok_vat[(number, rate)] = {"net": r["net"] or 0.0, "vat": r["vat"] or 0.0}

    afa_inv: dict[str, dict[str, float]] = {}
    afa_vat: dict[tuple[str, str], dict[str, float]] = {}
    for r in conn.execute(
        "SELECT invoice_number, vat_rate, net, vat, gross FROM staging_afalista "
        "WHERE substr(issue_date, 1, 7) = ? OR invoice_number IN "
        "(SELECT invoice_number FROM invoice WHERE period_kelt = ?)",
        (period, period),
    ):
        number, rate = r["invoice_number"], r["vat_rate"]
        if rate == "*":
            afa_inv[number] = {"net": r["net"], "vat": r["vat"], "gross": r["gross"]}
        else:
            afa_vat[(number, rate)] = {"net": r["net"] or 0.0, "vat": r["vat"] or 0.0}
    for number, _ in afa_vat:
        afa_inv.setdefault(number, {})

    rows = _delta_rows("fokonyvi", cache_inv, cache_vat, fok_inv, fok_vat)
    rows += _delta_rows("afalista", cache_inv, cache_vat, afa_inv, afa_vat)
    out_dir = Path(args.db).parent if args.db != ":memory:" else Path.cwd()
    out_path = out_dir / f"reconcile-{period}.csv"
    with out_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(
            ["invoice_number", "vat_rate", "field", "cache_value", "staging_value", "delta"]
        )
        for row in rows:
            writer.writerow([*row[:5], f"{row[5]:.2f}"])
    beyond = [r for r in rows if abs(r[5]) > args.tolerance]
    compared = len(fok_inv) + len(afa_inv)
    if compared == 0:
        print(
            f"Nincs betöltött ellenőrző export erre az időszakra ({period}). "
            "Előbb: import-csv vagy import-afalista."
        )
        db.log_sync(
            conn,
            "reconcile",
            started,
            window_from=period,
            window_to=period,
            errors=1,
            note="nincs staging adat",
        )
        return EXIT_DATA
    print(
        f"Egyeztetés {period}: {compared} számla összevetve, {len(rows)} eltérés, "
        f"{len(beyond)} a tűréshatár ({args.tolerance:g}) felett. Részletek: {out_path}"
    )
    for number, rate, field_name, c, s, delta in beyond[:20]:
        rate_text = f" [{rate}]" if rate else ""
        print(
            f"  {number}{rate_text} {field_name}: cache={c or '-'} "
            f"export={s or '-'} delta={delta:+.2f}"
        )
    db.log_sync(
        conn,
        "reconcile",
        started,
        window_from=period,
        window_to=period,
        fetched=compared,
        errors=len(beyond),
        note=str(out_path),
    )
    return EXIT_DATA if beyond else EXIT_OK


def cmd_status(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    started = db.now_iso()
    print(f"Adatbázis: {args.db}")
    print("Utolsó szinkron forrásonként:")
    rows = conn.execute(
        "SELECT source, MAX(finished) AS finished, fetched, inserted, errors, note FROM sync_log "
        "WHERE source NOT IN ('status') GROUP BY source ORDER BY source"
    ).fetchall()
    if not rows:
        print("  (még nem volt szinkron)")
    for r in rows:
        print(
            f"  {r['source']:<11} {r['finished']}  letöltve={r['fetched']} új={r['inserted']} "
            f"hiba={r['errors']}  {r['note'] or ''}"
        )
    print("Számlák előtag és év szerint:")
    groups: dict[tuple[str, int], list[int]] = {}
    other = 0
    for r in conn.execute("SELECT invoice_number FROM invoice"):
        m = INVOICE_NUMBER_RE.match(r["invoice_number"])
        if m:
            groups.setdefault((m.group("prefix"), int(m.group("year"))), []).append(
                int(m.group("seq"))
            )
        else:
            other += 1
    if not groups and not other:
        print("  (nincs számla)")
    gap_lines = []
    for (prefix, year), seqs in sorted(groups.items()):
        lo, hi = min(seqs), max(seqs)
        print(f"  {prefix}-{year}: {len(seqs)} db ({lo}..{hi})")
        gaps = sorted(set(range(lo, hi + 1)) - set(seqs))
        if gaps:
            shown = ", ".join(str(g) for g in gaps[:20]) + (" ..." if len(gaps) > 20 else "")
            gap_lines.append(f"  {prefix}-{year}: {len(gaps)} hiányzó sorszám: {shown}")
    if other:
        print(f"  egyéb formátum: {other} db")
    print("Nem aktív láncok (storno vagy módosítás):")
    chains = conn.execute(
        "SELECT chain_root, chain_status, doc_count, effective_gross_huf, open_huf FROM v_chain "
        "WHERE chain_status != 'active' ORDER BY chain_root"
    ).fetchall()
    if not chains:
        print("  (nincs)")
    for c in chains:
        print(
            f"  {c['chain_root']:<16} {c['chain_status']:<9} {c['doc_count']} bizonylat, "
            f"bruttó={c['effective_gross_huf']:.0f} Ft, nyitott={c['open_huf']:.0f} Ft"
        )
    print("Számozási hiányok (piros zászló, a sorszámozás hézagmentes):")
    if gap_lines:
        print("\n".join(gap_lines))
    else:
        print("  (nincs)")
    db.log_sync(conn, "status", started, note="status")
    return EXIT_OK


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="szamlazz_sync.py",
        description="szamlazz.hu és NAV számlaadatok letöltése a helyi SQLite gyorsítótárba.",
    )
    parser.add_argument(
        "--db", default=None, help="SQLite fájl (alapból Riportok/data/invoices.db)"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Adatbázis és séma létrehozása.")
    p_pull = sub.add_parser(
        "pull", help="Számlák letöltése (NAV kivonat + Agent, vagy csak Agent)."
    )
    p_pull.add_argument("--period", help="Hónap YYYY-MM formában (NAV kivonat + Agent).")
    p_pull.add_argument(
        "--agent-only", action="store_true", help="Csak Agent, sorszám-felsorolással."
    )
    p_pull.add_argument(
        "--prefix", action="append", default=[], help="Számlaszám előtag, ismételhető."
    )
    p_pull.add_argument("--year", type=int, help="Év a sorszám-felsoroláshoz.")
    p_pull.add_argument(
        "--start-seq", type=int, default=None, help="Kezdő sorszám (alapból utolsó+1)."
    )
    p_pull.add_argument(
        "--max",
        type=int,
        default=DEFAULT_MAX_REQUESTS,
        help=f"Kérések felső korlátja előtagonként (alapból {DEFAULT_MAX_REQUESTS}).",
    )
    p_pull.add_argument(
        "--with-nav-data",
        action="store_true",
        help="A NAV teljes számla-XML-jét is letölti (queryInvoiceData).",
    )
    p_pull.add_argument("--nav-test", action="store_true", help="NAV tesztkörnyezet használata.")
    p_csv = sub.add_parser("import-csv", help="Főkönyvi adatexport CSV betöltése az egyeztetéshez.")
    p_csv.add_argument("path")
    p_afa = sub.add_parser("import-afalista", help="Áfalista XLSX betöltése az egyeztetéshez.")
    p_afa.add_argument("path")
    p_rec = sub.add_parser("reconcile", help="Gyorsítótár és export összevetése.")
    p_rec.add_argument("--period", required=True, help="Hónap YYYY-MM formában.")
    p_rec.add_argument(
        "--tolerance", type=float, default=1.0, help="Tűréshatár Ft-ban (alapból 1)."
    )
    sub.add_parser(
        "status", help="Állapot: utolsó szinkron, darabszámok, láncok, számozási hiányok."
    )
    return parser


def main(
    argv: list[str] | None = None,
    agent_factory: AgentFactory | None = None,
    nav_factory: NavFactory | None = None,
) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    args.db = str(args.db or db.default_db_path())
    if args.command == "pull":
        if args.agent_only and args.period:
            print("A --period és az --agent-only nem adható meg egyszerre.")
            return EXIT_USAGE
        if args.agent_only and (not args.prefix or not args.year):
            print("Az --agent-only módhoz --prefix és --year is kell.")
            return EXIT_USAGE
        if not args.agent_only and not args.period:
            print("Adj meg --period YYYY-MM értéket, vagy használd az --agent-only módot.")
            return EXIT_USAGE
        if args.period and not PERIOD_RE.match(args.period):
            print("A --period formátuma YYYY-MM, például 2026-08.")
            return EXIT_USAGE
    if args.command == "reconcile" and not PERIOD_RE.match(args.period):
        print("A --period formátuma YYYY-MM, például 2026-08.")
        return EXIT_USAGE
    conn = db.connect(args.db)
    try:
        db.create_schema(conn)
        if args.command == "init":
            return cmd_init(conn, args)
        if args.command == "pull":
            agent = agent_factory or _default_agent_factory
            if args.agent_only:
                return cmd_pull_agent_only(conn, args, agent)
            base_url = nav_client.TEST_URL if args.nav_test else nav_client.PRODUCTION_URL
            nav = nav_factory or _default_nav_factory(base_url)
            return cmd_pull_period(conn, args, agent, nav)
        if args.command == "import-csv":
            return cmd_import_csv(conn, args)
        if args.command == "import-afalista":
            return cmd_import_afalista(conn, args)
        if args.command == "reconcile":
            return cmd_reconcile(conn, args)
        return cmd_status(conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
