"""Számla Agent client: XML parsing, error mapping, retry/backoff, rate limit. No network."""

from __future__ import annotations

import base64
import xml.etree.ElementTree as ET
from pathlib import Path

import agent_client
import pytest
import requests
from agent_client import (
    AgentClient,
    AgentNetworkError,
    NotFound,
    RateLimiter,
    build_request_xml,
    parse_invoice_xml,
    parse_response,
)

FIXTURES = Path(__file__).parent / "fixtures"


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
    def __init__(self, status_code: int, content: bytes = b"", headers: dict | None = None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


class FakeSession:
    """Returns queued responses (or raises queued exceptions) and records every post."""

    def __init__(self, queue: list):
        self.queue = list(queue)
        self.calls: list[dict] = []

    def post(self, url, files=None, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "files": files, "data": data, "timeout": timeout})
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# --- parsing -----------------------------------------------------------------


def test_parse_normal_header_customer_lines_vat_payments():
    doc = parse_invoice_xml(fixture("agent_szamla_normal.xml"))
    h = doc.header
    assert h.invoice_number == "SZLA-2026-1"
    assert h.doc_type_code == "SZ"
    assert h.is_einvoice is False
    assert (h.issue_date, h.delivery_date, h.due_date) == ("2026-08-05", "2026-08-05", "2026-08-20")
    assert h.payment_method_raw == "Átutalás"
    assert h.payment_method_unified == "transfer"
    assert h.language == "hu"
    assert h.currency == "Ft"
    assert h.fx_rate == 0
    assert h.reference is None
    assert h.order_ref == "PO-2026-11"
    assert h.note == "Augusztusi fejlesztés"
    assert h.is_test is False
    c = doc.customer
    assert c.szamlazz_id == "501"
    assert c.name == "Alfa Ügyfél Zrt."
    assert c.tax_number == "23456789-2-41"
    assert c.eu_tax_number is None
    assert (c.country, c.postcode, c.city, c.address) == (
        "Magyarország",
        "1052",
        "Budapest",
        "Váci utca 10.",
    )
    assert c.email == "penzugy@alfa.example"
    assert c.is_private is False
    assert [
        (
            ln.line_no,
            ln.name,
            ln.quantity,
            ln.unit,
            ln.unit_price,
            ln.vat_rate,
            ln.net,
            ln.vat,
            ln.gross,
            ln.ledger_code,
        )
        for ln in doc.lines
    ] == [
        (
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
        (2, "Szakkönyv", 4.0, "db", 5000.0, "5", 20000.0, 1000.0, 21000.0, "912"),
    ]
    assert [(v.vat_rate, v.net, v.vat, v.gross) for v in doc.vat_totals] == [
        ("27", 100000.0, 27000.0, 127000.0),
        ("5", 20000.0, 1000.0, 21000.0),
    ]
    assert (doc.total_net, doc.total_vat, doc.total_gross) == (120000.0, 28000.0, 148000.0)
    assert len(doc.payments) == 1
    p = doc.payments[0]
    assert (p.seq, p.pay_date, p.pay_type, p.amount, p.note) == (
        1,
        "2026-08-18",
        "átutalás",
        100000.0,
        "részfizetés",
    )
    assert p.bank_account == "11111111-22222222-33333333"
    assert p.fx_rate is None
    assert doc.pdf is None


def test_parse_storno_is_signed_negative_and_references_original():
    doc = parse_invoice_xml(fixture("agent_szamla_storno.xml"))
    assert doc.header.invoice_number == "SZLA-2026-2"
    assert doc.header.doc_type_code == "SS"
    assert doc.header.reference == "SZLA-2026-1"
    assert doc.header.issue_date == "2026-08-25"
    assert doc.header.delivery_date == "2026-08-05"
    assert (doc.total_net, doc.total_vat, doc.total_gross) == (-120000.0, -28000.0, -148000.0)
    assert [ln.net for ln in doc.lines] == [-100000.0, -20000.0]
    assert [ln.quantity for ln in doc.lines] == [-10.0, -4.0]
    assert doc.payments == []


def test_parse_modifier_adds_one_line():
    doc = parse_invoice_xml(fixture("agent_szamla_modifier.xml"))
    assert doc.header.invoice_number == "SZLA-2026-4"
    assert doc.header.doc_type_code == "HS"
    assert doc.header.reference == "SZLA-2026-3"
    assert doc.header.due_date == "2026-09-06"
    assert len(doc.lines) == 1
    assert (doc.lines[0].name, doc.lines[0].net, doc.lines[0].vat, doc.lines[0].gross) == (
        "Kiegészítő tanácsadás",
        10000.0,
        2700.0,
        12700.0,
    )
    assert (doc.total_net, doc.total_vat, doc.total_gross) == (10000.0, 2700.0, 12700.0)


def test_parse_active_cash_invoice():
    doc = parse_invoice_xml(fixture("agent_szamla_active.xml"))
    assert doc.header.invoice_number == "SZLA-2026-3"
    assert doc.header.payment_method_raw == "Készpénz"
    assert doc.header.payment_method_unified == "cash"
    assert doc.header.currency == "HUF"
    assert doc.header.fx_rate == 1.0
    assert doc.customer.szamlazz_id == "502"
    assert doc.payments[0].amount == 63500.0
    assert doc.payments[0].pay_type == "készpénz"


def test_parse_eur_invoice_with_devizaarf_and_payment_rate():
    doc = parse_invoice_xml(fixture("agent_szamla_eur.xml"))
    h = doc.header
    assert h.invoice_number == "E-SZLA-2026-1"
    assert h.is_einvoice is True
    assert h.currency == "EUR"
    assert h.fx_rate == 400.0
    assert h.language == "en"
    assert h.order_ref == "AT-77"
    assert doc.customer.szamlazz_id == "601"
    assert doc.customer.tax_number is None
    assert doc.customer.eu_tax_number == "ATU12345678"
    assert doc.customer.country == "Ausztria"
    assert doc.lines[0].vat_rate == "EU"
    assert doc.vat_totals[0].vat_rate == "EU"
    assert (doc.total_net, doc.total_vat, doc.total_gross) == (1000.0, 0.0, 1000.0)
    assert doc.payments[0].amount == 600.0
    assert doc.payments[0].fx_rate == 400.0
    assert doc.payments[0].bank_account == "HU11 1111 1111 2222 2222 3333 3333"


def test_parse_rejects_non_szamla_root():
    with pytest.raises(ValueError):
        parse_invoice_xml(fixture("agent_error_7.xml"))


def test_parse_decodes_embedded_pdf():
    pdf_bytes = b"%PDF-1.4 fake"
    xml = fixture("agent_szamla_active.xml").replace(
        b"</szamla>", b"<pdf>" + base64.b64encode(pdf_bytes) + b"</pdf></szamla>"
    )
    assert parse_invoice_xml(xml).pdf == pdf_bytes
    result = parse_response(200, {}, xml)
    assert result.ok and result.pdf == pdf_bytes


# --- error mapping -----------------------------------------------------------


def test_error_7_body_maps_to_not_found():
    result = parse_response(200, {}, fixture("agent_error_7.xml"))
    assert result.ok is False
    assert result.error_code == 7
    assert result.not_found is True
    assert "ismeretlen számlaszám" in (result.error_message or "")
    with pytest.raises(NotFound):
        result.raise_for_error()


def test_error_code_in_headers_wins():
    result = parse_response(
        200, {"szlahu_error_code": "3", "szlahu_error": "Sikertelen bejelentkezés"}, b"<szamla/>"
    )
    assert (result.ok, result.error_code, result.error_message) == (
        False,
        3,
        "Sikertelen bejelentkezés",
    )
    assert result.not_found is False
    with pytest.raises(agent_client.AgentError):
        result.raise_for_error()


def test_http_4xx_is_not_ok_and_not_retried():
    session = FakeSession([FakeResponse(403, b"forbidden")])
    client = AgentClient("KEY", session=session, sleep=lambda s: None)
    result = client.fetch_invoice("SZLA-2026-1")
    assert result.ok is False
    assert result.error_message == "HTTP 403"
    assert len(session.calls) == 1


def test_unexpected_root_is_not_ok():
    result = parse_response(200, {}, b"<valami/>")
    assert result.ok is False
    result = parse_response(200, {}, b"not xml at all")
    assert result.ok is False


# --- request building and transport -----------------------------------------


def test_build_request_xml_field_order_and_namespace():
    xml = build_request_xml("K" * 42, "SZLA-2026-1", with_pdf=True)
    root = ET.fromstring(xml)
    assert root.tag == f"{{{agent_client.REQUEST_NS}}}xmlszamlaxml"
    names = [child.tag.split("}")[1] for child in root]
    assert names == ["szamlaagentkulcs", "szamlaszam", "rendelesSzam", "pdf", "szamlaKulsoAzon"]
    assert root[0].text == "K" * 42
    assert root[1].text == "SZLA-2026-1"
    assert root[3].text == "true"
    assert b"<pdf>false</pdf>" in build_request_xml("k", "X-1")


def test_fetch_posts_multipart_field_and_parses_success():
    session = FakeSession([FakeResponse(200, fixture("agent_szamla_normal.xml"))])
    client = AgentClient("SECRET-KEY", session=session, sleep=lambda s: None)
    result = client.fetch_invoice("SZLA-2026-1")
    assert result.ok is True
    assert parse_invoice_xml(result.xml).header.invoice_number == "SZLA-2026-1"
    call = session.calls[0]
    assert call["url"] == agent_client.AGENT_URL
    assert list(call["files"]) == [agent_client.FORM_FIELD]
    filename, body, content_type = call["files"][agent_client.FORM_FIELD]
    assert filename == "request.xml"
    assert b"<szamlaagentkulcs>SECRET-KEY</szamlaagentkulcs>" in body
    assert content_type == "text/xml"


def test_retry_with_exponential_backoff_on_5xx():
    sleeps: list[float] = []
    session = FakeSession(
        [
            FakeResponse(502),
            FakeResponse(503),
            FakeResponse(200, fixture("agent_szamla_active.xml")),
        ]
    )
    client = AgentClient("k", session=session, sleep=sleeps.append)
    result = client.fetch_invoice("SZLA-2026-3")
    assert result.ok is True
    assert len(session.calls) == 3
    assert [s for s in sleeps if s >= 2.0] == [2.0, 4.0]


def test_retry_exhausted_after_five_attempts_and_key_never_leaks():
    clock, sleep, sleeps = advancing_clock()
    session = FakeSession([requests.Timeout("t")] * 3 + [requests.ConnectionError("c")] * 2)
    client = AgentClient("VERY-SECRET", session=session, sleep=sleep, clock=clock)
    with pytest.raises(AgentNetworkError) as info:
        client.fetch_invoice("SZLA-2026-9")
    assert len(session.calls) == 5
    assert sleeps == [2.0, 4.0, 8.0, 16.0]
    assert "VERY-SECRET" not in str(info.value)
    assert "SZLA-2026-9" in str(info.value)
    assert "VERY-SECRET" not in repr(client)


def test_rate_limiter_one_request_per_second_with_injected_clock():
    now = [100.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(min_interval=1.0, clock=lambda: now[0], sleep=sleep)
    limiter.wait()
    assert sleeps == []
    limiter.wait()
    assert sleeps == [pytest.approx(1.0)]
    now[0] += 5.0
    limiter.wait()
    assert len(sleeps) == 1


def test_client_rate_limits_consecutive_fetches():
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    body = fixture("agent_szamla_active.xml")
    session = FakeSession(
        [FakeResponse(200, body), FakeResponse(200, body), FakeResponse(200, body)]
    )
    client = AgentClient("k", session=session, sleep=sleep, clock=lambda: now[0])
    for _ in range(3):
        client.fetch_invoice("SZLA-2026-3")
    assert sleeps == [pytest.approx(1.0), pytest.approx(1.0)]
