# NS-3.48 DSR instrumentation source mirror

This package preserves the DSR source patch and scenario driver found in the separate local `/Users/bistupaul/ns-3.48` checkout. It deliberately excludes that checkout's build files and `results/` tree.

## Contents

- `ns3-3.48-dsr.patch`: tracked DSR source changes against the exact upstream base commit in `manifest.json`.
- `src/dsr/model/stage2-dsr-event-sink.h`: the JSONL event sink included by the patch.
- `scratch/dsr_manet_dataset.cc`: the ignored external scratch driver that configures the event sink, captures DSR control packets, and supports a separately logged range outage.
- `manifest.json`: source commit, per-file hashes, and known behavior notes.
- `apply.sh`: verifies the pinned NS-3 commit and payload hashes, then applies/copies only these source files. It refuses to overwrite different existing files.

## Apply to a clean NS-3 checkout

```bash
bash ns3/dsr_instrumentation/apply.sh /content/ns-3.48
```

The target must be at the exact commit in the manifest. The script is idempotent when the exact patch and files are already present.

## Review status and caveats

This is a preserved source snapshot, not yet validated instrumentation. The patch adds hooks for selected RREQ/RREP/RERR, route discovery, cache, failure, and recovery events. The C++ event sink is configured only when the scenario driver receives a non-empty event-file path.

The source diff also adds an early return in `DsrRouting::Start()` when its priority queue is already populated. That is a lifecycle behavior change, not merely logging. Keep it explicitly identified and include regression coverage before treating this patch as scientifically validated.

The current event sink uses manual JSON serialization and does not check whether its event output stream opened successfully. Address and test these points before declaring instrumentation regression complete.

Do not treat the external checkout's existing outputs as pilot evidence. Do not copy its `results/` tree into the repository.
