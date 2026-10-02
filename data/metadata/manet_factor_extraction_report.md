# MANET Factor Extraction Report

This revised extraction includes both the raw MANET files in `data/raw/` and the geometry-derived connectivity file in `data/topology/Topology_data.csv`.

## Included sources
- `data/raw/manet_dataset.csv` for node-level MANET telemetry
- `data/topology/Topology_data.csv` for geometry-derived connectivity topology factors
- the remaining raw CSVs were inspected for mobility, wireless, performance, congestion, and failure metadata

## Important constraint
The topology CSV is not packet-level RF measurement data. It contains link existence, adjacency IDs, and connectivity-source metadata derived from radio-range geometry, not RSSI, SNR, PRR, ETX, route state, or actual DSR route repair events.

