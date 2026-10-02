# Mobility data

## Purpose and provenance

`Mobility_data.csv` contains node positions sampled from ns-3 DSR simulations configured from `data/metadata/Simulation_data.csv`. It is simulation-generated data, not real-world measurement. Original raw datasets were inspected but not modified or merged because none can be mapped scientifically to the manifest scenarios.

The inspected manifest contains 180 scenarios; this generation contains 5 scenarios and 300500 node-time records. The manifest specifies `RandomWaypoint` mobility, 1 s sampling, [200] m X-area, [200] m Y-area, and [600] s duration.

## Existing source assessment

The following files contain candidate coordinates. Their available keys, temporal coverage, or coordinate bounds do not match the current experiment matrix, so they were excluded:

| File | Rows | Nodes | Time coverage | Position columns | Speed | Mobility model | Run key | Scenario key | Compatibility |
|---|---:|---:|---|---|---|---|---|---|---|
| `data/raw/manet_dataset.csv` | 54000 | 30 | 1.0–60.0 (60 samples) | `x,y` | `none` | `not recorded` | `run_id` | `none` | Incompatible |
| `data/raw/positions_100_run1.csv` | 5100 | 100 | 0.0–500.0 (51 samples) | `x,y` | `speed` | `not recorded` | `run` | `none` | Incompatible |
| `data/raw/positions_150n_seed1.csv` | 7650 | 150 | 0.0–500.0 (51 samples) | `x,y` | `speed` | `not recorded` | `run` | `none` | Incompatible |
| `data/raw/positions_150n_seed2.csv` | 7650 | 150 | 0.0–500.0 (51 samples) | `x,y` | `speed` | `not recorded` | `run` | `none` | Incompatible |
| `data/raw/positions_150n_seed3.csv` | 7650 | 150 | 0.0–500.0 (51 samples) | `x,y` | `speed` | `not recorded` | `run` | `none` | Incompatible |
| `data/raw/positions_150n_seed4.csv` | 7650 | 150 | 0.0–500.0 (51 samples) | `x,y` | `speed` | `not recorded` | `run` | `none` | Incompatible |
| `data/raw/positions_150n_seed5.csv` | 7650 | 150 | 0.0–500.0 (51 samples) | `x,y` | `speed` | `not recorded` | `run` | `none` | Incompatible |
| `data/raw/positions_200_run1.csv` | 10200 | 200 | 0.0–500.0 (51 samples) | `x,y` | `speed` | `not recorded` | `run` | `none` | Incompatible |
| `data/raw/positions_300_run1.csv` | 15300 | 300 | 0.0–500.0 (51 samples) | `x,y` | `speed` | `not recorded` | `run` | `none` | Incompatible |
| `data/raw/positions_400_run1.csv` | 20400 | 400 | 0.0–500.0 (51 samples) | `x,y` | `speed` | `not recorded` | `run` | `none` | Incompatible |
| `data/raw/positions_500_run1.csv` | 25500 | 500 | 0.0–500.0 (51 samples) | `x,y` | `speed` | `not recorded` | `run` | `none` | Incompatible |

`data/raw/positions_*.csv` traces have 51 samples at 10 s intervals over 0–500 s, coordinates approximately 0–1000 m, and no scenario/model key; the manifest requires 1 s observations over 0–600 s in a 200×200 m area with RandomWaypoint. `data/raw/manet_dataset.csv` has 30 nodes and 60 samples over 1–60 s, and lacks compatible seed/model/scenario mapping. `nodes_dynamic.csv` has no coordinates. The existing topology dataset is not joined: its generator selects those position files by node count and seed modulo, so its nominal scenario keys do not identify the same ns-3 realization.

The full per-file schema and row-count audit is recorded in `mobility_generation_report.json`, including files under `data/raw/`, `cleaned/`, `processed/`, `final/`, `topology/`, and `metadata/`.

## Configuration and sampling

Each mobility realization uses the selected manifest values for node count, area, duration, speed, random seed/run, mobility model, and DSR routing. `ns3/scratch/dsr_manet_dataset.cc` samples the installed ns-3 `MobilityModel` at the selected interval, including t=0 and the configured final time when it is an interval boundary. Scenario outputs are isolated under `ns3/results/scenarios/<scenario_id>/`; losslessly compressed raw traces are kept under `ns3/results/mobility_traces/*.csv.gz`.

Coordinates are Cartesian metres in the ns-3 simulation rectangle. They are not geographic coordinates. Speed comes from each manifest row. The manifest does not define RandomWaypoint pause duration, so the ns-3.48 model default of 2.0 s is used and recorded in `mobility_pause_s`; measured `speed_mps` is the finite-difference average between sampled positions.

## Features

- `velocity_x_mps` and `velocity_y_mps`: successive X/Y coordinate differences divided by the actual elapsed time.
- `speed_mps`: Euclidean magnitude of the finite-difference velocity.
- `direction_deg`: `atan2(vy, vx)` converted to degrees and normalized to [0, 360); undefined at the first sample and while stationary.
- `distance_moved_m`: Euclidean displacement from the prior sample.
- `acceleration_mps2`: change in derived speed divided by elapsed time; unavailable until two speeds exist.
- `distance_to_nearest_neighbor_m`: nearest other node at the same scenario/time, computed from the sampled coordinates.
- `neighbor_count`: number of other nodes within the configured 250 m `RangePropagationLossModel` radius at the same time. This is geometry-derived candidate connectivity, not a DSR route or measured RF-neighbor table.
- `relative_speed_mps`: null. The existing Step 2 topology pairs cannot be joined to these exact RandomWaypoint simulations, so no unrelated node pairs are used.

## Missing values and provenance fields

The first sample of every node has no prior position, so velocity, speed, direction, and distance moved are null there. Acceleration is null until a prior derived speed exists. Direction is also null at zero speed because direction is undefined. `relative_speed_mps` is null throughout because a compatible topology-pair dataset is not available. `source_file`, `source_scenario_id`, `source_run_id`, `source_time_s`, and `source_type` trace each row to its archived ns-3 position trace. Every manifest row is simulated independently because a paired traffic-rate pilot produced different positions.

## Validation

- Scenarios: 5 of 180 manifest scenarios selected.
- Runs: 5; scenario-node instances: 500; records: 300500.
- Expected sampling interval: 1 s; observed model(s): RandomWaypoint.
- Invalid coordinates: 0; invalid node IDs: 0; duplicate node-time records: 0; missing node-time records: 0; unexpected intervals: 0.
- The machine-readable report includes missing-value counts, speed consistency, bounds, mapping, and per-source inventory results.

## Regeneration

Run in the project virtual environment with a built ns-3 checkout:

```bash
python3 ml/generate_mobility_dataset.py --ns3-dir /path/to/ns-3.48 --scenario-id DSR_N100_MLOW_TLOW_S10001_R001
python3 ml/generate_mobility_dataset.py --ns3-dir /path/to/ns-3.48 --limit 5
python3 ml/generate_mobility_dataset.py --ns3-dir /path/to/ns-3.48 --all
```

The default is one manifest scenario. `--limit 5` supports the pilot stage; `--all` reads the manifest dynamically and runs every scenario independently. A pilot comparison of two rows that differed only in traffic rate produced different positions, so scenario traces are never reused across manifest rows. NetAnim packet tracing is disabled during mobility collection to reduce disk use; the ns-3 DSR simulation, traffic, and mobility logger still run.

## Limitations

This dataset records node mobility only. It does not claim measured RSSI/SNR, packet delivery, route state, failure, or recovery. The geometry-derived neighbor count depends on the configured hard radio-range model. Relative speed by a topology-confirmed link is omitted until Step 2 topology is regenerated from these same scenario traces. Preserve the generation report alongside the CSV when using it in later stages.
