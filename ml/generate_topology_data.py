#!/usr/bin/env python3
"""Generate compact, scenario-keyed topology from validated mobility traces."""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.neighbors import KDTree

ROOT = Path(__file__).resolve().parent.parent
METADATA_PATH = ROOT / "data" / "metadata" / "Simulation_data.csv"
MOBILITY_PATH = ROOT / "data" / "mobility" / "Mobility_data.csv"
TOPOLOGY_DIR = ROOT / "data" / "topology"
DEFAULT_TOPOLOGY_PATH = TOPOLOGY_DIR / "Topology_data.csv"
README_PATH = TOPOLOGY_DIR / "README.md"
REPORT_PATH = TOPOLOGY_DIR / "topology_generation_report.json"
DEFAULT_MAX_RANGE_M = 250.0
DEFAULT_OBSERVATION_INTERVAL_S = 1.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate topology data from actual mobility traces for DSR metadata scenarios.")
    parser.add_argument("--metadata-csv", type=Path, default=METADATA_PATH, help="Simulation_data.csv to process")
    parser.add_argument("--mobility-csv", type=Path, default=MOBILITY_PATH, help="Scenario-keyed mobility CSV to process")
    parser.add_argument("--scenario-id", type=str, help="Select one scenario ID to process")
    parser.add_argument("--all", action="store_true", help="Process all scenarios from the metadata CSV")
    parser.add_argument("--limit", type=int, help="Process the first N manifest scenarios")
    parser.add_argument("--resume", action="store_true", help="Keep validated topology rows and skip scenarios already present")
    parser.add_argument("--replace-existing", action="store_true", help="Build a fresh dataset and replace output only after successful validation")
    parser.add_argument("--observation-interval", type=float, default=DEFAULT_OBSERVATION_INTERVAL_S, help="Topology sampling interval in seconds")
    parser.add_argument("--max-range-m", type=float, default=DEFAULT_MAX_RANGE_M, help="Propagation range used for candidate connectivity")
    parser.add_argument("--minimum-free-space-gb", type=float, default=5.0, help="Stop if less free disk space remains")
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_TOPOLOGY_PATH, help="Destination CSV for topology rows")
    return parser.parse_args()


def build_topology_rows_for_scenario(
    row: dict[str, Any], positions: pd.DataFrame, obs_interval_s: float, max_range_m: float
) -> list[dict[str, Any]]:
    metadata = row
    node_count = int(metadata["node_count"])
    scenario_id = str(metadata["scenario_id"])
    run_id = int(metadata["run_id"])
    random_seed = int(metadata["random_seed"])
    random_run = int(metadata["random_run"])
    mobility_model = str(metadata["mobility_model"])
    simulation_duration_s = float(metadata["simulation_duration_s"])
    expected_records = int(node_count * (simulation_duration_s / obs_interval_s + 1))
    if len(positions) != expected_records:
        raise ValueError(f"Expected {expected_records} mobility rows for {scenario_id}, found {len(positions)}.")
    for column, expected in (("run_id", run_id), ("random_seed", random_seed), ("random_run", random_run)):
        if not positions[column].eq(expected).all():
            raise ValueError(f"Mobility {column} differs from the manifest for {scenario_id}.")
    if not positions["scenario_id"].astype(str).eq(scenario_id).all():
        raise ValueError(f"Mobility scenario_id differs from the manifest for {scenario_id}.")
    if not positions["source_scenario_id"].astype(str).eq(scenario_id).all():
        raise ValueError(f"Mobility source_scenario_id differs from the manifest for {scenario_id}.")
    if not positions["source_run_id"].eq(run_id).all():
        raise ValueError(f"Mobility source_run_id differs from the manifest for {scenario_id}.")
    if not positions["node_id"].between(0, node_count - 1).all():
        raise ValueError(f"Invalid node IDs in mobility trace for {scenario_id}.")
    if not positions["x_m"].between(0, float(metadata["area_x_m"])).all() or not positions["y_m"].between(0, float(metadata["area_y_m"])).all():
        raise ValueError(f"Coordinates exceed manifest bounds for {scenario_id}.")

    hex_width = math.ceil(node_count / 4)
    expected_times = [index * obs_interval_s for index in range(int(simulation_duration_s / obs_interval_s) + 1)]
    observed_times = sorted(float(value) for value in positions["time_s"].unique())
    if len(observed_times) != len(expected_times) or any(
        not math.isclose(observed, expected, rel_tol=0.0, abs_tol=1e-6)
        for observed, expected in zip(observed_times, expected_times)
    ):
        raise ValueError(f"Time coverage does not match the manifest for {scenario_id}.")

    rows: list[dict[str, Any]] = []
    for time_s, snapshot in positions.groupby("time_s", sort=True):
        snapshot = snapshot.sort_values("node_id")
        node_ids = snapshot["node_id"].astype(int).to_numpy()
        if len(node_ids) != node_count or set(node_ids) != set(range(node_count)):
            raise ValueError(f"Node coverage is incomplete at t={time_s} for {scenario_id}.")
        coordinates = snapshot[["x_m", "y_m"]].to_numpy(dtype=float)
        tree = KDTree(coordinates)
        neighborhoods = tree.query_radius(coordinates, r=max_range_m, return_distance=False)
        for node_id, neighbor_indexes in zip(node_ids, neighborhoods):
            neighbor_ids = sorted(int(node_ids[index]) for index in neighbor_indexes if node_ids[index] != node_id)
            neighbor_bits = sum(1 << neighbor_id for neighbor_id in neighbor_ids)
            rows.append({
                "scenario_id": scenario_id,
                "run_id": run_id,
                "random_seed": random_seed,
                "random_run": random_run,
                "time_s": float(time_s),
                "node_id": int(node_id),
                "neighbor_count": len(neighbor_ids),
                "neighbor_ids_hex": format(neighbor_bits, f"0{hex_width}x"),
                "node_count": node_count,
            })
    return rows


def choose_scenarios(frame: pd.DataFrame, scenario_id: str | None, limit: int | None) -> list[dict[str, Any]]:
    if scenario_id is not None:
        matches = frame[frame["scenario_id"].astype(str) == scenario_id]
        if matches.empty:
            raise ValueError(f"Scenario {scenario_id} was not found in {METADATA_PATH}.")
        return matches.to_dict(orient="records")
    if limit is not None:
        if limit < 1:
            raise ValueError("--limit must be at least 1")
        return frame.head(limit).to_dict(orient="records")
    return frame.to_dict(orient="records")


def validate_topology(frame: pd.DataFrame, metadata_frame: pd.DataFrame) -> dict[str, int]:
    metadata_lookup = metadata_frame.set_index("scenario_id")
    duplicates = int(frame.duplicated(subset=["scenario_id", "time_s", "node_id"]).sum())
    invalid_node_ids = int((~frame["node_id"].between(0, frame["node_count"] - 1)).sum())
    missing_values = int(frame.isna().sum().sum())
    invalid_time_count = int((frame["time_s"] < 0).sum())
    scenario_missing = int((~frame["scenario_id"].isin(metadata_lookup.index)).sum())
    invalid_bitsets = 0
    neighbor_count_mismatches = 0
    mapping_mismatches = {key: 0 for key in ("run_id", "random_seed", "random_run")}
    for item in frame.itertuples(index=False):
        bits = int(item.neighbor_ids_hex, 16)
        invalid_bitsets += int(bits >> int(item.node_count) != 0 or bool(bits & (1 << int(item.node_id))))
        neighbor_count_mismatches += int(bits.bit_count() != int(item.neighbor_count))
    joined = frame[["scenario_id", "run_id", "random_seed", "random_run"]].drop_duplicates().join(
        metadata_lookup[["run_id", "random_seed", "random_run"]], on="scenario_id", rsuffix="_manifest"
    )
    for key in mapping_mismatches:
        mapping_mismatches[key] = int((~joined[key].eq(joined[f"{key}_manifest"])).sum())
    return {
        "duplicate_count": duplicates,
        "invalid_node_count": invalid_node_ids,
        "invalid_neighbor_bitset_count": invalid_bitsets,
        "neighbor_count_mismatch_count": neighbor_count_mismatches,
        "missing_value_count": missing_values,
        "invalid_time_count": invalid_time_count,
        "scenario_missing_count": scenario_missing,
        **{f"{key}_mismatch_count": value for key, value in mapping_mismatches.items()},
    }


def write_report(frame: pd.DataFrame, metadata_frame: pd.DataFrame, observation_interval_s: float, max_range_m: float, scenarios_completed: int, scenarios_failed: list[dict[str, Any]], report_path: Path) -> None:
    report = {
        "number_of_simulations": int(metadata_frame.shape[0]),
        "scenarios_completed_this_run": int(scenarios_completed),
        "number_of_node_time_observations_this_run": int(len(frame)),
        "observation_interval_s": float(observation_interval_s),
        "minimum_neighbor_count": int(frame["neighbor_count"].min()) if not frame.empty else 0,
        "maximum_neighbor_count": int(frame["neighbor_count"].max()) if not frame.empty else 0,
        "mean_neighbor_count": float(frame["neighbor_count"].mean()) if not frame.empty else 0.0,
        "scenarios_completed": int(scenarios_completed),
        "scenarios_failed": [
            {
                "scenario_id": item["scenario_id"],
                "error": item["error"],
                "reason": item["reason"],
            }
            for item in scenarios_failed
        ],
        "metadata_reference": str(METADATA_PATH.relative_to(ROOT)),
        "mobility_reference": str(MOBILITY_PATH.relative_to(ROOT)),
        "connectivity_source": "scenario_mobility_radio_range_geometry",
        "radio_range_m": float(max_range_m),
        "neighbor_encoding": "neighbor_ids_hex: bit i is set iff node i is a neighbor; decode with int(value, 16)",
        "topology_schema": [
            "scenario_id",
            "run_id",
            "random_seed",
            "random_run",
            "time_s",
            "node_id",
            "neighbor_count",
            "neighbor_ids_hex",
            "node_count",
        ],
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def write_readme(readme_path: Path) -> None:
    lines = [
        "# MANET topology data",
        "",
        "This dataset is generated from each scenario's validated `data/mobility/Mobility_data.csv` positions and the configured 250 m ns-3 radio range. It does not use the unmapped legacy `data/raw/positions_*.csv` files.",
        "",
        "## What this dataset represents",
        "- One row represents one node at one scenario/time observation.",
        "- `neighbor_ids_hex` is a lossless adjacency bitset: bit i is set exactly when node i is within `max_range_m` of this row's node. Decode the neighbor IDs with `int(neighbor_ids_hex, 16)` and enumerate set bit positions.",
        "- `neighbor_count` is the number of set bits. Self-links are excluded.",
        "- This is geometry-derived candidate connectivity, not measured RF quality or DSR route-state data.",
        "",
        "`scenario_id`, `run_id`, `random_seed`, and `random_run` are copied from the manifest and checked against the mobility rows before graph construction. The generation report maps each scenario to its exact source trace and records the shared radio range and sampling interval.",
        "",
        "## Regeneration",
        "Run the generator from the project root:",
        "",
        "```bash",
        "python3 ml/generate_topology_data.py --all --mobility-csv data/mobility/Mobility_data.csv --replace-existing",
        "```",
        "",
        "## Limitations",
        "- This dataset does not include RSSI, SNR, PRR, ETX, route IDs, or route failures.",
        "- Existing output requires explicit `--resume` or `--replace-existing`; canonical replacement requires `Topology_data_backup.csv`.",
        "- Bitsets preserve exact neighbor IDs while avoiding the infeasible expansion of dense graphs into billions of CSV edge rows.",
    ]
    readme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    TOPOLOGY_DIR.mkdir(parents=True, exist_ok=True)
    metadata = pd.read_csv(args.metadata_csv)
    required = {"scenario_id", "run_id", "random_seed", "random_run", "node_count", "area_x_m", "area_y_m", "mobility_model", "simulation_duration_s"}
    if metadata.empty or metadata["scenario_id"].duplicated().any() or required - set(metadata.columns):
        raise ValueError("Metadata must contain unique scenarios and all topology configuration fields.")
    if args.observation_interval <= 0 or args.max_range_m <= 0 or args.minimum_free_space_gb <= 0:
        raise ValueError("Observation interval, radio range, and minimum free space must be positive.")
    if args.all and (args.scenario_id or args.limit):
        raise ValueError("--all cannot be combined with --scenario-id or --limit")
    if args.resume and args.replace_existing:
        raise ValueError("--resume and --replace-existing cannot be combined")
    scenarios = choose_scenarios(metadata, args.scenario_id, args.limit)
    selected_by_id = {str(row["scenario_id"]): row for row in scenarios}
    expected_rows = {
        sid: int(row["node_count"] * (float(row["simulation_duration_s"]) / args.observation_interval + 1))
        for sid, row in selected_by_id.items()
    }
    output_path = args.output_csv.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not (args.resume or args.replace_existing):
        raise ValueError("Output already exists; pass --resume or --replace-existing to preserve scenarios explicitly.")
    if args.replace_existing and output_path == DEFAULT_TOPOLOGY_PATH.resolve():
        backup_path = output_path.with_name("Topology_data_backup.csv")
        if not backup_path.is_file():
            raise ValueError(f"Refusing replacement without the required backup: {backup_path}")
    if shutil.disk_usage(output_path.parent).free < args.minimum_free_space_gb * 1024**3:
        raise OSError(f"Stopping safely: insufficient free disk space at {output_path.parent}.")

    existing_scenarios: set[str] = set()
    report_path = REPORT_PATH if output_path == DEFAULT_TOPOLOGY_PATH.resolve() else output_path.parent / "topology_generation_report.json"
    source_trace_by_scenario: dict[str, str] = {}
    if args.resume and output_path.exists():
        existing = pd.read_csv(output_path, usecols=["scenario_id", "run_id", "random_seed", "random_run"])
        existing_keys = existing[["scenario_id", "run_id", "random_seed", "random_run"]].drop_duplicates()
        expected_keys = metadata.set_index("scenario_id")[["run_id", "random_seed", "random_run"]]
        joined = existing_keys.join(expected_keys, on="scenario_id", rsuffix="_manifest")
        if joined.isna().any().any() or any(not joined[key].eq(joined[f"{key}_manifest"]).all() for key in ("run_id", "random_seed", "random_run")):
            raise ValueError("Existing topology output cannot be safely resumed; keys or mobility provenance do not match.")
        if not report_path.is_file():
            raise ValueError(f"Cannot resume topology without its provenance report: {report_path}")
        prior_report = json.loads(report_path.read_text(encoding="utf-8"))
        source_trace_by_scenario = {
            str(sid): str(filename) for sid, filename in prior_report.get("source_trace_by_scenario", {}).items()
        }
        if not set(existing["scenario_id"].astype(str)).issubset(source_trace_by_scenario):
            raise ValueError("Existing topology scenarios are missing source-trace provenance in the report.")
        counts = existing.groupby("scenario_id").size()
        existing_scenarios = {
            str(sid) for sid, count in counts.items()
            if sid in expected_rows and int(count) == expected_rows[sid]
        }
        selected_by_id = {sid: row for sid, row in selected_by_id.items() if sid not in existing_scenarios}
        expected_rows = {sid: expected_rows[sid] for sid in selected_by_id}
        if not selected_by_id:
            print("All selected scenarios already have complete, manifest-matched topology rows.")
            return

    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()
    if args.resume and output_path.exists():
        shutil.copy2(output_path, temporary_path)
    first_output = not temporary_path.exists()
    completed = 0
    total_rows = 0
    pending: dict[str, pd.DataFrame] = {}
    input_columns = ["scenario_id", "run_id", "random_seed", "random_run", "time_s", "node_id", "x_m", "y_m", "source_scenario_id", "source_run_id", "source_file"]
    try:
        for chunk in pd.read_csv(args.mobility_csv, usecols=input_columns, chunksize=300_000):
            for sid, part in chunk.groupby("scenario_id", sort=False):
                sid = str(sid)
                if sid not in selected_by_id:
                    continue
                pending[sid] = pd.concat([pending[sid], part], ignore_index=True) if sid in pending else part.copy()
                count = len(pending[sid])
                if count > expected_rows[sid]:
                    raise ValueError(f"Mobility has too many rows for scenario {sid}: {count}.")
                if count < expected_rows[sid]:
                    continue
                if shutil.disk_usage(output_path.parent).free < args.minimum_free_space_gb * 1024**3:
                    raise OSError(f"Stopping safely: less than {args.minimum_free_space_gb:.1f} GiB remains free.")
                scenario_positions = pending.pop(sid)
                source_trace_by_scenario[sid] = str(scenario_positions["source_file"].iloc[0])
                rows = build_topology_rows_for_scenario(
                    selected_by_id[sid], scenario_positions, args.observation_interval, args.max_range_m
                )
                topology_frame = pd.DataFrame(rows)
                validation = validate_topology(topology_frame, metadata)
                if any(validation.values()):
                    raise ValueError(f"Topology validation failed for {sid}: {validation}")
                topology_frame.to_csv(temporary_path, index=False, mode="w" if first_output else "a", header=first_output)
                first_output = False
                completed += 1
                total_rows += len(topology_frame)
                print(f"Validated {sid}: {len(topology_frame)} node-time rows, {topology_frame['time_s'].nunique()} times", flush=True)
        if pending:
            incomplete = {sid: len(frame) for sid, frame in pending.items()}
            raise ValueError(f"Mobility input ended before selected scenarios were complete: {incomplete}")
        if completed == 0:
            raise ValueError("No topology rows were generated.")
        os.replace(temporary_path, output_path)
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        raise

    summary = pd.DataFrame({"scenario_id": list(selected_by_id), "rows": [expected_rows[sid] for sid in selected_by_id]})
    report = {
        "manifest_scenario_count": int(len(metadata)),
        "scenarios_completed_this_run": completed,
        "node_time_observations_this_run": total_rows,
        "observation_interval_s": args.observation_interval,
        "radio_range_m": args.max_range_m,
        "connectivity_source": "scenario_mobility_radio_range_geometry",
        "neighbor_encoding": "neighbor_ids_hex, with bit i representing neighbor node i",
        "source_trace_by_scenario": source_trace_by_scenario,
        "input_mobility_csv": str(args.mobility_csv),
        "output_csv": str(output_path),
        "processed_scenario_ids": summary["scenario_id"].tolist(),
        "status": "PASS" if completed == len(selected_by_id) else "FAIL",
    }
    readme_path = README_PATH if output_path == DEFAULT_TOPOLOGY_PATH.resolve() else output_path.parent / "README.md"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_readme(readme_path)
    print(f"Generated topology node-time rows this run: {total_rows}")
    print(f"Scenarios processed this run: {completed}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
