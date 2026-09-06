# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "pyyaml>=6"]
# ///
"""Report engine: measure catalogue, period resolution, frames and computation.

Public API:
    MEASURES: dict[str, MeasureDef]          catalogue (documented in docs/MEASURES.md)
    merge_local_measures(catalogue) -> dict  optional measures_local.py extension
    resolve_period(spec, run_date, override) -> Period
    load_frames(conn, spec, period) -> Frames
    compute(frames, spec, period) -> Result
    calendar_frame(start, end, fiscal_start_month) -> DataFrame (Power BI dim_date)

All money values are HUF unless a column name says otherwise. Storno and
modifier rows carry signed amounts, so plain sums give effective values.
"""

from __future__ import annotations

import calendar as _cal
import fnmatch
import importlib
import importlib.util
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd
from report_spec import MeasureSpec, Spec, eval_formula

AGING_BUCKETS = ("not_due", "1_30", "31_60", "61_90", "90_plus")
AGING_LABELS_HU = {
    "not_due": "Nem lejárt",
    "1_30": "1-30 nap",
    "31_60": "31-60 nap",
    "61_90": "61-90 nap",
    "90_plus": "90+ nap",
}
AGING_LABELS_EN = {
    "not_due": "Not due",
    "1_30": "1-30 days",
    "31_60": "31-60 days",
    "61_90": "61-90 days",
    "90_plus": "90+ days",
}
SEVERITY_ORDER = {"critical": 0, "warn": 1, "info": 2}
EXCEPTION_COLUMNS = [
    "rule_id",
    "rule",
    "severity",
    "invoice_number",
    "customer",
    "amount",
    "days",
    "note",
]
MEASURE_COLUMNS = [
    "measure_id",
    "dim_name",
    "dim_value",
    "period_label",
    "value",
    "prior",
    "prior_year",
    "ytd",
    "ytd_prior",
    "mom_pct",
    "yoy_pct",
    "avg3m",
]


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


def month_start(d: date) -> date:
    return d.replace(day=1)


def month_end(d: date) -> date:
    return d.replace(day=_cal.monthrange(d.year, d.month)[1])


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    m += 1
    return date(y, m, min(d.day, _cal.monthrange(y, m)[1]))


def fiscal_period_no(d: date, fy_start: int) -> int:
    return (d.month - fy_start) % 12 + 1


def fiscal_year_of(d: date, fy_start: int) -> int:
    """Fiscal year named after the calendar year in which it starts."""
    return d.year if d.month >= fy_start else d.year - 1


def fiscal_year_start(d: date, fy_start: int) -> date:
    return date(fiscal_year_of(d, fy_start), fy_start, 1)


def fiscal_quarter_of(d: date, fy_start: int) -> int:
    return (fiscal_period_no(d, fy_start) - 1) // 3 + 1


def fiscal_quarter_start(d: date, fy_start: int) -> date:
    q = fiscal_quarter_of(d, fy_start)
    return add_months(fiscal_year_start(d, fy_start), (q - 1) * 3)


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _iso_week_label(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


# ---------------------------------------------------------------------------
# Period
# ---------------------------------------------------------------------------


@dataclass
class Period:
    grain: str
    basis: str
    start: date
    end: date
    label: str
    prior_start: date
    prior_end: date
    prior_label: str
    py_start: date
    py_end: date
    py_label: str
    ytd_start: date
    ytd_prior_start: date
    ytd_prior_end: date
    as_of: date
    run_date: date
    fiscal_year_start_month: int
    history_months: int
    to_date: bool = False

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def history(self) -> list[tuple[date, date]]:
        """Monthly windows, oldest first, ending with the month containing `end`."""
        out = []
        last = month_start(self.end)
        for i in range(self.history_months - 1, -1, -1):
            s = add_months(last, -i)
            out.append((s, month_end(s)))
        return out

    def shift(self, start: date, end: date, n: int) -> tuple[date, date]:
        """Shift a window back by n grain units (n periods for prior())."""
        return _shift_window(self.grain, start, end, n)


def _unit_end(grain: str, start: date, fy: int) -> date:
    if grain == "month":
        return month_end(start)
    if grain == "quarter":
        return month_end(add_months(start, 2))
    if grain == "week":
        return start + timedelta(days=6)
    return start


def _shift_window(grain: str, start: date, end: date, n: int) -> tuple[date, date]:
    if grain == "week":
        return start - timedelta(days=7 * n), end - timedelta(days=7 * n)
    if grain == "month":
        months = n
    elif grain == "quarter":
        months = 3 * n
    else:
        months = 12 * n
    s = add_months(start, -months)
    full = end == month_end(end)
    e = month_end(add_months(end, -months)) if full else add_months(end, -months)
    return s, e


def _label(grain: str, start: date, end: date, fy: int) -> str:
    if grain == "month":
        return start.strftime("%Y-%m")
    if grain == "quarter":
        return f"{fiscal_year_of(start, fy)}-Q{fiscal_quarter_of(start, fy)}"
    if grain == "week":
        return _iso_week_label(start)
    if grain == "ytd":
        return f"{fiscal_year_of(start, fy)}-YTD{end.month:02d}"
    return f"{start.isoformat()}_{end.isoformat()}"


_RE_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
_RE_QUARTER = re.compile(r"^(\d{4})-Q([1-4])$")
_RE_WEEK = re.compile(r"^(\d{4})-W(\d{2})$")
_RE_RANGE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})$")


class PeriodError(ValueError):
    def __init__(self, message_hu: str):
        super().__init__(message_hu)
        self.message_hu = message_hu


def _parse_override(
    token: str, run_date: date, spec_grain: str, fy: int
) -> tuple[str, date, date, bool]:
    """Return (grain, start, end, to_date) for a --period token."""
    token = token.strip()
    if token == "previous_month":
        s = month_start(add_months(run_date, -1))
        return "month", s, month_end(s), False
    if token == "current_month":
        return "month", month_start(run_date), run_date, True
    if token == "previous_quarter":
        s = add_months(fiscal_quarter_start(run_date, fy), -3)
        return "quarter", s, month_end(add_months(s, 2)), False
    if token == "previous_week":
        s = week_start(run_date) - timedelta(days=7)
        return "week", s, s + timedelta(days=6), False
    if token == "ytd":
        s = fiscal_year_start(run_date, fy)
        return "ytd", s, month_end(add_months(run_date, -1)), False
    try:
        if m := _RE_MONTH.match(token):
            s = date(int(m.group(1)), int(m.group(2)), 1)
            if spec_grain == "ytd":
                return "ytd", fiscal_year_start(s, fy), month_end(s), False
            return "month", s, month_end(s), False
        if m := _RE_QUARTER.match(token):
            s = add_months(date(int(m.group(1)), fy, 1), (int(m.group(2)) - 1) * 3)
            return "quarter", s, month_end(add_months(s, 2)), False
        if m := _RE_WEEK.match(token):
            s = date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
            return "week", s, s + timedelta(days=6), False
        if m := _RE_RANGE.match(token):
            s, e = date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2))
            if e < s:
                raise PeriodError("az időszak vége a kezdete előtt van")
            return "custom", s, e, False
    except ValueError as exc:
        raise PeriodError(f"érvénytelen dátum az időszakban: {token} ({exc})") from exc
    raise PeriodError(
        f"ismeretlen időszak: {token} (elfogadott: previous_month, current_month, "
        "previous_quarter, "
        "previous_week, ytd, ÉÉÉÉ-HH, ÉÉÉÉ-Qn, ÉÉÉÉ-Whh, ÉÉÉÉ-HH-NN..ÉÉÉÉ-HH-NN)"
    )


def _window_from_offset(spec: Spec, run_date: date) -> tuple[str, date, date, bool]:
    p = spec.period
    fy = p.fiscal_year_start_month
    grain, offset = p.grain, p.offset
    if grain == "custom":
        if not isinstance(offset, dict):
            raise PeriodError("custom időszakhoz {start, end} kell")
        s = (
            offset["start"]
            if isinstance(offset["start"], date)
            else date.fromisoformat(str(offset["start"]))
        )
        e = (
            offset["end"]
            if isinstance(offset["end"], date)
            else date.fromisoformat(str(offset["end"]))
        )
        return "custom", s, e, False
    if grain == "week":
        if offset == "current_week_to_date":
            return "week", week_start(run_date), run_date, True
        s = week_start(run_date) - timedelta(days=7)
        return "week", s, s + timedelta(days=6), False
    to_date = offset == "current_month_to_date"
    if offset == "previous_full_quarter":
        anchor_end = add_months(fiscal_quarter_start(run_date, fy), -1)
        anchor_end = month_end(anchor_end)
    elif to_date:
        anchor_end = run_date
    else:  # previous_full_month, previous_full_week (treated as previous month for month grains)
        anchor_end = month_end(add_months(run_date, -1))
    if grain == "month":
        return "month", month_start(anchor_end), anchor_end, to_date
    if grain == "quarter":
        return "quarter", fiscal_quarter_start(anchor_end, fy), anchor_end, to_date
    return "ytd", fiscal_year_start(anchor_end, fy), anchor_end, to_date


def resolve_period(spec: Spec, run_date: date | None = None, override: str | None = None) -> Period:
    run_date = run_date or date.today()
    fy = spec.period.fiscal_year_start_month
    if override:
        grain, start, end, to_date = _parse_override(override, run_date, spec.period.grain, fy)
    else:
        grain, start, end, to_date = _window_from_offset(spec, run_date)

    if grain in ("ytd", "custom"):
        prior_start, prior_end = _shift_window(grain, start, end, 1)
    else:
        prior_start, prior_end = _shift_window(grain, start, end, 1)
    py_start, py_end = (
        (start - timedelta(days=364), end - timedelta(days=364))
        if grain == "week"
        else (
            add_months(start, -12),
            month_end(add_months(end, -12)) if end == month_end(end) else add_months(end, -12),
        )
    )
    ytd_start = fiscal_year_start(end, fy)
    ytd_prior_start = add_months(ytd_start, -12)
    ytd_prior_end = (
        month_end(add_months(end, -12)) if end == month_end(end) else add_months(end, -12)
    )
    as_of = run_date if spec.period.as_of == "run_date" else end
    return Period(
        grain=grain,
        basis=spec.period.basis,
        start=start,
        end=end,
        label=_label(grain, start, end, fy),
        prior_start=prior_start,
        prior_end=prior_end,
        prior_label=_label(grain, prior_start, prior_end, fy),
        py_start=py_start,
        py_end=py_end,
        py_label=_label(grain, py_start, py_end, fy),
        ytd_start=ytd_start,
        ytd_prior_start=ytd_prior_start,
        ytd_prior_end=ytd_prior_end,
        as_of=as_of,
        run_date=run_date,
        fiscal_year_start_month=fy,
        history_months=spec.period.history_months,
        to_date=to_date,
    )


# ---------------------------------------------------------------------------
# Frames
# ---------------------------------------------------------------------------


@dataclass
class Frames:
    invoice: pd.DataFrame
    line: pd.DataFrame
    vat: pd.DataFrame
    payment: pd.DataFrame
    customer: pd.DataFrame
    as_of: date
    basis: str
    filters_hu: list[str] = field(default_factory=list)

    def row_counts(self) -> dict[str, int]:
        return {
            "invoice": int(len(self.invoice)),
            "line": int(len(self.line)),
            "payment": int(len(self.payment)),
            "customer": int(len(self.customer)),
        }


def _read(conn: sqlite3.Connection, sql: str) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn)


def _to_dates(df: pd.DataFrame, cols: list[str]) -> None:
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")


def _match_any(value: str, patterns: list[str]) -> bool:
    v = (value or "").lower()
    return any(fnmatch.fnmatchcase(v, p.lower()) for p in patterns)


def load_frames(conn: sqlite3.Connection, spec: Spec, period: Period) -> Frames:
    inv_all = _read(conn, "SELECT * FROM invoice")
    _to_dates(inv_all, ["issue_date", "delivery_date", "due_date"])
    customer = _read(conn, "SELECT * FROM customer")
    _to_dates(customer, ["first_invoice_date", "last_invoice_date"])
    f = spec.filters
    filters_hu: list[str] = []

    inv = inv_all.copy()
    if f.exclude_proforma:
        inv = inv[inv["doc_type"] != "proforma"]
    inv = inv[inv["doc_type"].isin(f.doc_types)]
    filters_hu.append("bizonylattípus: " + ", ".join(f.doc_types))
    if f.invoice_prefixes:
        mask = pd.Series(False, index=inv.index)
        for pre in f.invoice_prefixes:
            mask |= inv["invoice_number"].astype(str).str.startswith(pre)
        inv = inv[mask]
        filters_hu.append("előtag: " + ", ".join(f.invoice_prefixes))
    if f.currencies:
        inv = inv[inv["currency"].isin(f.currencies)]
        filters_hu.append("deviza: " + ", ".join(f.currencies))
    names = dict(zip(customer["customer_key"], customer["name"].fillna(""), strict=False))
    if f.customers_include != ["*"] or f.customers_exclude:

        def keep(key: str) -> bool:
            name = names.get(key, "")
            inc = _match_any(name, f.customers_include) or _match_any(key, f.customers_include)
            exc = _match_any(name, f.customers_exclude) or _match_any(key, f.customers_exclude)
            return inc and not exc

        inv = inv[inv["customer_key"].map(keep).astype(bool)]
        if f.customers_include != ["*"]:
            filters_hu.append("vevő (csak): " + ", ".join(f.customers_include))
        if f.customers_exclude:
            filters_hu.append("vevő (kizárva): " + ", ".join(f.customers_exclude))
    if f.min_net_huf:
        inv = inv[inv["net_huf"].abs() >= float(f.min_net_huf)]
        filters_hu.append(f"minimum nettó: {f.min_net_huf:,.0f} Ft")
    inv = inv.copy()

    # storno attribution to the chain root's month
    if spec.period.storno_attribution == "original_month":
        roots = inv_all.set_index("invoice_number")
        is_storno = inv["doc_type"] == "storno"
        for idx in inv.index[is_storno]:
            root = inv.at[idx, "chain_root"]
            if root in roots.index and root != inv.at[idx, "invoice_number"]:
                for col in ("issue_date", "delivery_date", "period_kelt", "period_telj"):
                    inv.at[idx, col] = roots.at[root, col]
        filters_hu.append("sztornó az eredeti számla hónapjában")
    else:
        filters_hu.append("sztornó a kiállítás hónapjában")

    # cash / card auto-paid
    inv["pay_status_raw"] = inv["pay_status"]
    if spec.sources.cash_card_autopaid:
        mask = inv["pay_status"].isin(["unpaid", "partial"]) & inv["payment_method"].isin(
            ["cash", "card"]
        )
        inv.loc[mask, "pay_status"] = "paid"
        inv.loc[mask, "paid_huf"] = inv.loc[mask, "gross_huf"]
        filters_hu.append("készpénzes és kártyás számla fizetettnek számít")

    basis_col = "issue_date" if spec.period.basis == "kelt" else "delivery_date"
    inv["basis_date"] = inv[basis_col].fillna(inv["issue_date"])
    inv["period_month"] = inv["basis_date"].dt.strftime("%Y-%m")
    inv["customer_name"] = inv["customer_key"].map(names).fillna("")
    inv = inv.sort_values(["issue_date", "invoice_number"]).reset_index(drop=True)

    numbers = set(inv["invoice_number"])
    line = _read(conn, "SELECT * FROM invoice_line")
    line = line[line["invoice_number"].isin(numbers)]
    vat = _read(conn, "SELECT * FROM invoice_vat")
    vat = vat[vat["invoice_number"].isin(numbers)]
    if f.vat_rates:
        rates = [str(r) for r in f.vat_rates]
        line = line[line["vat_rate"].astype(str).isin(rates)]
        vat = vat[vat["vat_rate"].astype(str).isin(rates)]
        filters_hu.append("ÁFA-kulcs: " + ", ".join(rates))
    fx = inv.set_index("invoice_number")["fx_rate_invoice"]
    line = line.copy()
    line["net_huf"] = line["net"] * line["invoice_number"].map(fx)
    line["vat_huf"] = line["vat"] * line["invoice_number"].map(fx)
    line = line.sort_values(["invoice_number", "line_no"]).reset_index(drop=True)
    vat = vat.sort_values(["invoice_number", "vat_rate"]).reset_index(drop=True)

    payment = _read(conn, "SELECT * FROM payment")
    payment = payment[payment["invoice_number"].isin(numbers)].copy()
    _to_dates(payment, ["pay_date"])
    payment["amount_huf"] = payment["amount"] * payment["invoice_number"].map(fx)
    payment["currency"] = payment["invoice_number"].map(inv.set_index("invoice_number")["currency"])
    payment = payment.sort_values(["pay_date", "payment_id"]).reset_index(drop=True)

    customer = customer[customer["customer_key"].isin(set(inv["customer_key"]))].copy()
    customer = customer.sort_values("customer_key").reset_index(drop=True)

    return Frames(
        invoice=inv,
        line=line,
        vat=vat,
        payment=payment,
        customer=customer,
        as_of=period.as_of,
        basis=spec.period.basis,
        filters_hu=filters_hu,
    )


# ---------------------------------------------------------------------------
# Measure context
# ---------------------------------------------------------------------------


class Ctx:
    """Window slicing with memoisation. One per compute() call."""

    def __init__(self, frames: Frames, spec: Spec, period: Period):
        self.frames = frames
        self.spec = spec
        self.period = period
        self._docs: dict[tuple[date, date], pd.DataFrame] = {}
        self._ar: dict[date, pd.DataFrame] = {}
        self._first_invoice = self._first_invoice_dates()

    def _first_invoice_dates(self) -> pd.Series:
        inv = self.frames.invoice
        first = inv.groupby("customer_key")["issue_date"].min()
        cust = self.frames.customer.set_index("customer_key")["first_invoice_date"]
        return cust.reindex(first.index).fillna(first)

    def docs(self, start: date, end: date) -> pd.DataFrame:
        key = (start, end)
        if key not in self._docs:
            inv = self.frames.invoice
            s, e = pd.Timestamp(start), pd.Timestamp(end)
            self._docs[key] = inv[(inv["basis_date"] >= s) & (inv["basis_date"] <= e)]
        return self._docs[key]

    def invoices(self, start: date, end: date) -> pd.DataFrame:
        d = self.docs(start, end)
        return d[d["doc_type"] == "invoice"]

    def ar(self, as_of: date) -> pd.DataFrame:
        if as_of not in self._ar:
            self._ar[as_of] = ar_frame(self.frames, as_of)
        return self._ar[as_of]

    def rev_by_customer(self, start: date, end: date) -> pd.Series:
        d = self.docs(start, end)
        return d.groupby("customer_name")["net_huf"].sum().sort_values(ascending=False)

    def active_customers(self, start: date, end: date) -> set[str]:
        d = self.docs(start, end)
        by = d.groupby("customer_key")["net_huf"].sum()
        return set(by[by > 0].index)


def ar_frame(frames: Frames, as_of: date) -> pd.DataFrame:
    """Open receivables per chain as of `as_of`.

    open = sum(gross_huf of chain docs issued <= as_of) - payments booked <= as_of.
    Docs without payment rows fall back to their stored paid_huf (cash/card
    auto-paid rows already carry paid_huf = gross_huf). Aging uses the chain
    root's due date.
    """
    inv = frames.invoice
    ts = pd.Timestamp(as_of)
    docs = inv[inv["issue_date"] <= ts]
    if docs.empty:
        return pd.DataFrame(
            columns=[
                "chain_root",
                "invoice_number",
                "customer_key",
                "customer_name",
                "currency",
                "due_date",
                "open_huf",
                "days_overdue",
                "bucket",
            ]
        )
    pay = frames.payment
    pay = pay[pay["pay_date"] <= ts]
    paid_rows = pay.groupby("invoice_number")["amount_huf"].sum()
    has_rows = frames.payment.groupby("invoice_number").size()
    paid = pd.Series(0.0, index=docs["invoice_number"])
    for num, stored in zip(docs["invoice_number"], docs["paid_huf"], strict=False):
        if num in has_rows.index:
            paid[num] = float(paid_rows.get(num, 0.0))
        else:
            paid[num] = float(stored)
    d = docs.assign(paid_asof=paid.values)
    grouped = d.groupby("chain_root").agg(gross=("gross_huf", "sum"), paid=("paid_asof", "sum"))
    grouped["open_huf"] = (grouped["gross"] - grouped["paid"]).round(2)
    roots = (
        d.sort_values("modification_index").drop_duplicates("chain_root").set_index("chain_root")
    )
    out = grouped.join(
        roots[["invoice_number", "customer_key", "customer_name", "currency", "due_date"]]
    )
    out = out[out["open_huf"].abs() >= 0.5].reset_index()
    due = out["due_date"].fillna(pd.Timestamp(as_of))
    days = (ts - due).dt.days
    out["days_overdue"] = days.where((days > 0) & (out["open_huf"] > 0), 0).astype(int)
    out["bucket"] = pd.cut(
        out["days_overdue"],
        bins=[-1, 0, 30, 60, 90, 10**6],
        labels=list(AGING_BUCKETS),
    ).astype(str)
    return (
        out[
            [
                "chain_root",
                "invoice_number",
                "customer_key",
                "customer_name",
                "currency",
                "due_date",
                "open_huf",
                "days_overdue",
                "bucket",
            ]
        ]
        .sort_values(["days_overdue", "open_huf"], ascending=[False, False])
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# Measure functions (flow: window [start, end]; snapshot: as of `end`)
# ---------------------------------------------------------------------------


def _safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def m_rev_net(ctx: Ctx, start, end, params):
    return float(ctx.docs(start, end)["net_huf"].sum())


def m_rev_gross(ctx: Ctx, start, end, params):
    return float(ctx.docs(start, end)["gross_huf"].sum())


def m_vat_total(ctx: Ctx, start, end, params):
    return float(ctx.docs(start, end)["vat_huf"].sum())


def m_inv_count(ctx: Ctx, start, end, params):
    return float(len(ctx.invoices(start, end)))


def m_avg_inv(ctx: Ctx, start, end, params):
    return _safe_div(m_rev_net(ctx, start, end, params), m_inv_count(ctx, start, end, params))


def m_storno_rate(ctx: Ctx, start, end, params):
    d = ctx.docs(start, end)
    return _safe_div(float((d["doc_type"] == "storno").sum()), m_inv_count(ctx, start, end, params))


def m_modifier_rate(ctx: Ctx, start, end, params):
    d = ctx.docs(start, end)
    return _safe_div(
        float((d["doc_type"] == "modifier").sum()), m_inv_count(ctx, start, end, params)
    )


def m_rev_net_cust(ctx: Ctx, start, end, params):
    return {str(k): float(v) for k, v in ctx.rev_by_customer(start, end).items()}


def m_rev_net_prod(ctx: Ctx, start, end, params):
    nums = set(ctx.docs(start, end)["invoice_number"])
    ln = ctx.frames.line
    ln = ln[ln["invoice_number"].isin(nums)]
    by = ln.groupby("product_name")["net_huf"].sum().sort_values(ascending=False)
    return {str(k): float(v) for k, v in by.items()}


def _vat_rows(ctx: Ctx, start, end) -> pd.DataFrame:
    nums = set(ctx.docs(start, end)["invoice_number"])
    v = ctx.frames.vat
    return v[v["invoice_number"].isin(nums)]


def m_rev_net_vat(ctx: Ctx, start, end, params):
    by = _vat_rows(ctx, start, end).groupby("vat_rate")["net_huf"].sum()
    return {str(k): float(v) for k, v in by.items()}


def m_vat_by_rate(ctx: Ctx, start, end, params):
    by = _vat_rows(ctx, start, end).groupby("vat_rate")["vat_huf"].sum()
    return {str(k): float(v) for k, v in by.items()}


def m_rev_net_cur(ctx: Ctx, start, end, params):
    by = ctx.docs(start, end).groupby("currency")["net_huf"].sum()
    return {str(k): float(v) for k, v in by.items()}


def m_top_n_share(ctx: Ctx, start, end, params):
    n = int(params.get("n", 5))
    by = ctx.rev_by_customer(start, end)
    by = by[by > 0]
    total = m_rev_net(ctx, start, end, params)
    return _safe_div(float(by.head(n).sum()), total)


def m_cust_active(ctx: Ctx, start, end, params):
    return float(len(ctx.active_customers(start, end)))


def m_cust_new(ctx: Ctx, start, end, params):
    first = ctx._first_invoice
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    return float(((first >= s) & (first <= e)).sum())


def m_cust_returning(ctx: Ctx, start, end, params):
    active = ctx.active_customers(start, end)
    first = ctx._first_invoice
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    new = set(first[(first >= s) & (first <= e)].index)
    return float(len(active - new))


def m_cust_churned(ctx: Ctx, start, end, params):
    t3_start = month_start(add_months(end, -2))
    prior_start = month_start(add_months(end, -14))
    prior_end = t3_start - timedelta(days=1)
    before = ctx.active_customers(prior_start, prior_end)
    recent = ctx.active_customers(t3_start, end)
    return float(len(before - recent))


def m_ar_balance(ctx: Ctx, start, end, params):
    return float(ctx.ar(end)["open_huf"].sum())


def m_ar_aging(ctx: Ctx, start, end, params):
    ar = ctx.ar(end)
    by = ar.groupby("bucket")["open_huf"].sum()
    return {b: float(by.get(b, 0.0)) for b in AGING_BUCKETS}


def m_overdue_amt(ctx: Ctx, start, end, params):
    ar = ctx.ar(end)
    return float(ar.loc[(ar["days_overdue"] > 0) & (ar["open_huf"] > 0), "open_huf"].sum())


def m_overdue_cnt(ctx: Ctx, start, end, params):
    ar = ctx.ar(end)
    return float(((ar["days_overdue"] > 0) & (ar["open_huf"] > 0)).sum())


def m_dso(ctx: Ctx, start, end, params):
    t_start = month_start(add_months(end, -2))
    t_end = month_end(end)
    rev = m_rev_net(ctx, t_start, t_end, params)
    days = (t_end - t_start).days + 1
    return _safe_div(m_ar_balance(ctx, start, end, params), _safe_div(rev, days))


def m_cash_in(ctx: Ctx, start, end, params):
    p = ctx.frames.payment
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    return float(p.loc[(p["pay_date"] >= s) & (p["pay_date"] <= e), "amount_huf"].sum())


def m_coll_rate(ctx: Ctx, start, end, params):
    return _safe_div(m_cash_in(ctx, start, end, params), m_rev_gross(ctx, start, end, params))


def m_ontime_rate(ctx: Ctx, start, end, params):
    inv = ctx.frames.invoice
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    due = inv[(inv["doc_type"] == "invoice") & (inv["due_date"] >= s) & (inv["due_date"] <= e)]
    paid = due[due["pay_status"] == "paid"]
    if paid.empty:
        return None
    last_pay = ctx.frames.payment.groupby("invoice_number")["pay_date"].max()
    lp = paid["invoice_number"].map(last_pay)
    on_time = lp.isna() | (lp <= paid["due_date"])
    return float(on_time.sum()) / float(len(paid))


def m_einv_share(ctx: Ctx, start, end, params):
    inv = ctx.invoices(start, end)
    return _safe_div(float((inv["is_einvoice"] == 1).sum()), float(len(inv)))


def m_pm_mix(ctx: Ctx, start, end, params):
    d = ctx.docs(start, end)
    total = float(d["net_huf"].sum())
    by = d.groupby("payment_method")["net_huf"].sum()
    return {str(k): (float(v) / total if total else None) for k, v in by.items()}


def m_eur_share(ctx: Ctx, start, end, params):
    d = ctx.docs(start, end)
    fx = float(d.loc[d["currency"] != "HUF", "net_huf"].sum())
    return _safe_div(fx, float(d["net_huf"].sum()))


def m_eur_open(ctx: Ctx, start, end, params):
    ar = ctx.ar(end)
    return float(ar.loc[ar["currency"] == "EUR", "open_huf"].sum())


def m_fx_dev(ctx: Ctx, start, end, params):
    d = ctx.docs(start, end)
    d = d[(d["currency"] != "HUF") & (d["net_amount"] != 0)]
    if d.empty:
        return 0.0
    implied = d["net_huf"] / (d["net_amount"] * d["fx_rate_invoice"])
    return float((implied - 1).abs().max())


@dataclass(frozen=True)
class MeasureDef:
    id: str
    label_hu: str
    label_en: str
    formula_words: str
    source: str
    default_format: str
    fn: Callable
    kind: str = "flow"
    dim: str | None = None
    default_comparisons: tuple[str, ...] = ("mom", "yoy")
    source_fields: str = "invoice.net_huf"


def _m(*args, **kw) -> MeasureDef:
    return MeasureDef(*args, **kw)


MEASURES: dict[str, MeasureDef] = {
    d.id: d
    for d in [
        _m(
            "rev_net",
            "Nettó árbevétel",
            "Net revenue",
            "A szűrt bizonylatok (számla, helyesbítő, sztornó) előjeles nettó HUF összege az "
            "időszak alapdátuma szerint.",
            "D",
            "huf_k",
            m_rev_net,
            default_comparisons=("mom", "yoy", "ytd"),
        ),
        _m(
            "rev_net_cust",
            "Nettó árbevétel vevőnként",
            "Net revenue by customer",
            "Nettó árbevétel vevőnév szerint csoportosítva.",
            "D",
            "huf_k",
            m_rev_net_cust,
            dim="customer",
            source_fields="invoice.net_huf, customer.name",
        ),
        _m(
            "rev_net_prod",
            "Nettó árbevétel termékenként",
            "Net revenue by product",
            "Tételsorok nettó értéke a számla árfolyamával forintosítva, terméknév szerint.",
            "A",
            "huf_k",
            m_rev_net_prod,
            dim="product",
            source_fields="invoice_line.net, invoice.fx_rate_invoice",
        ),
        _m(
            "rev_net_vat",
            "Nettó árbevétel ÁFA-kulcsonként",
            "Net revenue by VAT rate",
            "Az ÁFA-bontás nettó HUF összege kulcsonként.",
            "A",
            "huf_k",
            m_rev_net_vat,
            dim="vat_rate",
            source_fields="invoice_vat.net_huf",
        ),
        _m(
            "rev_net_cur",
            "Nettó árbevétel devizánként",
            "Net revenue by currency",
            "Nettó árbevétel HUF-ban, a számla devizaneme szerint csoportosítva.",
            "D",
            "huf_k",
            m_rev_net_cur,
            dim="currency",
            source_fields="invoice.net_huf, invoice.currency",
        ),
        _m(
            "rev_gross",
            "Bruttó árbevétel",
            "Gross revenue",
            "A szűrt bizonylatok előjeles bruttó HUF összege.",
            "D",
            "huf_k",
            m_rev_gross,
            default_comparisons=("mom", "yoy", "ytd"),
            source_fields="invoice.gross_huf",
        ),
        _m(
            "vat_by_rate",
            "Fizetendő ÁFA kulcsonként",
            "VAT payable by rate",
            "Az ÁFA-bontás ÁFA HUF összege kulcsonként, az időszak alapdátuma (kelt vagy "
            "teljesítés) szerint.",
            "A",
            "huf_k",
            m_vat_by_rate,
            dim="vat_rate",
            source_fields="invoice_vat.vat_huf",
        ),
        _m(
            "vat_total",
            "ÁFA összesen",
            "Total VAT",
            "A szűrt bizonylatok előjeles ÁFA HUF összege.",
            "D",
            "huf_k",
            m_vat_total,
            source_fields="invoice.vat_huf",
        ),
        _m(
            "inv_count",
            "Számlák száma",
            "Invoice count",
            "A számla típusú bizonylatok darabszáma (helyesbítő és sztornó nélkül).",
            "D",
            "count",
            m_inv_count,
            default_comparisons=("mom", "yoy", "avg3m"),
            source_fields="invoice.doc_type",
        ),
        _m(
            "avg_inv",
            "Átlagos számlaérték",
            "Average invoice value",
            "Nettó árbevétel osztva a számlák számával.",
            "D",
            "huf_k",
            m_avg_inv,
            default_comparisons=("mom", "avg3m"),
        ),
        _m(
            "storno_rate",
            "Sztornó arány",
            "Storno rate",
            "Sztornó bizonylatok száma osztva a számlák számával az időszakban.",
            "D",
            "pct",
            m_storno_rate,
            default_comparisons=("mom", "avg3m"),
            source_fields="invoice.doc_type",
        ),
        _m(
            "modifier_rate",
            "Helyesbítő arány",
            "Modifier rate",
            "Helyesbítő bizonylatok száma osztva a számlák számával az időszakban.",
            "D",
            "pct",
            m_modifier_rate,
            default_comparisons=("mom", "avg3m"),
            source_fields="invoice.doc_type",
        ),
        _m(
            "top_n_share",
            "Top-N vevő részesedés",
            "Top-N customer share",
            "A legnagyobb N (params.n, alapból 5) vevő nettó árbevétele osztva a teljes nettó "
            "árbevétellel.",
            "D",
            "pct",
            m_top_n_share,
            default_comparisons=("mom", "yoy"),
            source_fields="invoice.net_huf, customer.name",
        ),
        _m(
            "cust_active",
            "Aktív vevők",
            "Active customers",
            "Azon vevők száma, akiknek az időszakban pozitív a nettó árbevétele.",
            "D",
            "count",
            m_cust_active,
            source_fields="invoice.customer_key",
        ),
        _m(
            "cust_new",
            "Új vevők",
            "New customers",
            "Azon vevők száma, akiknek az első számlája az időszakba esik "
            "(customer.first_invoice_date, "
            "hiányában a legkorábbi számla kelte).",
            "D",
            "count",
            m_cust_new,
            source_fields="customer.first_invoice_date",
        ),
        _m(
            "cust_returning",
            "Visszatérő vevők",
            "Returning customers",
            "Aktív vevők száma az új vevők nélkül.",
            "D",
            "count",
            m_cust_returning,
            source_fields="invoice.customer_key, customer.first_invoice_date",
        ),
        _m(
            "cust_churned",
            "Elvesztett vevők",
            "Churned customers",
            "Azon vevők száma, akiknek az időszak végét megelőző 12 hónapban (a záró 3 hónap "
            "előtt) volt "
            "árbevétele, de a záró 3 hónapban nem.",
            "D",
            "count",
            m_cust_churned,
            default_comparisons=("mom",),
            source_fields="invoice.customer_key",
        ),
        _m(
            "ar_balance",
            "Kintlévőség",
            "AR balance",
            "Nyitott követelés a fordulónapon: a számlaláncok bruttó HUF összege mínusz a "
            "fordulónapig "
            "könyvelt kifizetések (kifizetés-sor nélküli bizonylatnál a tárolt fizetett összeg).",
            "A",
            "huf_k",
            m_ar_balance,
            kind="snapshot",
            default_comparisons=("mom",),
            source_fields="invoice.gross_huf, payment.amount, invoice.paid_huf",
        ),
        _m(
            "ar_aging",
            "Korosított kintlévőség",
            "AR aging",
            "Nyitott követelés a lánc eredeti számlájának fizetési határideje szerinti sávokban: "
            "nem "
            "lejárt, 1-30, 31-60, 61-90, 90+ nap.",
            "A",
            "huf_k",
            m_ar_aging,
            kind="snapshot",
            dim="bucket",
            default_comparisons=("mom",),
            source_fields="invoice.due_date, payment.pay_date",
        ),
        _m(
            "overdue_amt",
            "Lejárt kintlévőség",
            "Overdue amount",
            "Nyitott követelés, ahol a fizetési határidő a fordulónap előtt van.",
            "A",
            "huf_k",
            m_overdue_amt,
            kind="snapshot",
            default_comparisons=("mom",),
            source_fields="invoice.due_date, payment.pay_date",
        ),
        _m(
            "overdue_cnt",
            "Lejárt számlák száma",
            "Overdue count",
            "Lejárt, nyitott számlaláncok darabszáma a fordulónapon.",
            "A",
            "count",
            m_overdue_cnt,
            kind="snapshot",
            default_comparisons=("mom",),
            source_fields="invoice.due_date",
        ),
        _m(
            "dso",
            "DSO (vevőállomány forgási ideje)",
            "Days sales outstanding",
            "Kintlévőség osztva a fordulónapot záró 3 naptári hónap napi átlagos nettó "
            "árbevételével "
            "(3 havi nettó árbevétel / a 3 hónap napjainak száma).",
            "A",
            "days",
            m_dso,
            kind="snapshot",
            default_comparisons=("mom", "avg3m"),
            source_fields="invoice.gross_huf, payment.amount, invoice.net_huf",
        ),
        _m(
            "cash_in",
            "Beérkezett pénz",
            "Cash collected",
            "Az időszakban könyvelt kifizetések összege a számla árfolyamával forintosítva.",
            "A",
            "huf_k",
            m_cash_in,
            default_comparisons=("mom", "yoy", "ytd"),
            source_fields="payment.amount, payment.pay_date, invoice.fx_rate_invoice",
        ),
        _m(
            "coll_rate",
            "Beszedési arány",
            "Collection rate",
            "Beérkezett pénz osztva az időszakban kiállított bruttó árbevétellel.",
            "A",
            "pct",
            m_coll_rate,
            default_comparisons=("mom", "avg3m"),
            source_fields="payment.amount, invoice.gross_huf",
        ),
        _m(
            "ontime_rate",
            "Határidőre fizetett arány",
            "Paid-on-time share",
            "Az időszakban esedékes, kifizetett számlák közül azok aránya, amelyek utolsó "
            "kifizetése "
            "legkésőbb a fizetési határidőn történt (kifizetés-sor nélküli, fizetettnek jelölt "
            "számla "
            "határidőben fizetettnek számít).",
            "A",
            "pct",
            m_ontime_rate,
            default_comparisons=("mom", "avg3m"),
            source_fields="invoice.due_date, payment.pay_date",
        ),
        _m(
            "einv_share",
            "E-számla arány",
            "E-invoice share",
            "E-számlaként kiállított számlák száma osztva a számlák számával.",
            "A",
            "pct",
            m_einv_share,
            default_comparisons=("mom",),
            source_fields="invoice.is_einvoice",
        ),
        _m(
            "pm_mix",
            "Fizetési mód megoszlás",
            "Payment method mix",
            "Nettó árbevétel részesedése fizetési módonként.",
            "D",
            "pct",
            m_pm_mix,
            dim="payment_method",
            default_comparisons=("mom",),
            source_fields="invoice.payment_method, invoice.net_huf",
        ),
        _m(
            "eur_share",
            "EUR kitettség",
            "FX exposure share",
            "Nem HUF devizanemű bizonylatok nettó HUF árbevétele osztva a teljes nettó "
            "árbevétellel.",
            "D",
            "pct",
            m_eur_share,
            source_fields="invoice.currency, invoice.net_huf",
        ),
        _m(
            "eur_open",
            "Nyitott EUR követelés",
            "Open EUR receivables",
            "EUR devizanemű számlaláncok nyitott követelése HUF-ban a fordulónapon.",
            "A",
            "huf_k",
            m_eur_open,
            kind="snapshot",
            default_comparisons=("mom",),
            source_fields="invoice.currency, invoice.gross_huf, payment.amount",
        ),
        _m(
            "fx_dev",
            "Árfolyam eltérés",
            "FX rate deviation",
            "A nem HUF bizonylatoknál a tárolt HUF nettó és a nettó × számlaárfolyam hányadosának "
            "legnagyobb abszolút eltérése 1-től az időszakban.",
            "A",
            "pct",
            m_fx_dev,
            default_comparisons=(),
            source_fields="invoice.net_huf, invoice.net_amount, invoice.fx_rate_invoice",
        ),
    ]
}


# ---------------------------------------------------------------------------
# Local extension (measures_local.py, optional, not shipped by the kit)
# ---------------------------------------------------------------------------


class LocalMeasureError(ValueError):
    """A measures_local.py entry cannot be merged into the catalogue."""

    def __init__(self, message_hu: str):
        super().__init__(message_hu)
        self.message_hu = message_hu


def merge_local_measures(catalogue: dict[str, MeasureDef]) -> dict[str, MeasureDef]:
    """Merge `measures_local.MEASURES` into `catalogue` in place when the module exists.

    `measures_local.py` sits next to this file (any sys.path entry works) and is
    not part of the kit manifest, so an installer update never overwrites it.
    Local ids may add to the catalogue but never override a shipped id.
    """
    if importlib.util.find_spec("measures_local") is None:
        return catalogue
    local = getattr(importlib.import_module("measures_local"), "MEASURES", None)
    if not isinstance(local, dict):
        return catalogue
    for mid, mdef in local.items():
        if mid in catalogue:
            raise LocalMeasureError(
                f"a helyi mérőszám ütközik a katalógussal: {mid} (measures_local.py), "
                "válassz másik azonosítót"
            )
        if not isinstance(mdef, MeasureDef) or mdef.id != mid:
            raise LocalMeasureError(
                f"a helyi mérőszám nem MeasureDef, vagy az id nem egyezik a kulccsal: {mid} "
                "(measures_local.py)"
            )
        catalogue[mid] = mdef
    return catalogue


merge_local_measures(MEASURES)


# ---------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------


@dataclass
class Result:
    measures: pd.DataFrame
    series: pd.DataFrame
    thresholds: pd.DataFrame
    exceptions: pd.DataFrame
    ar_aging: pd.DataFrame
    vat_summary: pd.DataFrame
    top_customers: pd.DataFrame
    top_series: pd.DataFrame
    ar: pd.DataFrame
    values: dict[str, float | None]
    exception_totals: dict[str, int]

    def value(self, key: str) -> float | None:
        return self.values.get(key)

    def level(self, key: str) -> str:
        t = self.thresholds
        hit = t[t["measure_id"] == key]
        return str(hit["level"].iloc[0]) if len(hit) else "none"


def _pct(cur: float | None, base: float | None) -> float | None:
    if cur is None or base is None or base == 0:
        return None
    return (cur - base) / abs(base)


def _fmt_for(m: MeasureSpec, mdef: MeasureDef | None) -> str:
    if m.format:
        return m.format
    return mdef.default_format if mdef else "huf_k"


class _Evaluator:
    """Evaluates catalogue and custom measures over windows with caching."""

    def __init__(self, ctx: Ctx, spec: Spec):
        self.ctx = ctx
        self.spec = spec
        self._cache: dict[tuple[str, date, date, str], object] = {}

    def catalogue_value(self, mid: str, start: date, end: date, params: dict | None = None):
        params = params or {}
        key = (mid, start, end, repr(sorted(params.items())))
        if key not in self._cache:
            self._cache[key] = MEASURES[mid].fn(self.ctx, start, end, params)
        return self._cache[key]

    def value(self, m: MeasureSpec, start: date, end: date):
        if m.is_custom:
            return self.custom_value(m, start, end)
        return self.catalogue_value(m.id, start, end, m.params)

    def custom_value(self, m: MeasureSpec, start: date, end: date) -> float | None:
        assert m.formula
        period = self.ctx.period
        values: dict[str, float | None] = {}
        for mid in MEASURES:
            if mid in m.formula:
                v = self.catalogue_value(mid, start, end)
                values[mid] = v if not isinstance(v, dict) else None

        def prior(mid: str, n: int) -> float | None:
            s, e = period.shift(start, end, n)
            v = self.catalogue_value(mid, s, e)
            return None if isinstance(v, dict) else v

        return eval_formula(m.formula, values, prior)


def _threshold_level(value: float | None, warn, critical, direction: str) -> str:
    if value is None:
        return "none"
    if direction == "above":
        if critical is not None and value >= critical:
            return "critical"
        if warn is not None and value >= warn:
            return "warn"
    else:
        if critical is not None and value <= critical:
            return "critical"
        if warn is not None and value <= warn:
            return "warn"
    return "none"


def compute(frames: Frames, spec: Spec, period: Period) -> Result:
    ctx = Ctx(frames, spec, period)
    ev = _Evaluator(ctx, spec)
    rows: list[dict] = []
    values: dict[str, float | None] = {}
    history = period.history()

    windows = {
        "cur": (period.start, period.end),
        "prior": (period.prior_start, period.prior_end),
        "py": (period.py_start, period.py_end),
        "ytd": (period.ytd_start, period.end),
        "ytd_prior": (period.ytd_prior_start, period.ytd_prior_end),
    }
    avg_windows = [
        (add_months(month_start(period.start), -i), month_end(add_months(period.start, -i)))
        for i in (1, 2, 3)
    ]

    def snapshot_windows(mdef: MeasureDef | None) -> dict[str, tuple[date, date]]:
        if mdef is None or mdef.kind != "snapshot":
            return windows
        return {
            "cur": (period.start, period.as_of),
            "prior": (period.prior_start, period.prior_end),
            "py": (period.py_start, period.py_end),
        }

    for m in spec.measures:
        mdef = None if m.is_custom else MEASURES[m.id]
        wins = snapshot_windows(mdef)
        got = {name: ev.value(m, s, e) for name, (s, e) in wins.items()}
        if mdef is not None and mdef.kind == "snapshot":
            avg_vals = [ev.value(m, s, e) for s, e in avg_windows]
        else:
            avg_vals = [ev.value(m, s, e) for s, e in avg_windows]
        cur = got["cur"]
        if isinstance(cur, dict):
            keys = list(cur)
            for k in keys:
                prior_v = got["prior"].get(k) if isinstance(got["prior"], dict) else None
                py_v = got["py"].get(k) if isinstance(got["py"], dict) else None
                ytd_v = got.get("ytd", {}).get(k) if isinstance(got.get("ytd"), dict) else None
                ytdp_v = (
                    got.get("ytd_prior", {}).get(k)
                    if isinstance(got.get("ytd_prior"), dict)
                    else None
                )
                avg = [a.get(k) for a in avg_vals if isinstance(a, dict) and a.get(k) is not None]
                rows.append(
                    {
                        "measure_id": m.key,
                        "dim_name": mdef.dim if mdef else "",
                        "dim_value": k,
                        "period_label": period.label,
                        "value": cur[k],
                        "prior": prior_v,
                        "prior_year": py_v,
                        "ytd": ytd_v,
                        "ytd_prior": ytdp_v,
                        "mom_pct": _pct(cur[k], prior_v),
                        "yoy_pct": _pct(cur[k], py_v),
                        "avg3m": (sum(avg) / len(avg)) if avg else None,
                    }
                )
            values[m.key] = float(sum(v for v in cur.values() if v is not None)) if cur else None
        else:
            avg = [a for a in avg_vals if a is not None and not isinstance(a, dict)]
            rows.append(
                {
                    "measure_id": m.key,
                    "dim_name": "total",
                    "dim_value": "",
                    "period_label": period.label,
                    "value": cur,
                    "prior": got["prior"],
                    "prior_year": got["py"],
                    "ytd": got.get("ytd"),
                    "ytd_prior": got.get("ytd_prior"),
                    "mom_pct": _pct(cur, got["prior"]),
                    "yoy_pct": _pct(cur, got["py"]),
                    "avg3m": (sum(avg) / len(avg)) if avg else None,
                }
            )
            values[m.key] = cur
    measures = pd.DataFrame(rows, columns=MEASURE_COLUMNS)

    # series for tiles (13-month history)
    srows = []
    for ref in spec.output.executive.tiles:
        m = spec.find_measure(ref)
        if m is None:
            continue
        for s, e in history:
            v = ev.value(m, s, e)
            if isinstance(v, dict):
                v = float(sum(x for x in v.values() if x is not None)) if v else None
            srows.append({"measure_id": ref, "month": s.strftime("%Y-%m"), "value": v})
    series = pd.DataFrame(srows, columns=["measure_id", "month", "value"])

    # thresholds
    trows = []
    for key, t in spec.thresholds.items():
        v = values.get(key)
        ratio = v
        if t.unit.startswith("pct_of:"):
            ratio = _safe_div(v, values.get(t.unit.split(":", 1)[1]))
        trows.append(
            {
                "measure_id": key,
                "value": v,
                "ratio": ratio,
                "warn": t.warn,
                "critical": t.critical,
                "direction": t.direction,
                "unit": t.unit,
                "level": _threshold_level(ratio, t.warn, t.critical, t.direction),
            }
        )
    thresholds = pd.DataFrame(
        trows,
        columns=["measure_id", "value", "ratio", "warn", "critical", "direction", "unit", "level"],
    )

    # AR aging
    ar = ctx.ar(period.as_of)
    ag_rows = []
    total_open = float(ar["open_huf"].sum()) if len(ar) else 0.0
    for b in AGING_BUCKETS:
        sub = ar[ar["bucket"] == b]
        amt = float(sub["open_huf"].sum())
        ag_rows.append(
            {
                "bucket": b,
                "amount": amt,
                "count": int(len(sub)),
                "share": (amt / total_open) if total_open else None,
            }
        )
    ar_aging = pd.DataFrame(ag_rows, columns=["bucket", "amount", "count", "share"])

    # VAT summary
    vrows = _vat_rows(ctx, period.start, period.end)
    vs = (
        vrows.groupby("vat_rate")
        .agg(net_huf=("net_huf", "sum"), vat_huf=("vat_huf", "sum"))
        .reset_index()
    )
    vs["gross_huf"] = vs["net_huf"] + vs["vat_huf"]
    vs["_ord"] = vs["vat_rate"].map(lambda r: -int(r) if str(r).isdigit() else 1000)
    vs = vs.sort_values(["_ord", "vat_rate"]).drop(columns="_ord").reset_index(drop=True)
    vat_summary = vs[["vat_rate", "net_huf", "vat_huf", "gross_huf"]]

    # top customers
    cur_by = ctx.rev_by_customer(period.start, period.end)
    prior_by = ctx.rev_by_customer(period.prior_start, period.prior_end)
    total_net = float(cur_by.sum())
    cur_by = cur_by[cur_by > 0]
    top_n = spec.output.executive.top_n
    tc_rows = []
    cum = 0.0
    for name, net in cur_by.head(top_n).items():
        share = (float(net) / total_net) if total_net else None
        cum += share or 0.0
        tc_rows.append(
            {
                "name": str(name),
                "net": float(net),
                "share": share,
                "cum_share": cum if share is not None else None,
                "mom_pct": _pct(
                    float(net), float(prior_by.get(name, 0.0)) if name in prior_by.index else None
                ),
            }
        )
    top_customers = pd.DataFrame(tc_rows, columns=["name", "net", "share", "cum_share", "mom_pct"])
    six = history[-6:]
    ts_rows = []
    for name in top_customers["name"]:
        for s, e in six:
            by = ctx.rev_by_customer(s, e)
            ts_rows.append(
                {"name": name, "month": s.strftime("%Y-%m"), "value": float(by.get(name, 0.0))}
            )
    top_series = pd.DataFrame(ts_rows, columns=["name", "month", "value"])

    exceptions, totals = compute_exceptions(ctx)

    return Result(
        measures=measures,
        series=series,
        thresholds=thresholds,
        exceptions=exceptions,
        ar_aging=ar_aging,
        vat_summary=vat_summary,
        top_customers=top_customers,
        top_series=top_series,
        ar=ar,
        values=values,
        exception_totals=totals,
    )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


def normalize_customer_name(name: str) -> str:
    s = re.sub(r"[^a-z0-9áéíóöőúüű ]", " ", str(name).lower())
    s = re.sub(
        r"\b(kft|zrt|nyrt|bt|kkt|ev|nonprofit|gmbh|ag|ltd|llc|inc|sro|s r o|d o o)\b", " ", s
    )
    return " ".join(s.split())


def _exc_rows(ctx: Ctx, rule: str, params: dict) -> list[dict]:
    p, per = ctx.period, ctx.period
    rows: list[dict] = []
    if rule in ("overdue_gt_days", "overdue_gt_amount"):
        ar = ctx.ar(per.as_of)
        ar = ar[(ar["days_overdue"] > 0) & (ar["open_huf"] > 0)]
        if rule == "overdue_gt_days":
            ar = ar[ar["days_overdue"] > float(params.get("days", 0))]
        else:
            ar = ar[ar["open_huf"] > float(params.get("amount_huf", 0))]
        for r in ar.itertuples():
            rows.append(
                {
                    "invoice_number": r.invoice_number,
                    "customer": r.customer_name,
                    "amount": float(r.open_huf),
                    "days": int(r.days_overdue),
                    "note": f"határidő: {r.due_date.date().isoformat()}"
                    if pd.notna(r.due_date)
                    else "",
                }
            )
    elif rule in ("storno_in_period", "modifier_in_period"):
        kind = "storno" if rule == "storno_in_period" else "modifier"
        d = ctx.docs(p.start, p.end)
        for r in d[d["doc_type"] == kind].itertuples():
            rows.append(
                {
                    "invoice_number": r.invoice_number,
                    "customer": r.customer_name,
                    "amount": float(r.gross_huf),
                    "days": None,
                    "note": f"eredeti: {r.chain_root}",
                }
            )
    elif rule == "amount_outlier_zscore":
        z = float(params.get("z", 3.0))
        months = int(params.get("window_months", 12))
        w_start = month_start(add_months(p.start, -months))
        hist = ctx.invoices(w_start, p.end)["net_huf"]
        if len(hist) >= 3 and float(hist.std(ddof=0)) > 0:
            mean, std = float(hist.mean()), float(hist.std(ddof=0))
            cur = ctx.invoices(p.start, p.end)
            for r in cur.itertuples():
                score = (float(r.net_huf) - mean) / std
                if abs(score) > z:
                    rows.append(
                        {
                            "invoice_number": r.invoice_number,
                            "customer": r.customer_name,
                            "amount": float(r.net_huf),
                            "days": None,
                            "note": f"z={score:.1f}",
                        }
                    )
    elif rule == "missing_customer_taxno":
        only_domestic = bool(params.get("only_domestic_companies", False))
        cust = ctx.frames.customer.set_index("customer_key")
        d = ctx.invoices(p.start, p.end)
        for r in d.itertuples():
            if r.customer_key not in cust.index:
                continue
            c = cust.loc[r.customer_key]
            tax = c["tax_number"]
            if isinstance(tax, str) and tax.strip():
                continue
            if int(c["is_private"] or 0) == 1:
                continue
            if only_domestic and str(c["country"] or "HU").upper() not in ("HU", ""):
                continue
            rows.append(
                {
                    "invoice_number": r.invoice_number,
                    "customer": r.customer_name,
                    "amount": float(r.gross_huf),
                    "days": None,
                    "note": "hiányzó adószám",
                }
            )
    elif rule == "fx_deviation":
        tol = float(params.get("tolerance", 0.005))
        d = ctx.docs(p.start, p.end)
        d = d[(d["currency"] != "HUF") & (d["net_amount"] != 0)]
        for r in d.itertuples():
            dev = float(r.net_huf) / (float(r.net_amount) * float(r.fx_rate_invoice)) - 1
            if abs(dev) > tol:
                rows.append(
                    {
                        "invoice_number": r.invoice_number,
                        "customer": r.customer_name,
                        "amount": float(r.net_huf),
                        "days": None,
                        "note": f"eltérés {dev:+.2%} (árfolyam {r.fx_rate_invoice})",
                    }
                )
    elif rule == "duplicate_customer_name":
        cust = ctx.frames.customer
        groups: dict[str, list[tuple[str, str]]] = {}
        for r in cust.itertuples():
            groups.setdefault(normalize_customer_name(r.name), []).append((r.customer_key, r.name))
        for _norm, members in sorted(groups.items()):
            if len(members) < 2:
                continue
            rows.append(
                {
                    "invoice_number": "",
                    "customer": members[0][1],
                    "amount": None,
                    "days": None,
                    "note": "azonos név: " + ", ".join(f"{n} ({k})" for k, n in members),
                }
            )
    elif rule == "unpaid_cash_invoice":
        d = ctx.docs(p.start, p.end)
        d = d[(d["payment_method"] == "cash") & (d["pay_status_raw"].isin(["unpaid", "partial"]))]
        for r in d.itertuples():
            rows.append(
                {
                    "invoice_number": r.invoice_number,
                    "customer": r.customer_name,
                    "amount": float(r.gross_huf - r.paid_huf)
                    if r.pay_status_raw == "partial"
                    else float(r.gross_huf),
                    "days": None,
                    "note": "készpénzes számla nyitott státusszal",
                }
            )
    return rows


def compute_exceptions(ctx: Ctx) -> tuple[pd.DataFrame, dict[str, int]]:
    all_rows: list[dict] = []
    totals: dict[str, int] = {}
    for e in ctx.spec.exceptions:
        rows = _exc_rows(ctx, e.rule, e.params)
        rows.sort(
            key=lambda r: (
                -(abs(r["amount"]) if r["amount"] is not None else 0),
                r["invoice_number"],
            )
        )
        totals[e.id] = len(rows)
        for r in rows[: e.max_rows]:
            all_rows.append({"rule_id": e.id, "rule": e.rule, "severity": e.severity, **r})
    df = pd.DataFrame(all_rows, columns=EXCEPTION_COLUMNS)
    if len(df):
        df["_sev"] = df["severity"].map(SEVERITY_ORDER)
        df["_amt"] = df["amount"].fillna(0).abs()
        df = df.sort_values(["_sev", "_amt", "invoice_number"], ascending=[True, False, True])
        df = df.drop(columns=["_sev", "_amt"]).reset_index(drop=True)
    return df, totals


# ---------------------------------------------------------------------------
# Calendar (Power BI dim_date)
# ---------------------------------------------------------------------------


def calendar_frame(start: date, end: date, fiscal_start_month: int = 1) -> pd.DataFrame:
    rows = []
    d = start
    while d <= end:
        fy = fiscal_year_of(d, fiscal_start_month)
        rows.append(
            {
                "date": d.isoformat(),
                "period_month": d.strftime("%Y-%m"),
                "quarter": f"{fy}-Q{fiscal_quarter_of(d, fiscal_start_month)}",
                "fiscal_year": fy,
                "fiscal_period_no": fiscal_period_no(d, fiscal_start_month),
                "is_month_end": int(d == month_end(d)),
                "is_business_day": int(d.weekday() < 5),
            }
        )
        d += timedelta(days=1)
    return pd.DataFrame(rows)
