# /// script
# requires-python = ">=3.12"
# dependencies = ["requests>=2.32"]
# ///
"""szamlazz.hu Számla Agent client: fetch one invoice as XML (xmlszamlaxml).

Request (verified against docs.szamlazz.hu/agent/querying_xml/xml on 2026-09-06):
    POST https://www.szamlazz.hu/szamla/  multipart field `action-szamla_agent_xml`
    <xmlszamlaxml xmlns="http://www.szamlazz.hu/xmlszamlaxml"> szamlaagentkulcs, szamlaszam,
    rendelesSzam, pdf, szamlaKulsoAzon (fixed order).
Response: <szamla> document on success; <xmlszamlavalasz> with sikeres/hibakod/hibauzenet on
failure (code 7 = unknown invoice number). Element names that could not be verified are
marked `# ASSUMPTION` and listed in docs/DATA-NOTES.md.

The Agent key is never logged and never placed in exception messages.
"""

from __future__ import annotations

import base64
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

import requests

AGENT_URL = "https://www.szamlazz.hu/szamla/"
FORM_FIELD = "action-szamla_agent_xml"
REQUEST_NS = "http://www.szamlazz.hu/xmlszamlaxml"
XSD_URL = "https://www.szamlazz.hu/szamla/docs/xsds/agentxml/xmlszamlaxml.xsd"
ERROR_NOT_FOUND = 7
ERROR_LOGIN = 3
MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 2.0
DEFAULT_TIMEOUT = 30.0
# ASSUMPTION: error headers of the Agent API (observation 52141 names the data headers
# szlahu_szamlaszam etc.; the error header names are not documented there).
HEADER_ERROR_CODE = "szlahu_error_code"
HEADER_ERROR_MESSAGE = "szlahu_error"


class AgentError(Exception):
    """Base class for Agent failures. Messages never contain the key."""


class AgentNetworkError(AgentError):
    """5xx or timeout after MAX_ATTEMPTS attempts."""


class NotFound(AgentError):
    """Error code 7: unknown invoice number."""


class RateLimiter:
    """Token bucket with one token per `min_interval` seconds (injectable clock and sleep)."""

    def __init__(
        self,
        min_interval: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._next_allowed: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._next_allowed is not None and now < self._next_allowed:
            self._sleep(self._next_allowed - now)
            now = self._next_allowed
        self._next_allowed = now + self._min_interval


@dataclass
class AgentResult:
    ok: bool
    error_code: int | None = None
    error_message: str | None = None
    xml: bytes = b""
    pdf: bytes | None = None

    @property
    def not_found(self) -> bool:
        return self.error_code == ERROR_NOT_FOUND

    def raise_for_error(self) -> None:
        if self.ok:
            return
        if self.not_found:
            raise NotFound(self.error_message or "ismeretlen számlaszám")
        raise AgentError(f"{self.error_code}: {self.error_message}")


@dataclass
class Header:
    invoice_number: str
    doc_type_code: str | None = None
    is_einvoice: bool = False
    issue_date: str | None = None
    delivery_date: str | None = None
    due_date: str | None = None
    payment_method_raw: str | None = None
    payment_method_unified: str | None = None
    language: str | None = None
    currency: str | None = None
    fx_rate: float | None = None
    reference: str | None = None
    order_ref: str | None = None
    note: str | None = None
    is_test: bool = False


@dataclass
class Customer:
    szamlazz_id: str | None = None
    name: str | None = None
    tax_number: str | None = None
    eu_tax_number: str | None = None
    country: str | None = None
    postcode: str | None = None
    city: str | None = None
    address: str | None = None
    email: str | None = None
    is_private: bool | None = None


@dataclass
class Line:
    line_no: int
    name: str
    quantity: float
    unit: str | None
    unit_price: float
    vat_rate: str
    net: float
    vat: float
    gross: float
    note: str | None = None
    ledger_code: str | None = None


@dataclass
class VatTotal:
    vat_rate: str
    net: float
    vat: float
    gross: float


@dataclass
class Payment:
    seq: int
    pay_date: str | None
    pay_type: str | None
    amount: float
    note: str | None = None
    bank_account: str | None = None
    fx_rate: float | None = None


@dataclass
class ParsedInvoice:
    header: Header
    customer: Customer
    lines: list[Line] = field(default_factory=list)
    vat_totals: list[VatTotal] = field(default_factory=list)
    total_net: float = 0.0
    total_vat: float = 0.0
    total_gross: float = 0.0
    payments: list[Payment] = field(default_factory=list)
    pdf: bytes | None = None


# ---------------------------------------------------------------------------
# XML helpers (namespace-agnostic)
# ---------------------------------------------------------------------------


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(el: ET.Element, name: str) -> Iterator[ET.Element]:
    for child in el:
        if _local(child.tag) == name:
            yield child


def _find(el: ET.Element | None, path: str) -> ET.Element | None:
    cur = el
    for part in path.split("/"):
        if cur is None:
            return None
        cur = next(_children(cur, part), None)
    return cur


def _text(el: ET.Element | None, path: str) -> str | None:
    node = _find(el, path)
    if node is None or node.text is None:
        return None
    value = node.text.strip()
    return value or None


def _num(el: ET.Element | None, path: str, default: float = 0.0) -> float:
    raw = _text(el, path)
    if raw is None:
        return default
    cleaned = raw.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return default


def _num_or_none(el: ET.Element | None, path: str) -> float | None:
    raw = _text(el, path)
    if raw is None:
        return None
    value = _num(el, path, default=float("nan"))
    return None if value != value else value


_DATE_RE = re.compile(r"^(\d{4})[-.](\d{1,2})[-.](\d{1,2})")


def _date(el: ET.Element | None, path: str) -> str | None:
    raw = _text(el, path)
    if raw is None:
        return None
    m = _DATE_RE.match(raw)
    if not m:
        return None
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def _bool(el: ET.Element | None, path: str) -> bool | None:
    raw = _text(el, path)
    if raw is None:
        return None
    return raw.strip().lower() in ("true", "1", "igen", "yes")


# ---------------------------------------------------------------------------
# Request / response
# ---------------------------------------------------------------------------


def build_request_xml(key: str, invoice_number: str, with_pdf: bool = False) -> bytes:
    """xmlszamlaxml request in the fixed field order required by the XSD."""
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<xmlszamlaxml xmlns="{REQUEST_NS}" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        f'xsi:schemaLocation="{REQUEST_NS} {XSD_URL}">'
        f"<szamlaagentkulcs>{escape(key)}</szamlaagentkulcs>"
        f"<szamlaszam>{escape(invoice_number)}</szamlaszam>"
        "<rendelesSzam></rendelesSzam>"
        f"<pdf>{'true' if with_pdf else 'false'}</pdf>"
        "<szamlaKulsoAzon></szamlaKulsoAzon>"
        "</xmlszamlaxml>"
    )
    return body.encode("utf-8")


def error_from_body(content: bytes) -> tuple[int | None, str | None] | None:
    """(hibakod, hibauzenet) when the body is an xmlszamlavalasz failure, else None."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return None
    if _local(root.tag) != "xmlszamlavalasz":
        return None
    ok = _bool(root, "sikeres")
    if ok:
        return None
    code_text = _text(root, "hibakod")
    code = int(code_text) if code_text and code_text.isdigit() else None
    return code, _text(root, "hibauzenet")


def parse_response(status_code: int, headers: dict, content: bytes) -> AgentResult:
    """Map an HTTP response to AgentResult: headers first, then body, then success."""
    lowered = {str(k).lower(): str(v) for k, v in headers.items()}
    if not 200 <= status_code < 300:
        return AgentResult(ok=False, error_message=f"HTTP {status_code}", xml=content)
    code_text = lowered.get(HEADER_ERROR_CODE, "").strip()
    if code_text and code_text != "0":
        code = int(code_text) if code_text.isdigit() else None
        return AgentResult(
            ok=False, error_code=code, error_message=lowered.get(HEADER_ERROR_MESSAGE), xml=content
        )
    body_error = error_from_body(content)
    if body_error is not None:
        return AgentResult(
            ok=False, error_code=body_error[0], error_message=body_error[1], xml=content
        )
    pdf = None
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return AgentResult(ok=False, error_message="nem XML válasz", xml=content)
    if _local(root.tag) != "szamla":
        return AgentResult(
            ok=False, error_message=f"váratlan gyökérelem: {_local(root.tag)}", xml=content
        )
    pdf_text = _text(root, "pdf")
    if pdf_text:
        try:
            pdf = base64.b64decode(pdf_text)
        except ValueError:
            pdf = None
    return AgentResult(ok=True, xml=content, pdf=pdf)


class AgentClient:
    def __init__(
        self,
        key: str,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        timeout: float = DEFAULT_TIMEOUT,
        min_interval: float = 1.0,
    ) -> None:
        self._key = key
        self._session = session or requests.Session()
        self._sleep = sleep
        self._timeout = timeout
        self._limiter = RateLimiter(min_interval=min_interval, clock=clock, sleep=sleep)

    def __repr__(self) -> str:
        return "AgentClient(key=***)"

    def _post(self, body: bytes, invoice_number: str) -> requests.Response:
        last_error = "ismeretlen hiba"
        for attempt in range(MAX_ATTEMPTS):
            self._limiter.wait()
            try:
                resp = self._session.post(
                    AGENT_URL,
                    files={FORM_FIELD: ("request.xml", body, "text/xml")},
                    timeout=self._timeout,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = f"hálózati hiba ({type(exc).__name__})"
            else:
                if resp.status_code < 500:
                    return resp
                last_error = f"HTTP {resp.status_code}"
            if attempt < MAX_ATTEMPTS - 1:
                self._sleep(BACKOFF_BASE_SECONDS * (2**attempt))
        raise AgentNetworkError(
            f"{invoice_number}: {last_error}, {MAX_ATTEMPTS} próbálkozás után feladva"
        )

    def fetch_invoice(self, invoice_number: str, with_pdf: bool = False) -> AgentResult:
        body = build_request_xml(self._key, invoice_number, with_pdf)
        resp = self._post(body, invoice_number)
        return parse_response(resp.status_code, dict(resp.headers), resp.content)


# ---------------------------------------------------------------------------
# Invoice XML parsing (pure)
# ---------------------------------------------------------------------------


def parse_invoice_xml(xml_bytes: bytes) -> ParsedInvoice:
    """Parse a <szamla> document into dataclasses. Namespace-agnostic."""
    root = ET.fromstring(xml_bytes)
    if _local(root.tag) != "szamla":
        raise ValueError(f"nem <szamla> dokumentum: <{_local(root.tag)}>")
    alap = _find(root, "alap")
    vevo = _find(root, "vevo")
    header = Header(
        invoice_number=_text(alap, "szamlaszam") or "",
        doc_type_code=_text(alap, "tipus"),
        is_einvoice=bool(_bool(alap, "eszamla")),
        issue_date=_date(alap, "kelt"),
        delivery_date=_date(alap, "telj"),
        due_date=_date(alap, "fizh"),
        payment_method_raw=_text(alap, "fizmod"),
        payment_method_unified=_text(alap, "fizmodunified"),
        language=_text(alap, "nyelv"),
        currency=_text(alap, "devizanem"),
        fx_rate=_num_or_none(alap, "devizaarf"),
        # ASSUMPTION: hivszamlaszam (referenced invoice) is documented on the Financial Data
        # Connection page, not on the Agent response page.
        reference=_text(alap, "hivszamlaszam"),
        # ASSUMPTION: rendelesszam element name in <alap>.
        order_ref=_text(alap, "rendelesszam"),
        note=_text(alap, "megjegyzes"),
        is_test=bool(_bool(alap, "teszt")),
    )
    customer = Customer(
        szamlazz_id=_text(vevo, "id"),
        name=_text(vevo, "nev"),
        tax_number=_text(vevo, "adoszam"),
        # ASSUMPTION: adoszameu (EU VAT number) mirrors the szallito block naming.
        eu_tax_number=_text(vevo, "adoszameu"),
        # ASSUMPTION: cim/orszag, cim/irsz, cim/telepules, cim/cim sub-elements.
        country=_text(vevo, "cim/orszag"),
        postcode=_text(vevo, "cim/irsz"),
        city=_text(vevo, "cim/telepules"),
        address=_text(vevo, "cim/cim"),
        email=_text(vevo, "email"),
        # ASSUMPTION: privatePersonIndicator (named on the Financial Data Connection page).
        is_private=_bool(vevo, "privatePersonIndicator"),
    )
    lines: list[Line] = []
    tetelek = _find(root, "tetelek")
    if tetelek is not None:
        for idx, tetel in enumerate(_children(tetelek, "tetel"), start=1):
            lines.append(
                Line(
                    line_no=idx,
                    name=_text(tetel, "nev") or "",
                    quantity=_num(tetel, "mennyiseg"),
                    unit=_text(tetel, "mennyisegiegyseg"),
                    unit_price=_num(tetel, "nettoegysegar"),
                    vat_rate=_text(tetel, "afakulcs") or "",
                    net=_num(tetel, "netto"),
                    vat=_num(tetel, "afa"),
                    gross=_num(tetel, "brutto"),
                    note=_text(tetel, "megjegyzes"),
                    # ASSUMPTION: tetel/fokonyv/arbevetel holds the revenue ledger code.
                    ledger_code=_text(tetel, "fokonyv/arbevetel"),
                )
            )
    vat_totals: list[VatTotal] = []
    osszegek = _find(root, "osszegek")
    if osszegek is not None:
        for row in _children(osszegek, "afakulcsossz"):
            vat_totals.append(
                VatTotal(
                    vat_rate=_text(row, "afakulcs") or "",
                    net=_num(row, "netto"),
                    vat=_num(row, "afa"),
                    gross=_num(row, "brutto"),
                )
            )
    total = _find(osszegek, "totalossz")
    total_net = _num(total, "netto")
    total_vat = _num(total, "afa")
    total_gross = _num(total, "brutto")
    if total is None and lines:
        total_net = sum(ln.net for ln in lines)
        total_vat = sum(ln.vat for ln in lines)
        total_gross = sum(ln.gross for ln in lines)
    payments: list[Payment] = []
    kifizetesek = _find(root, "kifizetesek")
    if kifizetesek is not None:
        for idx, k in enumerate(_children(kifizetesek, "kifizetes"), start=1):
            payments.append(
                Payment(
                    seq=idx,
                    pay_date=_date(k, "datum"),
                    pay_type=_text(k, "jogcim"),
                    amount=_num(k, "osszeg"),
                    note=_text(k, "megjegyzes"),
                    bank_account=_text(k, "bankszamlaszam"),
                    fx_rate=_num_or_none(k, "devizaarf"),
                )
            )
    pdf = None
    pdf_text = _text(root, "pdf")
    if pdf_text:
        try:
            pdf = base64.b64decode(pdf_text)
        except ValueError:
            pdf = None
    return ParsedInvoice(
        header=header,
        customer=customer,
        lines=lines,
        vat_totals=vat_totals,
        total_net=total_net,
        total_vat=total_vat,
        total_gross=total_gross,
        payments=payments,
        pdf=pdf,
    )
