# MANET topology data

This dataset is generated from each scenario's validated `data/mobility/Mobility_data.csv` positions and the configured 250 m ns-3 radio range. It does not use the unmapped legacy `data/raw/positions_*.csv` files.

## What this dataset represents
- One row represents one node at one scenario/time observation.
- `neighbor_ids_hex` is a lossless adjacency bitset: bit i is set exactly when node i is within `max_range_m` of this row's node. Decode the neighbor IDs with `int(neighbor_ids_hex, 16)` and enumerate set bit positions.
- `neighbor_count` is the number of set bits. Self-links are excluded.
- This is geometry-derived candidate connectivity, not measured RF quality or DSR route-state data.

`scenario_id`, `run_id`, `random_seed`, and `random_run` are copied from the manifest and checked against the mobility rows before graph construction. `source_scenario_id` records the exact mobility scenario used.

## Regeneration
Run the generator from the project root:

```bash
python3 ml/generate_topology_data.py --all --mobility-csv data/mobility/Mobility_data.csv
```

## Limitations
- This dataset does not include RSSI, SNR, PRR, ETX, route IDs, or route failures.
- Bitsets preserve exact neighbor IDs while avoiding the infeasible expansion of dense graphs into billions of CSV edge rows.
