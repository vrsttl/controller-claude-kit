"""szamlazz_sync CLI: incremental agent-only enumeration, period pull, exit codes, status."""

from __future__ import annotations

from pathlib import Path

import agent_client
import db
import get_secret
import nav_client
import pytest
import szamlazz_sync
from conftest import FIXTURES, load_fixture_raw

TEMPLATE = (FIXTURES / "agent_szamla_active.xml").read_bytes()
ERROR_7 = (FIXTURES / "agent_error_7.xml").read_bytes()


def invoice_xml(number: str) -> bytes:
    return TEMPLATE.replace(b"SZLA-2026-3", number.encode())


class FakeAgent:
    """Knows a set of invoice numbers; everything else is error 7. Records calls."""

    def __init__(
        self, known: set[str], fail_with: Exception | None = None, login_error: bool = False
    ):
        self.known = set(known)
        self.calls: list[str] = []
        self.fail_with = fail_with
        self.login_error = login_error

    def fetch_invoice(self, number: str, with_pdf: bool = False) -> agent_client.AgentResult:
        self.calls.append(number)
        if self.fail_with is not None:
            raise self.fail_with
        if self.login_error:
            return agent_client.AgentResult(
                ok=False, error_code=3, error_message="Sikertelen bejelentkezés"
            )
        if number in self.known:
            return agent_client.AgentResult(ok=True, xml=invoice_xml(number))
        return agent_client.parse_response(200, {}, ERROR_7)


class FakeNav:
    def __init__(
        self, digests: list[nav_client.NavDigest] | None = None, fail_with: Exception | None = None
    ):
        self.digests = digests or []
        self.fail_with = fail_with
        self.calls: list[tuple] = []
        self.data_calls: list[str] = []

    def iter_digests(self, date_from, date_to, direction="OUTBOUND"):
        self.calls.append((date_from, date_to))
        if self.fail_with is not None:
            raise self.fail_with
        yield from self.digests

    def query_invoice_data(self, number: str, direction: str = "OUTBOUND") -> bytes:
        self.data_calls.append(number)
        if number == "E-SZLA-2026-1":
            return (FIXTURES / "nav_invoicedata.xml").read_bytes()
        raise nav_client.NavError("nincs adat", error_code="INVALID_INVOICE")


def all_digests() -> list[nav_client.NavDigest]:
    out = []
    for name in ("nav_digest_page1.xml", "nav_digest_page2.xml"):
        out.extend(nav_client.parse_digest_response((FIXTURES / name).read_bytes()).digests)
    return out


def run(db_path: Path, *argv: str, agent=None, nav=None) -> int:
    return szamlazz_sync.main(
        ["--db", str(db_path), *argv],
        agent_factory=(lambda: agent) if agent is not None else None,
        nav_factory=(lambda: nav) if nav is not None else None,
    )


def invoice_numbers(db_path: Path) -> list[str]:
    conn = db.connect(db_path)
    try:
        return [
            r[0] for r in conn.execute("SELECT invoice_number FROM invoice ORDER BY invoice_number")
        ]
    finally:
        conn.close()


def sync_rows(db_path: Path) -> list[tuple]:
    conn = db.connect(db_path)
    try:
        return [
            tuple(r)
            for r in conn.execute(
                "SELECT source, window_from, window_to, fetched, inserted, errors "
                "FROM sync_log ORDER BY id"
            )
        ]
    finally:
        conn.close()


# --- agent-only enumeration --------------------------------------------------


def test_agent_only_enumerates_until_three_misses_and_is_incremental(tmp_path: Path):
    path = tmp_path / "inv.db"
    agent = FakeAgent({"SZLA-2026-1", "SZLA-2026-2", "SZLA-2026-3"})
    code = run(path, "pull", "--agent-only", "--prefix", "SZLA", "--year", "2026", agent=agent)
    assert code == 0
    assert agent.calls == [f"SZLA-2026-{i}" for i in range(1, 7)]
    assert invoice_numbers(path) == ["SZLA-2026-1", "SZLA-2026-2", "SZLA-2026-3"]
    rows = sync_rows(path)
    assert rows[-1] == ("agent", "SZLA-2026-1", "SZLA-2026-6", 3, 3, 0)

    agent.calls.clear()
    agent.known.add("SZLA-2026-4")
    code = run(path, "pull", "--agent-only", "--prefix", "SZLA", "--year", "2026", agent=agent)
    assert code == 0
    assert agent.calls == ["SZLA-2026-4", "SZLA-2026-5", "SZLA-2026-6", "SZLA-2026-7"]
    assert invoice_numbers(path) == ["SZLA-2026-1", "SZLA-2026-2", "SZLA-2026-3", "SZLA-2026-4"]
    assert sync_rows(path)[-1] == ("agent", "SZLA-2026-4", "SZLA-2026-7", 1, 1, 0)


def test_agent_only_multiple_prefixes_and_dash_in_prefix(tmp_path: Path):
    path = tmp_path / "inv.db"
    agent = FakeAgent({"SZLA-2026-1", "E-SZLA-2026-1", "E-SZLA-2026-2"})
    code = run(
        path,
        "pull",
        "--agent-only",
        "--prefix",
        "SZLA",
        "--prefix",
        "E-SZLA",
        "--year",
        "2026",
        agent=agent,
    )
    assert code == 0
    assert invoice_numbers(path) == ["E-SZLA-2026-1", "E-SZLA-2026-2", "SZLA-2026-1"]
    assert agent.calls[:4] == ["SZLA-2026-1", "SZLA-2026-2", "SZLA-2026-3", "SZLA-2026-4"]
    assert agent.calls[4:] == [f"E-SZLA-2026-{i}" for i in range(1, 6)]


def test_agent_only_max_cap_and_start_seq(tmp_path: Path):
    path = tmp_path / "inv.db"
    agent = FakeAgent({f"SZLA-2026-{i}" for i in range(1, 50)})
    code = run(
        path,
        "pull",
        "--agent-only",
        "--prefix",
        "SZLA",
        "--year",
        "2026",
        "--max",
        "2",
        "--start-seq",
        "10",
        agent=agent,
    )
    assert code == 0
    assert agent.calls == ["SZLA-2026-10", "SZLA-2026-11"]
    assert invoice_numbers(path) == ["SZLA-2026-10", "SZLA-2026-11"]


def test_agent_only_nothing_found_exits_1(tmp_path: Path):
    path = tmp_path / "inv.db"
    agent = FakeAgent(set())
    assert (
        run(path, "pull", "--agent-only", "--prefix", "NINCS", "--year", "2026", agent=agent) == 1
    )
    assert agent.calls == ["NINCS-2026-1", "NINCS-2026-2", "NINCS-2026-3"]


def test_agent_only_network_failure_exits_3(tmp_path: Path):
    path = tmp_path / "inv.db"
    agent = FakeAgent(set(), fail_with=agent_client.AgentNetworkError("SZLA-2026-1: HTTP 503"))
    assert run(path, "pull", "--agent-only", "--prefix", "SZLA", "--year", "2026", agent=agent) == 3
    assert sync_rows(path)[-1][0] == "agent"
    assert sync_rows(path)[-1][5] == 1


def test_agent_login_error_exits_2(tmp_path: Path, capsys):
    path = tmp_path / "inv.db"
    agent = FakeAgent(set(), login_error=True)
    assert run(path, "pull", "--agent-only", "--prefix", "SZLA", "--year", "2026", agent=agent) == 2
    assert "get_secret.py set szamlazz.hu agent-key" in capsys.readouterr().out


def test_missing_secret_exits_2_with_hungarian_command(tmp_path: Path, capsys):
    path = tmp_path / "inv.db"

    def factory():
        raise get_secret.SecretMissing("szamlazz.hu", "agent-key")

    code = szamlazz_sync.main(
        ["--db", str(path), "pull", "--agent-only", "--prefix", "SZLA", "--year", "2026"],
        agent_factory=factory,
    )
    assert code == 2
    out = capsys.readouterr().out
    assert "Hiányzó titok: szamlazz.hu / agent-key" in out
    assert "uv run scripts/get_secret.py set szamlazz.hu agent-key" in out


def test_get_secret_raises_secret_missing(monkeypatch):
    monkeypatch.setattr(get_secret.keyring, "get_password", lambda service, name: None)
    with pytest.raises(get_secret.SecretMissing) as info:
        get_secret.get_secret("nav.gov.hu", "signing-key")
    assert "uv run scripts/get_secret.py set nav.gov.hu signing-key" in str(info.value)
    assert get_secret.get_secret("nav.gov.hu", "signing-key", required=False) is None
    monkeypatch.setattr(get_secret.keyring, "get_password", lambda service, name: "value")
    assert get_secret.get_secret("nav.gov.hu", "signing-key") == "value"
    rows = get_secret.check_all()
    assert len(rows) == 5 and all(r[3] == "megvan" for r in rows)


@pytest.mark.parametrize(
    "argv",
    [
        ["pull"],
        ["pull", "--agent-only"],
        ["pull", "--agent-only", "--prefix", "SZLA"],
        ["pull", "--period", "2026-8"],
        ["pull", "--period", "2026-08", "--agent-only", "--prefix", "A", "--year", "2026"],
        ["reconcile", "--period", "augusztus"],
    ],
)
def test_usage_errors_exit_2(tmp_path: Path, argv):
    assert run(tmp_path / "inv.db", *argv, agent=FakeAgent(set()), nav=FakeNav()) == 2


# --- period pull (NAV digest then Agent) ---------------------------------------


def test_pull_period_fetches_only_numbers_unknown_to_agent(tmp_path: Path):
    path = tmp_path / "inv.db"
    nav = FakeNav(all_digests())
    agent = FakeAgent({"SZLA-2026-1", "SZLA-2026-2", "SZLA-2026-3", "SZLA-2026-4", "E-SZLA-2026-1"})
    code = run(path, "pull", "--period", "2026-08", agent=agent, nav=nav)
    assert code == 0
    assert nav.calls == [
        (__import__("datetime").date(2026, 8, 1), __import__("datetime").date(2026, 8, 31))
    ]
    assert agent.calls == [
        "SZLA-2026-1",
        "SZLA-2026-2",
        "SZLA-2026-3",
        "SZLA-2026-4",
        "E-SZLA-2026-1",
        "SZLA-2026-5",
    ]
    assert invoice_numbers(path) == [
        "E-SZLA-2026-1",
        "SZLA-2026-1",
        "SZLA-2026-2",
        "SZLA-2026-3",
        "SZLA-2026-4",
        "SZLA-2026-5",
    ]
    rows = sync_rows(path)
    assert ("nav_digest", "2026-08-01", "2026-08-31", 6, 6, 0) in rows
    assert ("agent", "SZLA-2026-1", "SZLA-2026-5", 5, 5, 1) in rows

    agent.calls.clear()
    code = run(path, "pull", "--period", "2026-08", agent=agent, nav=nav)
    assert code == 0
    assert agent.calls == ["SZLA-2026-5"]
    assert sync_rows(path)[-2][:5] == ("nav_digest", "2026-08-01", "2026-08-31", 6, 0)


def test_pull_period_with_nav_data(tmp_path: Path):
    path = tmp_path / "inv.db"
    nav = FakeNav(all_digests())
    agent = FakeAgent({"SZLA-2026-1", "SZLA-2026-2", "SZLA-2026-3", "SZLA-2026-4", "E-SZLA-2026-1"})
    code = run(path, "pull", "--period", "2026-08", "--with-nav-data", agent=agent, nav=nav)
    assert code == 0
    assert nav.data_calls == [
        "SZLA-2026-1",
        "SZLA-2026-2",
        "SZLA-2026-3",
        "SZLA-2026-4",
        "E-SZLA-2026-1",
        "SZLA-2026-5",
    ]
    conn = db.connect(path)
    try:
        assert (
            conn.execute("SELECT COUNT(*) FROM raw_documents WHERE source = 'nav_data'").fetchone()[
                0
            ]
            == 1
        )
        r = conn.execute(
            "SELECT source_flags, net_huf FROM invoice WHERE invoice_number = 'E-SZLA-2026-1'"
        ).fetchone()
        assert (r[0], r[1]) == ("agent,nav_data,nav_digest", 399500.0)
        assert [
            tuple(x)
            for x in conn.execute(
                "SELECT source, fetched, errors FROM sync_log WHERE source = 'nav_data'"
            )
        ] == [("nav_data", 1, 5)]
    finally:
        conn.close()


def test_pull_period_without_digests_exits_1(tmp_path: Path):
    path = tmp_path / "inv.db"
    assert run(path, "pull", "--period", "2026-07", agent=FakeAgent(set()), nav=FakeNav([])) == 1
    assert sync_rows(path)[-1][:4] == ("nav_digest", "2026-07-01", "2026-07-31", 0)


def test_pull_period_nav_failures(tmp_path: Path):
    path = tmp_path / "inv.db"
    nav = FakeNav(fail_with=nav_client.NavNetworkError("queryInvoiceDigest: HTTP 503"))
    assert run(path, "pull", "--period", "2026-08", agent=FakeAgent(set()), nav=nav) == 3
    nav = FakeNav(fail_with=nav_client.NavError("bad login", error_code="INVALID_SECURITY_USER"))
    assert run(path, "pull", "--period", "2026-08", agent=FakeAgent(set()), nav=nav) == 2
    nav = FakeNav(fail_with=nav_client.NavError("boom", error_code="OPERATION_FAILED"))
    assert run(path, "pull", "--period", "2026-08", agent=FakeAgent(set()), nav=nav) == 3


# --- init and status ---------------------------------------------------------


def test_init_creates_schema_and_logs(tmp_path: Path, capsys):
    path = tmp_path / "sub" / "inv.db"
    assert run(path, "init") == 0
    assert path.exists()
    assert "Adatbázis kész" in capsys.readouterr().out
    assert sync_rows(path)[0][0] == "init"


def test_status_smoke_with_fixture_data_and_gap(tmp_path: Path, capsys):
    path = tmp_path / "inv.db"
    conn = db.connect(path)
    db.create_schema(conn)
    load_fixture_raw(conn)
    conn.execute("DELETE FROM raw_documents WHERE doc_key = 'SZLA-2026-4'")
    db.rebuild(conn)
    db.log_sync(
        conn,
        "agent",
        "2026-09-01T00:00:00Z",
        "2026-09-01T00:00:10Z",
        "SZLA-2026-1",
        "SZLA-2026-8",
        fetched=5,
        inserted=5,
        note="teszt",
    )
    conn.close()
    assert run(path, "status") == 0
    out = capsys.readouterr().out
    assert "Utolsó szinkron forrásonként:" in out
    assert "agent" in out and "letöltve=5" in out
    assert "SZLA-2026: 4 db (1..5)" in out
    assert "E-SZLA-2026: 1 db (1..1)" in out
    assert "SZLA-2026-1      stornoed  2 bizonylat" in out
    assert "modified" not in out
    assert "SZLA-2026: 1 hiányzó sorszám: 4" in out


def test_status_on_empty_db(tmp_path: Path, capsys):
    assert run(tmp_path / "inv.db", "status") == 0
    out = capsys.readouterr().out
    assert "(még nem volt szinkron)" in out
    assert "(nincs számla)" in out
    assert out.count("(nincs)") == 2
