# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6", "pandas>=2.2"]
# ///
"""Report spec (`reports/<slug>/spec.yaml`): schema, defaults, validation, CLI.

Public API:
    load_spec(path) -> Spec
    validate(spec) -> list[SpecError]
    measure_key(measure) -> str
    parse_formula(formula, allowed_ids) -> None (raises FormulaError)
    eval_formula(formula, values, prior) -> float | None
    spec_hash(path) -> str

CLI (Hungarian output):
    --validate PATH...
    --catalogue
    --diff OLD NEW
    --bump PATH minor|patch --note TEXT
    --new SLUG --title-hu TEXT [--out PATH]

Every default is documented in docs/SPEC-SCHEMA.md; keep the two in sync.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import re
import secrets
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Allowed values
# ---------------------------------------------------------------------------

GRAINS = ("month", "quarter", "ytd", "week", "custom")
BASES = ("kelt", "teljesites")
OFFSETS = (
    "previous_full_month",
    "current_month_to_date",
    "previous_full_quarter",
    "previous_full_week",
    "current_week_to_date",
)
AS_OF_VALUES = ("period_end", "run_date")
STORNO_ATTRIBUTIONS = ("issue_month", "original_month")
STATUSES = ("draft", "active", "retired")
DOC_TYPES = ("invoice", "modifier", "storno", "proforma")
DIMENSIONS = ("month", "customer", "product", "vat_rate", "currency", "payment_method")
COMPARISONS = ("mom", "yoy", "ytd", "avg3m")
FORMATS = ("huf_k", "huf", "eur", "pct", "days", "count")
DIRECTIONS = ("above", "below")
EXCEPTION_RULES = (
    "overdue_gt_days",
    "overdue_gt_amount",
    "storno_in_period",
    "modifier_in_period",
    "amount_outlier_zscore",
    "missing_customer_taxno",
    "fx_deviation",
    "duplicate_customer_name",
    "unpaid_cash_invoice",
)
SEVERITIES = ("info", "warn", "critical")
LANGUAGES = ("hu", "en")
NUMBER_PROFILES = ("huf_thousands", "huf_full")
SHEETS = (
    "executive",
    "exceptions",
    "invoice",
    "line",
    "payment",
    "customer",
    "measure",
    "definitions",
    "runlog",
)
EXECUTIVE_BLOCKS = (
    "title",
    "tiles",
    "variance",
    "ar_aging",
    "vat_summary",
    "top_customers",
    "exceptions",
    "footnote",
)
POWERBI_FILES = (
    "fact_invoice",
    "fact_invoice_line",
    "fact_payment",
    "fact_measure",
    "dim_customer",
    "dim_date",
)
OVERWRITE_MODES = ("never", "same_version", "always")
CHECK_IDS = tuple(f"V{i:02d}" for i in range(1, 17))
CHECK_SEVERITIES = ("fail", "warn")
DEFAULT_BLOCKING_CHECKS = frozenset({"V01", "V04", "V05", "V11", "V15", "V16"})
DEFAULT_CHECK_TOLERANCE = {
    "V04": 1.0,
    "V05": 1.0,
    "V06": 0.005,
    "V07": 1.0,
    "V12": 2.0,
    "V15": 1.0,
}
DEFAULT_CHECK_SEVERITY = {
    "V02": "fail",
    "V06": "warn",
    "V07": "warn",
    "V08": "warn",
    "V10": "warn",
    "V12": "warn",
    "V13": "warn",
}
MAX_TILES = 6
MAX_VARIANCE_ROWS = 9
DEFAULT_EXCEPTION_MAX_ROWS = 50

RE_ID = re.compile(r"^rpt_[0-9a-f]{8}$")
RE_SLUG = re.compile(r"^[a-z0-9_]+$")
RE_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
RE_TABLE_PREFIX = re.compile(r"^tbl_[a-z0-9_]+$")
RE_MONTH = re.compile(r"^\d{4}-\d{2}$")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SpecError:
    path: str
    message_hu: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message_hu}"


class SpecLoadError(Exception):
    """Raised when the YAML file cannot be read or is not a mapping."""

    def __init__(self, message_hu: str):
        super().__init__(message_hu)
        self.message_hu = message_hu


class FormulaError(Exception):
    def __init__(self, message_hu: str):
        super().__init__(message_hu)
        self.message_hu = message_hu


@dataclass
class ReportSection:
    id: str = ""
    slug: str = ""
    title_hu: str = ""
    title_en: str = ""
    owner: str = ""
    version: str = "0.1.0"
    status: str = "draft"
    changelog: list[dict] = field(default_factory=list)


@dataclass
class PeriodSection:
    grain: str = "month"
    basis: str = "kelt"
    offset: Any = "previous_full_month"
    fiscal_year_start_month: int = 1
    as_of: str = "period_end"
    history_months: int = 13
    storno_attribution: str = "issue_month"


@dataclass
class SourceSpec:
    required: bool = False
    path: str | None = None


@dataclass
class SourcesSection:
    agent: SourceSpec = field(default_factory=lambda: SourceSpec(required=True))
    nav_digest: SourceSpec = field(default_factory=SourceSpec)
    fokonyvi_csv: SourceSpec = field(
        default_factory=lambda: SourceSpec(path="data/drops/fokonyvi_{period}.csv")
    )
    afalista: SourceSpec = field(
        default_factory=lambda: SourceSpec(path="data/drops/afalista_{period}.xlsx")
    )
    max_age_days: int = 3
    cash_card_autopaid: bool = True


@dataclass
class FiltersSection:
    customers_include: list[str] = field(default_factory=lambda: ["*"])
    customers_exclude: list[str] = field(default_factory=list)
    invoice_prefixes: list[str] = field(default_factory=list)
    currencies: list[str] = field(default_factory=list)
    vat_rates: list[str] = field(default_factory=list)
    doc_types: list[str] = field(default_factory=lambda: ["invoice", "modifier", "storno"])
    exclude_proforma: bool = True
    min_net_huf: float = 0


@dataclass
class MeasureSpec:
    id: str
    params: dict = field(default_factory=dict)
    comparisons: list[str] | None = None
    format: str | None = None
    formula: str | None = None

    @property
    def key(self) -> str:
        return measure_key(self)

    @property
    def is_custom(self) -> bool:
        return self.id.startswith("custom:")


@dataclass
class ThresholdSpec:
    measure: str
    warn: float | None = None
    critical: float | None = None
    direction: str = "above"
    unit: str = "abs"


@dataclass
class ExceptionSpec:
    id: str
    rule: str
    params: dict = field(default_factory=dict)
    severity: str = "warn"
    max_rows: int = DEFAULT_EXCEPTION_MAX_ROWS


@dataclass
class ExecutiveSection:
    blocks: list[str] = field(default_factory=lambda: list(EXECUTIVE_BLOCKS))
    tiles: list[str] = field(default_factory=list)
    variance_rows: list[str] = field(default_factory=list)
    top_n: int = 10


@dataclass
class OutputSection:
    file_pattern: str = "{slug}_{period}_v{version}.xlsx"
    language: str = "hu"
    number_profile: str = "huf_thousands"
    sheets: list[str] = field(
        default_factory=lambda: [
            "executive",
            "exceptions",
            "invoice",
            "customer",
            "measure",
            "definitions",
            "runlog",
        ]
    )
    executive: ExecutiveSection = field(default_factory=ExecutiveSection)
    table_prefix: str = ""


@dataclass
class PowerBISection:
    enabled: bool = False
    folder: str = "exports/powerbi"
    files: list[str] = field(
        default_factory=lambda: ["fact_invoice", "fact_measure", "dim_customer", "dim_date"]
    )


@dataclass
class DeliverySection:
    folder: str = "exports"
    overwrite: str = "same_version"
    keep_n_versions: int = 6


@dataclass
class CheckSpec:
    id: str
    tolerance: float = 0.0
    severity: str = "fail"
    blocks_delivery: bool = False


@dataclass
class ValidationSection:
    checks: list[CheckSpec] = field(default_factory=list)
    min_rows: int = 1


@dataclass
class Spec:
    report: ReportSection = field(default_factory=ReportSection)
    period: PeriodSection = field(default_factory=PeriodSection)
    sources: SourcesSection = field(default_factory=SourcesSection)
    filters: FiltersSection = field(default_factory=FiltersSection)
    dimensions: list[str] = field(default_factory=lambda: ["month", "customer", "vat_rate"])
    measures: list[MeasureSpec] = field(default_factory=list)
    thresholds: dict[str, ThresholdSpec] = field(default_factory=dict)
    exceptions: list[ExceptionSpec] = field(default_factory=list)
    output: OutputSection = field(default_factory=OutputSection)
    powerbi: PowerBISection = field(default_factory=PowerBISection)
    delivery: DeliverySection = field(default_factory=DeliverySection)
    validation: ValidationSection = field(default_factory=ValidationSection)
    path: Path | None = None
    raw: dict = field(default_factory=dict)
    load_errors: list[SpecError] = field(default_factory=list)

    # -- helpers -----------------------------------------------------------

    @property
    def slug(self) -> str:
        return self.report.slug

    @property
    def project_root(self) -> Path:
        """`Riportok` root: parent of the nearest `reports` folder above the spec."""
        if self.path is None:
            return Path.cwd()
        for parent in self.path.resolve().parents:
            if parent.name == "reports":
                return parent.parent
        return self.path.resolve().parent

    @property
    def spec_dir(self) -> Path:
        return self.path.resolve().parent if self.path else Path.cwd()

    def resolve_path(self, value: str) -> Path:
        p = Path(value).expanduser()
        return p if p.is_absolute() else self.project_root / p

    def measure_keys(self) -> set[str]:
        """Bracket keys of all measures plus bare ids that occur once."""
        keys = {m.key for m in self.measures}
        ids = [m.id for m in self.measures]
        keys.update(i for i in ids if ids.count(i) == 1)
        return keys

    def find_measure(self, ref: str) -> MeasureSpec | None:
        for m in self.measures:
            if m.key == ref:
                return m
        hits = [m for m in self.measures if m.id == ref]
        return hits[0] if len(hits) == 1 else None

    def check(self, check_id: str) -> CheckSpec:
        for c in self.validation.checks:
            if c.id == check_id:
                return c
        return default_check(check_id)


# ---------------------------------------------------------------------------
# Defaults and loading
# ---------------------------------------------------------------------------


def default_check(check_id: str) -> CheckSpec:
    return CheckSpec(
        id=check_id,
        tolerance=DEFAULT_CHECK_TOLERANCE.get(check_id, 0.0),
        severity=DEFAULT_CHECK_SEVERITY.get(check_id, "fail"),
        blocks_delivery=check_id in DEFAULT_BLOCKING_CHECKS,
    )


def default_checks() -> list[CheckSpec]:
    return [default_check(cid) for cid in CHECK_IDS]


def measure_key(m: MeasureSpec) -> str:
    if not m.params:
        return m.id
    inner = ",".join(f"{k}={m.params[k]}" for k in sorted(m.params))
    return f"{m.id}[{inner}]"


def spec_hash(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _section(raw: dict, name: str, errors: list[SpecError]) -> dict:
    value = raw.get(name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        errors.append(
            SpecError(name, "a szakasznak kulcs-érték párokból álló blokknak kell lennie")
        )
        return {}
    return value


def _source(raw: Any, default: SourceSpec, path: str, errors: list[SpecError]) -> SourceSpec:
    if raw is None:
        return copy.deepcopy(default)
    if not isinstance(raw, dict):
        errors.append(SpecError(path, "a forrás megadása {required, path} formában történik"))
        return copy.deepcopy(default)
    return SourceSpec(
        required=raw.get("required", default.required),
        path=raw.get("path", default.path),
    )


def _build_spec(raw: dict, path: Path | None) -> Spec:
    errors: list[SpecError] = []
    spec = Spec(path=path, raw=raw)

    r = _section(raw, "report", errors)
    spec.report = ReportSection(
        id=str(r.get("id", "") or ""),
        slug=str(r.get("slug", "") or ""),
        title_hu=str(r.get("title_hu", "") or ""),
        title_en=str(r.get("title_en", "") or ""),
        owner=str(r.get("owner", "") or ""),
        version=str(r.get("version", "0.1.0")),
        status=str(r.get("status", "draft")),
        changelog=_as_list(r.get("changelog")),
    )

    p = _section(raw, "period", errors)
    spec.period = PeriodSection(
        grain=p.get("grain", "month"),
        basis=p.get("basis", "kelt"),
        offset=p.get("offset", "previous_full_month"),
        fiscal_year_start_month=p.get("fiscal_year_start_month", 1),
        as_of=p.get("as_of", "period_end"),
        history_months=p.get("history_months", 13),
        storno_attribution=p.get("storno_attribution", "issue_month"),
    )

    s = _section(raw, "sources", errors)
    defaults = SourcesSection()
    spec.sources = SourcesSection(
        agent=_source(s.get("agent"), defaults.agent, "sources.agent", errors),
        nav_digest=_source(s.get("nav_digest"), defaults.nav_digest, "sources.nav_digest", errors),
        fokonyvi_csv=_source(
            s.get("fokonyvi_csv"), defaults.fokonyvi_csv, "sources.fokonyvi_csv", errors
        ),
        afalista=_source(s.get("afalista"), defaults.afalista, "sources.afalista", errors),
        max_age_days=s.get("max_age_days", 3),
        cash_card_autopaid=s.get("cash_card_autopaid", True),
    )

    f = _section(raw, "filters", errors)
    customers = f.get("customers") or {}
    if not isinstance(customers, dict):
        errors.append(SpecError("filters.customers", "{include, exclude} listákat vár"))
        customers = {}
    spec.filters = FiltersSection(
        customers_include=_as_list(customers.get("include", ["*"])) or ["*"],
        customers_exclude=_as_list(customers.get("exclude", [])),
        invoice_prefixes=_as_list(f.get("invoice_prefixes")),
        currencies=_as_list(f.get("currencies")),
        vat_rates=[str(v) for v in _as_list(f.get("vat_rates"))],
        doc_types=_as_list(f.get("doc_types", ["invoice", "modifier", "storno"])),
        exclude_proforma=f.get("exclude_proforma", True),
        min_net_huf=f.get("min_net_huf", 0),
    )

    spec.dimensions = _as_list(raw.get("dimensions", ["month", "customer", "vat_rate"]))

    measures = raw.get("measures")
    if measures is not None and not isinstance(measures, list):
        errors.append(SpecError("measures", "a mérőszámokat listaként kell megadni"))
        measures = []
    spec.measures = []
    for i, m in enumerate(measures or []):
        if isinstance(m, str):
            m = {"id": m}
        if not isinstance(m, dict) or "id" not in m:
            errors.append(SpecError(f"measures[{i}]", "hiányzik az id mező"))
            continue
        spec.measures.append(
            MeasureSpec(
                id=str(m["id"]),
                params=dict(m.get("params") or {}),
                comparisons=(
                    _as_list(m["comparisons"]) if m.get("comparisons") is not None else None
                ),
                format=m.get("format"),
                formula=m.get("formula"),
            )
        )

    t = _section(raw, "thresholds", errors)
    spec.thresholds = {}
    for key, cfg in t.items():
        if not isinstance(cfg, dict):
            errors.append(
                SpecError(f"thresholds.{key}", "{warn, critical, direction, unit} blokkot vár")
            )
            continue
        spec.thresholds[str(key)] = ThresholdSpec(
            measure=str(key),
            warn=cfg.get("warn"),
            critical=cfg.get("critical"),
            direction=cfg.get("direction", "above"),
            unit=str(cfg.get("unit", "abs")),
        )

    excs = raw.get("exceptions")
    if excs is not None and not isinstance(excs, list):
        errors.append(SpecError("exceptions", "a kivételszabályokat listaként kell megadni"))
        excs = []
    spec.exceptions = []
    for i, e in enumerate(excs or []):
        if not isinstance(e, dict) or "rule" not in e:
            errors.append(SpecError(f"exceptions[{i}]", "hiányzik a rule mező"))
            continue
        spec.exceptions.append(
            ExceptionSpec(
                id=str(e.get("id") or f"exc_{e['rule']}"),
                rule=str(e["rule"]),
                params=dict(e.get("params") or {}),
                severity=str(e.get("severity", "warn")),
                max_rows=e.get("max_rows", DEFAULT_EXCEPTION_MAX_ROWS),
            )
        )

    o = _section(raw, "output", errors)
    ex = o.get("executive") or {}
    if not isinstance(ex, dict):
        errors.append(
            SpecError("output.executive", "{blocks, tiles, variance_rows, top_n} blokkot vár")
        )
        ex = {}
    out_defaults = OutputSection()
    spec.output = OutputSection(
        file_pattern=str(o.get("file_pattern", out_defaults.file_pattern)),
        language=str(o.get("language", "hu")),
        number_profile=str(o.get("number_profile", "huf_thousands")),
        sheets=_as_list(o.get("sheets", out_defaults.sheets)),
        executive=ExecutiveSection(
            blocks=_as_list(ex.get("blocks", list(EXECUTIVE_BLOCKS))),
            tiles=[str(x) for x in _as_list(ex.get("tiles"))],
            variance_rows=[str(x) for x in _as_list(ex.get("variance_rows"))],
            top_n=ex.get("top_n", 10),
        ),
        table_prefix=str(o.get("table_prefix") or f"tbl_{spec.report.slug}"),
    )

    pb = _section(raw, "powerbi", errors)
    pb_defaults = PowerBISection()
    spec.powerbi = PowerBISection(
        enabled=pb.get("enabled", False),
        folder=str(pb.get("folder", pb_defaults.folder)),
        files=_as_list(pb.get("files", pb_defaults.files)),
    )

    d = _section(raw, "delivery", errors)
    spec.delivery = DeliverySection(
        folder=str(d.get("folder", "exports")),
        overwrite=str(d.get("overwrite", "same_version")),
        keep_n_versions=d.get("keep_n_versions", 6),
    )

    v = _section(raw, "validation", errors)
    checks_raw = v.get("checks")
    if checks_raw is not None and not isinstance(checks_raw, list):
        errors.append(SpecError("validation.checks", "az ellenőrzéseket listaként kell megadni"))
        checks_raw = None
    checks = default_checks()
    for i, c in enumerate(checks_raw or []):
        if not isinstance(c, dict) or "id" not in c:
            errors.append(SpecError(f"validation.checks[{i}]", "hiányzik az id mező"))
            continue
        cid = str(c["id"])
        base = default_check(cid)
        override = CheckSpec(
            id=cid,
            tolerance=c.get("tolerance", base.tolerance),
            severity=str(c.get("severity", base.severity)),
            blocks_delivery=c.get("blocks_delivery", base.blocks_delivery),
        )
        replaced = False
        for j, existing in enumerate(checks):
            if existing.id == cid:
                checks[j] = override
                replaced = True
        if not replaced:
            checks.append(override)
    min_rows = v.get("min_rows", 1)
    if isinstance(min_rows, dict):
        min_rows = min_rows.get("invoice", 1)
    spec.validation = ValidationSection(checks=checks, min_rows=min_rows)

    spec.load_errors = errors
    return spec


def load_spec(path: Path | str) -> Spec:
    path = Path(path)
    if not path.exists():
        raise SpecLoadError(f"a spec fájl nem található: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SpecLoadError(f"a spec.yaml nem értelmezhető YAML: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SpecLoadError("a spec.yaml gyökere kulcs-érték párokból álló blokk kell legyen")
    return _build_spec(raw, path)


def spec_from_dict(raw: dict, path: Path | None = None) -> Spec:
    return _build_spec(copy.deepcopy(raw), path)


# ---------------------------------------------------------------------------
# Custom formula grammar
# ---------------------------------------------------------------------------

_BINOPS = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}


def parse_formula(formula: str, allowed_ids: set[str]) -> None:
    """Raise FormulaError unless `formula` uses only the whitelisted grammar."""
    if not isinstance(formula, str) or not formula.strip():
        raise FormulaError("a formula üres")
    try:
        tree = ast.parse(formula.strip(), mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"a formula nem értelmezhető: {exc.msg}") from exc

    def walk(node: ast.AST) -> None:
        if isinstance(node, ast.Expression):
            walk(node.body)
        elif isinstance(node, ast.BinOp):
            if type(node.op) not in _BINOPS:
                raise FormulaError("csak + - * / műveletek engedélyezettek")
            walk(node.left)
            walk(node.right)
        elif isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, (ast.USub, ast.UAdd)):
                raise FormulaError("csak előjel (+/-) engedélyezett egyoperandusú műveletként")
            walk(node.operand)
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise FormulaError("csak számkonstansok engedélyezettek")
        elif isinstance(node, ast.Name):
            if node.id not in allowed_ids:
                raise FormulaError(f"ismeretlen mérőszám a formulában: {node.id}")
        elif isinstance(node, ast.Call):
            if not (isinstance(node.func, ast.Name) and node.func.id == "prior"):
                raise FormulaError("csak a prior(id, n) függvény hívható")
            if node.keywords or len(node.args) != 2:
                raise FormulaError("prior(id, n) pontosan két argumentumot vár")
            ref, n = node.args
            if not isinstance(ref, ast.Name) or ref.id not in allowed_ids:
                raise FormulaError("prior() első argumentuma katalógusbeli mérőszám kell legyen")
            if (
                not isinstance(n, ast.Constant)
                or isinstance(n.value, bool)
                or not isinstance(n.value, int)
                or n.value < 1
            ):
                raise FormulaError("prior() második argumentuma pozitív egész szám kell legyen")
        else:
            raise FormulaError(f"nem engedélyezett elem a formulában: {type(node).__name__}")

    walk(tree)


def eval_formula(formula: str, values: dict[str, float | None], prior) -> float | None:
    """Evaluate a parsed formula. Any None operand or division by zero yields None."""
    tree = ast.parse(formula.strip(), mode="eval")

    def ev(node: ast.AST) -> float | None:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            v = values.get(node.id)
            return None if v is None else float(v)
        if isinstance(node, ast.UnaryOp):
            v = ev(node.operand)
            if v is None:
                return None
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.Call):
            v = prior(node.args[0].id, int(node.args[1].value))
            return None if v is None else float(v)
        if isinstance(node, ast.BinOp):
            left, right = ev(node.left), ev(node.right)
            if left is None or right is None:
                return None
            op = type(node.op)
            if op is ast.Add:
                return left + right
            if op is ast.Sub:
                return left - right
            if op is ast.Mult:
                return left * right
            return None if right == 0 else left / right
        raise FormulaError("nem engedélyezett elem a formulában")

    return ev(tree)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _catalogue() -> dict:
    from report_engine import MEASURES  # lazy: report_engine imports this module

    return MEASURES


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_iso_date(v: Any) -> bool:
    if isinstance(v, date):
        return True
    try:
        date.fromisoformat(str(v))
        return True
    except ValueError:
        return False


def validate(spec: Spec) -> list[SpecError]:
    errors: list[SpecError] = list(spec.load_errors)
    err = errors.append
    catalogue = _catalogue()

    # report
    r = spec.report
    if not RE_ID.match(r.id):
        err(SpecError("report.id", "rpt_ előtag és 8 hexa karakter kell (pl. rpt_3f9a1c2e)"))
    if not RE_SLUG.match(r.slug):
        err(SpecError("report.slug", "csak kisbetű, számjegy és aláhúzás engedélyezett"))
    elif spec.path is not None and spec.path.name == "spec.yaml":
        dir_name = spec.path.resolve().parent.name
        if dir_name != r.slug:
            err(
                SpecError(
                    "report.slug", f"a slug ({r.slug}) nem egyezik a mappa nevével ({dir_name})"
                )
            )
    if not r.title_hu.strip():
        err(SpecError("report.title_hu", "a magyar cím kötelező"))
    if not RE_SEMVER.match(r.version):
        err(SpecError("report.version", "semver formátum kell (pl. 1.0.0)"))
    if r.status not in STATUSES:
        err(SpecError("report.status", f"megengedett értékek: {', '.join(STATUSES)}"))
    for i, entry in enumerate(r.changelog):
        if not isinstance(entry, dict) or not {"version", "date", "note"} <= set(entry):
            err(SpecError(f"report.changelog[{i}]", "{version, date, note} mezők kellenek"))

    # period
    p = spec.period
    if p.grain not in GRAINS:
        err(SpecError("period.grain", f"megengedett értékek: {', '.join(GRAINS)}"))
    if p.basis not in BASES:
        err(SpecError("period.basis", f"megengedett értékek: {', '.join(BASES)}"))
    if isinstance(p.offset, dict):
        if not (_is_iso_date(p.offset.get("start")) and _is_iso_date(p.offset.get("end"))):
            err(SpecError("period.offset", "egyedi időszakhoz {start, end} ISO dátumok kellenek"))
        elif p.grain != "custom":
            err(SpecError("period.offset", "{start, end} csak custom grain mellett adható meg"))
    elif p.offset not in OFFSETS:
        err(
            SpecError(
                "period.offset", f"megengedett értékek: {', '.join(OFFSETS)} vagy {{start, end}}"
            )
        )
    elif p.grain == "custom":
        err(SpecError("period.offset", "custom grain mellett {start, end} kötelező"))
    if not (_is_int(p.fiscal_year_start_month) and 1 <= p.fiscal_year_start_month <= 12):
        err(SpecError("period.fiscal_year_start_month", "1 és 12 közötti egész szám kell"))
    if p.as_of not in AS_OF_VALUES:
        err(SpecError("period.as_of", f"megengedett értékek: {', '.join(AS_OF_VALUES)}"))
    if not (_is_int(p.history_months) and 1 <= p.history_months <= 60):
        err(SpecError("period.history_months", "1 és 60 közötti egész szám kell"))
    if p.storno_attribution not in STORNO_ATTRIBUTIONS:
        err(
            SpecError(
                "period.storno_attribution",
                f"megengedett értékek: {', '.join(STORNO_ATTRIBUTIONS)}",
            )
        )

    # sources
    s = spec.sources
    for name in ("agent", "nav_digest", "fokonyvi_csv", "afalista"):
        src: SourceSpec = getattr(s, name)
        if not isinstance(src.required, bool):
            err(SpecError(f"sources.{name}.required", "igaz/hamis érték kell"))
    if not (_is_int(s.max_age_days) and s.max_age_days >= 0):
        err(SpecError("sources.max_age_days", "nemnegatív egész szám kell"))
    if not isinstance(s.cash_card_autopaid, bool):
        err(SpecError("sources.cash_card_autopaid", "igaz/hamis érték kell"))

    # filters
    f = spec.filters
    for name in ("customers_include", "customers_exclude", "invoice_prefixes", "currencies"):
        if not all(isinstance(x, str) for x in getattr(f, name)):
            err(SpecError(f"filters.{name}", "szöveges elemek listáját várja"))
    bad = [d for d in f.doc_types if d not in DOC_TYPES]
    if bad or not f.doc_types:
        err(SpecError("filters.doc_types", f"megengedett értékek: {', '.join(DOC_TYPES)}"))
    if not isinstance(f.exclude_proforma, bool):
        err(SpecError("filters.exclude_proforma", "igaz/hamis érték kell"))
    if not (_is_num(f.min_net_huf) and f.min_net_huf >= 0):
        err(SpecError("filters.min_net_huf", "nemnegatív szám kell"))

    # dimensions
    bad = [d for d in spec.dimensions if d not in DIMENSIONS]
    if bad:
        err(SpecError("dimensions", f"ismeretlen dimenzió: {', '.join(map(str, bad))}"))

    # measures
    if not spec.measures:
        err(SpecError("measures", "legalább egy mérőszám kell"))
    seen_keys: set[str] = set()
    catalogue_ids = set(catalogue)
    custom_ids: set[str] = set()
    for i, m in enumerate(spec.measures):
        path = f"measures[{i}]"
        if m.is_custom:
            slug = m.id.split(":", 1)[1]
            if not RE_SLUG.match(slug):
                err(
                    SpecError(
                        f"{path}.id", "custom:<slug> alakban, csak kisbetű, számjegy, aláhúzás"
                    )
                )
            if slug in catalogue_ids:
                err(SpecError(f"{path}.id", f"a(z) {slug} név foglalt a katalógusban"))
            custom_ids.add(slug)
            if not m.formula:
                err(SpecError(f"{path}.formula", "egyedi mérőszámhoz formula kötelező"))
            else:
                try:
                    parse_formula(m.formula, catalogue_ids)
                except FormulaError as exc:
                    err(SpecError(f"{path}.formula", exc.message_hu))
        elif m.id not in catalogue_ids:
            err(SpecError(f"{path}.id", f"ismeretlen mérőszám: {m.id}"))
        else:
            if catalogue[m.id].source == "A" and not s.agent.required:
                err(
                    SpecError(
                        f"{path}.id",
                        f"a(z) {m.id} Agent-adatot igényel, de sources.agent.required hamis",
                    )
                )
            if m.formula:
                err(
                    SpecError(f"{path}.formula", "katalógusbeli mérőszámnál nem adható meg formula")
                )
            dim = catalogue[m.id].dim
            if dim and dim != "bucket" and dim not in spec.dimensions:
                err(
                    SpecError(
                        f"{path}.id",
                        f"a(z) {m.id} a(z) {dim} dimenziót igényli, vedd fel a dimensions listába",
                    )
                )
        if m.comparisons is not None:
            bad = [c for c in m.comparisons if c not in COMPARISONS]
            if bad:
                err(
                    SpecError(
                        f"{path}.comparisons", f"megengedett értékek: {', '.join(COMPARISONS)}"
                    )
                )
        if m.format is not None and m.format not in FORMATS:
            err(SpecError(f"{path}.format", f"megengedett értékek: {', '.join(FORMATS)}"))
        if not isinstance(m.params, dict):
            err(SpecError(f"{path}.params", "kulcs-érték párokat vár"))
        if m.key in seen_keys:
            err(SpecError(f"{path}", f"ismétlődő mérőszám: {m.key}"))
        seen_keys.add(m.key)
    keys = spec.measure_keys()

    # thresholds
    for key, t in spec.thresholds.items():
        path = f"thresholds.{key}"
        if key not in keys:
            err(
                SpecError(
                    path, "a küszöb olyan mérőszámra hivatkozik, ami nincs a measures listában"
                )
            )
        if t.warn is None and t.critical is None:
            err(SpecError(path, "legalább warn vagy critical érték kell"))
        for lvl in ("warn", "critical"):
            v = getattr(t, lvl)
            if v is not None and not _is_num(v):
                err(SpecError(f"{path}.{lvl}", "szám kell"))
        if t.direction not in DIRECTIONS:
            err(SpecError(f"{path}.direction", f"megengedett értékek: {', '.join(DIRECTIONS)}"))
        if t.unit.startswith("pct_of:"):
            ref = t.unit.split(":", 1)[1]
            if ref not in keys:
                err(SpecError(f"{path}.unit", f"pct_of hivatkozás ismeretlen mérőszámra: {ref}"))
        elif t.unit not in ("abs", "pct"):
            err(SpecError(f"{path}.unit", "megengedett értékek: abs, pct, pct_of:<id>"))

    # exceptions
    seen_exc: set[str] = set()
    for i, e in enumerate(spec.exceptions):
        path = f"exceptions[{i}]"
        if e.rule not in EXCEPTION_RULES:
            err(SpecError(f"{path}.rule", f"ismeretlen szabály: {e.rule}"))
        if e.severity not in SEVERITIES:
            err(SpecError(f"{path}.severity", f"megengedett értékek: {', '.join(SEVERITIES)}"))
        if not (_is_int(e.max_rows) and e.max_rows >= 1):
            err(SpecError(f"{path}.max_rows", "pozitív egész szám kell"))
        if not RE_SLUG.match(e.id):
            err(SpecError(f"{path}.id", "csak kisbetű, számjegy és aláhúzás engedélyezett"))
        if e.id in seen_exc:
            err(SpecError(f"{path}.id", f"ismétlődő kivétel-azonosító: {e.id}"))
        seen_exc.add(e.id)
        if e.rule == "overdue_gt_days" and not _is_num(e.params.get("days")):
            err(SpecError(f"{path}.params.days", "napok száma kell"))
        if e.rule == "overdue_gt_amount" and not _is_num(e.params.get("amount_huf")):
            err(SpecError(f"{path}.params.amount_huf", "HUF összeg kell"))

    # output
    o = spec.output
    if not o.file_pattern.endswith(".xlsx") or "{" not in o.file_pattern:
        err(
            SpecError(
                "output.file_pattern",
                "xlsx végződés és legalább egy {slug}/{period}/{version}/{run_date} token kell",
            )
        )
    if o.language not in LANGUAGES:
        err(SpecError("output.language", f"megengedett értékek: {', '.join(LANGUAGES)}"))
    if o.number_profile not in NUMBER_PROFILES:
        err(
            SpecError("output.number_profile", f"megengedett értékek: {', '.join(NUMBER_PROFILES)}")
        )
    bad = [x for x in o.sheets if x not in SHEETS]
    if bad:
        err(SpecError("output.sheets", f"ismeretlen lap: {', '.join(map(str, bad))}"))
    if len(set(o.sheets)) != len(o.sheets):
        err(SpecError("output.sheets", "ismétlődő lap"))
    if "executive" not in o.sheets:
        err(SpecError("output.sheets", "a vezetői összefoglaló (executive) lap kötelező"))
    ex = o.executive
    bad = [b for b in ex.blocks if b not in EXECUTIVE_BLOCKS]
    if bad:
        err(SpecError("output.executive.blocks", f"ismeretlen blokk: {', '.join(map(str, bad))}"))
    if len(ex.tiles) > MAX_TILES:
        err(SpecError("output.executive.tiles", f"legfeljebb {MAX_TILES} csempe engedélyezett"))
    if len(ex.variance_rows) > MAX_VARIANCE_ROWS:
        err(
            SpecError(
                "output.executive.variance_rows",
                f"legfeljebb {MAX_VARIANCE_ROWS} sor engedélyezett",
            )
        )
    for name, refs in (("tiles", ex.tiles), ("variance_rows", ex.variance_rows)):
        for ref in refs:
            if ref not in keys:
                err(SpecError(f"output.executive.{name}", f"ismeretlen mérőszám-hivatkozás: {ref}"))
    if not (_is_int(ex.top_n) and ex.top_n >= 1):
        err(SpecError("output.executive.top_n", "pozitív egész szám kell"))
    if not RE_TABLE_PREFIX.match(o.table_prefix):
        err(SpecError("output.table_prefix", "tbl_ előtag, csak kisbetű, számjegy, aláhúzás"))

    # powerbi
    pb = spec.powerbi
    if not isinstance(pb.enabled, bool):
        err(SpecError("powerbi.enabled", "igaz/hamis érték kell"))
    bad = [x for x in pb.files if x not in POWERBI_FILES]
    if bad:
        err(SpecError("powerbi.files", f"ismeretlen fájl: {', '.join(map(str, bad))}"))
    if pb.enabled and not pb.folder:
        err(SpecError("powerbi.folder", "Power BI export mappát kell megadni"))

    # delivery
    d = spec.delivery
    if not d.folder:
        err(SpecError("delivery.folder", "kézbesítési mappa kötelező"))
    if d.overwrite not in OVERWRITE_MODES:
        err(SpecError("delivery.overwrite", f"megengedett értékek: {', '.join(OVERWRITE_MODES)}"))
    if not (_is_int(d.keep_n_versions) and d.keep_n_versions >= 1):
        err(SpecError("delivery.keep_n_versions", "pozitív egész szám kell"))

    # validation
    v = spec.validation
    raw_checks = (spec.raw.get("validation") or {}).get("checks") or []
    raw_index = {str(c.get("id")): i for i, c in enumerate(raw_checks) if isinstance(c, dict)}
    for i, c in enumerate(v.checks):
        path = f"validation.checks[{raw_index.get(c.id, i)}]"
        if c.id not in CHECK_IDS:
            err(SpecError(f"{path}.id", "V01 és V16 közötti azonosító kell"))
        if not (_is_num(c.tolerance) and c.tolerance >= 0):
            err(SpecError(f"{path}.tolerance", "nemnegatív szám kell"))
        if c.severity not in CHECK_SEVERITIES:
            err(
                SpecError(f"{path}.severity", f"megengedett értékek: {', '.join(CHECK_SEVERITIES)}")
            )
        if not isinstance(c.blocks_delivery, bool):
            err(SpecError(f"{path}.blocks_delivery", "igaz/hamis érték kell"))
    if not (_is_int(v.min_rows) and v.min_rows >= 0):
        err(SpecError("validation.min_rows", "nemnegatív egész szám kell"))

    return errors


# ---------------------------------------------------------------------------
# Diff (edit guard) and bump
# ---------------------------------------------------------------------------


def _version_tuple(v: str) -> tuple[int, int, int]:
    parts = v.split(".")
    return tuple(int(x) for x in parts[:3])  # type: ignore[return-value]


def diff_specs(old: Spec, new: Spec) -> list[SpecError]:
    """Refusal cases for /report-edit. Empty list means the change is allowed."""
    errors: list[SpecError] = []
    if old.report.id != new.report.id:
        errors.append(SpecError("report.id", "a riport azonosítója nem változtatható"))
    released = (
        _version_tuple(old.report.version) >= (1, 0, 0)
        if RE_SEMVER.match(old.report.version)
        else False
    )
    if released and old.output.table_prefix != new.output.table_prefix:
        errors.append(
            SpecError(
                "output.table_prefix",
                "1.0.0 után a táblák előtagja nem nevezhető át (Power BI hivatkozik rá), új "
                "riportot hozz létre",
            )
        )
    new_keys = new.measure_keys()
    referenced = (
        set(new.output.executive.tiles)
        | set(new.output.executive.variance_rows)
        | set(new.thresholds)
    )
    for ref in sorted(referenced):
        if ref not in new_keys:
            errors.append(
                SpecError(
                    "measures",
                    f"a(z) {ref} mérőszám hiányzik, de csempe, eltéréstábla-sor vagy küszöb "
                    "hivatkozik rá",
                )
            )
    if released:
        table_entities = {"exceptions", "invoice", "line", "payment", "customer", "measure"}
        removed = (set(old.output.sheets) - set(new.output.sheets)) & table_entities
        for ent in sorted(removed):
            errors.append(
                SpecError(
                    "output.sheets",
                    f"a(z) {old.output.table_prefix}_{ent} tábla 1.0.0 után nem távolítható el",
                )
            )
    return errors


def bump_spec(path: Path | str, part: str, note: str, today: date | None = None) -> str:
    """Bump report.version in place, append a changelog entry, return the new version."""
    if part not in ("minor", "patch"):
        raise SpecLoadError("a verzióemelés csak minor vagy patch lehet")
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    report = raw.setdefault("report", {})
    current = str(report.get("version", "0.1.0"))
    if not RE_SEMVER.match(current):
        raise SpecLoadError(f"a jelenlegi verzió nem semver: {current}")
    major, minor, patch = _version_tuple(current)
    if part == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    new_version = f"{major}.{minor}.{patch}"
    report["version"] = new_version
    changelog = report.setdefault("changelog", [])
    if not isinstance(changelog, list):
        changelog = []
        report["changelog"] = changelog
    changelog.append(
        {"version": new_version, "date": (today or date.today()).isoformat(), "note": note}
    )
    path.write_text(dump_yaml(raw), encoding="utf-8")
    return new_version


def dump_yaml(raw: dict) -> str:
    return yaml.safe_dump(raw, sort_keys=False, allow_unicode=True, width=100)


# ---------------------------------------------------------------------------
# Skeleton
# ---------------------------------------------------------------------------

SKELETON_HEADER = """# Riport specifikáció (a /report-new hozta létre).
# A spec.yaml az egyetlen igazságforrás: a build.py ebből dolgozik.
# Ellenőrzés: uv run scripts/report_spec.py --validate reports/<slug>/spec.yaml
"""


def skeleton(slug: str, title_hu: str, today: date | None = None) -> dict:
    today = today or date.today()
    return {
        "report": {
            "id": f"rpt_{secrets.token_hex(4)}",
            "slug": slug,
            "title_hu": title_hu,
            "title_en": "",
            "owner": "",
            "version": "0.1.0",
            "status": "draft",
            "changelog": [{"version": "0.1.0", "date": today.isoformat(), "note": "vázlat"}],
        },
        "period": {
            "grain": "month",
            "basis": "kelt",
            "offset": "previous_full_month",
            "fiscal_year_start_month": 1,
            "as_of": "period_end",
            "history_months": 13,
            "storno_attribution": "issue_month",
        },
        "sources": {
            "agent": {"required": True},
            "nav_digest": {"required": False},
            "fokonyvi_csv": {"required": False, "path": "data/drops/fokonyvi_{period}.csv"},
            "afalista": {"required": False, "path": "data/drops/afalista_{period}.xlsx"},
            "max_age_days": 3,
            "cash_card_autopaid": True,
        },
        "filters": {
            "customers": {"include": ["*"], "exclude": []},
            "invoice_prefixes": [],
            "currencies": [],
            "vat_rates": [],
            "doc_types": ["invoice", "modifier", "storno"],
            "exclude_proforma": True,
            "min_net_huf": 0,
        },
        "dimensions": ["month", "customer", "vat_rate"],
        "measures": [
            {"id": "rev_net", "comparisons": ["mom", "yoy", "ytd"], "format": "huf_k"},
            {"id": "inv_count", "comparisons": ["mom", "yoy"], "format": "count"},
        ],
        "thresholds": {},
        "exceptions": [],
        "output": {
            "file_pattern": "{slug}_{period}_v{version}.xlsx",
            "language": "hu",
            "number_profile": "huf_thousands",
            "sheets": [
                "executive",
                "exceptions",
                "invoice",
                "customer",
                "measure",
                "definitions",
                "runlog",
            ],
            "executive": {
                "blocks": list(EXECUTIVE_BLOCKS),
                "tiles": ["rev_net", "inv_count"],
                "variance_rows": ["rev_net", "inv_count"],
                "top_n": 10,
            },
            "table_prefix": f"tbl_{slug}",
        },
        "powerbi": {
            "enabled": False,
            "folder": "exports/powerbi",
            "files": ["fact_invoice", "fact_measure", "dim_customer", "dim_date"],
        },
        "delivery": {"folder": "exports", "overwrite": "same_version", "keep_n_versions": 6},
        "validation": {
            "checks": [
                {
                    "id": c.id,
                    "tolerance": c.tolerance,
                    "severity": c.severity,
                    "blocks_delivery": c.blocks_delivery,
                }
                for c in default_checks()
            ],
            "min_rows": 1,
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_validate(paths: list[str]) -> int:
    rc = 0
    for p in paths:
        try:
            spec = load_spec(p)
        except SpecLoadError as exc:
            print(f"{p}: {exc.message_hu}")
            rc = 1
            continue
        errors = validate(spec)
        if errors:
            rc = 1
            for e in errors:
                print(f"{p}: {e.path}: {e.message_hu}")
        else:
            print(f"OK: {p}")
    return rc


def _cmd_catalogue() -> int:
    catalogue = _catalogue()
    rows = [(mid, m.label_hu, m.source, m.default_format) for mid, m in catalogue.items()]
    w0 = max(len(r[0]) for r in rows)
    w1 = max(len(r[1]) for r in rows)
    print(f"{'id':<{w0}}  {'megnevezés':<{w1}}  forrás  formátum")
    for mid, label, src, fmt in rows:
        print(f"{mid:<{w0}}  {label:<{w1}}  {src:<6}  {fmt}")
    return 0


def _cmd_diff(old_path: str, new_path: str) -> int:
    try:
        old, new = load_spec(old_path), load_spec(new_path)
    except SpecLoadError as exc:
        print(exc.message_hu)
        return 1
    errors = diff_specs(old, new)
    for e in errors:
        print(f"{e.path}: {e.message_hu}")
    if not errors:
        print("OK: a módosítás engedélyezett")
    return 1 if errors else 0


def _cmd_bump(path: str, part: str, note: str) -> int:
    try:
        new_version = bump_spec(path, part, note)
    except SpecLoadError as exc:
        print(exc.message_hu)
        return 1
    print(f"{path}: verzió {new_version}")
    return 0


def _cmd_new(slug: str, title_hu: str, out: str | None) -> int:
    if not RE_SLUG.match(slug):
        print("a slug csak kisbetűt, számjegyet és aláhúzást tartalmazhat")
        return 1
    target = Path(out) if out else Path("reports") / slug / "spec.yaml"
    if target.exists():
        print(f"már létezik: {target}")
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(SKELETON_HEADER + dump_yaml(skeleton(slug, title_hu)), encoding="utf-8")
    print(f"létrehozva: {target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Riport spec eszközök")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--validate", nargs="+", metavar="PATH")
    g.add_argument("--catalogue", action="store_true")
    g.add_argument("--diff", nargs=2, metavar=("OLD", "NEW"))
    g.add_argument("--bump", nargs=2, metavar=("PATH", "PART"))
    g.add_argument("--new", metavar="SLUG")
    parser.add_argument("--note", default="")
    parser.add_argument("--title-hu", default="")
    parser.add_argument("--out")
    args = parser.parse_args(argv)

    if args.validate:
        return _cmd_validate(args.validate)
    if args.catalogue:
        return _cmd_catalogue()
    if args.diff:
        return _cmd_diff(*args.diff)
    if args.bump:
        if not args.note:
            print("a --note szöveg kötelező a verzióemeléshez")
            return 1
        return _cmd_bump(args.bump[0], args.bump[1], args.note)
    if args.new:
        if not args.title_hu:
            print("a --title-hu cím kötelező")
            return 1
        return _cmd_new(args.new, args.title_hu, args.out)
    return 2


if __name__ == "__main__":
    sys.exit(main())
