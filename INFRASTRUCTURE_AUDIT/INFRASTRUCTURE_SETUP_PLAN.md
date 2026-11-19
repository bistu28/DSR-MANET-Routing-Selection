# Infrastructure setup plan

Status: **Initial audit complete; the user-approved local restore and LFS recovery are complete. Drive/GitHub synchronization and broader project recovery remain pending approval.**

## Recommended architecture
1. Keep GitHub `main` at `6232193` as the code baseline; use `stage2-development` only after recovery approval.
2. Treat the existing Drive `My Drive/DISSERTATION` as a historical recovery source, not a clean mirror. Do not create the requested `My Drive/MANET_DISSERTATION/` or upload/move files until approved.
3. Preserve `/Users/bistupaul/ns-3.48` independently; it contains uncommitted DSR instrumentation and historical output. Do not reset or build over it.
4. Use local `/content` for Colab builds, Drive for validated large data, and GitHub for source/manifests/documentation.

## Phase A — approval-gated recovery
- [x] Restore the eight missing tracked files from exact `origin/main`; only absent paths were written.
- [x] Fetch and verify the three Git LFS payloads by exact expected size and SHA-256.
- [ ] Preserve the Drive-only `dashboard/` source in a separate recovery copy, compare versions, and omit `node_modules`, `dist`, caches, logs, PID files, and virtual environments.
- Search authorized backup locations for Stage 1 validated aggregates and Stage 2 pilot artifacts before regeneration.
- Archive the external DSR source edits and event sink in a reviewed patch/source mirror with hashes; do not classify current 134 baseline scenarios as Stage 2.

## Phase B — repository hygiene
- Add reviewed `.gitignore` and confirm `.gitattributes`/LFS policies and quotas.
- Add status/policy docs and stage trackers on an approved feature branch.
- Before each push, inspect status, staged paths, sizes, secrets, Stage 1 hashes, and remote compatibility. Never force-push. GitHub write authentication is not configured (`gh` missing; prior SSH test returned public-key denial).

## Phase C — Drive and Colab
- After approved Drive authentication, create the dedicated folder and transfer only approved, hashed project assets; verify size and SHA-256. Never upload `.git`, environments, node_modules, build caches, or all of Drive.
- Build a resumable sync utility that never deletes and reports conflicts; use an approved disposable test file.
- Implement NS-3.48 Colab bootstrap with AUTO/RESTORE/BUILD/VERIFY and runtime/compiler manifests. Restore build caches only when compatible; otherwise build under `/content`.
- Create the shared setup library and requested notebooks after source/data recovery; verify environment and pilot before any matrix run.

## Validation gates
1. Reconcile source versions and establish authorities.
2. Verify Stage 1 datasets and hashes without modifying them.
3. Run instrumentation regression and validated pilot checks.
4. Validate features, labels, leakage, data quality, and splits.
5. Assess runtime/storage and publish readiness.
6. Keep the 180-run Stage 2 matrix held until all gates pass and user approval is given.

## Approval boundary
The audit itself did not change research data or remote stores. The approved local restore and LFS checkout have completed. No Drive file was copied or uploaded, no branch was created, no simulation was run, and no commit or push was made.
