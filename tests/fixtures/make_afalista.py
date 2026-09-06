# /// script
# requires-python = ">=3.12"
# dependencies = ["openpyxl>=3.1"]
# ///
"""Generate tests/fixtures/afalista_sample.xlsx (Áfalista export look-alike).

Run: uv run tests/fixtures/make_afalista.py
Header labels are the maintainer's best guess (see docs/DATA-NOTES.md); the rows match the
Agent fixtures SZLA-2026-1 and SZLA-2026-3 exactly, so an import + reconcile is clean.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl

HEADERS = [
    "Számlaszám",
    "Típus",
    "Hivatkozási szám",
    "Vevő neve",
    "Adószáma",
    "EU adószáma",
    "Számla kiállításának dátuma",
    "Teljesítési dátum",
    "Fizetési határidő",
    "Nettó ár",
    "Áfa",
    "Bruttó ár",
    "Devizanem",
    "Fizetési mód",
    "27% alap",
    "27% áfa",
    "5% alap",
    "5% áfa",
    "AAM alap",
    "AAM áfa",
    "EU alap",
    "EU áfa",
]

ROWS = [
    [
        "SZLA-2026-1",
        "számla",
        None,
        "Alfa Ügyfél Zrt.",
        "23456789-2-41",
        None,
        "2026.08.05.",
        "2026.08.05.",
        "2026.08.20.",
        120000,
        28000,
        148000,
        "Ft",
        "Átutalás",
        100000,
        27000,
        20000,
        1000,
        None,
        None,
        None,
        None,
    ],
    [
        "SZLA-2026-3",
        "számla",
        None,
        "Béta Bt.",
        "34567890-1-03",
        None,
        "2026.08.10.",
        "2026.08.10.",
        "2026.08.10.",
        50000,
        13500,
        63500,
        "Ft",
        "Készpénz",
        50000,
        13500,
        None,
        None,
        None,
        None,
        None,
        None,
    ],
    [
        None,
        "Összesen",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        170000,
        41500,
        211500,
        None,
        None,
        150000,
        40500,
        20000,
        1000,
        None,
        None,
        None,
        None,
    ],
]


def main() -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Áfalista"
    ws.append(["Áfalista 2026.08. (teljesítés szerint)"])
    ws.append(HEADERS)
    for row in ROWS:
        ws.append(row)
    out = Path(__file__).with_name("afalista_sample.xlsx")
    wb.save(out)
    print(f"written: {out}")


if __name__ == "__main__":
    main()
