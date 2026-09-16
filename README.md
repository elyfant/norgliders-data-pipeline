# norgliders-data-pipeline

**Norgliders Data Pipeline**

An open-source, realtime and delayed-mode processing pipeline for glider data at the NorGliders facility.

The project automates the journey from raw telemetry to community-standard scientific data products, and is designed to be robust, reproducible, and extensible. Rather than reimplementing what already exists, norgliders-data-pipeline is our pipeline in the sense of *orchestration*: it links together established, community-maintained tools — `pyglider` for decoding and concatenation of raw data, the `OG1` NetCDF format as the shared output standard, and `pelagos_py` for corrections and QC — with the mission resolution, triggering, database bookkeeping, and NMDC delivery logic that is ours.

Currently this repo is only set up for Slocum gliders. Our Seaglider processing is handled separately, via IOP-supplied BS3 tooling. norgliders-data-pipeline mirrors that structure where practical, so both converge on the same OG1 output and are subject to the same corrections and QC controls, whether automated or manual. See [Current Scope](#current-scope) for details.

> **Project Status:** 🚧 Early development

---

## Vision

norgliders-data-pipeline is a complete processing pipeline for the NorGliders facility. Our fleet is made up of Slocum and Seagliders, but the operational outline may be of use to other glider operators too. This includes:

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

norgliders-data-pipeline follows several core principles:

* **Raw data is immutable.**

  * The raw archive is never modified.

* **Derived products are reproducible.**

  * All processing outputs can be regenerated from the raw archive.

* **Community standards first.**

  * Use established tools and standards wherever practical (e.g. PyGlider, OG1, pelagos_py).

* **Small, composable components.**

  * Each module has a single responsibility.

* **NRT and delayed-mode share one processing core.**

  * Pyglider's decode/concatenate step doesn't know or care whether it's running in realtime or delayed mode — only *what triggers it* and *how complete the raw data is* differs. `python/src/norgliders_data_pipeline/processing/` is that shared core; `nrt/` and `delayed/` are thin triggers into it.

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

The current focus is **near-real-time processing**, with delayed-mode processing starting now on the same pyglider-based processing core (see `python/src/norgliders_data_pipeline/processing/`) — the two share decode/concatenate logic and differ only in what triggers them and how complete the raw data is at that point.

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
* pelagos_py integration
* Database integration (OGDB)
* Parquet mission products
* Battery endurance analysis
* Mission reporting
* NMDC integration

---

## Repository Structure

```text
norgliders-data-pipeline/

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
* OG1 export
* Quality control - pelagos_py
* Database integration
* Analytics

---

## Documentation

Project documentation is located in the `docs/` directory.

Architecture decisions are recorded as Architecture Decision Records (ADRs), allowing the reasoning behind major design choices to be preserved alongside the code.

---

## Contributing

norgliders-data-pipeline is being developed as an open-source project.

Contributions, suggestions, bug reports, and discussions are welcome as the project matures.

---

## License

License to be determined.
