"""NAV Online Számla client: signing, windows, paging, parsing, retries. No network."""

from __future__ import annotations

import base64
import gzip
import hashlib
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime
from pathlib import Path

import nav_client
import pytest
import requests
from nav_client import (
    NavClient,
    NavError,
    NavNetworkError,
    decode_invoice_data,
    new_request_id,
    parse_digest_response,
    parse_invoice_data,
    password_hash,
    request_signature,
    signature_timestamp,
    split_windows,
)

FIXTURES = Path(__file__).parent / "fixtures"
COMMON = f"{{{nav_client.COMMON_NS}}}"
API = f"{{{nav_client.API_NS}}}"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def advancing_clock():
    """(clock, sleep, sleeps): the fake sleep advances the fake clock, like real time would."""
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    return (lambda: now[0]), sleep, sleeps


class FakeResponse:
    def __init__(self, status_code: int, content: bytes = b""):
        self.status_code = status_code
        self.content = content
        self.headers = {}


class FakeSession:
    """`responder(url, body) -> FakeResponse | Exception`; records every post body."""

    def __init__(self, responder):
        self.responder = responder
        self.calls: list[tuple[str, bytes]] = []

    def post(self, url, data=None, headers=None, timeout=None, files=None):
        self.calls.append((url, data))
        item = self.responder(url, data)
        if isinstance(item, Exception):
            raise item
        return item


def make_client(session, **kwargs) -> NavClient:
    return NavClient(
        login="techuser",
        password="Passw0rd!",
        signing_key="ce-8f5e-215119fa7dd621DLMRHRLH2S",
        tax_number="12345678",
        session=session,
        sleep=kwargs.pop("sleep", lambda s: None),
        clock=kwargs.pop("clock", lambda: 0.0),
        now=kwargs.pop("now", lambda: datetime(2026, 9, 6, 10, 0, 0, tzinfo=UTC)),
        request_id_factory=kwargs.pop("request_id_factory", lambda: "RIDTESTFIXEDREQUESTID000001"),
        **kwargs,
    )


# --- signing -----------------------------------------------------------------


def test_password_hash_is_sha512_upper_hex():
    """Expected value computed inline with hashlib (no external worked example available)."""
    expected = hashlib.sha512(b"Passw0rd!").hexdigest().upper()
    assert password_hash("Passw0rd!") == expected
    assert len(expected) == 128 and expected == expected.upper()


def test_request_signature_is_sha3_512_of_id_timestamp_key():
    """Expected value computed inline with hashlib per NAV 3.0 section 1.5 (requestId +
    yyyyMMddHHmmss + signing key, SHA3-512 upper hex). Not verified against a NAV worked
    example, because the public sample does not publish its signing key."""
    request_id = "RID896801578348"
    timestamp = "2019-09-11T10:55:31.440Z"
    key = "ce-8f5e-215119fa7dd621DLMRHRLH2S"
    expected = (
        hashlib.sha3_512((request_id + "20190911105531" + key).encode("utf-8")).hexdigest().upper()
    )
    assert request_signature(request_id, timestamp, key) == expected
    assert request_signature(request_id, "20190911105531", key) == expected


def test_signature_timestamp_strips_to_14_digits_and_rejects_short():
    assert signature_timestamp("2026-09-06T10:00:00.000Z") == "20260906100000"
    assert signature_timestamp("2026-09-06T10:00:00Z") == "20260906100000"
    with pytest.raises(ValueError):
        signature_timestamp("2026-09-06")


def test_new_request_id_is_30_alnum_and_unique():
    ids = {new_request_id() for _ in range(50)}
    assert len(ids) == 50
    for rid in ids:
        assert len(rid) == 30 and rid.isalnum() and rid.startswith("RID")


# --- window splitting --------------------------------------------------------


def test_split_windows_90_days_into_three():
    windows = split_windows(date(2026, 1, 1), date(2026, 3, 31))
    assert windows == [
        (date(2026, 1, 1), date(2026, 2, 4)),
        (date(2026, 2, 5), date(2026, 3, 11)),
        (date(2026, 3, 12), date(2026, 3, 31)),
    ]
    for start, end in windows:
        assert (end - start).days <= 34
    assert split_windows(date(2026, 8, 1), date(2026, 8, 31)) == [
        (date(2026, 8, 1), date(2026, 8, 31))
    ]
    with pytest.raises(ValueError):
        split_windows(date(2026, 2, 1), date(2026, 1, 1))


def test_query_invoice_digest_rejects_window_over_35_days():
    client = make_client(FakeSession(lambda u, b: FakeResponse(200, b"")))
    with pytest.raises(ValueError):
        client.query_invoice_digest(date(2026, 1, 1), date(2026, 2, 5))


# --- parsing -----------------------------------------------------------------


def test_parse_digest_pages():
    page1 = parse_digest_response(fixture("nav_digest_page1.xml"))
    assert (page1.current_page, page1.available_page) == (1, 2)
    assert [d.invoice_number for d in page1.digests] == [
        "SZLA-2026-1",
        "SZLA-2026-2",
        "SZLA-2026-3",
    ]
    d = page1.digests[0]
    assert (d.operation, d.category, d.issue_date) == ("CREATE", "NORMAL", "2026-08-05")
    assert (d.customer_name, d.customer_tax_number) == ("Alfa Ügyfél Zrt.", "23456789")
    assert (d.payment_method, d.payment_date, d.delivery_date) == (
        "TRANSFER",
        "2026-08-20",
        "2026-08-05",
    )
    assert (d.currency, d.net, d.net_huf, d.vat, d.vat_huf) == (
        "HUF",
        120000.0,
        120000.0,
        28000.0,
        28000.0,
    )
    assert d.appearance == "PAPER" and d.source == "XML" and d.index == 1
    assert d.original_invoice_number is None and d.modification_index is None
    assert d.ins_date == "2026-08-05T10:15:00Z" and d.completeness_indicator is False
    assert nav_client.parse_digest_element(d.xml).invoice_number == "SZLA-2026-1"
    storno = page1.digests[1]
    assert (storno.operation, storno.original_invoice_number, storno.modification_index) == (
        "STORNO",
        "SZLA-2026-1",
        1,
    )
    assert storno.net == -120000.0
    page2 = parse_digest_response(fixture("nav_digest_page2.xml"))
    assert (page2.current_page, page2.available_page) == (2, 2)
    assert [d.invoice_number for d in page2.digests] == [
        "SZLA-2026-4",
        "E-SZLA-2026-1",
        "SZLA-2026-5",
    ]
    eur = page2.digests[1]
    assert (eur.currency, eur.net, eur.net_huf, eur.appearance) == (
        "EUR",
        1000.0,
        399500.0,
        "ELECTRONIC",
    )
    assert eur.customer_tax_number is None


def test_parse_invoice_data_fixture():
    data = parse_invoice_data(fixture("nav_invoicedata.xml"))
    assert data.invoice_number == "E-SZLA-2026-1"
    assert data.issue_date == "2026-08-12"
    assert (data.category, data.delivery_date, data.currency, data.exchange_rate) == (
        "NORMAL",
        "2026-08-12",
        "EUR",
        399.5,
    )
    assert (data.payment_method, data.payment_date, data.appearance) == (
        "TRANSFER",
        "2026-09-11",
        "ELECTRONIC",
    )
    assert data.original_invoice_number is None and data.modification_index is None
    assert (data.customer_name, data.customer_tax_number) == ("Gamma GmbH", "ATU12345678")
    assert (data.net, data.vat, data.gross) == (1000.0, 0.0, 1000.0)
    assert (data.net_huf, data.vat_huf, data.gross_huf) == (399500.0, 0.0, 399500.0)
    assert len(data.vat_rows) == 1
    row = data.vat_rows[0]
    assert (row.vat_rate, row.net, row.vat, row.gross, row.net_huf, row.vat_huf) == (
        "KBAET",
        1000.0,
        0.0,
        1000.0,
        399500.0,
        0.0,
    )


def test_nav_vat_key_variants():
    def el(inner: str) -> ET.Element:
        return ET.fromstring(f"<vatRate>{inner}</vatRate>")

    assert nav_client.nav_vat_key(el("<vatPercentage>0.27</vatPercentage>")) == "27"
    assert nav_client.nav_vat_key(el("<vatPercentage>0.05</vatPercentage>")) == "5"
    assert nav_client.nav_vat_key(el("<vatPercentage>0</vatPercentage>")) == "0"
    assert nav_client.nav_vat_key(el("<vatExemption><case>AAM</case></vatExemption>")) == "AAM"
    assert (
        nav_client.nav_vat_key(el("<vatOutOfScope><case>EUFAD37</case></vatOutOfScope>"))
        == "EUFAD37"
    )
    assert (
        nav_client.nav_vat_key(el("<vatDomesticReverseCharge>true</vatDomesticReverseCharge>"))
        == "F.AFA"
    )
    assert (
        nav_client.nav_vat_key(el("<vatAmountMismatch><vatRate>0.18</vatRate></vatAmountMismatch>"))
        == "18"
    )
    assert nav_client.nav_vat_key(None) == ""


def test_decode_invoice_data_plain_and_gzip():
    raw = fixture("nav_invoicedata.xml")

    def response(payload: bytes, compressed: bool) -> bytes:
        return (
            f'<QueryInvoiceDataResponse xmlns="{nav_client.API_NS}" '
            f'xmlns:common="{nav_client.COMMON_NS}">'
            "<common:result><common:funcCode>OK</common:funcCode></common:result>"
            f"<invoiceDataResult><invoiceData>{base64.b64encode(payload).decode()}</invoiceData>"
            "<auditData><insdate>2026-08-12T14:45:00Z</insdate></auditData>"
            "<compressedContentIndicator>"
            f"{'true' if compressed else 'false'}</compressedContentIndicator>"
            "</invoiceDataResult></QueryInvoiceDataResponse>"
        ).encode()

    assert decode_invoice_data(response(raw, False)) == raw
    assert decode_invoice_data(response(gzip.compress(raw), True)) == raw


def test_general_error_response_raises_nav_error():
    body = (
        f'<GeneralErrorResponse xmlns="{nav_client.API_NS}" xmlns:common="{nav_client.COMMON_NS}">'
        "<common:result><common:funcCode>ERROR</common:funcCode>"
        "<common:errorCode>INVALID_SECURITY_USER</common:errorCode>"
        "<common:message>Invalid login or password</common:message></common:result>"
        "</GeneralErrorResponse>"
    ).encode()
    with pytest.raises(NavError) as info:
        parse_digest_response(body, 401)
    assert info.value.error_code == "INVALID_SECURITY_USER"
    assert info.value.func_code == "ERROR"
    assert info.value.http_status == 401


# --- request envelope --------------------------------------------------------


def test_build_request_envelope_structure_and_hashes():
    client = make_client(FakeSession(lambda u, b: FakeResponse(200, b"")))
    xml = client.build_request("QueryInvoiceDigestRequest", "<page>1</page>")
    root = ET.fromstring(xml)
    assert root.tag == f"{API}QueryInvoiceDigestRequest"
    header = root.find(f"{COMMON}header")
    assert [c.tag for c in header] == [
        f"{COMMON}requestId",
        f"{COMMON}timestamp",
        f"{COMMON}requestVersion",
        f"{COMMON}headerVersion",
    ]
    assert header.find(f"{COMMON}requestId").text == "RIDTESTFIXEDREQUESTID000001"
    assert header.find(f"{COMMON}timestamp").text == "2026-09-06T10:00:00.000Z"
    assert header.find(f"{COMMON}requestVersion").text == "3.0"
    user = root.find(f"{COMMON}user")
    assert user.find(f"{COMMON}login").text == "techuser"
    pw = user.find(f"{COMMON}passwordHash")
    assert pw.get("cryptoType") == "SHA-512"
    assert pw.text == hashlib.sha512(b"Passw0rd!").hexdigest().upper()
    assert user.find(f"{COMMON}taxNumber").text == "12345678"
    sig = user.find(f"{COMMON}requestSignature")
    assert sig.get("cryptoType") == "SHA3-512"
    expected = (
        hashlib.sha3_512(
            b"RIDTESTFIXEDREQUESTID000001" + b"20260906100000" + b"ce-8f5e-215119fa7dd621DLMRHRLH2S"
        )
        .hexdigest()
        .upper()
    )
    assert sig.text == expected
    software = root.find(f"{API}software")
    assert software.find(f"{API}softwareId").text == nav_client.DEFAULT_SOFTWARE_ID
    assert len(nav_client.DEFAULT_SOFTWARE_ID) == 18
    assert software.find(f"{API}softwareOperation").text == "LOCAL_SOFTWARE"
    assert root.find(f"{API}page").text == "1"
    assert b"Passw0rd!" not in xml
    assert b"ce-8f5e-215119fa7dd621DLMRHRLH2S" not in xml
    assert "Passw0rd!" not in repr(client)


# --- paging and windows through the client -----------------------------------


def make_digest_responder(pages: dict[int, bytes]):
    def responder(url: str, body: bytes):
        assert url.endswith("/queryInvoiceDigest")
        for page, content in pages.items():
            if f"<page>{page}</page>".encode() in body:
                return FakeResponse(200, content)
        raise AssertionError("unexpected page")

    return responder


def test_iter_digests_pages_and_windows():
    session = FakeSession(
        make_digest_responder(
            {1: fixture("nav_digest_page1.xml"), 2: fixture("nav_digest_page2.xml")}
        )
    )
    client = make_client(session)
    digests = list(client.iter_digests(date(2026, 1, 1), date(2026, 3, 31)))
    assert len(session.calls) == 6
    assert len(digests) == 18
    bodies = [b for _, b in session.calls]
    assert bodies[0].count(b"<dateFrom>2026-01-01</dateFrom>") == 1
    assert b"<dateTo>2026-02-04</dateTo>" in bodies[0]
    assert b"<page>2</page>" in bodies[1]
    assert b"<dateFrom>2026-02-05</dateFrom>" in bodies[2]
    assert b"<dateFrom>2026-03-12</dateFrom>" in bodies[4]
    assert b"<dateTo>2026-03-31</dateTo>" in bodies[5]
    assert b"<invoiceDirection>OUTBOUND</invoiceDirection>" in bodies[0]
    assert digests[0].invoice_number == "SZLA-2026-1"
    assert digests[5].invoice_number == "SZLA-2026-5"


def test_iter_digests_single_window_single_page():
    page = fixture("nav_digest_page2.xml").replace(
        b"<currentPage>2</currentPage>", b"<currentPage>1</currentPage>"
    )
    page = page.replace(b"<availablePage>2</availablePage>", b"<availablePage>1</availablePage>")
    session = FakeSession(make_digest_responder({1: page}))
    client = make_client(session)
    assert len(list(client.iter_digests(date(2026, 8, 1), date(2026, 8, 31)))) == 3
    assert len(session.calls) == 1


def test_query_invoice_data_roundtrip():
    raw = fixture("nav_invoicedata.xml")
    body = (
        f'<QueryInvoiceDataResponse xmlns="{nav_client.API_NS}" '
        f'xmlns:common="{nav_client.COMMON_NS}">'
        "<common:result><common:funcCode>OK</common:funcCode></common:result>"
        f"<invoiceDataResult><invoiceData>{base64.b64encode(gzip.compress(raw)).decode()}</invoiceData>"
        "<compressedContentIndicator>true</compressedContentIndicator></invoiceDataResult>"
        "</QueryInvoiceDataResponse>"
    ).encode()
    session = FakeSession(lambda u, b: FakeResponse(200, body))
    client = make_client(session)
    assert client.query_invoice_data("E-SZLA-2026-1") == raw
    url, sent = session.calls[0]
    assert url.endswith("/queryInvoiceData")
    assert b"<invoiceNumber>E-SZLA-2026-1</invoiceNumber>" in sent


def test_token_exchange_parses_token():
    body = (
        f'<TokenExchangeResponse xmlns="{nav_client.API_NS}" xmlns:common="{nav_client.COMMON_NS}">'
        "<common:result><common:funcCode>OK</common:funcCode></common:result>"
        "<encodedExchangeToken>QUJD</encodedExchangeToken>"
        "<tokenValidityFrom>2026-09-06T10:00:00.000Z</tokenValidityFrom>"
        "<tokenValidityTo>2026-09-06T10:05:00.000Z</tokenValidityTo>"
        "</TokenExchangeResponse>"
    ).encode()
    client = make_client(FakeSession(lambda u, b: FakeResponse(200, body)))
    token, valid_from, valid_to = client.token_exchange()
    assert token == "QUJD"
    assert valid_from.startswith("2026-09-06T10:00") and valid_to.startswith("2026-09-06T10:05")


def test_retry_on_5xx_then_success_and_exhaustion():
    clock, sleep, sleeps = advancing_clock()
    attempts = {"n": 0}

    def responder(url, body):
        attempts["n"] += 1
        if attempts["n"] < 3:
            return FakeResponse(503, b"")
        return FakeResponse(
            200,
            fixture("nav_digest_page2.xml").replace(
                b"<availablePage>2</availablePage>", b"<availablePage>1</availablePage>"
            ),
        )

    client = make_client(FakeSession(responder), sleep=sleep, clock=clock)
    page = client.query_invoice_digest(date(2026, 8, 1), date(2026, 8, 31))
    assert len(page.digests) == 3
    assert sleeps == [2.0, 4.0]

    clock, sleep, sleeps = advancing_clock()
    failing = FakeSession(lambda u, b: requests.Timeout("t"))
    client = make_client(failing, sleep=sleep, clock=clock)
    with pytest.raises(NavNetworkError) as info:
        client.token_exchange()
    assert len(failing.calls) == 5
    assert sleeps == [2.0, 4.0, 8.0, 16.0]
    assert "Passw0rd!" not in str(info.value)


def test_http_4xx_without_error_body_raises_nav_error():
    client = make_client(FakeSession(lambda u, b: FakeResponse(404, b"<x/>")))
    with pytest.raises(NavError) as info:
        client.token_exchange()
    assert info.value.http_status == 404
