"""Tests for report_spec: defaults, cross-checks, formula whitelist, diff, bump, new, CLI."""

from __future__ import annotations

import copy
import re
from datetime import date
from pathlib import Path

import pytest
import report_spec as rs
import yaml
from engine_fixture import EXAMPLES_DIR
from report_engine import MEASURES

EXAMPLE_SLUGS = sorted(p.name for p in EXAMPLES_DIR.iterdir() if (p / "spec.yaml").exists())


@pytest.fixture
def base_raw() -> dict:
    return yaml.safe_load(
        (EXAMPLES_DIR / "havi_arbev_kintlev" / "spec.yaml").read_text(encoding="utf-8")
    )


def build(raw: dict, path: Path | None = None) -> rs.Spec:
    return rs.spec_from_dict(raw, path)


def errors_for(raw: dict, path: Path | None = None) -> list[rs.SpecError]:
    return rs.validate(build(raw, path))


def paths_of(errors: list[rs.SpecError]) -> list[str]:
    return [e.path for e in errors]


# ---------------------------------------------------------------------------
# Defaults and examples
# ---------------------------------------------------------------------------


def test_minimal_spec_gets_documented_defaults():
    spec = build(
        {
            "report": {"id": "rpt_0123abcd", "slug": "proba", "title_hu": "Próba"},
            "measures": [{"id": "rev_net"}],
        }
    )
    assert rs.validate(spec) == []
    p = spec.period
    assert (p.grain, p.basis, p.offset, p.fiscal_year_start_month) == (
        "month",
        "kelt",
        "previous_full_month",
        1,
    )
    assert (p.as_of, p.history_months, p.storno_attribution) == ("period_end", 13, "issue_month")
    s = spec.sources
    assert s.agent.required is True and s.nav_digest.required is False
    assert (
        s.fokonyvi_csv.required is False
        and s.fokonyvi_csv.path == "data/drops/fokonyvi_{period}.csv"
    )
    assert s.afalista.required is False and s.afalista.path == "data/drops/afalista_{period}.xlsx"
    assert s.max_age_days == 3 and s.cash_card_autopaid is True
    f = spec.filters
    assert f.customers_include == ["*"] and f.customers_exclude == []
    assert f.invoice_prefixes == [] and f.currencies == [] and f.vat_rates == []
    assert (
        f.doc_types == ["invoice", "modifier", "storno"]
        and f.exclude_proforma is True
        and f.min_net_huf == 0
    )
    assert spec.dimensions == ["month", "customer", "vat_rate"]
    o = spec.output
    assert o.file_pattern == "{slug}_{period}_v{version}.xlsx" and o.language == "hu"
    assert o.number_profile == "huf_thousands"
    assert o.sheets == [
        "executive",
        "exceptions",
        "invoice",
        "customer",
        "measure",
        "definitions",
        "runlog",
    ]
    assert o.executive.blocks == list(rs.EXECUTIVE_BLOCKS) and o.executive.top_n == 10
    assert o.table_prefix == "tbl_proba"
    assert spec.powerbi.enabled is False and spec.powerbi.folder == "exports/powerbi"
    assert spec.powerbi.files == ["fact_invoice", "fact_measure", "dim_customer", "dim_date"]
    assert (spec.delivery.folder, spec.delivery.overwrite, spec.delivery.keep_n_versions) == (
        "exports",
        "same_version",
        6,
    )
    assert [c.id for c in spec.validation.checks] == list(rs.CHECK_IDS)
    assert {c.id for c in spec.validation.checks if c.blocks_delivery} == set(
        rs.DEFAULT_BLOCKING_CHECKS
    )
    assert spec.validation.min_rows == 1
    assert spec.check("V07").severity == "warn" and spec.check("V05").severity == "fail"
    assert spec.report.version == "0.1.0" and spec.report.status == "draft"


@pytest.mark.parametrize("slug", EXAMPLE_SLUGS)
def test_example_specs_validate(slug):
    spec = rs.load_spec(EXAMPLES_DIR / slug / "spec.yaml")
    assert rs.validate(spec) == []
    assert spec.report.slug == slug


def test_four_examples_present():
    assert EXAMPLE_SLUGS == [
        "afa_analitika_negyedev",
        "havi_arbev_kintlev",
        "kintlev_behajtas_heti",
        "ugyfel_koncentracio_churn",
    ]


def test_validation_check_overrides_merge_with_defaults(base_raw):
    spec = build(base_raw)
    assert len(spec.validation.checks) == 16
    v07 = spec.check("V07")
    assert v07.tolerance == 1 and v07.severity == "warn" and v07.blocks_delivery is False
    assert spec.check("V02").blocks_delivery is False and spec.check("V16").blocks_delivery is True


# ---------------------------------------------------------------------------
# Cross-check error paths (Hungarian messages)
# ---------------------------------------------------------------------------


def _set(raw, dotted, value):
    node = raw
    keys = dotted.split(".")
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    node[keys[-1]] = value
    return raw


ERROR_CASES = [
    ("report.id", lambda r: _set(r, "report.id", "rpt_xyz"), "rpt_ előtag"),
    ("report.slug", lambda r: _set(r, "report.slug", "Havi-Riport"), "kisbetű"),
    ("report.title_hu", lambda r: _set(r, "report.title_hu", ""), "kötelező"),
    ("report.version", lambda r: _set(r, "report.version", "1.0"), "semver"),
    ("report.status", lambda r: _set(r, "report.status", "live"), "megengedett"),
    ("period.grain", lambda r: _set(r, "period.grain", "year"), "megengedett"),
    ("period.offset", lambda r: _set(r, "period.offset", "last_month"), "megengedett"),
    ("period.offset", lambda r: _set(r, "period.grain", "custom"), "custom grain"),
    (
        "period.offset",
        lambda r: _set(r, "period.offset", {"start": "2026-01-01", "end": "2026-01-31"}),
        "csak custom",
    ),
    (
        "period.fiscal_year_start_month",
        lambda r: _set(r, "period.fiscal_year_start_month", 13),
        "1 és 12",
    ),
    (
        "period.storno_attribution",
        lambda r: _set(r, "period.storno_attribution", "never"),
        "megengedett",
    ),
    ("sources.max_age_days", lambda r: _set(r, "sources.max_age_days", -1), "nemnegatív"),
    (
        "filters.doc_types",
        lambda r: _set(r, "filters.doc_types", ["invoice", "receipt"]),
        "megengedett",
    ),
    ("dimensions", lambda r: _set(r, "dimensions", ["month", "warehouse"]), "ismeretlen dimenzió"),
    ("measures", lambda r: _set(r, "measures", []), "legalább egy"),
    ("measures[0].id", lambda r: r["measures"].insert(0, {"id": "profit"}), "ismeretlen mérőszám"),
    (
        "measures[0].id",
        lambda r: r["measures"].insert(0, {"id": "rev_net_prod"}),
        "product dimenziót",
    ),
    (
        "measures[0].id",
        lambda r: (
            _set(r, "sources.agent", {"required": False}),
            r["measures"].insert(0, {"id": "cash_in"}),
        ),
        "Agent-adatot",
    ),
    (
        "measures[0].format",
        lambda r: r["measures"].insert(0, {"id": "rev_net", "format": "usd"}),
        "megengedett",
    ),
    (
        "measures[0].comparisons",
        lambda r: r["measures"].insert(0, {"id": "rev_net", "comparisons": ["qoq"]}),
        "megengedett",
    ),
    ("measures[16]", lambda r: r["measures"].append({"id": "rev_net"}), "ismétlődő"),
    (
        "thresholds.eur_share",
        lambda r: _set(r, "thresholds.eur_share", {"warn": 0.4}),
        "nincs a measures",
    ),
    (
        "thresholds.dso",
        lambda r: _set(r, "thresholds.dso", {"direction": "above"}),
        "legalább warn",
    ),
    (
        "thresholds.dso.direction",
        lambda r: _set(r, "thresholds.dso.direction", "up"),
        "megengedett",
    ),
    (
        "thresholds.dso.unit",
        lambda r: _set(r, "thresholds.dso.unit", "pct_of:profit"),
        "ismeretlen mérőszám",
    ),
    (
        "exceptions[0].rule",
        lambda r: _set(r["exceptions"][0], "rule", "late_payment"),
        "ismeretlen szabály",
    ),
    (
        "exceptions[0].severity",
        lambda r: _set(r["exceptions"][0], "severity", "high"),
        "megengedett",
    ),
    ("exceptions[0].max_rows", lambda r: _set(r["exceptions"][0], "max_rows", 0), "pozitív"),
    (
        "exceptions[1].id",
        lambda r: _set(r["exceptions"][1], "id", r["exceptions"][0]["id"]),
        "ismétlődő",
    ),
    ("exceptions[0].params.days", lambda r: _set(r["exceptions"][0], "params", {}), "napok"),
    ("output.file_pattern", lambda r: _set(r, "output.file_pattern", "riport.csv"), "xlsx"),
    ("output.language", lambda r: _set(r, "output.language", "de"), "megengedett"),
    ("output.number_profile", lambda r: _set(r, "output.number_profile", "eur"), "megengedett"),
    ("output.sheets", lambda r: _set(r, "output.sheets", ["executive", "pivot"]), "ismeretlen lap"),
    ("output.sheets", lambda r: _set(r, "output.sheets", ["invoice", "runlog"]), "executive"),
    (
        "output.executive.blocks",
        lambda r: _set(r, "output.executive.blocks", ["tiles", "chart"]),
        "ismeretlen blokk",
    ),
    (
        "output.executive.tiles",
        lambda r: _set(r, "output.executive.tiles", ["rev_net"] * 7),
        "legfeljebb 6",
    ),
    (
        "output.executive.tiles",
        lambda r: _set(r, "output.executive.tiles", ["profit"]),
        "ismeretlen mérőszám",
    ),
    (
        "output.executive.variance_rows",
        lambda r: _set(r, "output.executive.variance_rows", ["rev_net"] * 10),
        "legfeljebb 9",
    ),
    (
        "output.executive.variance_rows",
        lambda r: _set(r, "output.executive.variance_rows", ["eur_share"]),
        "ismeretlen mérőszám",
    ),
    ("output.executive.top_n", lambda r: _set(r, "output.executive.top_n", 0), "pozitív"),
    ("output.table_prefix", lambda r: _set(r, "output.table_prefix", "Tbl-Havi"), "tbl_ előtag"),
    ("powerbi.files", lambda r: _set(r, "powerbi.files", ["fact_orders"]), "ismeretlen fájl"),
    ("delivery.overwrite", lambda r: _set(r, "delivery.overwrite", "sometimes"), "megengedett"),
    ("delivery.keep_n_versions", lambda r: _set(r, "delivery.keep_n_versions", 0), "pozitív"),
    ("delivery.folder", lambda r: _set(r, "delivery.folder", ""), "kötelező"),
    (
        "validation.checks[3].id",
        lambda r: r["validation"]["checks"].append({"id": "V99"}),
        "V01 és V16",
    ),
    (
        "validation.checks[0].severity",
        lambda r: _set(r["validation"]["checks"][0], "severity", "info"),
        "megengedett",
    ),
    ("validation.min_rows", lambda r: _set(r, "validation.min_rows", -5), "nemnegatív"),
]


@pytest.mark.parametrize(
    "path,mutate,fragment", ERROR_CASES, ids=[f"{c[0]}:{c[2]}" for c in ERROR_CASES]
)
def test_cross_check_error_paths(base_raw, path, mutate, fragment):
    raw = copy.deepcopy(base_raw)
    mutate(raw)
    errors = errors_for(raw)
    hits = [e for e in errors if e.path == path]
    assert hits, f"expected an error at {path}, got {[str(e) for e in errors]}"
    assert any(fragment in e.message_hu for e in hits), [e.message_hu for e in hits]
    assert all(re.search(r"[a-záéíóöőúüű]", e.message_hu) for e in errors)


def test_slug_must_match_directory_when_loaded_from_spec_yaml(base_raw, tmp_path):
    d = tmp_path / "reports" / "masik_nev"
    d.mkdir(parents=True)
    p = d / "spec.yaml"
    p.write_text(yaml.safe_dump(base_raw, allow_unicode=True), encoding="utf-8")
    errors = rs.validate(rs.load_spec(p))
    assert [e.path for e in errors] == ["report.slug"]
    assert "mappa" in errors[0].message_hu


def test_non_mapping_section_is_reported_not_raised(base_raw):
    raw = copy.deepcopy(base_raw)
    raw["period"] = "havi"
    errors = errors_for(raw)
    assert "period" in paths_of(errors)


def test_load_errors_for_missing_and_broken_files(tmp_path):
    with pytest.raises(rs.SpecLoadError) as exc:
        rs.load_spec(tmp_path / "nincs.yaml")
    assert "nem található" in exc.value.message_hu
    bad = tmp_path / "spec.yaml"
    bad.write_text("report: [unclosed", encoding="utf-8")
    with pytest.raises(rs.SpecLoadError) as exc:
        rs.load_spec(bad)
    assert "YAML" in exc.value.message_hu
    bad.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(rs.SpecLoadError):
        rs.load_spec(bad)


# ---------------------------------------------------------------------------
# Measure keys and parameterised measures
# ---------------------------------------------------------------------------


def test_parameterised_measures_use_bracket_keys(base_raw):
    raw = copy.deepcopy(base_raw)
    raw["measures"] += [
        {"id": "top_n_share", "params": {"n": 1}},
        {"id": "top_n_share", "params": {"n": 5}},
    ]
    raw["output"]["executive"]["tiles"] = ["top_n_share[n=1]", "top_n_share[n=5]"]
    raw["thresholds"]["top_n_share[n=1]"] = {
        "warn": 0.3,
        "critical": 0.5,
        "direction": "above",
        "unit": "pct",
    }
    spec = build(raw)
    assert rs.validate(spec) == []
    assert {"top_n_share[n=1]", "top_n_share[n=5]"} <= spec.measure_keys()
    assert "top_n_share" not in spec.measure_keys()
    raw["output"]["executive"]["tiles"] = ["top_n_share"]
    errors = errors_for(raw)
    assert any(e.path == "output.executive.tiles" for e in errors)


def test_measure_key_helper():
    assert rs.measure_key(rs.MeasureSpec(id="rev_net")) == "rev_net"
    assert rs.measure_key(rs.MeasureSpec(id="top_n_share", params={"n": 3})) == "top_n_share[n=3]"


# ---------------------------------------------------------------------------
# Custom formula whitelist
# ---------------------------------------------------------------------------

ALLOWED = set(MEASURES)


@pytest.mark.parametrize(
    "formula",
    [
        "rev_net / prior(rev_net, 12) - 1",
        "(rev_net - cash_in) * 1.27",
        "-rev_net + 2",
        "rev_net / inv_count",
        "prior(ar_balance, 1)",
    ],
)
def test_formula_accepts_whitelisted_grammar(formula):
    rs.parse_formula(formula, ALLOWED)


@pytest.mark.parametrize(
    "formula,fragment",
    [
        ("__import__('os').system('x')", "prior"),
        ("rev_net.real", "nem engedélyezett elem"),
        ("abs(rev_net)", "prior"),
        ("prior(rev_net)", "két argumentumot"),
        ("prior(rev_net, 0)", "pozitív egész"),
        ("prior(rev_net, n=1)", "két argumentumot"),
        ("prior('rev_net', 1)", "katalógusbeli"),
        ("rev_net ** 2", "csak + - * /"),
        ("rev_net % 3", "csak + - * /"),
        ("profit + 1", "ismeretlen mérőszám"),
        ("rev_net if 1 else 2", "nem engedélyezett elem"),
        ("rev_net[0]", "nem engedélyezett elem"),
        ("lambda: 1", "nem engedélyezett elem"),
        ("'a' + 'b'", "számkonstansok"),
        ("rev_net +", "nem értelmezhető"),
        ("", "üres"),
        ("not rev_net", "előjel"),
        ("rev_net > 1", "nem engedélyezett elem"),
    ],
)
def test_formula_rejects_everything_else(formula, fragment):
    with pytest.raises(rs.FormulaError) as exc:
        rs.parse_formula(formula, ALLOWED)
    assert fragment in exc.value.message_hu


def test_custom_measure_validation_paths(base_raw):
    raw = copy.deepcopy(base_raw)
    raw["measures"].append(
        {"id": "custom:novekedes", "formula": "rev_net / prior(rev_net, 12) - 1", "format": "pct"}
    )
    assert errors_for(raw) == []
    raw["measures"][-1]["formula"] = "__import__('os')"
    errors = errors_for(raw)
    assert [e.path for e in errors] == ["measures[16].formula"]
    raw["measures"][-1] = {"id": "custom:novekedes"}
    assert "measures[16].formula" in paths_of(errors_for(raw))
    raw["measures"][-1] = {"id": "custom:Rossz-Nev", "formula": "rev_net"}
    assert "measures[16].id" in paths_of(errors_for(raw))
    raw["measures"][-1] = {"id": "custom:rev_net", "formula": "rev_net"}
    assert any("foglalt" in e.message_hu for e in errors_for(raw))
    raw["measures"][-1] = {"id": "rev_gross", "formula": "rev_net * 1.27"}
    assert any("nem adható meg formula" in e.message_hu for e in errors_for(raw))


def test_eval_formula_semantics():
    values = {"rev_net": 120.0, "inv_count": 0.0, "cash_in": None}
    prior = lambda mid, n: {("rev_net", 12): 100.0}.get((mid, n))  # noqa: E731
    assert rs.eval_formula("rev_net / prior(rev_net, 12) - 1", values, prior) == pytest.approx(0.2)
    assert rs.eval_formula("rev_net / inv_count", values, prior) is None
    assert rs.eval_formula("rev_net + cash_in", values, prior) is None
    assert rs.eval_formula("prior(rev_net, 3)", values, prior) is None
    assert rs.eval_formula("-(rev_net - 20) * 2", values, prior) == -200.0


# ---------------------------------------------------------------------------
# diff, bump, new, CLI
# ---------------------------------------------------------------------------


def test_diff_refusals(base_raw):
    old = build(base_raw)
    new_raw = copy.deepcopy(base_raw)
    new_raw["report"]["id"] = "rpt_ffffffff"
    assert [e.path for e in rs.diff_specs(old, build(new_raw))] == ["report.id"]

    new_raw = copy.deepcopy(base_raw)
    new_raw["output"]["table_prefix"] = "tbl_uj_nev"
    errs = rs.diff_specs(old, build(new_raw))
    assert [e.path for e in errs] == ["output.table_prefix"] and "1.0.0" in errs[0].message_hu
    draft_raw = copy.deepcopy(base_raw)
    draft_raw["report"]["version"] = "0.3.0"
    assert rs.diff_specs(build(draft_raw), build(new_raw)) == []

    new_raw = copy.deepcopy(base_raw)
    new_raw["measures"] = [m for m in new_raw["measures"] if m["id"] != "dso"]
    errs = rs.diff_specs(old, build(new_raw))
    assert (
        errs
        and all(e.path == "measures" for e in errs)
        and any("dso" in e.message_hu for e in errs)
    )

    new_raw = copy.deepcopy(base_raw)
    new_raw["output"]["sheets"] = [s for s in new_raw["output"]["sheets"] if s != "customer"]
    errs = rs.diff_specs(old, build(new_raw))
    assert [e.path for e in errs] == [
        "output.sheets"
    ] and "tbl_havi_arbev_kintlev_customer" in errs[0].message_hu

    new_raw = copy.deepcopy(base_raw)
    new_raw["report"]["title_hu"] = "Más cím"
    new_raw["output"]["sheets"].append("line")
    assert rs.diff_specs(old, build(new_raw)) == []


def test_bump_updates_version_and_changelog(base_raw, tmp_path):
    p = tmp_path / "spec.yaml"
    p.write_text(rs.dump_yaml(base_raw), encoding="utf-8")
    assert rs.bump_spec(p, "minor", "új csempe", today=date(2026, 9, 6)) == "1.1.0"
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert raw["report"]["version"] == "1.1.0"
    assert raw["report"]["changelog"][-1] == {
        "version": "1.1.0",
        "date": "2026-09-06",
        "note": "új csempe",
    }
    assert list(raw) == list(base_raw)  # key order preserved
    assert rs.bump_spec(p, "patch", "javítás") == "1.1.1"
    with pytest.raises(rs.SpecLoadError):
        rs.bump_spec(p, "major", "x")
    text = p.read_text(encoding="utf-8")
    assert "ÁFA" in text or "ő" in text or "é" in text  # unicode kept, not escaped


def test_new_skeleton_validates(tmp_path):
    sk = rs.skeleton("proba_riport", "Próba riport", today=date(2026, 9, 6))
    assert rs.RE_ID.match(sk["report"]["id"])
    assert sk["report"]["status"] == "draft" and sk["report"]["version"] == "0.1.0"
    assert rs.validate(build(sk)) == []
    out = tmp_path / "reports" / "proba_riport" / "spec.yaml"
    assert rs.main(["--new", "proba_riport", "--title-hu", "Próba riport", "--out", str(out)]) == 0
    spec = rs.load_spec(out)
    assert rs.validate(spec) == []
    assert out.read_text(encoding="utf-8").startswith("# Riport")
    assert rs.main(["--new", "proba_riport", "--title-hu", "X", "--out", str(out)]) == 1  # exists
    assert (
        rs.main(["--new", "Rossz Slug", "--title-hu", "X", "--out", str(tmp_path / "x.yaml")]) == 1
    )
    assert rs.main(["--new", "masik", "--out", str(tmp_path / "y.yaml")]) == 1  # missing title


def test_cli_validate_and_catalogue(base_raw, tmp_path, capsys):
    good = EXAMPLES_DIR / "havi_arbev_kintlev" / "spec.yaml"
    assert rs.main(["--validate", str(good)]) == 0
    assert capsys.readouterr().out.strip() == f"OK: {good}"
    raw = copy.deepcopy(base_raw)
    raw["report"]["version"] = "x"
    raw["output"]["executive"]["tiles"] = ["profit"]
    bad = tmp_path / "havi_arbev_kintlev" / "spec.yaml"
    bad.parent.mkdir()
    bad.write_text(rs.dump_yaml(raw), encoding="utf-8")
    assert rs.main(["--validate", str(bad), str(good)]) == 1
    out = capsys.readouterr().out
    assert f"{bad}: report.version: " in out and f"{bad}: output.executive.tiles: " in out
    assert f"OK: {good}" in out
    assert rs.main(["--validate", str(tmp_path / "nincs.yaml")]) == 1
    assert "nem található" in capsys.readouterr().out

    assert rs.main(["--catalogue"]) == 0
    out = capsys.readouterr().out
    assert "rev_net" in out and "Nettó árbevétel" in out
    for mid, m in MEASURES.items():
        assert mid in out
        assert m.source in ("D", "A")
    assert len(MEASURES) == 30


def test_cli_diff_and_bump(base_raw, tmp_path, capsys):
    old = tmp_path / "old.yaml"
    new = tmp_path / "new.yaml"
    old.write_text(rs.dump_yaml(base_raw), encoding="utf-8")
    raw = copy.deepcopy(base_raw)
    raw["report"]["id"] = "rpt_00000000"
    new.write_text(rs.dump_yaml(raw), encoding="utf-8")
    assert rs.main(["--diff", str(old), str(new)]) == 1
    assert "report.id: " in capsys.readouterr().out
    assert rs.main(["--diff", str(old), str(old)]) == 0
    assert "OK" in capsys.readouterr().out
    assert rs.main(["--bump", str(old), "patch"]) == 1  # note required
    assert rs.main(["--bump", str(old), "patch", "--note", "apró"]) == 0
    assert "1.0.1" in capsys.readouterr().out
