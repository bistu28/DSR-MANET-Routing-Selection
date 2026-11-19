# Local NS-3.48 execution

The Stage 2 workflow runs on the local Mac against the pinned checkout at
`/Users/bistupaul/ns-3.48`. Do not use the older `setup_colab.sh` or
`run_colab.sh` scripts for this workflow; they target ns-3.47.

## Prepare and verify NS-3

The instrumentation package applies only to the clean NS-3.48 commit recorded
in `dsr_instrumentation/manifest.json`. The working checkout already contains
the patch and its ignored scratch driver. Verify it without changing unrelated
files:

```bash
bash ns3/dsr_instrumentation/apply.sh /Users/bistupaul/ns-3.48
cd /Users/bistupaul/ns-3.48
./ns3 show config
./ns3 build -j 4
```

The build produces local NS-3 build files only. Do not run `git clean`, reset
the checkout, or copy its build directory or historical `results/` into this
repository.

## Resumable execution

Use the standard-library runner; its default output root is
`~/Movies/MANET_STAGE2_RUNS`, outside Git. Preview a scenario before execution:

```bash
python3 ns3/run_local_matrix.py --scenario-id DSR_N100_MLOW_TLOW_S10001_R001 --dry-run
```

Then run one scenario or an explicitly bounded subset:

```bash
python3 ns3/run_local_matrix.py --scenario-id DSR_N100_MLOW_TLOW_S10001_R001
python3 ns3/run_local_matrix.py --limit 3
```

The runner records per-attempt logs, execution state, output checks, and SHA-256
hashes in `execution_manifest.json`. Repeating the same command revalidates and
skips completed scenarios, resumes incomplete work, preserves failed attempt
outputs, and retries up to the configured additional-attempt count. A stale
`.runner.lock` is only removable after verifying no runner is active.
The runner refuses output roots inside the repository or NS-3 checkout, and it
will not mix new runs into a non-empty output root without an execution manifest.

Every attempt is checked for non-empty DSR event JSONL, application packet
timestamp CSV, PCAP and packet index, metrics, mobility trace, FlowMonitor XML,
and route CSV. JSON records, event/run identifiers, event sequence numbers,
application Tx/Rx packet identity and delay, PCAP record framing and exact
event-index alignment, mobility provenance, and the simulator completion
marker are validated. Application delay is measured from the simulator Tx/Rx
timestamps for the same packet UID; it is not inferred from FlowMonitor when
DSR has no classifiable IPv4 flow. This runner does not infer a DSR-observed
link failure from geometry-derived topology data.

The full matrix is guarded. Do not pass the following options until the
resource/readiness gate has been reviewed and the user has explicitly approved
full execution:

```bash
python3 ns3/run_local_matrix.py --allow-full-matrix --approval-reference "approved by user"
```

## Controlled outage validation

An outage is a deliberate propagation-range intervention, not an ordinary
matrix scenario. Keep it in a separate output root and record the selected
start, duration, and outage range:

```bash
python3 ns3/run_local_matrix.py \
  --scenario-id DSR_N100_MLOW_TLOW_S10001_R001 \
  --output-root ~/Movies/MANET_STAGE2_OUTAGE_CHECK \
  --controlled-outage 300 10 0
```

The outage is only validated as an intervention if its control log and all
other required event/PCAP/FlowMonitor outputs pass. Do not report the injected
intervention itself as proof that DSR observed a link failure or recovered.

## Existing results and data safety

The historical `ns3/results/` tree and the external checkout's `results/`
directory are preserved. They are not Stage 2 pilots unless their complete
configuration, event log, PCAP/index, FlowMonitor, mobility trace, hashes, and
validation report are present and pass the current checks. The local runner
never writes into these historical directories. Keep full raw simulation
outputs under the external output root and commit only source, documentation,
tests, and reviewed manifests.
