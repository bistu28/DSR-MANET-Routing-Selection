# Storage analysis

Audit date: 2026-11-15.

| Location | Observed size | Notes |
|---|---:|---|
| Dissertation worktree at initial inventory | 440.8 MB content; 571 MB including `.git` | 249 upstream paths; eight absent at that time. They have since been restored. |
| GitHub repo | API size 153,012 KB | 249 blobs; three LFS payloads expected to total 552,633,536 bytes. They have since been fetched and verified locally. |
| Drive project mirror | 222.45 MiB inventoried content | excludes virtual environment, node_modules, build/caches; large-file hashes deferred. |
| External ns-3.48 | 2.4 GiB | results tree 1.03 GB, 655 files, 134 scenario folders. |

## Storage findings
- GitHub is not a complete backup: no `.gitignore`, no current Stage 2 artifacts or validated 180-scenario aggregates. The initial local snapshot had only LFS pointers; all three payloads have since been fetched and verified.
- Drive contains generated `venv/`, `dashboard/node_modules/`, `dashboard/dist/`, Python caches, PID/log files, and Dashboard experiment outputs. Keep environments/build caches out of GitHub.
- Drive has only 14 compressed mobility traces in the inspected project and `.gsheet`/`.gdoc` stubs for several older data files. Stubs are not actual data content.
- External NS-3 results are not Stage 2 evidence; route-event CSVs examined are baseline placeholder content and no PCAPs were found.
- Do not copy the full ns-3 build tree to the dissertation repository.

## External ns-3.48 DSR source hashes

| Path | Bytes | SHA-256 |
|---|---:|---|
| `src/dsr/model/dsr-options.cc` | 64,827 | `15b0eb749656dfdedb9645a80ced758621cd15bd9e46325fd7cf36c722fd04a6` |
| `src/dsr/model/dsr-rcache.cc` | 41,027 | `ca79003f9dc410ffd3c5e6b73b422d4651d4b5f7317c06b72a019f075d24cd83` |
| `src/dsr/model/dsr-rcache.h` | 25,165 | `9902bc07ea38cf226a4aab005df667533793fe1856e7374b21a60b8dd72cd1a0` |
| `src/dsr/model/dsr-routing.cc` | 152,987 | `a922124d4e5cbdf095ab33633122e9721d6aa4d89be0d9f0b52d994d9e9d4958` |
| `src/dsr/model/dsr-routing.h` | 34,399 | `73c5b57d97f616397da590869d9ea5f009107025b6a43ab2f5ff92b0d75a0c82` |
| `src/dsr/model/stage2-dsr-event-sink.h` | 5,704 | `e170edca0328abf961f39cd4141fb9f4131f4a831d6103b7887fda069437d612` |


## Recommended storage roles
- **GitHub:** source, configs, tests, schemas, manifests, docs, compact validation summaries. Selectively use LFS after confirming quota and payload availability.
- **Drive:** validated large raw/intermediate/final data, event/PCAP archives, snapshots, and checkpoints; keep SHA-256 manifests in GitHub.
- **Local Mac:** working checkout and external ns-3.48; separate source from builds/simulation output.
- **Colab:** `/content` for ephemeral builds; Drive for verified, batched persistent outputs.
