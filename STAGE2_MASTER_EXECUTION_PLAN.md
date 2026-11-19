# Stage 2 Master Execution Plan

Audit checkpoint: 2026-11-16  
Repository baseline: `main` at `6232193cac952abaf306ba27442845e1eb3451c5`

## Objective

Complete the remaining Stage 2 work with reproducible NS-3.48 DSR instrumentation and evidence-backed, ML-ready datasets. Final ML model training is out of scope. The 180-run Stage 2 matrix stays held until all readiness checks pass and the user explicitly approves the cost.

## Verified starting point

- The local checkout and public GitHub `main` are at the same commit; GitHub has one branch and two commits.
- All 249 currently tracked paths exist locally. The three historical LFS objects were fetched and hash/size-verified in the preceding recovery.
- `data/metadata/Simulation_data.csv` contains 180 rows and 180 unique scenario IDs, six node-count groups, and five seed/run groups.
- The Stage 1 aggregate filenames and 2026-11-14 validation/recovery manifests stated in the current-status claim are absent locally, on GitHub `main`, and in the inspected Drive project.
- Existing local validation records describe an older partial state: 5 mobility scenarios and 1 topology scenario. The Drive batch summary dated 2026-11-01 says 125/180 completed, with 81 `VERIFIED_EXISTING`, 44 `PASS`, and 55 `FAIL`; its detailed manifest/matrix files are Google shortcut stubs, not locally available contents.
- The two claimed validated Stage 2 pilot artifacts were not found in the inspected roots. The external `/Users/bistupaul/ns-3.48` checkout has five modified DSR source files, an untracked event-sink header, and historical results; it is not yet a versioned project patch or validated pilot package.
- The repository has no `colab/` directory, no `ns3/dsr_instrumentation/`, no DSR event JSONL or PCAP, and no test suite. Its existing Colab setup scripts pin ns-3.47, not ns-3.48.
- The local Google Drive desktop mirror exposes the historical `My Drive/DISSERTATION`; the requested `My Drive/MANET_DISSERTATION` folder is absent. No Google Drive or Colab execution integration is available in this session. GitHub write authentication is also unavailable.

The evidence and scope limits are documented in [STAGE2_INITIAL_AUDIT_REPORT.md](./STAGE2_INITIAL_AUDIT_REPORT.md). Missing historical data must not be inferred from older LFS objects, generated legacy tables, or simulation summaries.

## Execution sequence and dependencies

### A. Audit and provenance — completed for this checkpoint

1. Reconcile local files, GitHub history/tree, LFS, Drive mirror, existing notebooks/scripts, data matrix, and external ns-3 checkout.
2. Record current branch/status, hashes, missing files, integration limitations, and the difference between claimed and verified research status.
3. Keep the 2026-11-01 batch and all existing outputs unchanged; do not treat failed or incomplete records as validated Stage 1 output.

### B. Recover immutable source data and pilot evidence

1. Search authorized, project-specific backup/Colab locations for the exact Stage 1 aggregates and manifests and the two validated Stage 2 pilot packages.
2. Verify each recovered file against its manifest, row counts, scenario/run coverage, and SHA-256 before registering it.
3. Preserve the external ns-3.48 working tree. Review its diff and event sink, then package the source patch and tests under version control without copying build products or historical output trees.
4. If exact artifacts cannot be recovered, report the exact missing scenarios and provenance. Do not regenerate Stage 1 data or claim prior validation. Any Stage 2 regeneration must use the recorded experiment matrix and remain separate from the missing Stage 1 data.

### C. Reusable Colab environment — implement locally; runtime verification blocked on access

1. Replace the stale ns-3.47 setup path with a pinned ns-3.48 environment manager supporting `AUTO`, `RESTORE`, `BUILD`, and `VERIFY`.
2. Keep compilation and active execution under `/content`; persist source, patches, manifests, and validated checkpoints in the designated Drive folder only after authenticated access is available.
3. Verify compiler/Python/OS/build configuration and source/patch hashes before reuse. Rebuild incompatible artifacts rather than restoring them blindly.
4. Add thin, task-specific notebooks that invoke versioned Python modules. Add tests for the reusable bootstrap and manifest logic.
5. Do not report Colab readiness or a successful Colab run until an authenticated runtime actually executes the verification notebook.

### D. Instrumentation regression and reproducibility

1. Build the pristine pinned ns-3.48 source with the reviewed patch.
2. Verify event hooks, stable identifiers/provenance, JSONL validity, flushing/closure, and packet-capture alignment.
3. Re-run frozen pilots with their recorded seed/run/configuration and compare deterministic fields separately from runtime metadata.
4. Publish regression and reproducibility reports only with captured command outputs and validated artifacts.

### E. Controlled pilot and resource readiness

1. After regression passes, run a small representative set from the actual 180-row matrix, with fixed seeds and bounded concurrency.
2. Include baseline communication, route discovery, controlled outage/recovery, and varied mobility/traffic where supported by the matrix.
3. Validate events, PCAP, FlowMonitor, logs, configuration and hashes; measure runtime, disk, RAM, and instrumentation overhead.
4. Build a resumable execution manager with per-run state, timeouts, retry limits, checkpoints, and verified output manifests.
5. Publish the resource and full-matrix readiness reports. **Do not launch the 180-run matrix without separate explicit approval.**

### F. Evidence-aligned data processing

1. Keep raw validated inputs immutable. Process in chunks or partitions; join only on actual scenario/run/node/flow/packet/time identifiers.
2. Define schemas and provenance for events, PCAP, FlowMonitor, mobility and geometry-derived topology; clearly distinguish geometry-derived candidate connectivity from measured wireless state.
3. Create features only when supported by observed data. Exclude future information and target-derived fields from current-time inputs.
4. Define prediction horizons, observation windows, censoring, missingness and exclusions before generating labels. Do not turn right-censored observations into negative labels.
5. Implement leakage, provenance, quality, schema, integrity, and group-split checks. Use `PASS`, `FAIL`, `WARNING`, and `NOT AVAILABLE` distinctly.
6. Generate ML-ready datasets and fixed scenario/run-grouped splits only after required source data and validation gates pass. Do not train final models.

### G. Synchronization and completion

1. Keep source, code, notebooks, manifests, tests and reports in Git; keep large raw/processed data and checkpoints in Drive.
2. Use non-destructive, hash-verifying transfers. Never sync `.git`, environments, caches, build trees, or unvalidated output.
3. Resolve GitHub write and Drive authentication before any remote writes. Verify all uploads before recording them as synchronized.
4. Produce the final completion report only when the completion criteria in the user prompt are met; otherwise state the highest verified status and remaining blockers.

## Approval gates and safety rules

- No full-matrix execution until regression, controlled pilot, resource estimates, data readiness and explicit user approval pass.
- No overwrite, regeneration, move, or deletion of any validated Stage 1/Stage 2 data.
- No Drive upload or GitHub push until the relevant account integration is authenticated and the exact transfer set is reviewed.
- Preserve the external ns-3 checkout and existing outputs; do not reset it or copy generated/build trees.
- Never infer successful runs from process exit codes alone.
- Maintain [STAGE2_TODO.md](./STAGE2_TODO.md), [STAGE2_PROGRESS_LOG.md](./STAGE2_PROGRESS_LOG.md), and [PROJECT_SYNC_STATUS.json](./PROJECT_SYNC_STATUS.json) after each meaningful milestone.

## Immediate work

Proceed with local, non-destructive implementation: review and preserve the external DSR patch, add a hash-checked NS-3.48 bootstrap and environment-verification notebooks, and add tests for those components. Stop before Colab/Drive execution, remote writes, or expensive simulation until access and missing research evidence are resolved.
