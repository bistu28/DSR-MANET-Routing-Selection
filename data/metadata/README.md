# MANET raw-factor extraction metadata

This directory contains the raw-factor inventory extracted from the project CSVs in `data/raw/` and the geometry-derived topology file in `data/topology/Topology_data.csv`.

## Scope
The extraction keeps only factors that are genuinely present or clearly derived from project source files.

## Included topology data
The topology CSV contributes `scenario_id`, `run_id`, `random_seed`, `random_run`, `neighbor_id`, `link_src_id`, `link_dst_id`, `link_id`, `link_exists`, `connectivity_source`, `node_count`, `mobility_model`, and `observation_interval_s`.
These are not RF measurements or DSR route events; they are geometry-derived adjacency and connectivity values.

## Data quality and provenance
- All rows retain `source_file` and original run identifiers.
- No raw files were modified.
- No missing DSR route-state fields were fabricated.

