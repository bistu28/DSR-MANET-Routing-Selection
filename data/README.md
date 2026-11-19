# Data contract

Place the public dataset in `data/raw/`. The reproducible pipeline writes cleaned data and audit reports to `data/cleaned/`, engineered features and fixed split IDs to `data/processed/`, model artifacts to `models/`, and metrics/plots to `results/`.

## Target and leakage rule

The first target is `route_failure`: `1` means the active route fails within the configured prediction window, and `0` means it remains usable. The label may be generated from a future failure-event timestamp, but feature rows may contain only measurements at or before the prediction timestamp. Columns that explicitly describe the future outcome, recovery, post-failure counters, or event timestamps are excluded by the pipeline and listed in the leakage report.

Expected research feature families are mobility speed, link quality, RSSI/SNR, delay, loss/PDR, throughput, queue/congestion, remaining energy, hop count, route history/stability, and DSR discovery/failure counters. RREQ/RREP/RERR and recovery fields must be timestamped so pre-failure features and post-failure outcomes remain distinct.

## Stage 2 raw evidence

The local runner stores each scenario attempt outside Git with DSR event JSONL,
DSR control PCAP plus a JSONL packet index, FlowMonitor XML, mobility samples,
application packet timestamps, metrics, and an execution manifest with
configuration/source/output hashes. The manifest must pass validation before
an attempt is eligible for downstream processing.

Application delay is measured as the receive timestamp minus the transmit
timestamp for the same `ns3uid:` application packet. It is an application-layer
measure, not a FlowMonitor value; keep the delay sample count and measurement
layer with the aggregate. Join DSR `packet_tx`/`packet_rx` events to PCAP by
scenario/run identity and `pcap_record_index`, verifying packet ID, time, node,
and direction. A packet UID alone is not a unique PCAP-record key because
simulator packet copies can retain a UID.

Geometry-derived topology at 250 m is a candidate-connectivity representation,
not observed MAC connectivity and not proof of a DSR link failure. Use direct
DSR failure/recovery events and their simulation timestamps as observed labels.
Do not generate ML-ready tables until the immutable Stage 1 aggregates and
required Stage 2 runs are recovered/validated; do not train final models in
Stage 2.
