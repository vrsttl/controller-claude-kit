# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "xlsxwriter>=3.2", "pyyaml>=6"]
# ///
"""Excel writer (xlsxwriter) and Power BI CSV export for a computed report.

Public API:
    write_workbook(result, spec, period, out_path, run_info) -> Path
    write_powerbi_csvs(result, frames, spec, folder) -> list[Path]
    sheet_name(entity, language) -> str
    expected_sheets(spec) -> list[str]
    expected_tables(spec) -> list[str]

`run_info` is the dict produced by report_validate.build_run_info (run_ts,
spec_version, spec_hash, kit_version, row_counts, checks, delivered_path).
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import pandas as pd
import xlsxwriter
from report_engine import (
    AGING_BUCKETS,
    AGING_LABELS_EN,
    AGING_LABELS_HU,
    MEASURES,
    Frames,
    Period,
    Result,
    calendar_frame,
    month_start,
)
from report_spec import MAX_TILES, Spec
from xlsxwriter.utility import xl_rowcol_to_cell

SHEET_NAMES = {
    "hu": {
        "executive": "Vezetői összefoglaló",
        "exceptions": "Kivételek",
        "invoice": "Számlák",
        "line": "Tételek",
        "payment": "Kifizetések",
        "customer": "Ügyfelek",
        "measure": "Mutatók",
        "definitions": "Definíciók",
        "runlog": "Futtatási napló",
    },
    "en": {
        "executive": "Executive",
        "exceptions": "Exceptions",
        "invoice": "Invoices",
        "line": "Lines",
        "payment": "Payments",
        "customer": "Customers",
        "measure": "Measures",
        "definitions": "Definitions",
        "runlog": "Run log",
    },
}
TABLE_ENTITIES = ("exceptions", "invoice", "line", "payment", "customer", "measure")
SERIES_SHEET = "_series"
MAX_EXEC_EXCEPTIONS = 12

NUMBER_FORMATS = {
    "huf_k": '#,##0," e Ft"',
    "huf": '#,##0" Ft"',
    "eur": '#,##0.00" €"',
    "pct": "0.0%",
    "delta": "+0.0%;-0.0%;0.0%",
    "days": '0" nap"',
    "count": '#,##0" db"',
}
COLOR_BODY = "#404040"
COLOR_HEADER_BG = "#F2F2F2"
COLOR_BORDER = "#D9D9D9"
COLOR_TILE = "#1F3864"
COLOR_CRITICAL = "#C00000"
COLOR_WARN = "#B45F06"
COLOR_BAR = "#8EA9DB"
COLOR_SPARK = "#7F7F7F"

LEFT_COL = 1  # B
RIGHT_COL = 12  # M
TILE_COLS = (1, 4, 7, 11, 14, 17)  # B, E, H, L, O, R
LAST_COL = 21  # V

T = {
    "hu": {
        "badge_ok": "ELLENŐRZÖTT",
        "badge_warn": "FIGYELMEZTETÉS ({n})",
        "badge_fail": "HIBÁS",
        "basis": "alap",
        "run": "futtatva",
        "spec": "spec v",
        "kelt": "kelt",
        "teljesites": "teljesítés",
        "measure": "Mutató",
        "cur": "Akt.",
        "prior": "Előző",
        "mom": "MoM%",
        "py": "Előző év",
        "yoy": "YoY%",
        "ytd": "YTD",
        "ytd_py": "YTD PY",
        "ytd_pct": "YTD%",
        "aging": "Korosítás",
        "amount": "Összeg",
        "count": "db",
        "share": "Arány",
        "total": "Összesen",
        "vat_rate": "ÁFA-kulcs",
        "net": "Nettó",
        "vat": "ÁFA",
        "gross": "Bruttó",
        "top": "Top-{n} vevő",
        "cum": "Kum.",
        "trend": "Trend (6 hó)",
        "exceptions": "Kivételek ({shown}/{total}, teljes lista: {sheet} lap)",
        "exceptions_all": "Kivételek ({shown})",
        "exc_type": "Típus",
        "exc_invoice": "Számla",
        "exc_customer": "Vevő",
        "exc_amount": "Összeg",
        "exc_note": "Nap / megjegyzés",
        "foot1": (
            "Definíciók: árbevétel = {basis} szerinti időszak, {storno}; előjeles összegek "
            "(helyesbítő és sztornó levonva)."
        ),
        "foot2": (
            "Kintlévőség a(z) {as_of} fordulónapon, a lánc eredeti számlájának határideje "
            "szerint korosítva. Küszöbök: {thresholds}"
        ),
        "foot3": (
            "Forrás: számlázó Agent gyorsítótár; ellenőrzések: {ok} OK, {warn} "
            "figyelmeztetés, {fail} hiba, {skipped} kihagyva. Kit v{kit}."
        ),
        "storno_issue": "sztornó a kiállítás hónapjában",
        "storno_orig": "sztornó az eredeti számla hónapjában",
        "no_thresholds": "nincs",
        "def_headers": [
            "measure_id",
            "label_hu",
            "label_en",
            "formula_words",
            "source_fields",
            "filters_applied",
            "threshold_warn",
            "threshold_critical",
        ],
        "runlog": {
            "period": "Időszak",
            "run_ts": "Futtatva",
            "spec_version": "Spec verzió",
            "spec_hash": "Spec hash (sha256)",
            "kit_version": "Kit verzió",
            "rows": "Sorok",
            "checks": "Ellenőrzések",
            "check_cols": ["Azonosító", "Ellenőrzés", "Státusz", "Részletek", "Blokkol"],
            "delivered": "Kézbesített fájl",
            "pending": "(kézbesítés még nem történt meg)",
        },
        "status": {"ok": "OK", "warn": "figyelmeztetés", "fail": "HIBA", "skipped": "kihagyva"},
        "yes": "igen",
        "no": "nem",
    },
    "en": {
        "badge_ok": "VERIFIED",
        "badge_warn": "WARNING ({n})",
        "badge_fail": "FAILED",
        "basis": "basis",
        "run": "run",
        "spec": "spec v",
        "kelt": "issue date",
        "teljesites": "delivery date",
        "measure": "Measure",
        "cur": "Current",
        "prior": "Prior",
        "mom": "MoM%",
        "py": "Prior year",
        "yoy": "YoY%",
        "ytd": "YTD",
        "ytd_py": "YTD PY",
        "ytd_pct": "YTD%",
        "aging": "Aging",
        "amount": "Amount",
        "count": "count",
        "share": "Share",
        "total": "Total",
        "vat_rate": "VAT rate",
        "net": "Net",
        "vat": "VAT",
        "gross": "Gross",
        "top": "Top-{n} customers",
        "cum": "Cum.",
        "trend": "Trend (6 mo)",
        "exceptions": "Exceptions ({shown}/{total}, full list: {sheet} sheet)",
        "exceptions_all": "Exceptions ({shown})",
        "exc_type": "Type",
        "exc_invoice": "Invoice",
        "exc_customer": "Customer",
        "exc_amount": "Amount",
        "exc_note": "Days / note",
        "foot1": (
            "Definitions: revenue by {basis}, {storno}; signed amounts (modifiers and "
            "stornos deducted)."
        ),
        "foot2": (
            "Receivables as of {as_of}, aged by the chain root's due date. Thresholds: {thresholds}"
        ),
        "foot3": (
            "Source: invoicing Agent cache; checks: {ok} OK, {warn} warnings, {fail} failed, "
            "{skipped} skipped. Kit v{kit}."
        ),
        "storno_issue": "storno in its issue month",
        "storno_orig": "storno in the original invoice's month",
        "no_thresholds": "none",
        "def_headers": [
            "measure_id",
            "label_hu",
            "label_en",
            "formula_words",
            "source_fields",
            "filters_applied",
            "threshold_warn",
            "threshold_critical",
        ],
        "runlog": {
            "period": "Period",
            "run_ts": "Run at",
            "spec_version": "Spec version",
            "spec_hash": "Spec hash (sha256)",
            "kit_version": "Kit version",
            "rows": "Rows",
            "checks": "Checks",
            "check_cols": ["Id", "Check", "Status", "Detail", "Blocking"],
            "delivered": "Delivered file",
            "pending": "(not delivered yet)",
        },
        "status": {"ok": "OK", "warn": "warning", "fail": "FAIL", "skipped": "skipped"},
        "yes": "yes",
        "no": "no",
    },
}


def sheet_name(entity: str, language: str) -> str:
    return SHEET_NAMES.get(language, SHEET_NAMES["hu"])[entity]


def expected_sheets(spec: Spec) -> list[str]:
    return [sheet_name(e, spec.output.language) for e in spec.output.sheets]


def expected_tables(spec: Spec) -> list[str]:
    return [f"{spec.output.table_prefix}_{e}" for e in spec.output.sheets if e in TABLE_ENTITIES]


def _num(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _fmt_key(fmt: str | None, profile: str) -> str:
    fmt = fmt or "huf_k"
    if profile == "huf_full" and fmt == "huf_k":
        return "huf"
    return fmt


def _measure_format(spec: Spec, key: str) -> str:
    m = spec.find_measure(key)
    if m is None:
        return _fmt_key(None, spec.output.number_profile)
    if m.format:
        return _fmt_key(m.format, spec.output.number_profile)
    mdef = MEASURES.get(m.id)
    return _fmt_key(mdef.default_format if mdef else None, spec.output.number_profile)


def _measure_label(spec: Spec, key: str, lang: str) -> str:
    m = spec.find_measure(key)
    if m is None:
        return key
    mdef = MEASURES.get(m.id)
    if mdef is None:
        return m.id.split(":", 1)[1] if m.is_custom else m.id
    label = mdef.label_hu if lang == "hu" else mdef.label_en
    if m.params:
        label = f"{label} ({', '.join(f'{k}={v}' for k, v in sorted(m.params.items()))})"
    return label


class _Formats:
    """Lazy xlsxwriter format cache keyed by (num_format, level, bold, size, align, bg)."""

    def __init__(self, wb: xlsxwriter.Workbook):
        self.wb = wb
        self._cache: dict[tuple, object] = {}

    def get(
        self,
        num: str | None = None,
        level: str = "none",
        bold: bool = False,
        size: int = 9,
        align: str | None = None,
        header: bool = False,
        color: str | None = None,
        wrap: bool = False,
    ):
        key = (num, level, bold, size, align, header, color, wrap)
        if key not in self._cache:
            props: dict = {
                "font_name": "Calibri",
                "font_size": size,
                "font_color": color or COLOR_BODY,
                "valign": "vcenter",
            }
            if num:
                props["num_format"] = NUMBER_FORMATS.get(num, num)
            if level == "critical":
                props["font_color"] = COLOR_CRITICAL
            elif level == "warn":
                props["font_color"] = COLOR_WARN
            if bold:
                props["bold"] = True
            if align:
                props["align"] = align
            if header:
                props.update(
                    {
                        "bg_color": COLOR_HEADER_BG,
                        "bottom": 1,
                        "bottom_color": COLOR_BORDER,
                        "bold": True,
                    }
                )
            if wrap:
                props["text_wrap"] = True
            self._cache[key] = self.wb.add_format(props)
        return self._cache[key]


# ---------------------------------------------------------------------------
# Executive sheet
# ---------------------------------------------------------------------------


class _Exec:
    def __init__(
        self,
        wb,
        ws,
        series_ws,
        result: Result,
        spec: Spec,
        period: Period,
        run_info: dict,
        fm: _Formats,
    ):
        self.wb, self.ws, self.series_ws = wb, ws, series_ws
        self.r, self.spec, self.p, self.run_info, self.fm = result, spec, period, run_info, fm
        self.lang = spec.output.language
        self.t = T[self.lang]
        self.profile = spec.output.number_profile
        self.series_row = 1
        self.tile_count = 0
        self.exec_exception_rows = 0

    # -- helpers ----------------------------------------------------------

    def write_num(self, row, col, value, num, level="none", bold=False, size=9):
        v = _num(value)
        fmt = self.fm.get(num=num, level=level, bold=bold, size=size, align="right")
        if v is None:
            self.ws.write_blank(row, col, None, fmt)
        else:
            self.ws.write_number(row, col, v, fmt)

    def write_text(
        self, row, col, text, bold=False, header=False, level="none", size=9, align=None
    ):
        self.ws.write_string(
            row,
            col,
            str(text) if text is not None else "",
            self.fm.get(bold=bold, header=header, level=level, size=size, align=align),
        )

    def header_row(self, row, col, labels):
        for i, lab in enumerate(labels):
            self.write_text(row, col + i, lab, header=True)

    def add_series(self, name: str, values: list[float | None]) -> str:
        """Write one series row to the hidden sheet and return its A1 range."""
        row = self.series_row
        self.series_ws.write_string(row, 0, name)
        for i, v in enumerate(values):
            fv = _num(v)
            if fv is None:
                self.series_ws.write_blank(row, 1 + i, None)
            else:
                self.series_ws.write_number(row, 1 + i, fv)
        self.series_row += 1
        if not values:
            values = [None]
        first = xl_rowcol_to_cell(row, 1, row_abs=True, col_abs=True)
        last = xl_rowcol_to_cell(row, len(values), row_abs=True, col_abs=True)
        return f"'{SERIES_SHEET}'!{first}:{last}"

    def sparkline(self, row, col, rng):
        self.ws.add_sparkline(
            xl_rowcol_to_cell(row, col),
            {
                "range": rng,
                "type": "line",
                "series_color": COLOR_SPARK,
                "high_point": True,
                "high_color": COLOR_TILE,
                "last_point": True,
                "last_color": COLOR_TILE,
                "empty_cells": "gaps",
            },
        )

    def badge(self) -> tuple[str, str]:
        checks = self.run_info.get("checks") or []
        fails = [c for c in checks if getattr(c, "status", None) == "fail"]
        warns = [c for c in checks if getattr(c, "status", None) == "warn"]
        if fails:
            return self.t["badge_fail"], "critical"
        if warns:
            return self.t["badge_warn"].format(n=len(warns)), "warn"
        return self.t["badge_ok"], "none"

    # -- blocks -----------------------------------------------------------

    def block_title(self, row: int) -> int:
        spec, p, t = self.spec, self.p, self.t
        title = (
            spec.report.title_hu
            if self.lang == "hu"
            else (spec.report.title_en or spec.report.title_hu)
        )
        self.ws.merge_range(
            0, LEFT_COL, 0, 13, title, self.fm.get(bold=True, size=12, color=COLOR_TILE)
        )
        badge, level = self.badge()
        self.ws.merge_range(
            0, 15, 0, 20, badge, self.fm.get(bold=True, size=10, level=level, align="right")
        )
        end_note = (
            f" ({p.start.isoformat()} .. {p.end.isoformat()})"
            if p.to_date or p.grain in ("custom", "ytd")
            else ""
        )
        sub = (
            f"{p.label}{end_note} · {t['basis']}: {t[spec.period.basis]} · {t['run']} "
            f"{self.run_info.get('run_ts', '')} · {t['spec']}{spec.report.version}"
        )
        self.write_text(1, LEFT_COL, sub, size=9)
        return 2

    def block_tiles(self, row: int) -> int:
        tiles = self.spec.output.executive.tiles[:MAX_TILES]
        if not tiles:
            return row
        r = self.r
        history = [s.strftime("%Y-%m") for s, _ in self.p.history()]
        for i, key in enumerate(tiles):
            col = TILE_COLS[i]
            num = _measure_format(self.spec, key)
            level = r.level(key)
            self.write_text(row, col, _measure_label(self.spec, key, self.lang), bold=True)
            self.write_num(row + 1, col, r.value(key), num, level=level, bold=True, size=14)
            m = self.spec.find_measure(key)
            comps = (
                m.comparisons
                if (m and m.comparisons is not None)
                else list(
                    MEASURES[m.id].default_comparisons if m and m.id in MEASURES else ("mom", "yoy")
                )
            )
            mrow = r.measures[
                (r.measures["measure_id"] == key) & (r.measures["dim_name"] == "total")
            ]
            parts = []
            if len(mrow):
                mom, yoy = _num(mrow["mom_pct"].iloc[0]), _num(mrow["yoy_pct"].iloc[0])
                if "mom" in comps:
                    parts.append(f"MoM {mom:+.1%}" if mom is not None else "MoM n.a.")
                if "yoy" in comps:
                    parts.append(f"YoY {yoy:+.1%}" if yoy is not None else "YoY n.a.")
            self.write_text(row + 2, col, " · ".join(parts), size=8, level=level)
            ser = r.series[r.series["measure_id"] == key].set_index("month")["value"]
            values = [_num(ser.get(mth)) for mth in history]
            rng = self.add_series(key, values)
            self.sparkline(row + 3, col, rng)
            self.tile_count += 1
        self.ws.set_row(row + 3, 24)
        return row + 5

    def block_variance(self, row: int, col: int) -> int:
        t = self.t
        self.header_row(
            row,
            col,
            [
                t["measure"],
                t["cur"],
                t["prior"],
                t["mom"],
                t["py"],
                t["yoy"],
                t["ytd"],
                t["ytd_py"],
                t["ytd_pct"],
            ],
        )
        r = self.r
        rr = row + 1
        for key in self.spec.output.executive.variance_rows[:9]:
            num = _measure_format(self.spec, key)
            level = r.level(key)
            mrow = r.measures[
                (r.measures["measure_id"] == key) & (r.measures["dim_name"] == "total")
            ]
            vals = mrow.iloc[0] if len(mrow) else {}
            self.write_text(rr, col, _measure_label(self.spec, key, self.lang), level=level)
            self.write_num(rr, col + 1, vals.get("value"), num, level=level)
            self.write_num(rr, col + 2, vals.get("prior"), num)
            self.write_num(rr, col + 3, vals.get("mom_pct"), "delta")
            self.write_num(rr, col + 4, vals.get("prior_year"), num)
            self.write_num(rr, col + 5, vals.get("yoy_pct"), "delta")
            ytd, ytdp = _num(vals.get("ytd")), _num(vals.get("ytd_prior"))
            self.write_num(rr, col + 6, ytd, num)
            self.write_num(rr, col + 7, ytdp, num)
            ytd_pct = (
                (ytd - ytdp) / abs(ytdp) if (ytd is not None and ytdp not in (None, 0)) else None
            )
            self.write_num(rr, col + 8, ytd_pct, "delta")
            rr += 1
        return rr + 1

    def block_ar_aging(self, row: int, col: int) -> int:
        t = self.t
        labels = AGING_LABELS_HU if self.lang == "hu" else AGING_LABELS_EN
        num = _fmt_key("huf_k", self.profile)
        self.header_row(row, col, [t["aging"], t["amount"], t["count"], t["share"]])
        ag = self.r.ar_aging.set_index("bucket")
        rr = row + 1
        total = float(ag["amount"].sum()) if len(ag) else 0.0
        for b in AGING_BUCKETS:
            self.write_text(rr, col, labels[b])
            amt = _num(ag["amount"].get(b)) if b in ag.index else 0.0
            self.write_num(rr, col + 1, amt, num)
            self.write_num(rr, col + 2, ag["count"].get(b) if b in ag.index else 0, "count")
            self.write_num(rr, col + 3, ag["share"].get(b) if b in ag.index else None, "pct")
            rr += 1
        first, last = xl_rowcol_to_cell(row + 1, col + 1), xl_rowcol_to_cell(rr - 1, col + 1)
        self.ws.conditional_format(
            f"{first}:{last}",
            {
                "type": "data_bar",
                "bar_color": COLOR_BAR,
                "bar_solid": True,
                "min_type": "num",
                "min_value": 0,
                "max_type": "num",
                "max_value": max(total, 1.0),
                "bar_no_border": True,
            },
        )
        self.write_text(rr, col, t["total"], bold=True)
        self.write_num(rr, col + 1, total, num, bold=True)
        self.write_num(rr, col + 2, int(ag["count"].sum()) if len(ag) else 0, "count", bold=True)
        return rr + 2

    def block_vat_summary(self, row: int, col: int) -> int:
        t = self.t
        num = _fmt_key("huf_k", self.profile)
        self.header_row(row, col, [t["vat_rate"], t["net"], t["vat"], t["gross"]])
        rr = row + 1
        vs = self.r.vat_summary
        for rec in vs.itertuples():
            rate = str(rec.vat_rate)
            self.write_text(rr, col, f"{rate}%" if rate.isdigit() else rate)
            self.write_num(rr, col + 1, rec.net_huf, num)
            self.write_num(rr, col + 2, rec.vat_huf, num)
            self.write_num(rr, col + 3, rec.gross_huf, num)
            rr += 1
        self.write_text(rr, col, t["total"], bold=True)
        self.write_num(rr, col + 1, vs["net_huf"].sum() if len(vs) else 0, num, bold=True)
        self.write_num(rr, col + 2, vs["vat_huf"].sum() if len(vs) else 0, num, bold=True)
        self.write_num(rr, col + 3, vs["gross_huf"].sum() if len(vs) else 0, num, bold=True)
        return rr + 2

    def block_top_customers(self, row: int, col: int) -> int:
        t = self.t
        num = _fmt_key("huf_k", self.profile)
        n = self.spec.output.executive.top_n
        self.header_row(
            row, col, [t["top"].format(n=n), "", t["net"], t["share"], t["cum"], "MoM", t["trend"]]
        )
        rr = row + 1
        months = [s.strftime("%Y-%m") for s, _ in self.p.history()[-6:]]
        ts = self.r.top_series
        for rec in self.r.top_customers.itertuples():
            self.write_text(rr, col, rec.name)
            self.write_num(rr, col + 2, rec.net, num)
            self.write_num(rr, col + 3, rec.share, "pct")
            self.write_num(rr, col + 4, rec.cum_share, "pct")
            self.write_num(rr, col + 5, rec.mom_pct, "delta")
            ser = ts[ts["name"] == rec.name].set_index("month")["value"]
            rng = self.add_series(f"top:{rec.name}", [_num(ser.get(mth)) for mth in months])
            self.sparkline(rr, col + 6, rng)
            rr += 1
        if rr > row + 1:
            first, last = xl_rowcol_to_cell(row + 1, col + 5), xl_rowcol_to_cell(rr - 1, col + 5)
            self.ws.conditional_format(
                f"{first}:{last}", {"type": "icon_set", "icon_style": "3_arrows_gray"}
            )
        return rr + 1

    def block_exceptions(self, row: int, col: int) -> int:
        t = self.t
        exc = self.r.exceptions
        total = int(sum(self.r.exception_totals.values()))
        shown = min(len(exc), MAX_EXEC_EXCEPTIONS)
        if total > shown:
            title = t["exceptions"].format(
                shown=shown, total=total, sheet=sheet_name("exceptions", self.lang)
            )
        else:
            title = t["exceptions_all"].format(shown=shown)
        self.write_text(row, col, title, bold=True)
        self.header_row(
            row + 1,
            col,
            [
                t["exc_type"],
                t["exc_invoice"],
                t["exc_customer"],
                "",
                t["exc_amount"],
                t["exc_note"],
            ],
        )
        rr = row + 2
        for rec in exc.head(MAX_EXEC_EXCEPTIONS).itertuples():
            level = rec.severity if rec.severity in ("critical", "warn") else "none"
            self.write_text(rr, col, rec.rule_id, level=level)
            self.write_text(rr, col + 1, rec.invoice_number, level=level)
            self.write_text(rr, col + 2, rec.customer, level=level)
            self.write_num(rr, col + 4, rec.amount, "huf", level=level)
            days = _num(rec.days)
            note = f"{int(days)} nap · {rec.note}" if days is not None else str(rec.note or "")
            self.write_text(rr, col + 5, note, level=level)
            rr += 1
            self.exec_exception_rows += 1
        return rr + 1

    def block_footnote(self, row: int) -> int:
        t, spec, p = self.t, self.spec, self.p
        storno = (
            t["storno_orig"]
            if spec.period.storno_attribution == "original_month"
            else t["storno_issue"]
        )
        thr = (
            ", ".join(
                f"{k}: {'/'.join(str(x) for x in (v.warn, v.critical) if x is not None)}"
                for k, v in spec.thresholds.items()
            )
            or t["no_thresholds"]
        )
        checks = self.run_info.get("checks") or []
        counts = {
            s: sum(1 for c in checks if getattr(c, "status", None) == s)
            for s in ("ok", "warn", "fail", "skipped")
        }
        self.write_text(
            row, LEFT_COL, t["foot1"].format(basis=t[spec.period.basis], storno=storno), size=8
        )
        self.write_text(
            row + 1, LEFT_COL, t["foot2"].format(as_of=p.as_of.isoformat(), thresholds=thr), size=8
        )
        self.write_text(
            row + 2,
            LEFT_COL,
            t["foot3"].format(kit=self.run_info.get("kit_version", ""), **counts),
            size=8,
        )
        return row + 3

    # -- layout -----------------------------------------------------------

    def write(self) -> None:
        ws = self.ws
        ws.set_column(0, 0, 2)
        ws.set_column(1, 20, 9)
        ws.set_column(LAST_COL, LAST_COL, 2)
        ws.set_default_row(15)
        ws.freeze_panes(2, 0)
        ws.set_landscape()
        ws.set_paper(9)
        ws.fit_to_pages(1, 1)
        ws.set_margins(0.2, 0.2, 0.3, 0.3)
        ws.hide_gridlines(2)
        ws.set_zoom(100)

        blocks = list(self.spec.output.executive.blocks)
        self.block_title(0)
        row = 3
        if "tiles" in blocks:
            row = self.block_tiles(row)
        left = right = row
        for b in blocks:
            if b == "variance":
                left = self.block_variance(left, LEFT_COL)
            elif b == "top_customers":
                left = self.block_top_customers(left, LEFT_COL)
            elif b == "ar_aging":
                right = self.block_ar_aging(right, RIGHT_COL)
            elif b == "vat_summary":
                right = self.block_vat_summary(right, RIGHT_COL)
            elif b == "exceptions":
                right = self.block_exceptions(right, RIGHT_COL)
        end = max(left, right)
        if "footnote" in blocks:
            end = self.block_footnote(end)
        ws.print_area(0, 0, max(end - 1, 0), LAST_COL)


# ---------------------------------------------------------------------------
# Data sheets
# ---------------------------------------------------------------------------


def _col_num_format(col: str) -> str | None:
    if col.endswith("_huf") or col in ("open_huf", "amount_huf", "rev_net_12m"):
        return "huf"
    if col.endswith("_pct") or col in ("share", "share_12m", "cum_share"):
        return "pct"
    if col in (
        "net",
        "vat",
        "gross",
        "net_amount",
        "vat_amount",
        "gross_amount",
        "amount",
        "unit_price",
        "value",
        "prior",
        "prior_year",
        "ytd",
        "ytd_prior",
        "avg3m",
    ):
        return "#,##0.00"
    return None


def _cell_value(v):
    if v is None:
        return None
    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if hasattr(v, "item"):
        try:
            v = v.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def write_table(ws, name: str, df: pd.DataFrame, fm: _Formats) -> None:
    cols = [str(c) for c in df.columns]
    records = [[_cell_value(v) for v in row] for row in df.itertuples(index=False, name=None)]
    if not records:
        records = [[None] * len(cols)]
    widths = [max(len(c), 8) for c in cols]
    for rec in records:
        for i, v in enumerate(rec):
            if v is not None:
                widths[i] = max(widths[i], min(len(str(v)), 40))
    columns = []
    for c in cols:
        num = _col_num_format(c)
        entry: dict = {"header": c}
        if num:
            entry["format"] = fm.get(num=num)
        columns.append(entry)
    ws.add_table(
        0,
        0,
        len(records),
        len(cols) - 1,
        {
            "name": name,
            "columns": columns,
            "data": records,
            "autofilter": True,
            "style": "Table Style Light 1",
        },
    )
    for i, w in enumerate(widths):
        ws.set_column(i, i, w + 2)
    ws.freeze_panes(1, 0)


def _invoice_table(frames: Frames, result: Result) -> pd.DataFrame:
    inv = frames.invoice.copy()
    ts = pd.Timestamp(frames.as_of)
    inv["open_huf"] = (inv["gross_huf"] - inv["paid_huf"]).round(2)
    days = (ts - inv["due_date"]).dt.days
    inv["days_overdue"] = days.where((days > 0) & (inv["open_huf"] > 0), 0).fillna(0).astype(int)
    cols = [
        "invoice_number",
        "chain_root",
        "doc_type",
        "modification_index",
        "customer_key",
        "customer_name",
        "issue_date",
        "delivery_date",
        "due_date",
        "period_kelt",
        "period_telj",
        "period_month",
        "currency",
        "fx_rate_invoice",
        "net_amount",
        "vat_amount",
        "gross_amount",
        "net_huf",
        "vat_huf",
        "gross_huf",
        "paid_huf",
        "open_huf",
        "pay_status",
        "payment_method",
        "is_einvoice",
        "days_overdue",
    ]
    return inv[cols]


def _customer_table(frames: Frames, result: Result) -> pd.DataFrame:
    inv = frames.invoice
    start = pd.Timestamp(month_start(frames.as_of)) - pd.DateOffset(months=11)
    last12 = inv[(inv["basis_date"] >= start) & (inv["basis_date"] <= pd.Timestamp(frames.as_of))]
    rev = last12.groupby("customer_key")["net_huf"].sum()
    total = float(rev.sum()) or None
    open_by = (
        result.ar.groupby("customer_key")["open_huf"].sum()
        if len(result.ar)
        else pd.Series(dtype=float)
    )
    c = frames.customer.copy()
    c["rev_net_12m"] = c["customer_key"].map(rev).fillna(0.0)
    c["share_12m"] = c["rev_net_12m"] / total if total else None
    c["open_huf"] = c["customer_key"].map(open_by).fillna(0.0)
    return c[
        [
            "customer_key",
            "name",
            "tax_number",
            "country",
            "is_private",
            "first_invoice_date",
            "last_invoice_date",
            "rev_net_12m",
            "share_12m",
            "open_huf",
        ]
    ]


def _measure_table(result: Result, spec: Spec) -> pd.DataFrame:
    m = result.measures.copy()
    keep = m["dim_name"].isin(["total", "bucket"]) | m["dim_name"].isin(spec.dimensions)
    m = m[keep].copy()
    levels = (
        dict(zip(result.thresholds["measure_id"], result.thresholds["level"], strict=False))
        if len(result.thresholds)
        else {}
    )
    m["status"] = (
        m["measure_id"]
        .map(lambda k: levels.get(k, "ok" if k not in levels else levels[k]))
        .replace({"none": "ok"})
    )
    return m


def _line_table(frames: Frames) -> pd.DataFrame:
    return frames.line[
        [
            "invoice_number",
            "line_no",
            "product_name",
            "quantity",
            "unit",
            "unit_price",
            "vat_rate",
            "net",
            "vat",
            "gross",
            "net_huf",
            "vat_huf",
            "ledger_code",
        ]
    ]


def _payment_table(frames: Frames) -> pd.DataFrame:
    return frames.payment[
        [
            "payment_id",
            "invoice_number",
            "pay_date",
            "pay_type",
            "amount",
            "currency",
            "amount_huf",
            "bank_account",
            "note",
        ]
    ]


def entity_frame(entity: str, result: Result, frames: Frames, spec: Spec) -> pd.DataFrame:
    if entity == "invoice":
        return _invoice_table(frames, result)
    if entity == "line":
        return _line_table(frames)
    if entity == "payment":
        return _payment_table(frames)
    if entity == "customer":
        return _customer_table(frames, result)
    if entity == "measure":
        return _measure_table(result, spec)
    if entity == "exceptions":
        return result.exceptions
    raise KeyError(entity)


def _write_definitions(ws, spec: Spec, frames: Frames, fm: _Formats, lang: str) -> None:
    headers = T[lang]["def_headers"]
    for i, h in enumerate(headers):
        ws.write_string(0, i, h, fm.get(header=True))
    filters = "; ".join(frames.filters_hu)
    for r, m in enumerate(spec.measures, start=1):
        mdef = MEASURES.get(m.id)
        thr = spec.thresholds.get(m.key) or spec.thresholds.get(m.id)
        row = [
            m.key,
            mdef.label_hu if mdef else m.id,
            mdef.label_en if mdef else m.id,
            mdef.formula_words if mdef else f"egyedi képlet: {m.formula}",
            mdef.source_fields if mdef else "",
            filters,
            thr.warn if thr else None,
            thr.critical if thr else None,
        ]
        for c, v in enumerate(row):
            if v is None:
                ws.write_blank(r, c, None)
            elif isinstance(v, (int, float)):
                ws.write_number(r, c, float(v))
            else:
                ws.write_string(r, c, str(v), fm.get(wrap=c == 3))
    ws.set_column(0, 2, 24)
    ws.set_column(3, 3, 80)
    ws.set_column(4, 5, 40)
    ws.set_column(6, 7, 14)
    ws.freeze_panes(1, 0)


def _write_runlog(ws, spec: Spec, period: Period, run_info: dict, fm: _Formats, lang: str) -> None:
    t = T[lang]["runlog"]
    st = T[lang]["status"]
    rows = [
        (t["period"], period.label),
        (t["run_ts"], run_info.get("run_ts", "")),
        (t["spec_version"], spec.report.version),
        (t["spec_hash"], run_info.get("spec_hash", "")),
        (t["kit_version"], run_info.get("kit_version", "")),
    ]
    for k, v in (run_info.get("row_counts") or {}).items():
        rows.append((f"{t['rows']}: {k}", v))
    r = 0
    for k, v in rows:
        ws.write_string(r, 0, k, fm.get(bold=True))
        if isinstance(v, (int, float)):
            ws.write_number(r, 1, float(v))
        else:
            ws.write_string(r, 1, str(v))
        r += 1
    r += 1
    ws.write_string(r, 0, t["checks"], fm.get(bold=True))
    r += 1
    for i, h in enumerate(t["check_cols"]):
        ws.write_string(r, i, h, fm.get(header=True))
    r += 1
    for c in run_info.get("checks") or []:
        level = "critical" if c.status == "fail" else ("warn" if c.status == "warn" else "none")
        ws.write_string(r, 0, c.id, fm.get(level=level))
        ws.write_string(r, 1, c.title_hu, fm.get(level=level))
        ws.write_string(r, 2, st.get(c.status, c.status), fm.get(level=level, bold=True))
        ws.write_string(r, 3, c.detail_hu or "", fm.get(level=level))
        ws.write_string(r, 4, T[lang]["yes"] if c.blocking else T[lang]["no"])
        r += 1
    r += 1
    ws.write_string(r, 0, t["delivered"], fm.get(bold=True))
    ws.write_string(r, 1, str(run_info.get("delivered_path") or t["pending"]))
    ws.set_column(0, 0, 26)
    ws.set_column(1, 1, 40)
    ws.set_column(2, 2, 14)
    ws.set_column(3, 3, 90)


# ---------------------------------------------------------------------------
# Workbook
# ---------------------------------------------------------------------------


def write_workbook(
    result: Result,
    spec: Spec,
    period: Period,
    out_path: Path | str,
    run_info: dict,
    frames: Frames | None = None,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lang = spec.output.language if spec.output.language in SHEET_NAMES else "hu"
    wb = xlsxwriter.Workbook(str(out_path), {"nan_inf_to_errors": True})
    wb.set_properties(
        {
            "title": spec.report.title_hu,
            "subject": period.label,
            "comments": f"spec v{spec.report.version}",
        }
    )
    fm = _Formats(wb)
    sheets: dict[str, object] = {}
    for entity in spec.output.sheets:
        sheets[entity] = wb.add_worksheet(sheet_name(entity, lang))
    series_ws = wb.add_worksheet(SERIES_SHEET)
    series_ws.hide()

    if "executive" in sheets:
        _Exec(wb, sheets["executive"], series_ws, result, spec, period, run_info, fm).write()
    for entity in spec.output.sheets:
        ws = sheets[entity]
        if entity in TABLE_ENTITIES:
            if frames is None and entity in ("invoice", "line", "payment", "customer"):
                df = pd.DataFrame()
            else:
                df = (
                    entity_frame(entity, result, frames, spec)
                    if frames is not None
                    else result.exceptions
                    if entity == "exceptions"
                    else _measure_table(result, spec)
                )
            write_table(ws, f"{spec.output.table_prefix}_{entity}", df, fm)
        elif entity == "definitions":
            _write_definitions(
                ws,
                spec,
                frames
                if frames is not None
                else Frames(
                    pd.DataFrame(),
                    pd.DataFrame(),
                    pd.DataFrame(),
                    pd.DataFrame(),
                    pd.DataFrame(),
                    period.as_of,
                    spec.period.basis,
                ),
                fm,
                lang,
            )
        elif entity == "runlog":
            _write_runlog(ws, spec, period, run_info, fm, lang)
    wb.close()
    return out_path


# ---------------------------------------------------------------------------
# Power BI CSV export
# ---------------------------------------------------------------------------


def _powerbi_frame(name: str, result: Result, frames: Frames, spec: Spec) -> pd.DataFrame:
    inv = frames.invoice
    as_of = frames.as_of
    if name == "fact_invoice":
        df = _invoice_table(frames, result).copy()
        df["as_of_date"] = as_of.isoformat()
        df = df.drop(columns=["customer_name", "modification_index", "period_month"])
        return df.sort_values("invoice_number")
    if name == "fact_invoice_line":
        return _line_table(frames).sort_values(["invoice_number", "line_no"])
    if name == "fact_payment":
        return (
            _payment_table(frames)
            .drop(columns=["bank_account", "note"])
            .sort_values(["payment_id"])
        )
    if name == "fact_measure":
        m = _measure_table(result, spec)
        return (
            m[
                [
                    "period_label",
                    "measure_id",
                    "dim_name",
                    "dim_value",
                    "value",
                    "prior",
                    "prior_year",
                    "ytd",
                    "ytd_prior",
                    "mom_pct",
                    "yoy_pct",
                    "avg3m",
                    "status",
                ]
            ]
            .rename(columns={"period_label": "period"})
            .sort_values(["measure_id", "dim_name", "dim_value"])
        )
    if name == "dim_customer":
        c = _customer_table(frames, result).copy()
        c["segment"] = pd.cut(
            c["share_12m"].fillna(0.0), bins=[-1, 0.01, 0.05, 0.2, 2], labels=["D", "C", "B", "A"]
        ).astype(str)
        return c.drop(columns=["rev_net_12m", "share_12m", "open_huf"]).sort_values("customer_key")
    if name == "dim_date":
        start = month_start(inv["basis_date"].min().date()) if len(inv) else month_start(as_of)
        return calendar_frame(start, max(as_of, start), spec.period.fiscal_year_start_month)
    raise KeyError(name)


def write_powerbi_csvs(
    result: Result, frames: Frames, spec: Spec, folder: Path | str
) -> list[Path]:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name in spec.powerbi.files:
        df = _powerbi_frame(name, result, frames, spec).copy()
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = df[col].dt.strftime("%Y-%m-%d")
        target = folder / f"{name}.csv"
        df.to_csv(
            target, index=False, encoding="utf-8-sig", lineterminator="\n", float_format="%.2f"
        )
        written.append(target)
    return written


__all__ = [
    "write_workbook",
    "write_powerbi_csvs",
    "sheet_name",
    "expected_sheets",
    "expected_tables",
    "entity_frame",
    "SHEET_NAMES",
    "TABLE_ENTITIES",
    "SERIES_SHEET",
    "MAX_EXEC_EXCEPTIONS",
    "NUMBER_FORMATS",
    "TILE_COLS",
]
