# slocum_data_processing

**Slocum Data Processing**

An open-source realtime and delayed-mode processing pipeline for Slocum autonomous ocean gliders.

The project automates the journey from telemetry to community-standard scientific data products. It is designed to be robust, reproducible, and extensible, building upon established community tools wherever possible instead of reimplementing existing solutions.

> **Project Status:** 🚧 Early development

---

## Vision

slocum_data_processing aims to provide a complete processing pipeline for Slocum gliders, including:

* Realtime data ingestion
* Automated processing (near-real-time and delayed-mode)
* Quality control
* Community-standard data products
* Database integration
* Mission analytics
* Open and reproducible workflows

The project is being developed with scientific transparency, operational robustness, and long-term maintainability as primary design goals.

---

## Design Principles

slocum_data_processing follows several core principles:

* **Raw data is immutable.**

  * The raw archive is never modified.

* **Derived products are reproducible.**

  * All processing outputs can be regenerated from the raw archive.

* **Community standards first.**

  * Use established tools and standards wherever practical (e.g. PyGlider, OG1).

* **Small, composable components.**

  * Each module has a single responsibility.

* **NRT and delayed-mode share one processing core.**

  * Pyglider's decode/concatenate step doesn't know or care whether it's running in realtime or delayed mode — only *what triggers it* and *how complete the raw data is* differs. `python/src/slocum_data_processing/processing/` is that shared core; `nrt/` and `delayed/` are thin triggers into it.

* **Operational robustness over optimisation.**

  * Reliability and recoverability are prioritised over maximum performance.

* **Automation by default.**

  * Minimise manual intervention from data acquisition through to product generation.

---

## High-Level Architecture

```text
                 SFMC
                   │
                   ▼
        Realtime Event Listener
                   │
                   ▼
                 rsync
                   │
                   ▼
          Realtime Raw Archive
                   │
                   ▼
           Mission Resolution
                   │
                   ▼
             Processing Pipeline  ◄── shared by NRT + delayed-mode triggers
                   │
      ┌────────────┼────────────┐
      ▼            ▼            ▼
   QC & Corrections OG1 Export Database
                   │
                   ▼
          Mission Products
```

The ingestion layer is intentionally lightweight. Its responsibility is to safely mirror realtime data from the glider communication server into the local raw archive.

Scientific processing is performed as an independent stage.

---

## Current Scope

The current focus is **near-real-time processing**, with delayed-mode processing starting now on the same pyglider-based processing core (see `python/src/slocum_data_processing/processing/`) — the two share decode/concatenate logic and differ only in what triggers them and how complete the raw data is at that point.

This includes:

* SFMC event monitoring
* Automated rsync synchronisation
* Realtime and delayed-mode processing
* Mission management
* OG1 product generation
* Operational analytics

---

## Planned Features

* Realtime ingestion service
* Mission processing pipeline (NRT + delayed-mode)
* PyGlider integration
* Automated QC framework
* Thermal lag correction
* Database integration (OGDB)
* Parquet mission products
* Battery endurance analysis
* Mission reporting
* NMDC integration

---

## Repository Structure

```text
slocum_data_processing/

├── config/
├── docs/
├── examples/
├── js/
├── python/
├── scripts/
├── tests/
└── docker/
```

The repository contains source code, documentation, configuration templates, and tests only.

Mission data, raw archives, and generated products are intentionally stored outside the repository.

---

## Technology Stack

### JavaScript / Node.js

* SFMC event listener
* Realtime ingestion
* rsync orchestration

#### Prerequisites

The ingestion service depends on the Teledyne SFMC Node.js SDK.

This SDK is **not distributed with this repository** and must be obtained separately as part of the Teledyne SFMC installation.

Once installed, update `js/package.json` (or your local configuration) to point to the location of `sfmc.tgz`.

See `docs/user-guide/sfmc-installation.md` for details.


### Python

* Processing pipeline (NRT + delayed-mode, shared core)
* PyGlider integration
* Quality control
* OG1 export
* Database integration
* Analytics

---

## Documentation

Project documentation is located in the `docs/` directory.

Architecture decisions are recorded as Architecture Decision Records (ADRs), allowing the reasoning behind major design choices to be preserved alongside the code.

### Cross-project context

Facility-level architecture/planning lives in a separate repo,
`~/projects/norgliders` (not this one — see its `CLAUDE.md` for why).
Claude Code doesn't share memory across separate git repos, so a session
started here has no way to know about decisions made there without help.

Fix: a symlink into `.claude/rules/`, which Claude Code loads automatically
every session. It's gitignored (machine-local, points at an absolute path
that only resolves on this machine) — recreate it after a fresh clone or on
a new machine:

```bash
mkdir -p .claude/rules
ln -s ~/projects/norgliders/dependencies.md .claude/rules/norgliders-dependencies.md
ln -s ~/projects/norgliders/decisions .claude/rules/norgliders-decisions
```

---

## Contributing

slocum_data_processing is being developed as an open-source project.

Contributions, suggestions, bug reports, and discussions are welcome as the project matures.

---

## License

License to be determined.
