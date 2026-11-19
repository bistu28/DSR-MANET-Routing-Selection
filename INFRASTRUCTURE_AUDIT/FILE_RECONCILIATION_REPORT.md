# File reconciliation report

Audit date: 2026-11-15. This is the initial inventory snapshot, captured before the user-approved local restore and LFS checkout recorded in `../STAGE2_PROGRESS_LOG.md`. The audit was read-only with respect to research data and remote stores; no Git push, Drive write, or data replacement occurred.

## Scope and limitations
- Local project: `/Users/bistupaul/Movies/DISSERTATION`.
- GitHub: `bistu28/DSR-MANET-Routing-Selection`, branch `main`, commit `6232193cac952abaf306ba27442845e1eb3451c5`.
- Google Drive: accessible local desktop-sync mirror `My Drive/DISSERTATION`. The requested `My Drive/MANET_DISSERTATION/` was not found. The browser was not authenticated and showed a Google sign-in page; no Drive API/web inventory was available.
- Drive inventory excludes `venv`, `node_modules`, `dist`, `__pycache__`, `.cache`, and `.git` contents, recorded as excluded directory entries. Drive files larger than 1 MiB have metadata but their content hashes are deferred to avoid forcing downloads. `.gdoc`/`.gsheet` hashes describe only 177-byte shortcut stubs, not linked content.
- GitHub blobs over 5 MiB use Git blob SHA-1 identity only; small blobs have SHA-256. LFS pointer rows include the expected data SHA-256 and expected payload size.

## Summary
- Local project: 241 present files (420.64 MiB content), 29 directories; 8 tracked paths absent, plus `.DS_Store` modified.
- GitHub `main`: 249 tracked files, Git tree content size 420.68 MiB; one branch, two commits, public repo, API size 153,012 KB.
- Drive mirror: 239 inventoried files (222.45 MiB content) and 150 directories, excluding recorded environment/dependency/build trees.
- Path-level reconciliation counts: DIFFERENT_CONTENT=10, DRIVE_ONLY=52, GITHUB_ONLY=6, IDENTICAL=215, MISSING=6, NEEDS_REVIEW=132, OBSOLETE_CANDIDATE=1.
- Exact duplicate content at different paths: 7 SHA-256 groups; see `DUPLICATES.csv`. Identical FlowMonitor XML/config outputs may be repeated experiment artifacts, so this is not by itself a cleanup recommendation.

## Local project and GitHub
At the time of the initial inventory, the local branch pointed to the same commit as `origin/main`, but these tracked paths were missing: `.gitattributes`, `DATASET_AUDIT_REPORT.txt`, `PROJECT_GUIDE.md`, `README.md`, `requirements.txt`, `run_colab.sh`, `setup_colab.sh`, `to be done`. They were subsequently restored from that exact commit to absent paths only. `.DS_Store` differed and was left untouched.

GitHub `main` contains no `.gitignore`; `.gitattributes` covers only three LFS paths. At initial inventory time, the checkout contained 134-byte LFS pointers. The user later approved and the three payloads were fetched and checked out; all sizes and SHA-256 values matched the pointer metadata. The initial local inventory intentionally preserves the pre-recovery state; current verification is in `../STAGE2_PROGRESS_LOG.md`.

The tracked GitHub tree does not contain `dashboard/`, recent 180-run validated aggregates, Stage 2 recovery manifests, or the mirrored DSR instrumentation patch.

## Google Drive
`My Drive/DISSERTATION` is a historical project copy. It contains Dashboard source and experiment history, but also generated dependency/build trees and shortcut stubs. The inspected `data/mobility` folder contains no mobility aggregate, `data/stage2` and `ns3/dsr_instrumentation` are absent, and `ns3/results/mobility_traces` contains 14 compressed traces only. `Colab Notebooks/DISSERTATION` and `.Encrypted/My Drive/DISSERTATION` were empty at inspected level.

## External ns-3.48
`/Users/bistupaul/ns-3.48` is version 3.48 at commit `d2add90` (`ns-3.48`), 2.4 GiB total. Its working tree has five modified DSR source files, an untracked event-sink header, and untracked results. The results tree contains 134 scenario directories, 655 files, ~1.03 GB, and no PCAP/manifest/validation files. Sample route-event output is a baseline placeholder describing unavailable route tracing, not a validated Stage 2 event log. Modified source SHA-256 values are in `STORAGE_ANALYSIS.md`.

## Recommended reconciliation
1. Keep the current research files unchanged until each recovery operation is approved.
2. The eight absent tracked files have since been restored from the exact `origin/main` revision without overwriting existing paths.
3. The three Git LFS payloads have since been fetched and verified against their expected SHA-256 hashes and sizes.
4. Preserve Drive-only Dashboard source in a separate recovery copy, compare content, and exclude virtual environments, node_modules, dist, cache, logs, PIDs, and shortcut files.
5. Locate the recent Stage 1/Stage 2 validated artifacts from authorized backup locations before considering regeneration.
6. Archive external ns-3 source edits as a reviewed patch/source mirror with hashes; do not treat its scenario outputs as Stage 2.
7. Establish ignore/LFS policy, create a development branch, and perform a small verified Git/Drive sync test only after approval. No push or Drive write was performed.

See `LOCAL_INVENTORY.csv`, `GITHUB_INVENTORY.csv`, `GOOGLE_DRIVE_INVENTORY.csv`, `FILE_RECONCILIATION.csv`, and `DUPLICATES.csv` for records.
