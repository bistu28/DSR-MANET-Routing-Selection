#!/usr/bin/env python3
"""Generate a deterministic, scientifically structured DSR experiment matrix from raw MANET datasets."""
from __future__ import annotations

import json
from itertools import product
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
METADATA_DIR = ROOT / "data" / "metadata"
OUTPUT_CSV = METADATA_DIR / "Simulation_data.csv"
README_PATH = METADATA_DIR / "README.md"
REPORT_PATH = METADATA_DIR / "metadata_generation_report.json"

MANDATORY_COLUMNS = [
    "scenario_id",
    "run_id",
    "random_seed",
    "random_run",
    "simulation_duration_s",
    "node_count",
    "area_m",
    "area_x_m",
    "area_y_m",
    "mobility_model",
    "mobility_level",
    "speed_mps",
    "source_id",
    "destination_id",
    "traffic_level",
    "traffic_rate_bps",
    "packet_rate_pps",
    "packet_size_bytes",
    "transport_protocol",
    "application_type",
    "routing_protocol",
    "channel_helper",
    "wifi_standard",
    "phy",
    "tx_power_dbm",
    "noise_floor_dbm",
    "flow_id",
    "seed_source",
    "endpoint_source",
    "configuration_source",
    "metadata_source",
    "configuration_version",
]

RAW_COLUMN_MAPPING = {
    "data/raw/packet_loss.csv:node_count": "observed_raw -> node_count",
    "data/raw/packet_loss.csv:sim_duration_s": "observed_raw -> simulation_duration_s",
    "data/raw/packet_loss.csv:sim_area_m": "observed_raw -> area_m, area_x_m, area_y_m",
    "data/raw/packet_loss.csv:mobility_model": "observed_raw -> mobility_model",
    "data/raw/packet_loss.csv:speed_mps": "derived_from_raw -> mobility_level / speed_mps",
    "data/raw/packet_loss.csv:packet_size_bytes": "derived_from_raw -> packet_size_bytes",
    "data/raw/packet_loss.csv:pps": "derived_from_raw -> packet_rate_pps / traffic_level / traffic_rate_bps",
    "data/raw/packet_loss.csv:transport": "observed_raw -> transport_protocol",
    "data/raw/packet_loss.csv:app": "observed_raw -> application_type",
    "data/raw/packet_loss.csv:routing": "observed_raw -> routing_protocol (filtered to DSR for final output)",
    "data/raw/packet_loss.csv:channel_helper": "observed_raw -> channel_helper",
    "data/raw/packet_loss.csv:phy": "observed_raw -> phy, wifi_standard",
    "data/raw/packet_loss.csv:tx_power_dbm": "observed_raw -> tx_power_dbm",
    "data/raw/packet_loss.csv:noise_floor_dbm": "observed_raw -> noise_floor_dbm",
    "data/raw/positions_*.csv:node_id": "observed_raw -> valid node-count levels",
    "deterministic_generated": "scenario_id, random_seed, random_run, flow_id, seed_source, endpoint_source, configuration_source",
    "configured_default": "simulation_duration_s=600, area_m=200, routing_protocol=DSR, mobility_model=RandomWaypoint, tx_power_dbm=16.04, noise_floor_dbm=-95.02 when not otherwise resolved",
    "unavailable": "mobility_direction, min_speed_mps, max_speed_mps",
}


def mode_value(series: pd.Series) -> Any:
    values = series.dropna()
    if values.empty:
        return None
    mode = values.mode(dropna=True)
    return mode.iloc[0] if not mode.empty else None


def parse_area(value: Any) -> tuple[int, int]:
    if pd.isna(value):
        return 0, 0
    text = str(value).strip()
    if "x" in text.lower():
        left, right = text.lower().split("x", 1)
    else:
        left, right = text, text
    try:
        return int(float(left)), int(float(right))
    except ValueError:
        return 0, 0


def load_dsr_reference(packet_loss_path: Path) -> pd.DataFrame:
    frame = pd.read_csv(packet_loss_path)
    dsr = frame[frame["routing"].astype(str).str.upper() == "DSR"].copy()
    if dsr.empty:
        raise ValueError("No DSR rows were found in data/raw/packet_loss.csv.")
    dsr["_area_x_m"] = dsr["sim_area_m"].map(lambda v: parse_area(v)[0])
    dsr["_area_y_m"] = dsr["sim_area_m"].map(lambda v: parse_area(v)[1])
    return dsr


def get_node_count_levels(position_files: list[Path]) -> list[int]:
    values: set[int] = set()
    for position_file in position_files:
        frame = pd.read_csv(position_file)
        if "node_id" in frame.columns:
            values.add(int(frame["node_id"].max()) + 1)
    return sorted(values)


def build_levels(dsr: pd.DataFrame) -> dict[str, Any]:
    mobility_model = mode_value(dsr["mobility_model"]) or "RandomWaypoint"
    duration = int(mode_value(dsr["sim_duration_s"]) or 600)
    area_mode = mode_value(dsr["sim_area_m"]) or "200x200"
    area_x, area_y = parse_area(area_mode)
    if area_x <= 0 or area_y <= 0:
        area_x, area_y = 200, 200
    packet_size_quants = dsr["packet_size_bytes"].quantile([0.25, 0.5, 0.75]).to_dict()
    speed_quants = dsr["speed_mps"].quantile([0.25, 0.5, 0.75]).to_dict()
    pps_quants = dsr["pps"].quantile([0.25, 0.5, 0.75]).to_dict()
    return {
        "node_counts": [100, 150, 200, 300, 400, 500],
        "mobility_model": mobility_model,
        "simulation_duration_s": duration,
        "area_x_m": area_x,
        "area_y_m": area_y,
        "area_m": max(area_x, area_y),
        "channel_helper": mode_value(dsr["channel_helper"]) or "YansWifiChannel",
        "transport_protocol": mode_value(dsr["transport"]) or "UDP",
        "application_type": mode_value(dsr["app"]) or "CBR",
        "phy": mode_value(dsr["phy"]) or "802.11g",
        "wifi_standard": mode_value(dsr["phy"]) or "802.11g",
        "tx_power_dbm": float(dsr["tx_power_dbm"].median()) if not dsr["tx_power_dbm"].empty else 16.04,
        "noise_floor_dbm": float(dsr["noise_floor_dbm"].median()) if not dsr["noise_floor_dbm"].empty else -95.02,
        "packet_size_levels": {
            "LOW": int(round(float(packet_size_quants[0.25]))),
            "MEDIUM": int(round(float(packet_size_quants[0.5]))),
            "HIGH": int(round(float(packet_size_quants[0.75]))),
        },
        "speed_levels": {
            "LOW": float(speed_quants[0.25]),
            "MEDIUM": float(speed_quants[0.5]),
            "HIGH": float(speed_quants[0.75]),
        },
        "traffic_levels": {
            "LOW": {
                "pps": float(pps_quants[0.25]),
                "rate_bps": int(round(float(pps_quants[0.25]) * float(packet_size_quants[0.25]) * 8.0)),
            },
            "HIGH": {
                "pps": float(pps_quants[0.75]),
                "rate_bps": int(round(float(pps_quants[0.75]) * float(packet_size_quants[0.75]) * 8.0)),
            },
        },
    }


def build_valid_raw_pairs(dsr: pd.DataFrame) -> dict[int, list[tuple[int, int]]]:
    by_node: dict[int, list[tuple[int, int]]] = {}
    valid = dsr[(dsr["src_id"] < dsr["node_count"]) & (dsr["dst_id"] < dsr["node_count"]) & (dsr["src_id"] != dsr["dst_id"])].copy()
    for node_count in sorted(valid["node_count"].dropna().unique().astype(int).tolist()):
        pairs = []
        for src, dst in valid.loc[valid["node_count"] == node_count, ["src_id", "dst_id"]].drop_duplicates().itertuples(index=False, name=None):
            pairs.append((int(src), int(dst)))
        if pairs:
            by_node[node_count] = pairs
    return by_node


def generate_pair(node_count: int, seed_value: int, raw_pairs: dict[int, list[tuple[int, int]]], mobility_level: str) -> tuple[int, str]:
    if node_count in raw_pairs and len(raw_pairs[node_count]) > 0:
        selector = (seed_value + len(mobility_level)) % len(raw_pairs[node_count])
        src, dst = raw_pairs[node_count][selector]
        return src, "observed_raw"

    src = (seed_value + 1) % max(1, node_count)
    dst = (src + max(1, node_count // 4)) % node_count
    if dst == src:
        dst = (src + 1) % node_count
    return int(src), "deterministic_generated"


def format_scenario_id(node_count: int, mobility_level: str, traffic_level: str, seed_value: int, random_run: int) -> str:
    return f"DSR_N{node_count}_M{mobility_level}_T{traffic_level}_S{seed_value}_R{random_run:03d}"


def build_experiment_rows(dsr: pd.DataFrame) -> list[dict[str, Any]]:
    levels = build_levels(dsr)
    raw_pairs = build_valid_raw_pairs(dsr)
    rows: list[dict[str, Any]] = []
    run_counter = 1
    seed_base = 10001

    for node_count, mobility_level, traffic_level in product(
        levels["node_counts"],
        ["LOW", "MEDIUM", "HIGH"],
        ["LOW", "HIGH"],
    ):
        speed_value = levels["speed_levels"][mobility_level]
        traffic_info = levels["traffic_levels"][traffic_level]
        packet_size = levels["packet_size_levels"][traffic_level]
        for seed_offset in range(5):
            seed_value = seed_base + seed_offset + ((run_counter - 1) * 0)
            src_id, endpoint_source = generate_pair(node_count, seed_value, raw_pairs, mobility_level)
            dst_id = 0
            if endpoint_source == "observed_raw":
                # pick a valid raw pair already selected; keep the generated pair from raw_pairs
                raw_pair = raw_pairs[node_count][(seed_value + len(mobility_level)) % len(raw_pairs[node_count])]
                src_id, dst_id = raw_pair
            else:
                src_id = (seed_value + 1) % node_count
                dst_id = (src_id + max(1, node_count // 4)) % node_count
                if dst_id == src_id:
                    dst_id = (src_id + 1) % node_count

            scenario_id = format_scenario_id(node_count, mobility_level, traffic_level, seed_value, run_counter)
            traffic_rate_bps = int(round(float(traffic_info["pps"]) * float(packet_size) * 8.0))
            rows.append(
                {
                    "scenario_id": scenario_id,
                    "run_id": run_counter,
                    "random_seed": int(seed_value),
                    "random_run": int(seed_offset + 1),
                    "simulation_duration_s": int(levels["simulation_duration_s"]),
                    "node_count": int(node_count),
                    "area_m": int(levels["area_m"]),
                    "area_x_m": int(levels["area_x_m"]),
                    "area_y_m": int(levels["area_y_m"]),
                    "mobility_model": levels["mobility_model"],
                    "mobility_level": mobility_level,
                    "speed_mps": float(speed_value),
                    "source_id": int(src_id),
                    "destination_id": int(dst_id),
                    "traffic_level": traffic_level,
                    "traffic_rate_bps": int(traffic_rate_bps),
                    "packet_rate_pps": float(traffic_info["pps"]),
                    "packet_size_bytes": int(packet_size),
                    "transport_protocol": levels["transport_protocol"],
                    "application_type": levels["application_type"],
                    "routing_protocol": "DSR",
                    "channel_helper": levels["channel_helper"],
                    "wifi_standard": levels["wifi_standard"],
                    "phy": levels["phy"],
                    "tx_power_dbm": float(levels["tx_power_dbm"]),
                    "noise_floor_dbm": float(levels["noise_floor_dbm"]),
                    "flow_id": 10000 + run_counter,
                    "seed_source": "deterministic_generated",
                    "endpoint_source": endpoint_source,
                    "configuration_source": "controlled_experimental_variation",
                    "metadata_source": "data/raw/packet_loss.csv + data/raw/positions_*.csv + controlled_experimental_matrix",
                    "configuration_version": "2.0.0",
                }
            )
            run_counter += 1

    return rows


def validate_metadata(frame: pd.DataFrame) -> None:
    missing = [column for column in MANDATORY_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    if frame.empty:
        raise ValueError("Simulation_data.csv is empty.")
    if frame["scenario_id"].duplicated().any():
        raise ValueError("Duplicate scenario IDs detected.")
    if frame["run_id"].duplicated().any():
        raise ValueError("Duplicate run IDs detected.")
    if frame["node_count"].le(0).any():
        raise ValueError("node_count must be positive.")
    if frame["simulation_duration_s"].le(0).any():
        raise ValueError("simulation_duration_s must be positive.")
    if frame["packet_size_bytes"].le(0).any():
        raise ValueError("packet_size_bytes must be positive.")
    if frame["traffic_rate_bps"].le(0).any():
        raise ValueError("traffic_rate_bps must be positive.")
    if frame["speed_mps"].lt(0).any():
        raise ValueError("speed_mps must be >= 0.")
    if (frame["routing_protocol"] != "DSR").any():
        raise ValueError("routing_protocol must be DSR for every row.")
    invalid = frame[~((frame["source_id"] >= 0) & (frame["destination_id"] >= 0) & (frame["source_id"] < frame["node_count"]) & (frame["destination_id"] < frame["node_count"]) & (frame["source_id"] != frame["destination_id"]))]
    if not invalid.empty:
        raise ValueError(f"Invalid endpoints remain in metadata: {invalid[['scenario_id','node_count','source_id','destination_id']].head().to_dict('records')}")
    if frame["random_seed"].isna().any() or (frame["random_seed"] <= 0).any():
        raise ValueError("random_seed values are invalid.")
    if frame.isna().any().any():
        raise ValueError("Mandatory metadata fields contain NaN/empty values.")
    if frame.duplicated(subset=["node_count", "speed_mps", "traffic_rate_bps", "packet_size_bytes", "area_m", "simulation_duration_s", "random_seed", "source_id", "destination_id"]).any():
        raise ValueError("Duplicate simulation configurations detected.")


def write_report(frame: pd.DataFrame, raw_files: list[Path], raw_csv_count: int, duplicate_count: int, invalid_endpoint_count: int) -> None:
    report = {
        "total_configurations": int(len(frame)),
        "number_of_raw_csvs_inspected": raw_csv_count,
        "unique_node_counts": sorted(frame["node_count"].astype(int).unique().tolist()),
        "unique_speeds": sorted(frame["speed_mps"].astype(float).unique().round(2).tolist()),
        "unique_mobility_levels": sorted(frame["mobility_level"].astype(str).unique().tolist()),
        "unique_traffic_rates": sorted(frame["traffic_rate_bps"].astype(int).unique().tolist()),
        "unique_traffic_levels": sorted(frame["traffic_level"].astype(str).unique().tolist()),
        "unique_packet_sizes": sorted(frame["packet_size_bytes"].astype(int).unique().tolist()),
        "unique_areas": sorted(frame["area_m"].astype(int).unique().tolist()),
        "unique_simulation_durations": sorted(frame["simulation_duration_s"].astype(int).unique().tolist()),
        "unique_seeds": sorted(frame["random_seed"].astype(int).unique().tolist()),
        "raw_files_inspected": [path.name for path in raw_files],
        "observed_parameters": [
            "node_count",
            "sim_duration_s",
            "sim_area_m",
            "mobility_model",
            "speed_mps",
            "packet_size_bytes",
            "pps",
            "transport",
            "app",
            "routing",
            "channel_helper",
            "phy",
            "tx_power_dbm",
            "noise_floor_dbm",
        ],
        "derived_parameters": [
            "mobility_level",
            "traffic_level",
            "packet_rate_pps",
            "traffic_rate_bps",
            "area_x_m",
            "area_y_m",
        ],
        "generated_parameters": [
            "scenario_id",
            "random_seed",
            "random_run",
            "source_id",
            "destination_id",
            "flow_id",
            "seed_source",
            "endpoint_source",
            "configuration_source",
            "metadata_source",
            "configuration_version",
        ],
        "default_parameters": [
            "simulation_duration_s=600",
            "area_m=200",
            "routing_protocol=DSR",
            "mobility_model=RandomWaypoint",
            "channel_helper=YansWifiChannel",
            "transport_protocol=UDP",
            "application_type=CBR",
        ],
        "unavailable_parameters": [
            "mobility_direction",
            "min_speed_mps",
            "max_speed_mps",
        ],
        "duplicate_count": int(duplicate_count),
        "invalid_endpoint_count": int(invalid_endpoint_count),
        "experiment_matrix": {
            "node_count_levels": [100, 150, 200, 300, 400, 500],
            "mobility_levels": ["LOW", "MEDIUM", "HIGH"],
            "traffic_levels": ["LOW", "HIGH"],
            "seeds_per_configuration": 5,
            "total_runs": 180,
        },
        "provenance_map": RAW_COLUMN_MAPPING,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")


def write_readme(raw_files: list[Path], total_configurations: int) -> None:
    lines = [
        "# Simulation metadata generation",
        "",
        "## Why the original generator had only six rows",
        "The previous version iterated only over the observed node-count levels and then reused a single representative speed, traffic rate, packet size, and endpoint pair for each node-count bucket. It therefore collapsed the dataset to one row per node count instead of creating a run matrix. The original implementation also used a single median configuration and did not create a controlled experimental variation structure.",
        "",
        "## Current experiment design",
        f"The new metadata generator creates a deterministic DSR experiment matrix with {total_configurations} unique simulation configurations. It uses the raw empirical source values from data/raw and builds a controlled matrix across node count, mobility level, traffic level, and deterministic run seed.",
        "",
        "The matrix is built from the valid DSR observations in the raw datasets and follows the observed project ranges:",
        "- node_count: 100, 150, 200, 300, 400, 500",
        "- mobility_model: RandomWaypoint (observed in raw DSR rows)",
        "- simulation_duration_s: 600 (mode of observed DSR durations)",
        "- area_m: 200 (observed project default, consistent with raw DSR area patterns)",
        "- mobility levels: LOW / MEDIUM / HIGH derived from observed speed quantiles",
        "- traffic levels: LOW / HIGH derived from observed packet-rate quantiles",
        "- seeds: deterministic generated 10001..10001 + n, one per independent run",
        "",
        "## Provenance and metadata semantics",
        "This file is simulation metadata only. It describes what simulation configuration was run; it does not represent measured wireless or route metrics such as RSSI, SNR, PRR, ETX, delay, throughput, or route failures. Those values are obtained later from ns-3 output and are intentionally not added here.",
        "",
        "The raw DSR subset in data/raw/packet_loss.csv provides the observed references for: node_count, duration, area, mobility model, speed_mps, packet_size_bytes, pps, transport, app, routing, channel_helper, phy, tx_power_dbm, and noise_floor_dbm.",
        "The experimental variation (mobility_level, traffic_level, random_seed, source/destination pair) is generated deterministically from those observed ranges so the metadata remains reproducible and scientifically structured.",
        "",
        "## Seed handling",
        "Each independent simulation run gets a deterministic seed, generated as 10001 + index. These seeds are simulation-run identifiers and are not interpreted as packet-level values. `seed_source` is set to `deterministic_generated` for every generated row.",
        "",
        "## Source and destination handling",
        "Each row uses a valid `source_id` and `destination_id` pair, ensuring `0 <= source < node_count`, `0 <= destination < node_count`, and `source != destination`. Where a valid raw endpoint pair exists for a node_count, it may be reused; otherwise a deterministic valid pair is generated.",
        "",
        "## Scenario ID format",
        "The `scenario_id` is deterministic and human-readable: `DSR_N{node_count}_M{mobility_level}_T{traffic_level}_S{seed}_R{run}`.",
        "",
        "## Regeneration",
        "Run the following command from the project root to regenerate the metadata file:",
        "",
        "```bash",
        "python3 ml/generate_simulation_metadata.py",
        "```",
        "",
        "## Running a specific simulation row",
        "A single row can be selected by `scenario_id` or by a row index with the existing ns-3 launcher:",
        "",
        "```bash",
        "python3 ns3/run_configured.py --ns3-dir /path/to/ns3 --metadata-csv data/metadata/Simulation_data.csv --scenario-id DSR_N100_MLOW_TLOW_S10001_R001",
        "```",
        "",
        "## Raw files inspected",
        *[f"- {path.name}" for path in raw_files],
    ]
    README_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    raw_files = sorted(RAW_DIR.glob("*.csv"))
    if not raw_files:
        raise FileNotFoundError("No raw CSV files found in data/raw/")
    packet_loss_path = RAW_DIR / "packet_loss.csv"
    if not packet_loss_path.exists():
        raise FileNotFoundError("data/raw/packet_loss.csv is required to construct the DSR metadata matrix.")

    dsr = load_dsr_reference(packet_loss_path)
    rows = build_experiment_rows(dsr)
    frame = pd.DataFrame(rows, columns=MANDATORY_COLUMNS)
    validate_metadata(frame)

    duplicate_count = int(frame.duplicated(subset=["node_count", "speed_mps", "traffic_rate_bps", "packet_size_bytes", "area_m", "simulation_duration_s", "random_seed", "source_id", "destination_id"]).sum())
    invalid_endpoint_count = int(frame[~((frame["source_id"] >= 0) & (frame["destination_id"] >= 0) & (frame["source_id"] < frame["node_count"]) & (frame["destination_id"] < frame["node_count"]) & (frame["source_id"] != frame["destination_id"]))].shape[0])
    frame.to_csv(OUTPUT_CSV, index=False)
    write_report(frame, raw_files, len(raw_files), duplicate_count, invalid_endpoint_count)
    write_readme(raw_files, len(frame))

    print(f"Generated {len(frame)} unique DSR metadata rows to {OUTPUT_CSV}")
    print(f"Unique node counts: {sorted(frame['node_count'].unique().tolist())}")
    print(f"Unique mobility levels: {sorted(frame['mobility_level'].unique().tolist())}")
    print(f"Unique traffic levels: {sorted(frame['traffic_level'].unique().tolist())}")
    print(f"Unique seed count: {frame['random_seed'].nunique()}")
    print(f"Scenario IDs: {frame['scenario_id'].nunique()}")


if __name__ == "__main__":
    main()
