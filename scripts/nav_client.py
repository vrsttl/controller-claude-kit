# /// script
# requires-python = ">=3.12"
# dependencies = ["requests>=2.32"]
# ///
"""NAV Online Számla 3.0 client: tokenExchange, queryInvoiceDigest, queryInvoiceData.

Element names verified on 2026-09-06 against nav-gov-hu/Online-Invoice
(src/schemas/nav/gov/hu/OSA/invoiceApi.xsd, invoiceData.xsd, invoiceBase.xsd and
sample/API sample/tokenExchange.xml). Signing per the NAV 3.0 spec (claude-mem #52143):
passwordHash = SHA-512 upper hex, requestSignature = SHA3-512 upper hex of
requestId + timestamp(yyyyMMddHHmmss, UTC) + signing key.

Secrets are never logged and never placed in exception messages.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import re
import secrets
import string
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from xml.sax.saxutils import escape

import requests
from agent_client import RateLimiter

PRODUCTION_URL = "https://api.onlineszamla.nav.gov.hu/invoiceService/v3"
TEST_URL = "https://api-test.onlineszamla.nav.gov.hu/invoiceService/v3"
API_NS = "http://schemas.nav.gov.hu/OSA/3.0/api"
COMMON_NS = "http://schemas.nav.gov.hu/NTCA/1.0/common"
BASE_NS = "http://schemas.nav.gov.hu/OSA/3.0/base"
DATA_NS = "http://schemas.nav.gov.hu/OSA/3.0/data"
MAX_WINDOW_DAYS = 35
PAGE_SIZE = 100
REQUEST_ID_LENGTH = 30
DEFAULT_SOFTWARE_ID = "CONTROLLERKIT00001"  # SoftwareIdType: [0-9A-Z\-]{18}
MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 2.0
DEFAULT_TIMEOUT = 60.0


class NavError(Exception):
    def __init__(
        self,
        message: str,
        func_code: str | None = None,
        error_code: str | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.func_code = func_code
        self.error_code = error_code
        self.http_status = http_status


class NavNetworkError(NavError):
    """5xx or timeout after MAX_ATTEMPTS attempts."""


# ---------------------------------------------------------------------------
# Pure signing helpers
# ---------------------------------------------------------------------------


def password_hash(password: str) -> str:
    return hashlib.sha512(password.encode("utf-8")).hexdigest().upper()


def signature_timestamp(timestamp: str) -> str:
    """'2026-09-06T10:00:00.000Z' -> '20260906100000' (digits of the UTC timestamp)."""
    digits = re.sub(r"\D", "", timestamp)
    if len(digits) < 14:
        raise ValueError(f"érvénytelen időbélyeg: {timestamp}")
    return digits[:14]


def request_signature(request_id: str, timestamp: str, signing_key: str) -> str:
    payload = request_id + signature_timestamp(timestamp) + signing_key
    return hashlib.sha3_512(payload.encode("utf-8")).hexdigest().upper()


_ALPHABET = string.ascii_uppercase + string.digits


def new_request_id() -> str:
    """30-char unique id (pattern [+a-zA-Z0-9_]{1,30}); 'RID' + 27 random chars."""
    return "RID" + "".join(secrets.choice(_ALPHABET) for _ in range(REQUEST_ID_LENGTH - 3))


def split_windows(
    date_from: date, date_to: date, max_days: int = MAX_WINDOW_DAYS
) -> list[tuple[date, date]]:
    """Split [date_from, date_to] into inclusive windows of at most max_days calendar days."""
    if date_to < date_from:
        raise ValueError("date_to must not precede date_from")
    windows = []
    start = date_from
    while start <= date_to:
        end = min(start + timedelta(days=max_days - 1), date_to)
        windows.append((start, end))
        start = end + timedelta(days=1)
    return windows


# ---------------------------------------------------------------------------
# Parsed structures
# ---------------------------------------------------------------------------


@dataclass
class NavDigest:
    invoice_number: str
    operation: str | None = None
    category: str | None = None
    issue_date: str | None = None
    supplier_tax_number: str | None = None
    supplier_name: str | None = None
    customer_tax_number: str | None = None
    customer_name: str | None = None
    payment_method: str | None = None
    payment_date: str | None = None
    appearance: str | None = None
    source: str | None = None
    delivery_date: str | None = None
    currency: str | None = None
    net: float | None = None
    net_huf: float | None = None
    vat: float | None = None
    vat_huf: float | None = None
    transaction_id: str | None = None
    index: int | None = None
    original_invoice_number: str | None = None
    modification_index: int | None = None
    ins_date: str | None = None
    completeness_indicator: bool | None = None
    xml: bytes = b""


@dataclass
class DigestPage:
    current_page: int
    available_page: int
    digests: list[NavDigest] = field(default_factory=list)


@dataclass
class NavVatRow:
    vat_rate: str
    net: float
    vat: float
    gross: float
    net_huf: float
    vat_huf: float


@dataclass
class NavInvoiceData:
    invoice_number: str
    issue_date: str | None = None
    category: str | None = None
    delivery_date: str | None = None
    currency: str | None = None
    exchange_rate: float | None = None
    payment_method: str | None = None
    payment_date: str | None = None
    appearance: str | None = None
    original_invoice_number: str | None = None
    modification_index: int | None = None
    customer_name: str | None = None
    customer_tax_number: str | None = None
    net: float = 0.0
    vat: float = 0.0
    gross: float = 0.0
    net_huf: float = 0.0
    vat_huf: float = 0.0
    gross_huf: float = 0.0
    vat_rows: list[NavVatRow] = field(default_factory=list)


# ---------------------------------------------------------------------------
# XML helpers (namespace-agnostic reads)
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


def _float(el: ET.Element | None, path: str) -> float | None:
    raw = _text(el, path)
    if raw is None:
        return None
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def _int(el: ET.Element | None, path: str) -> int | None:
    raw = _text(el, path)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _bool(el: ET.Element | None, path: str) -> bool | None:
    raw = _text(el, path)
    if raw is None:
        return None
    return raw.lower() == "true"


def nav_vat_key(vat_rate: ET.Element | None) -> str:
    """VatRateType -> szamlazz.hu-style key: '27', '5', '0', 'AAM', 'KBAET', 'EUFAD37', ..."""
    if vat_rate is None:
        return ""
    pct = _float(vat_rate, "vatPercentage")
    if pct is not None:
        value = pct * 100
        return str(int(round(value))) if abs(value - round(value)) < 1e-9 else f"{value:g}"
    for case_path in ("vatExemption/case", "vatOutOfScope/case"):
        case = _text(vat_rate, case_path)
        if case:
            return case
    # ASSUMPTION: domestic reverse charge maps to the szamlazz.hu code F.AFA.
    if _bool(vat_rate, "vatDomesticReverseCharge"):
        return "F.AFA"
    mismatch = _float(vat_rate, "vatAmountMismatch/vatRate")
    if mismatch is not None:
        return str(int(round(mismatch * 100)))
    return "N/A"


def _tax_number(el: ET.Element | None) -> str | None:
    """TaxNumberType (taxpayerId, vatCode, countyCode) -> '12345678-2-41' or '12345678'."""
    if el is None:
        return None
    base = _text(el, "taxpayerId")
    if not base:
        return None
    vat_code = _text(el, "vatCode")
    county = _text(el, "countyCode")
    if vat_code and county:
        return f"{base}-{vat_code}-{county}"
    return base


# ---------------------------------------------------------------------------
# Response parsing (pure)
# ---------------------------------------------------------------------------


def parse_digest_element(xml_bytes: bytes) -> NavDigest:
    el = ET.fromstring(xml_bytes)
    if _local(el.tag) != "invoiceDigest":
        raise ValueError(f"nem <invoiceDigest> elem: <{_local(el.tag)}>")
    return NavDigest(
        invoice_number=_text(el, "invoiceNumber") or "",
        operation=_text(el, "invoiceOperation"),
        category=_text(el, "invoiceCategory"),
        issue_date=_text(el, "invoiceIssueDate"),
        supplier_tax_number=_text(el, "supplierTaxNumber"),
        supplier_name=_text(el, "supplierName"),
        customer_tax_number=_text(el, "customerTaxNumber"),
        customer_name=_text(el, "customerName"),
        payment_method=_text(el, "paymentMethod"),
        payment_date=_text(el, "paymentDate"),
        appearance=_text(el, "invoiceAppearance"),
        source=_text(el, "source"),
        delivery_date=_text(el, "invoiceDeliveryDate"),
        currency=_text(el, "currency"),
        net=_float(el, "invoiceNetAmount"),
        net_huf=_float(el, "invoiceNetAmountHUF"),
        vat=_float(el, "invoiceVatAmount"),
        vat_huf=_float(el, "invoiceVatAmountHUF"),
        transaction_id=_text(el, "transactionId"),
        index=_int(el, "index"),
        original_invoice_number=_text(el, "originalInvoiceNumber"),
        modification_index=_int(el, "modificationIndex"),
        ins_date=_text(el, "insDate"),
        completeness_indicator=_bool(el, "completenessIndicator"),
        xml=xml_bytes,
    )


def digest_element_xml(el: ET.Element) -> bytes:
    return ET.tostring(el, encoding="utf-8")


def _raise_if_error(root: ET.Element, http_status: int) -> None:
    result = _find(root, "result")
    func_code = _text(result, "funcCode")
    if _local(root.tag) == "GeneralErrorResponse" or func_code == "ERROR":
        code = _text(result, "errorCode")
        message = _text(result, "message") or "NAV hiba"
        raise NavError(
            f"NAV {func_code or 'ERROR'} {code or ''}: {message}".strip(),
            func_code=func_code,
            error_code=code,
            http_status=http_status,
        )


def parse_digest_response(xml_bytes: bytes, http_status: int = 200) -> DigestPage:
    root = ET.fromstring(xml_bytes)
    _raise_if_error(root, http_status)
    result = _find(root, "invoiceDigestResult")
    if result is None:
        raise NavError("hiányzó invoiceDigestResult a válaszban", http_status=http_status)
    page = DigestPage(
        current_page=_int(result, "currentPage") or 1,
        available_page=_int(result, "availablePage") or 1,
    )
    for el in _children(result, "invoiceDigest"):
        page.digests.append(parse_digest_element(digest_element_xml(el)))
    return page


def decode_invoice_data(response_xml: bytes, http_status: int = 200) -> bytes:
    """QueryInvoiceDataResponse -> decoded (and un-gzipped) InvoiceData XML bytes."""
    root = ET.fromstring(response_xml)
    _raise_if_error(root, http_status)
    result = _find(root, "invoiceDataResult")
    encoded = _text(result, "invoiceData")
    if not encoded:
        raise NavError("a válasz nem tartalmaz invoiceData elemet", http_status=http_status)
    raw = base64.b64decode(encoded)
    if _bool(result, "compressedContentIndicator"):
        raw = gzip.decompress(raw)
    return raw


def parse_invoice_data(xml_bytes: bytes) -> NavInvoiceData:
    root = ET.fromstring(xml_bytes)
    if _local(root.tag) != "InvoiceData":
        raise ValueError(f"nem <InvoiceData> dokumentum: <{_local(root.tag)}>")
    invoice = _find(root, "invoiceMain/invoice")
    head = _find(invoice, "invoiceHead")
    detail = _find(head, "invoiceDetail")
    reference = _find(invoice, "invoiceReference")
    customer = _find(head, "customerInfo")
    summary = _find(invoice, "invoiceSummary/summaryNormal")
    gross_data = _find(invoice, "invoiceSummary/summaryGrossData")
    data = NavInvoiceData(
        invoice_number=_text(root, "invoiceNumber") or "",
        issue_date=_text(root, "invoiceIssueDate"),
        category=_text(detail, "invoiceCategory"),
        delivery_date=_text(detail, "invoiceDeliveryDate"),
        currency=_text(detail, "currencyCode"),
        exchange_rate=_float(detail, "exchangeRate"),
        payment_method=_text(detail, "paymentMethod"),
        payment_date=_text(detail, "paymentDate"),
        appearance=_text(detail, "invoiceAppearance"),
        original_invoice_number=_text(reference, "originalInvoiceNumber"),
        modification_index=_int(reference, "modificationIndex"),
        customer_name=_text(customer, "customerName"),
        customer_tax_number=_tax_number(_find(customer, "customerVatData/customerTaxNumber"))
        or _text(customer, "customerVatData/communityVatNumber"),
    )
    for row in _children(summary, "summaryByVatRate") if summary is not None else ():
        net = _float(row, "vatRateNetData/vatRateNetAmount") or 0.0
        vat = _float(row, "vatRateVatData/vatRateVatAmount") or 0.0
        gross = _float(row, "vatRateGrossData/vatRateGrossAmount")
        net_huf = _float(row, "vatRateNetData/vatRateNetAmountHUF") or 0.0
        vat_huf = _float(row, "vatRateVatData/vatRateVatAmountHUF") or 0.0
        data.vat_rows.append(
            NavVatRow(
                vat_rate=nav_vat_key(_find(row, "vatRate")),
                net=net,
                vat=vat,
                gross=net + vat if gross is None else gross,
                net_huf=net_huf,
                vat_huf=vat_huf,
            )
        )
    data.net = _float(summary, "invoiceNetAmount") or 0.0
    data.vat = _float(summary, "invoiceVatAmount") or 0.0
    data.net_huf = _float(summary, "invoiceNetAmountHUF") or 0.0
    data.vat_huf = _float(summary, "invoiceVatAmountHUF") or 0.0
    gross = _float(gross_data, "invoiceGrossAmount")
    gross_huf = _float(gross_data, "invoiceGrossAmountHUF")
    data.gross = data.net + data.vat if gross is None else gross
    data.gross_huf = data.net_huf + data.vat_huf if gross_huf is None else gross_huf
    return data


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class NavClient:
    def __init__(
        self,
        login: str,
        password: str,
        signing_key: str,
        tax_number: str,
        software_id: str = DEFAULT_SOFTWARE_ID,
        base_url: str = PRODUCTION_URL,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        request_id_factory: Callable[[], str] = new_request_id,
        timeout: float = DEFAULT_TIMEOUT,
        software_name: str = "controller-claude-kit",
        software_version: str = "0.1.0",
        dev_name: str = "controller-claude-kit",
        dev_contact: str = "n/a",
    ) -> None:
        self._login = login
        self._password_hash = password_hash(password)
        self._signing_key = signing_key
        self._tax_number = tax_number[:8]
        self._software_id = software_id
        self._base_url = base_url.rstrip("/")
        self._session = session or requests.Session()
        self._sleep = sleep
        self._now = now
        self._request_id_factory = request_id_factory
        self._timeout = timeout
        self._software = (software_name, software_version, dev_name, dev_contact)
        self._limiter = RateLimiter(min_interval=1.0, clock=clock, sleep=sleep)

    def __repr__(self) -> str:
        return f"NavClient(login=***, tax_number={self._tax_number}, base_url={self._base_url})"

    def build_request(self, root: str, body: str) -> bytes:
        request_id = self._request_id_factory()
        timestamp = self._now().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        signature = request_signature(request_id, timestamp, self._signing_key)
        name, version, dev_name, dev_contact = self._software
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<{root} xmlns="{API_NS}" xmlns:common="{COMMON_NS}">'
            "<common:header>"
            f"<common:requestId>{request_id}</common:requestId>"
            f"<common:timestamp>{timestamp}</common:timestamp>"
            "<common:requestVersion>3.0</common:requestVersion>"
            "<common:headerVersion>1.0</common:headerVersion>"
            "</common:header>"
            "<common:user>"
            f"<common:login>{escape(self._login)}</common:login>"
            f'<common:passwordHash cryptoType="SHA-512">{self._password_hash}</common:passwordHash>'
            f"<common:taxNumber>{escape(self._tax_number)}</common:taxNumber>"
            f'<common:requestSignature cryptoType="SHA3-512">{signature}</common:requestSignature>'
            "</common:user>"
            "<software>"
            f"<softwareId>{escape(self._software_id)}</softwareId>"
            f"<softwareName>{escape(name)}</softwareName>"
            "<softwareOperation>LOCAL_SOFTWARE</softwareOperation>"
            f"<softwareMainVersion>{escape(version)}</softwareMainVersion>"
            f"<softwareDevName>{escape(dev_name)}</softwareDevName>"
            f"<softwareDevContact>{escape(dev_contact)}</softwareDevContact>"
            "</software>"
            f"{body}"
            f"</{root}>"
        )
        return xml.encode("utf-8")

    def _post(self, operation: str, body: bytes) -> tuple[int, bytes]:
        last_error = "ismeretlen hiba"
        for attempt in range(MAX_ATTEMPTS):
            self._limiter.wait()
            try:
                resp = self._session.post(
                    f"{self._base_url}/{operation}",
                    data=body,
                    headers={"Content-Type": "application/xml", "Accept": "application/xml"},
                    timeout=self._timeout,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = f"hálózati hiba ({type(exc).__name__})"
            else:
                if resp.status_code < 500:
                    return resp.status_code, resp.content
                last_error = f"HTTP {resp.status_code}"
            if attempt < MAX_ATTEMPTS - 1:
                self._sleep(BACKOFF_BASE_SECONDS * (2**attempt))
        raise NavNetworkError(f"{operation}: {last_error}, {MAX_ATTEMPTS} próbálkozás után feladva")

    def _call(self, operation: str, root: str, body: str) -> tuple[int, ET.Element, bytes]:
        status, content = self._post(operation, self.build_request(root, body))
        try:
            parsed = ET.fromstring(content)
        except ET.ParseError as exc:
            raise NavError(
                f"{operation}: nem XML válasz (HTTP {status})", http_status=status
            ) from exc
        _raise_if_error(parsed, status)
        if status >= 400:
            raise NavError(f"{operation}: HTTP {status}", http_status=status)
        return status, parsed, content

    def token_exchange(self) -> tuple[str, str | None, str | None]:
        """Returns (encodedExchangeToken, tokenValidityFrom, tokenValidityTo)."""
        _, root, _ = self._call("tokenExchange", "TokenExchangeRequest", "")
        token = _text(root, "encodedExchangeToken")
        if not token:
            raise NavError("tokenExchange: hiányzó encodedExchangeToken")
        return token, _text(root, "tokenValidityFrom"), _text(root, "tokenValidityTo")

    def query_invoice_digest(
        self, date_from: date, date_to: date, page: int = 1, direction: str = "OUTBOUND"
    ) -> DigestPage:
        if (date_to - date_from).days >= MAX_WINDOW_DAYS:
            raise ValueError(f"az időablak legfeljebb {MAX_WINDOW_DAYS} nap lehet")
        body = (
            f"<page>{page}</page>"
            f"<invoiceDirection>{direction}</invoiceDirection>"
            "<invoiceQueryParams><mandatoryQueryParams><invoiceIssueDate>"
            f"<dateFrom>{date_from.isoformat()}</dateFrom>"
            f"<dateTo>{date_to.isoformat()}</dateTo>"
            "</invoiceIssueDate></mandatoryQueryParams></invoiceQueryParams>"
        )
        status, _, content = self._call("queryInvoiceDigest", "QueryInvoiceDigestRequest", body)
        return parse_digest_response(content, status)

    def iter_digests(
        self, date_from: date, date_to: date, direction: str = "OUTBOUND"
    ) -> Iterator[NavDigest]:
        """All digests for the period: windows of at most 35 days, 100 per page."""
        for window_from, window_to in split_windows(date_from, date_to):
            page = 1
            while True:
                result = self.query_invoice_digest(window_from, window_to, page, direction)
                yield from result.digests
                if page >= result.available_page:
                    break
                page += 1

    def query_invoice_data(self, invoice_number: str, direction: str = "OUTBOUND") -> bytes:
        body = (
            "<invoiceNumberQuery>"
            f"<invoiceNumber>{escape(invoice_number)}</invoiceNumber>"
            f"<invoiceDirection>{direction}</invoiceDirection>"
            "</invoiceNumberQuery>"
        )
        status, _, content = self._call("queryInvoiceData", "QueryInvoiceDataRequest", body)
        return decode_invoice_data(content, status)
