# Stage 2 Initial Audit Report

Audit time: 2026-11-16  
Project: `/Users/bistupaul/Movies/DISSERTATION`  
GitHub: `bistu28/DSR-MANET-Routing-Selection`

## Executive status

**Stage 2 remains IN PROGRESS and is blocked before instrumentation regression.** The 180-row experiment matrix is present and structurally unique, but the stated immutable Stage 1 aggregates, dated recovery manifests, validated Stage 2 pilots, in-repository DSR patch, and Colab environment are not present in the locations inspected. Do not start the full matrix or claim Stage 1/2 completion based on older partial data.

The current-status claims in the execution request are recorded as claims, not independently verified facts. In particular, a Drive batch summary from 2026-11-01 conflicts with the asserted `180/180` validation status.

## Local project

- Branch `main` is at `6232193cac952abaf306ba27442845e1eb3451c5`, tracking `origin/main`.
- All 249 Git-tracked paths exist locally. Git status at audit time: `.DS_Store` modified; `INFRASTRUCTURE_AUDIT/`, `STAGE2_PROGRESS_LOG.md`, and `STAGE2_TODO.md` are untracked; no staged changes.
- The three LFS objects are checked out. Their exact sizes and SHA-256 values were verified during the approved recovery and `git lfs fsck --objects` passed.
- Present legacy data includes `data/mobility/Mobility_data.csv`, `data/topology/Topology_data.csv`, validation step batches, and the 180-row matrix. These are not substitutes for the missing dated validated aggregates.
- The following user-specified Stage 1 files are absent:
  - `data/mobility/Mobility_data_180_validated.csv.gz`
  - `data/topology/Topology_data_180_validated.csv.gz`
  - `data/validation/mobility_trace_inventory_20261114.json`
  - `data/validation/mobility_trace_inventory_20261114.csv`
  - `data/validation/mobility_recovery_manifest_20261114.csv`
  - `data/validation/stage1_aggregate_recovery_20261114.json`
- Local `data/validation/step_1_2_3_validation.json` describes only five mobility scenarios and one topology scenario. The older `full_data_audit.json` similarly marks mobility/topology partial and DSR routing/final ML data missing.
- No local `colab/` folder, `ns3/dsr_instrumentation/`, DSR event JSONL, PCAP/PCAPNG, or Python test suite was found. One older notebook exists at `ml/dataset_generation_colab.ipynb`; existing `setup_colab.sh` and `run_colab.sh` target ns-3.47.

## Experiment matrix

`data/metadata/Simulation_data.csv` was parsed with Python's CSV reader:

- 180 rows and 180 unique `scenario_id` values; no duplicate IDs.
- 6 node-count groups (`100`, `150`, `200`, `300`, `400`, `500`), 30 scenarios each.
- 5 `random_seed` values and 5 `random_run` values, with 36 rows per value.
- The matrix uses `RandomWaypoint` and `CBR`; further scenario selection must use the actual columns and not assume additional diversity.

This verifies the matrix's row/ID count only. It does not verify simulation outputs or Stage 1 aggregates.

## GitHub

- Read-only GitHub MCP inspection confirmed one unprotected branch (`main`) and two commits. `main` is the same commit as the local checkout.
- The remote `data/mobility` contains only the historical `Mobility_data.csv` LFS pointer plus its README/report. `data/topology` contains the older topology tables and report. The validation tree has older audit/step-batch files, not the named 2026-11-14 aggregate recovery manifests.
- No remote `colab/` or `ns3/dsr_instrumentation/` tree was listed.
- The saved origin is the SSH URL. A prior write-authentication check failed with SSH public-key denial; `gh` is not installed. No commit/push was attempted in this audit.

## Google Drive

- The accessible local desktop-sync mirror is `My Drive/DISSERTATION`. The requested `My Drive/MANET_DISSERTATION` is absent.
- This was a scoped inventory of the historical project and specific validation/mobility/simulation-results folders; it was not a Drive-wide search. The Drive website/API is not authenticated in this session.
- The inspected `data/mobility` folder has a generation report and shortcut stub, not the named 180-scenario aggregate.
- `data/validation/stage1_batch_20261101/batch_summary.json` reports 180 planned, 125 completed, 81 `VERIFIED_EXISTING`, 44 `PASS`, and 55 `FAIL`. The referenced run manifest, terminal log, matrix hash and scenario validation are `.gsheet`/`.gdoc` shortcut files, not their linked contents.
- The targeted Drive results search found only two `.gsheet` shortcut stubs named as route-event outputs; no local PCAP or Stage 2 event JSONL was found in the project results folder.
- No files were moved, copied, uploaded, or deleted.

## External ns-3.48 checkout

- `/Users/bistupaul/ns-3.48` is at tag `ns-3.48`, commit `d2add90`.
- It has modified `dsr-options.cc`, `dsr-rcache.cc`, `dsr-rcache.h`, `dsr-routing.cc`, and `dsr-routing.h`, plus untracked `stage2-dsr-event-sink.h` and an untracked `results/` tree. The Stage 2 scratch driver is ignored by the external checkout's `scratch/.gitignore`; it differs from the older driver in the project.
- The event sink emits JSONL-like records with schema version `dsr_event_v2`, event sequence/time, scenario/run/seed, source/destination, route, packet UID, hook and source provenance. The source hooks cover selected RREQ/RREP/RERR, discovery/cache/recovery events; this is a code-presence observation, not proof of hook completeness or output validity.
- The source diff has no whitespace errors. It also adds a `DsrRouting::Start()` early-return guard when the priority queue is already populated; this is a behavior/lifecycle change separate from logging and must be documented and exercised in regression.
- The external checkout was not modified or built by this audit. Its historical results are not accepted as validated Stage 2 outputs.

## Tooling and validation

- Available here: local file/shell inspection, read-only GitHub MCP, and Pylance LSP diagnostics. Workspace diagnostics returned no items for the two Python files Pylance currently analyzes.
- No Google Drive or Colab execution integration was returned by tool discovery. The local Drive mirror is read-only for this task; no authenticated Colab runtime was opened.
- No tests were found in the checkout. No simulation, build, data regeneration, upload, commit or push was run.

## Required follow-up

1. Recover exact validated Stage 1 aggregates/manifests and the two validated Stage 2 pilot packages from an authorized source, verifying hashes and provenance.
2. Review and version the external DSR patch without importing its build/results tree.
3. Build the pinned NS-3.48 Colab bootstrap/notebooks and add local tests; verify them in an authenticated Colab runtime before claiming runtime readiness.
4. Pass instrumentation regression and controlled pilot gates, then estimate capacity. Keep full-matrix execution held pending explicit approval.

See [STAGE2_MASTER_EXECUTION_PLAN.md](./STAGE2_MASTER_EXECUTION_PLAN.md), [STAGE2_TODO.md](./STAGE2_TODO.md), and [PROJECT_SYNC_STATUS.json](./PROJECT_SYNC_STATUS.json).

## Post-audit update — 2026-11-16

- Preserved the external DSR source patch, event-sink header, and ignored scenario driver under `ns3/dsr_instrumentation/`; the external build and `results/` tree were not copied.
- Recorded hashes for the patch and all preserved source files. The apply script's payload checks and idempotent no-op run against the existing external checkout passed; the patch also passed `git apply --reverse --check`.
- Instrumentation behavior/regression is still **NOT RUN**. The `DsrRouting::Start()` lifecycle guard and the event sink's unchecked output open remain review/test items.
