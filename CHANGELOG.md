# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-09-06

### Added

- Invoice data layer: szamlazz.hu Számla Agent and NAV Online Számla 3.0 clients
  with incremental sync into an append only SQLite cache and rebuildable
  canonical tables.
- Secrets read from the OS credential store (Windows Credential Manager via
  `keyring`); nothing sensitive lives in the repo.
- Report specification format `reports/<slug>/spec.yaml` with schema, defaults
  and a validation CLI.
- Report engine: measure catalogue, period resolution and frame computation.
- Excel writer (xlsxwriter) with an accompanying Power BI CSV export.
- Validation checks V01 to V16, staged delivery (build into `.staging/`, then
  move) and a per report run log.
- `run_reports.py` batch runner over every report, wired as the Task Scheduler
  entry point.
- Six skills: `report-new`, `report-run`, `report-edit`, `report-list`,
  `level-up`, `draft-email`.
- Five agents: `report-analyst`, `report-engineer`, `report-reviewer`,
  `gmail-utility`, `web-researcher`.
- Four hooks (`prime_nudge`, `session_tips`, `protect_delivery`,
  `memory_backup`), Python standard library only and fail open.
- Windows installer set: `install.bat`, idempotent `install.ps1` with `-WhatIf`,
  `update.ps1`, `doctor.ps1`, manifest driven copy with backups, non destructive
  `settings.json` merge and per level MCP registration including Gmail multi
  account OAuth.
- `Riportok` project scaffold with `/prime`, four example report specs and three
  level onboarding rules; every string the controller reads is Hungarian.
