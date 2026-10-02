# Data contract

Place the public dataset in `data/raw/`. The reproducible pipeline writes cleaned data and audit reports to `data/cleaned/`, engineered features and fixed split IDs to `data/processed/`, model artifacts to `models/`, and metrics/plots to `results/`.

## Target and leakage rule

The first target is `route_failure`: `1` means the active route fails within the configured prediction window, and `0` means it remains usable. The label may be generated from a future failure-event timestamp, but feature rows may contain only measurements at or before the prediction timestamp. Columns that explicitly describe the future outcome, recovery, post-failure counters, or event timestamps are excluded by the pipeline and listed in the leakage report.

Expected research feature families are mobility speed, link quality, RSSI/SNR, delay, loss/PDR, throughput, queue/congestion, remaining energy, hop count, route history/stability, and DSR discovery/failure counters. RREQ/RREP/RERR and recovery fields must be timestamped so pre-failure features and post-failure outcomes remain distinct.
