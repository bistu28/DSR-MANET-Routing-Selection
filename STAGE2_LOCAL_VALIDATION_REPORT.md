# Stage 2 local validation report

**Checked:** 2026-11-19
**Branch:** `main`
**Execution:** local macOS only; no Colab/cloud runs
**Matrix status:** 180 scenarios present; full execution remains held

## Verified environment

- macOS 27.2.1, Apple Silicon, 8 GiB physical memory; 28 GiB disk space free
  after local validation.
- NS-3.48 checkout is pinned at
  `d2add90b452d600cfb4859baed8e9ea633519447`. Apple clang 17, CMake 4.4.3,
  Ninja, DSR, examples, and tests are configured.
- `./ns3 build -j 4` completed successfully. NS-3's `routing-dsr` QUICK test
  suite passed (1/1).
- A local Python 3.13.5 environment was created outside the repo at
  `/Users/bistupaul/.venvs/dsr-manet-stage2-py313`. Declared dependencies
  installed, `pip check` passed, and the exact installed versions are recorded
  in `requirements-local.lock.txt`.
- Python tests: **23 passed**. Pylance reported no diagnostics for the runner
  or its tests.

## Existing-data audit

- `data/metadata/Simulation_data.csv` has 180 unique scenario IDs: 30 each at
  100, 150, 200, 300, 400, and 500 nodes. All runs are 600 simulated seconds;
  packet rates range from 85.09 to 176.8 packets/s.
- The asserted validated Stage 1 aggregates/recovery manifests and the two
  previously recovered Stage 2 pilot packages are not present in the inspected
  project, local NS-3 results, or the prior scoped inventory. Older mobility,
  topology, and simulation outputs are not substitutes.
- Existing `ns3/results/` data are legacy application-trace runs. They have no
  DSR event JSONL or PCAP, and FlowMonitor reports zero classifiable IPv4
  flows. Their delay field is empty. The external NS-3 checkout's historical
  `results/` tree was also not accepted as pilot evidence.
- Stage 1 topology remains geometry-derived at 250 m, not MAC-observed
  connectivity. No Stage 1 data were regenerated or used as observed DSR
  failures.

## New local pilot validations

Both use matrix row `DSR_N100_MLOW_TLOW_S10001_R001`: 100 nodes, 600 s,
200 m x 200 m, RandomWaypoint at 0.66 m/s, 275692 bps, 405-byte packets,
seed/run 10001/1. The two output roots are separate and outside Git:

- Baseline manifest:
  `/Users/bistupaul/Movies/MANET_STAGE2_LOCAL_VALIDATION_20261119_delay/baseline/execution_manifest.json`
- Controlled-outage manifest:
  `/Users/bistupaul/Movies/MANET_STAGE2_LOCAL_VALIDATION_20261119_delay/outage/execution_manifest.json`

| Measure | Baseline | Controlled outage |
|---|---:|---:|
| Wall time | 116.298 s (includes first scratch-driver compile) | 107.348 s |
| Peak process-tree RSS | 807.1 MiB (includes compile) | 142.7 MiB |
| Validated output size | 41.77 MiB | 43.74 MiB |
| DSR events | 51,193 | 53,793 |
| DSR control PCAP records | 102 | 901 |
| PCAP/event exact record joins | 102/102 | 901/901 |
| Application Tx / Rx | 50,883 / 50,882 | 50,883 / 49,571 |
| Application loss | 1 | 1,312 |
| PDR | 0.999980 | 0.974215 |
| Application goodput | 275,681.739 bps | 268,578.662 bps |
| Mean application delay | 2.199166 ms (50,882 samples) | 2.628178 ms (49,571 samples) |

The outage is an explicitly controlled global range intervention from 300 s
through 310 s (range 0 m, then restored to 250 m). Its intervention log records
both requested timestamps. Direct DSR observations include a broken-link
declaration at 300.200624 s, a recovery attempt, and `recovery_succeeded` at
315.728682 s (15.528058 s recovery duration). This supports that this pilot
observed failure and recovery; the injected range change alone is not treated as
a DSR failure.

The runner parses JSONL and CSV, validates identifiers/timestamps, and checks
one-to-one PCAP record-index joins against event packet ID, timestamp, node, and
direction. `ns3uid` alone is not a unique PCAP-record key because simulator
packet copies can retain a UID.

## Instrumentation findings and limits

- Observed in the outage pilot: RREQ Tx/Rx/forwarding and duplicate suppression;
  RREP generation/Tx/Rx and route discovery; RERR Tx; route/link-cache
  hit/miss/invalidation/expiry; packet Tx/Rx; maintenance attempts; broken-link
  declaration; and recovery attempt/success.
- The 100-node baseline/outage runs now write per-packet application
  Tx/Rx timestamps keyed by ns-3 packet UID. The runner requires every received
  packet to join to a Tx record and verifies the aggregate delay, PDR, loss,
  and goodput. This provides application-layer delay despite FlowMonitor's
  zero DSR flow entries; it does not claim FlowMonitor-derived delay.
- Event-sink JSONL open/flush/close failures now fail explicitly.
- `route_cache_remove`, route-cache entry expiry, and RERR reception were not
  triggered in these pilots; their hooks need targeted coverage. Logging
  overhead has not been measured against an uninstrumented build. The patch's
  `DsrRouting::Start()` lifecycle guard remains a behavior change that must
  stay documented and regression-tested.
- These are fresh local validation pilots, not recovered copies of the
  previously claimed pilot packages. Do not mark the missing historical
  packages recovered.

## Preliminary full-matrix resource estimate

This is an extrapolation, not a 500-node benchmark. The observed warm 100-node
run took about 107 s and produced 43.74 MiB with the outage trace; baseline
output was 41.77 MiB. For each matrix row, the planning model scales time by
the mean of `(node_count / 100)` and `(packet_rate_pps / 85.09)`. Across the
180 rows this gives an average scale factor of about 2.14:

- **Linear runtime estimate:** approximately 11.5 hours warm; about 12.5 hours
  including the first-run compile overhead seen in the baseline. Planning
  range: **12–25 hours sequentially**, allowing up to 2x for nonlinear
  500-node routing/event costs. This range is not yet validated at 500 nodes.
- **Disk estimate:** a component-wise linear estimate from measured baseline
  event, application, and mobility files is about **13 GB** for one successful
  attempt per scenario. A 2x planning allowance is about **26 GB**. Current
  free space is **28 GiB**, leaving only about 4 GiB under that allowance;
  retained retry/failed attempts could exceed it. Prefer at least **40 GiB
  free local storage** before the full matrix.
- **Memory:** measured process-tree RSS was 142.7 MiB for the warm 100-node
  outage run and 807.1 MiB while compiling the scratch driver. The Mac has 8
  GiB RAM. A 500-node peak was not measured; keep execution serial and reserve
  up to 2 GiB until a maximum-size capacity pilot verifies the estimate.

**Readiness decision:** do not launch the 180-run matrix yet. The local runner
requires explicit bounded selection by default and has a separate full-matrix
approval guard. Remaining instrumentation coverage and historical-data
provenance gaps remain, and current disk headroom is too narrow for a
conservative estimate plus retained retries.

## Recovery and synchronization

Use the resumable local runner and recovery instructions in `ns3/README.md`.
It writes to `~/Movies/MANET_STAGE2_RUNS` by default, keeps per-attempt logs and
SHA-256 manifests, and never writes to the historical `ns3/results/` folder.
The validation outputs above remain local and outside Git.

No datasets were generated and no ML models were trained. Existing modified
`.DS_Store` and untracked inventory CSVs were left untouched.
