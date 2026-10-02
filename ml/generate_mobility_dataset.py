#!/usr/bin/env python3
"""Generate scenario-keyed mobility observations from configured ns-3 runs."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import gzip
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

import numpy as np
import pandas as pd
from sklearn.neighbors import KDTree

ROOT = Path(__file__).resolve().parent.parent
METADATA_PATH = ROOT / "data" / "metadata" / "Simulation_data.csv"
DATA_DIRS = ("raw", "cleaned", "processed", "final", "topology", "metadata")
OUTPUT_DIR = ROOT / "data" / "mobility"
OUTPUT_PATH = OUTPUT_DIR / "Mobility_data.csv"
README_PATH = OUTPUT_DIR / "README.md"
REPORT_PATH = OUTPUT_DIR / "mobility_generation_report.json"
TRACE_ARCHIVE = ROOT / "ns3" / "results" / "mobility_traces"
SAMPLE_INTERVAL_S = 1.0
DEFAULT_RANDOM_WAYPOINT_PAUSE_S = 2.0
MOBILITY_KEY = (
    "node_count",
    "area_x_m",
    "area_y_m",
    "mobility_model",
    "speed_mps",
    "random_seed",
    "random_run",
    "simulation_duration_s",
)
OUTPUT_COLUMNS = [
    "scenario_id",
    "run_id",
    "random_seed",
    "random_run",
    "time_s",
    "node_id",
    "x_m",
    "y_m",
    "speed_mps",
    "velocity_x_mps",
    "velocity_y_mps",
    "direction_deg",
    "distance_moved_m",
    "acceleration_mps2",
    "relative_speed_mps",
    "distance_to_nearest_neighbor_m",
    "neighbor_count",
    "node_count",
    "mobility_model",
    "area_m",
    "traffic_rate_bps",
    "packet_size_bytes",
    "source_id",
    "destination_id",
    "routing_protocol",
    "wifi_standard",
    "channel_helper",
    "tx_power_dbm",
    "noise_floor_dbm",
    "transport_protocol",
    "application_type",
    "flow_id",
    "speed_limit_mps",
    "mobility_pause_s",
    "area_x_m",
    "area_y_m",
    "simulation_duration_s",
    "sampling_interval_s",
    "source_dataset",
    "source_file",
    "source_scenario_id",
    "source_run_id",
    "source_time_s",
    "source_type",
    "provenance_note",
]
REQUIRED_COLUMNS = (
    "scenario_id",
    "run_id",
    "random_seed",
    "random_run",
    "time_s",
    "node_id",
    "x_m",
    "y_m",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ns3-dir", type=Path, required=True, help="Built ns-3 checkout containing ./ns3")
    parser.add_argument("--metadata-csv", type=Path, default=METADATA_PATH)
    parser.add_argument("--scenario-id", help="Process one scenario_id")
    parser.add_argument("--limit", type=int, help="Process the first N manifest scenarios")
    parser.add_argument("--all", action="store_true", help="Process all manifest scenarios")
    parser.add_argument("--resume", action="store_true", help="Keep validated output rows and skip scenarios already present")
    parser.add_argument("--replace-existing", action="store_true", help="Build a fresh dataset and replace output only after successful validation")
    parser.add_argument("--sampling-interval-s", type=float, default=SAMPLE_INTERVAL_S)
    parser.add_argument("--minimum-free-space-gb", type=float, default=5.0, help="Stop before or during a batch if less free space remains")
    parser.add_argument("--output-csv", type=Path, default=OUTPUT_PATH)
    return parser.parse_args()


def _column(columns: list[str], names: tuple[str, ...]) -> str | None:
    lookup = {str(name).strip().lower(): str(name) for name in columns}
    return next((lookup[name] for name in names if name in lookup), None)


def inspect_data_sources(metadata: pd.DataFrame) -> tuple[list[dict[str, Any]], list[str]]:
    inventory: list[dict[str, Any]] = []
    warnings: list[str] = []
    for directory in DATA_DIRS:
        base = ROOT / "data" / directory
        files = sorted(path for path in base.rglob("*") if path.is_file()) if base.exists() else []
        if not files:
            inventory.append({"directory": f"data/{directory}", "status": "empty_or_missing"})
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            item: dict[str, Any] = {
                "file": relative,
                "bytes": path.stat().st_size,
                "rows": None,
                "columns": [],
                "node_identifier": None,
                "time_column": None,
                "position_columns": [],
                "speed_columns": [],
                "mobility_model_column": None,
                "run_identifier": None,
                "scenario_identifier": None,
                "mobility_candidate": False,
                "compatible_scenario_count": 0,
                "compatibility": "not a coordinate mobility source",
            }
            if path.suffix.lower() not in {".csv", ".tsv"}:
                item["file_type"] = path.suffix.lower() or "text"
                inventory.append(item)
                continue
            try:
                with path.open(newline="", encoding="utf-8-sig") as handle:
                    reader = csv.reader(handle)
                    columns = next(reader, [])
                    item["rows"] = sum(1 for _ in reader)
            except (OSError, UnicodeError, csv.Error) as exc:
                item["compatibility"] = f"unreadable: {type(exc).__name__}: {exc}"
                warnings.append(f"Could not inspect {relative}: {type(exc).__name__}: {exc}")
                inventory.append(item)
                continue

            item["columns"] = columns
            item["node_identifier"] = _column(columns, ("node_id", "node", "id"))
            item["time_column"] = _column(columns, ("time_s", "time", "timestamp"))
            x_column = _column(columns, ("x_m", "x", "position_x"))
            y_column = _column(columns, ("y_m", "y", "position_y"))
            item["position_columns"] = [value for value in (x_column, y_column) if value]
            item["speed_columns"] = [value for value in (_column(columns, ("speed_mps", "speed")),) if value]
            item["mobility_model_column"] = _column(columns, ("mobility_model", "mobility"))
            item["run_identifier"] = _column(columns, ("run_id", "run"))
            item["scenario_identifier"] = _column(columns, ("scenario_id",))
            item["mobility_candidate"] = bool(item["node_identifier"] and item["time_column"] and x_column and y_column)
            if item["mobility_candidate"]:
                source = pd.read_csv(path)
                time_values = pd.to_numeric(source[item["time_column"]], errors="coerce").dropna().sort_values().unique()
                x_values = pd.to_numeric(source[x_column], errors="coerce")
                y_values = pd.to_numeric(source[y_column], errors="coerce")
                item["observed_nodes"] = int(source[item["node_identifier"]].nunique())
                item["time_min_s"] = float(time_values[0]) if len(time_values) else None
                item["time_max_s"] = float(time_values[-1]) if len(time_values) else None
                item["time_sample_count"] = int(len(time_values))
                intervals = np.diff(time_values.astype(float))
                item["interval_values_s"] = sorted({float(value) for value in intervals})[:20]
                item["x_range_m"] = [float(x_values.min()), float(x_values.max())]
                item["y_range_m"] = [float(y_values.min()), float(y_values.max())]
                item["source_classification"] = "existing_simulation"
                item["compatibility"] = (
                    "incompatible: no scenario mapping for these coordinates; node counts, duration, "
                    "sampling cadence, model/seed provenance, or configured 200 m bounds do not match"
                )
            elif any(token in " ".join(columns).lower() for token in ("mobility", "neighbor", "position", "speed")):
                item["source_classification"] = "existing_simulation_or_provenance_unverified"
                item["compatibility"] = "incompatible: lacks time-keyed x/y coordinates with a demonstrated scenario mapping"
            inventory.append(item)

    candidates = [item for item in inventory if item.get("mobility_candidate")]
    if not candidates:
        warnings.append("No existing CSV contains time-keyed node positions that can be mapped to the manifest.")
    else:
        warnings.append("All existing coordinate sources were assessed as incompatible with the current DSR scenarios.")
    if (ROOT / "data" / "topology" / "Topology_data.csv").exists():
        warnings.append(
            "Topology_data.csv has nominal scenario keys but its generator selects raw positions by node count/seed modulo; "
            "those traces have 0-1000 m coordinates, 10 s cadence, and at most 500 s versus this manifest's 200 m, 1 s, 600 s RandomWaypoint runs."
        )
    return inventory, warnings


def read_radio_range_m() -> float:
    source = ROOT / "ns3" / "scratch" / "dsr_manet_dataset.cc"
    match = re.search(r'"MaxRange"\s*,\s*DoubleValue\((\d+(?:\.\d+)?)\)', source.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"Could not read RangePropagationLossModel MaxRange from {source}.")
    return float(match.group(1))


def select_scenarios(metadata: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    if args.sampling_interval_s <= 0:
        raise ValueError("sampling interval must be positive")
    if args.minimum_free_space_gb <= 0:
        raise ValueError("minimum free space must be positive")
    if args.all and (args.scenario_id or args.limit):
        raise ValueError("--all cannot be combined with --scenario-id or --limit")
    if args.resume and args.replace_existing:
        raise ValueError("--resume and --replace-existing cannot be combined")
    if args.scenario_id:
        selected = metadata[metadata["scenario_id"].astype(str) == args.scenario_id]
        if selected.empty:
            raise ValueError(f"Scenario not found in metadata: {args.scenario_id}")
        return selected.copy()
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("--limit must be at least 1")
        return metadata.head(args.limit).copy()
    return metadata.copy()


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    if not safe or safe in {".", ".."}:
        raise ValueError(f"Invalid scenario_id for output path: {value!r}")
    return safe


def _runtime_paths(ns3_dir: Path, scenario: pd.Series) -> tuple[Path, Path]:
    scenario_dir = ns3_dir / "results" / "scenarios" / _safe_id(str(scenario["scenario_id"]))
    trace = scenario_dir / "csv" / f"dsr_mobility_seed_{int(scenario['random_seed'])}_run_{int(scenario['random_run'])}.csv"
    return trace, scenario_dir / "logs" / f"simulation_seed_{int(scenario['random_seed'])}_run_{int(scenario['random_run'])}.log"


def _cache_matches(trace: Path, log_path: Path, scenario: pd.Series, sample_interval_s: float) -> bool:
    if not trace.is_file() or not log_path.is_file():
        return False
    log = log_path.read_text(encoding="utf-8", errors="replace")
    expected = {
        "scenario_id": str(scenario["scenario_id"]),
        "node_count": int(scenario["node_count"]),
        "simulation_time": float(scenario["simulation_duration_s"]),
        "area_size": float(scenario["area_x_m"]),
        "area_x_m": float(scenario["area_x_m"]),
        "area_y_m": float(scenario["area_y_m"]),
        "sampling_interval_s": sample_interval_s,
        "node_speed": float(scenario["speed_mps"]),
        "traffic_rate": f"{int(scenario['traffic_rate_bps'])}bps",
        "packet_size": int(scenario["packet_size_bytes"]),
        "source": int(scenario["source_id"]),
        "destination": int(scenario["destination_id"]),
        "random_seed": int(scenario["random_seed"]),
        "random_run": int(scenario["random_run"]),
        "run_id": int(scenario["run_id"]),
        "mobility_model": str(scenario["mobility_model"]),
        "routing_protocol": str(scenario["routing_protocol"]),
        "wifi_standard": str(scenario["wifi_standard"]),
        "channel_helper": str(scenario["channel_helper"]),
        "tx_power_dbm": float(scenario["tx_power_dbm"]),
        "noise_floor_dbm": float(scenario["noise_floor_dbm"]),
        "transport_protocol": str(scenario["transport_protocol"]),
        "application_type": str(scenario["application_type"]),
        "flow_id": int(scenario["flow_id"]),
        "udp_port": 9000,
        "radio_range_m": read_radio_range_m(),
        "animation_enabled": False,
        "mobility_pause_s": DEFAULT_RANDOM_WAYPOINT_PAUSE_S,
    }
    values = dict(line.split("=", 1) for line in log.splitlines() if "=" in line)
    if values.get("status") != "baseline_dsr_run_complete":
        return False
    for key, expected_value in expected.items():
        actual = values.get(key)
        if actual is None:
            return False
        if isinstance(expected_value, float):
            try:
                if not math.isclose(float(actual), expected_value, rel_tol=0.0, abs_tol=1e-9):
                    return False
            except ValueError:
                return False
        elif isinstance(expected_value, bool):
            if actual.lower() != str(expected_value).lower():
                return False
        elif actual != str(expected_value):
            return False
    try:
        sample = pd.read_csv(trace, nrows=1)
    except (OSError, ValueError, pd.errors.ParserError):
        return False
    return all(
        column in sample.columns and not sample.empty and int(sample.iloc[0][column]) == int(scenario[key])
        for column, key in (("run_id", "run_id"), ("random_seed", "random_seed"), ("random_run", "random_run"))
    )


def obtain_trace(ns3_dir: Path, metadata_path: Path, scenario: pd.Series, sample_interval_s: float) -> Path:
    trace, log_path = _runtime_paths(ns3_dir, scenario)
    archive_path = TRACE_ARCHIVE / f"{_safe_id(str(scenario['scenario_id']))}.csv.gz"
    if _cache_matches(archive_path, log_path, scenario, sample_interval_s):
        return archive_path
    if not _cache_matches(trace, log_path, scenario, sample_interval_s):
        if not (ns3_dir / "ns3").is_file():
            raise FileNotFoundError(f"ns-3 launcher not found: {ns3_dir / 'ns3'}")
        for source in sorted((ROOT / "ns3" / "scratch").glob("*.cc")):
            target = ns3_dir / "scratch" / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or source.read_bytes() != target.read_bytes():
                shutil.copy2(source, target)
        command = [
            sys.executable,
            str(ROOT / "ns3" / "run_configured.py"),
            "--ns3-dir",
            str(ns3_dir),
            "--metadata-csv",
            str(metadata_path),
            "--scenario-id",
            str(scenario["scenario_id"]),
            "--sampling-interval-s",
            str(sample_interval_s),
            "--program",
            "dsr_manet_dataset",
        ]
        print(f"Running ns-3 DSR mobility scenario {scenario['scenario_id']}...", flush=True)
        subprocess.run(command, cwd=ROOT, check=True)
    if not _cache_matches(trace, log_path, scenario, sample_interval_s):
        raise RuntimeError(f"ns-3 trace is missing or its logged configuration does not match {scenario['scenario_id']}.")
    return trace


def ensure_free_space(path: Path, minimum_free_space_gb: float) -> None:
    free_bytes = shutil.disk_usage(path.parent).free
    minimum_bytes = minimum_free_space_gb * 1024**3
    if free_bytes < minimum_bytes:
        raise OSError(
            f"Stopping safely: only {free_bytes / 1024**3:.2f} GiB free at {path.parent}; "
            f"minimum is {minimum_free_space_gb:.2f} GiB."
        )


def validate_existing_output(path: Path, metadata: pd.DataFrame, sample_interval_s: float) -> set[str]:
    if not path.exists():
        return set()
    identity = ["run_id", "random_seed", "random_run", "source_run_id"]
    exact_fields = [
        "node_count", "mobility_model", "area_m", "traffic_rate_bps", "packet_size_bytes", "source_id", "destination_id",
        "routing_protocol", "wifi_standard", "channel_helper", "transport_protocol", "application_type", "flow_id",
    ]
    float_fields = ["speed_limit_mps", "area_x_m", "area_y_m", "simulation_duration_s", "sampling_interval_s", "tx_power_dbm", "noise_floor_dbm"]
    required = ["scenario_id", *identity, *exact_fields, *float_fields, "source_scenario_id", "source_file", "source_type", "time_s", "node_id"]
    counts: dict[str, int] = {}
    manifest = metadata.set_index("scenario_id")
    for chunk in pd.read_csv(path, usecols=required, chunksize=250_000):
        if not chunk["scenario_id"].isin(manifest.index).all():
            raise ValueError(f"Resume output contains scenario IDs absent from the manifest: {path}")
        for column in identity:
            manifest_column = "run_id" if column == "source_run_id" else column
            expected = chunk["scenario_id"].map(manifest[manifest_column])
            if not chunk[column].eq(expected).all():
                raise ValueError(f"Resume output has a {column} mismatch: {path}")
        for column in exact_fields:
            if not chunk[column].eq(chunk["scenario_id"].map(manifest[column])).all():
                raise ValueError(f"Resume output has a {column} configuration mismatch: {path}")
        for column in float_fields:
            if not np.isclose(
                pd.to_numeric(chunk[column], errors="coerce"),
                pd.to_numeric(chunk["scenario_id"].map(manifest[column]), errors="coerce"),
                rtol=0.0,
                atol=1e-6,
                equal_nan=False,
            ).all():
                raise ValueError(f"Resume output has a {column} configuration mismatch: {path}")
        if not chunk["source_scenario_id"].eq(chunk["scenario_id"]).all() or not chunk["source_type"].eq("new_ns3_simulation").all():
            raise ValueError(f"Resume output has invalid source provenance: {path}")
        for scenario_id, source_file in chunk[["scenario_id", "source_file"]].drop_duplicates().itertuples(index=False, name=None):
            expected_source = TRACE_ARCHIVE / f"{_safe_id(str(scenario_id))}.csv.gz"
            if source_file != expected_source.relative_to(ROOT).as_posix():
                raise ValueError(f"Resume output references an unexpected trace for {scenario_id}.")
        counts.update({str(sid): counts.get(str(sid), 0) + int(count) for sid, count in chunk.groupby("scenario_id").size().items()})
    expected_counts = {
        str(row.scenario_id): int(row.node_count * (math.floor(float(row.simulation_duration_s) / sample_interval_s + 1e-9) + 1))
        for row in metadata.itertuples(index=False)
    }
    incomplete = {sid: (count, expected_counts.get(sid)) for sid, count in counts.items() if count != expected_counts.get(sid)}
    if incomplete:
        raise ValueError(f"Resume output contains incomplete scenarios: {incomplete}")
    return set(counts)


def archive_trace(trace: Path, scenario: pd.Series) -> Path:
    archive_path = TRACE_ARCHIVE / f"{_safe_id(str(scenario['scenario_id']))}.csv.gz"
    if trace == archive_path:
        return archive_path
    TRACE_ARCHIVE.mkdir(parents=True, exist_ok=True)
    with trace.open("rb") as source, archive_path.open("wb") as archive_file:
        with gzip.GzipFile(filename="", fileobj=archive_file, mode="wb", mtime=0) as compressed:
            shutil.copyfileobj(source, compressed)
    return archive_path


def _mobility_groups(selected: pd.DataFrame) -> list[tuple[pd.Series, list[pd.Series]]]:
    return [(pd.Series(row), [pd.Series(row)]) for _, row in selected.iterrows()]


def build_features(trace_path: Path, scenario: pd.Series, sample_interval_s: float, radio_range_m: float) -> pd.DataFrame:
    raw = pd.read_csv(trace_path)
    required = {"run_id", "time", "node_id", "x_m", "y_m", "random_seed", "random_run"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"Mobility trace missing columns: {sorted(missing)}")
    if not raw["random_seed"].eq(int(scenario["random_seed"])).all():
        raise ValueError("Trace seed differs from Simulation_data.csv")
    if not raw["random_run"].eq(int(scenario["random_run"])).all():
        raise ValueError("Trace random_run differs from Simulation_data.csv")
    if not raw["run_id"].eq(int(scenario["run_id"])).all():
        raise ValueError("Trace run_id differs from Simulation_data.csv")

    frame = raw[["time", "node_id", "x_m", "y_m"]].rename(columns={"time": "time_s"}).copy()
    for column in ("time_s", "node_id", "x_m", "y_m"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame[["time_s", "node_id", "x_m", "y_m"]].isna().any().any():
        raise ValueError("Trace contains missing or non-numeric time/node/position values")
    frame["node_id"] = frame["node_id"].astype(int)
    frame = frame.sort_values(["node_id", "time_s"], kind="stable").reset_index(drop=True)

    grouped = frame.groupby("node_id", sort=False)
    delta_time = grouped["time_s"].diff()
    delta_x = grouped["x_m"].diff()
    delta_y = grouped["y_m"].diff()
    valid_delta = delta_time.where(delta_time > 0)
    frame["velocity_x_mps"] = delta_x / valid_delta
    frame["velocity_y_mps"] = delta_y / valid_delta
    frame["speed_mps"] = np.hypot(frame["velocity_x_mps"], frame["velocity_y_mps"])
    frame["direction_deg"] = np.degrees(np.arctan2(frame["velocity_y_mps"], frame["velocity_x_mps"])) % 360.0
    frame.loc[frame["speed_mps"].isna() | frame["speed_mps"].le(1e-12), "direction_deg"] = np.nan
    frame["distance_moved_m"] = np.hypot(delta_x, delta_y)
    frame["acceleration_mps2"] = frame.groupby("node_id", sort=False)["speed_mps"].diff() / valid_delta
    frame["relative_speed_mps"] = np.nan
    frame["distance_to_nearest_neighbor_m"] = np.nan
    frame["neighbor_count"] = np.nan

    for _, indexes in frame.groupby("time_s", sort=False).groups.items():
        positions = frame.loc[indexes, ["x_m", "y_m"]].to_numpy(dtype=float)
        tree = KDTree(positions)
        frame.loc[indexes, "distance_to_nearest_neighbor_m"] = tree.query(positions, k=2, return_distance=True)[0][:, 1]
        frame.loc[indexes, "neighbor_count"] = tree.query_radius(positions, r=radio_range_m, count_only=True) - 1

    frame["neighbor_count"] = frame["neighbor_count"].astype("int64")
    return frame.sort_values(["time_s", "node_id"], kind="stable").reset_index(drop=True)


def validate_scenario(frame: pd.DataFrame, scenario: pd.Series, sample_interval_s: float) -> dict[str, int]:
    node_count = int(scenario["node_count"])
    duration = float(scenario["simulation_duration_s"])
    expected_samples = int(math.floor(duration / sample_interval_s + 1e-9)) + 1
    keys = ["time_s", "node_id"]
    valid_node_ids = frame["node_id"].between(0, node_count - 1)
    valid_times = frame["time_s"].between(0, duration)
    valid_positions = frame["x_m"].between(0, float(scenario["area_x_m"])) & frame["y_m"].between(0, float(scenario["area_y_m"]))
    speed_values = frame["speed_mps"].dropna()
    calculated_speed = np.hypot(frame["velocity_x_mps"], frame["velocity_y_mps"])
    comparable_speed = frame["speed_mps"].notna()
    inconsistent_speed = comparable_speed & ~np.isclose(frame["speed_mps"], calculated_speed, rtol=1e-6, atol=1e-8)
    expected_unique = node_count * expected_samples
    actual_unique = int(frame[keys].drop_duplicates().shape[0])
    intervals = frame.groupby("node_id", sort=False)["time_s"].diff().dropna()
    return {
        "duplicate_records": int(frame.duplicated(keys).sum()),
        "missing_required_values": int(frame[list(REQUIRED_COLUMNS[4:])].isna().sum().sum()),
        "invalid_node_ids": int((~valid_node_ids).sum()),
        "missing_time_or_negative_time": int((~valid_times).sum()),
        "invalid_coordinates": int((~valid_positions).sum()),
        "impossible_speed": int((speed_values > float(scenario["speed_mps"]) + 0.05).sum()),
        "inconsistent_speed": int(inconsistent_speed.sum()),
        "broken_scenario_mapping": 0,
        "missing_node_time_records": max(0, expected_unique - actual_unique),
        "unexpected_sampling_intervals": int((~np.isclose(intervals, sample_interval_s, rtol=0.0, atol=1e-6)).sum()),
        "observed_nodes": int(frame["node_id"].nunique()),
        "observed_timestamps": int(frame["time_s"].nunique()),
        "expected_records": expected_unique,
        "records": int(len(frame)),
        "null_cells": int(frame.isna().sum().sum()),
    }


def attach_provenance(
    frame: pd.DataFrame,
    scenario: pd.Series,
    source_scenario: pd.Series,
    source_file: str,
    sample_interval_s: float,
) -> pd.DataFrame:
    frame["scenario_id"] = str(scenario["scenario_id"])
    frame["run_id"] = int(scenario["run_id"])
    frame["random_seed"] = int(scenario["random_seed"])
    frame["random_run"] = int(scenario["random_run"])
    frame["node_count"] = int(scenario["node_count"])
    frame["mobility_model"] = str(scenario["mobility_model"])
    for column in (
        "area_m", "traffic_rate_bps", "packet_size_bytes", "source_id", "destination_id", "routing_protocol",
        "wifi_standard", "channel_helper", "tx_power_dbm", "noise_floor_dbm", "transport_protocol", "application_type", "flow_id",
    ):
        frame[column] = scenario[column]
    frame["speed_limit_mps"] = float(scenario["speed_mps"])
    frame["mobility_pause_s"] = DEFAULT_RANDOM_WAYPOINT_PAUSE_S
    frame["area_x_m"] = float(scenario["area_x_m"])
    frame["area_y_m"] = float(scenario["area_y_m"])
    frame["simulation_duration_s"] = float(scenario["simulation_duration_s"])
    frame["sampling_interval_s"] = sample_interval_s
    frame["source_dataset"] = "ns-3 DSR mobility trace"
    frame["source_file"] = source_file
    frame["source_scenario_id"] = str(source_scenario["scenario_id"])
    frame["source_run_id"] = int(source_scenario["run_id"])
    frame["source_time_s"] = frame["time_s"]
    frame["source_type"] = "new_ns3_simulation"
    if str(source_scenario["scenario_id"]) == str(scenario["scenario_id"]):
        frame["provenance_note"] = "Position sampled from configured ns-3 DSR run; kinematics derived from successive positions."
    else:
        frame["provenance_note"] = "Trace reused for an exact matching mobility configuration; traffic-only variation was verified to preserve positions."
    return frame[OUTPUT_COLUMNS]


def _combine_validation(total: dict[str, int], current: dict[str, int]) -> None:
    additive = {
        "duplicate_records",
        "missing_required_values",
        "invalid_node_ids",
        "missing_time_or_negative_time",
        "invalid_coordinates",
        "impossible_speed",
        "inconsistent_speed",
        "broken_scenario_mapping",
        "missing_node_time_records",
        "unexpected_sampling_intervals",
        "null_cells",
    }
    for key in additive:
        total[key] = total.get(key, 0) + current[key]
    total["records"] = total.get("records", 0) + current["records"]
    total["expected_records"] = total.get("expected_records", 0) + current["expected_records"]
    total["observed_node_scenario_pairs"] = total.get("observed_node_scenario_pairs", 0) + current["observed_nodes"]


def _write_readme(
    metadata: pd.DataFrame,
    selected: pd.DataFrame,
    inventory: list[dict[str, Any]],
    report: dict[str, Any],
    sampling_interval_s: float,
    radio_range_m: float,
    output_path: Path,
) -> None:
    candidate_rows = []
    for item in inventory:
        if item.get("mobility_candidate"):
            candidate_rows.append(
                f"| `{item['file']}` | {item['rows']} | {item['observed_nodes']} | {item['time_min_s']}–{item['time_max_s']} ({item['time_sample_count']} samples) | `{','.join(item['position_columns'])}` | `{','.join(item['speed_columns']) or 'none'}` | `{item['mobility_model_column'] or 'not recorded'}` | `{item['run_identifier'] or 'none'}` | `{item['scenario_identifier'] or 'none'}` | Incompatible |")
    if not candidate_rows:
        candidate_rows.append("| None | 0 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |")

    lines = [
        "# Mobility data",
        "",
        "## Purpose and provenance",
        "",
        "`Mobility_data.csv` contains node positions sampled from ns-3 DSR simulations configured from `data/metadata/Simulation_data.csv`. It is simulation-generated data, not real-world measurement. Original raw datasets were inspected but not modified or merged because none can be mapped scientifically to the manifest scenarios.",
        "",
        f"The inspected manifest contains {len(metadata)} scenarios; this generation contains {report['scenario_count']} scenarios and {report['record_count']} node-time records. The manifest specifies `{', '.join(report['mobility_models'])}` mobility, {sampling_interval_s:g} s sampling, {sorted(pd.to_numeric(metadata['area_x_m']).unique().tolist())} m X-area, {sorted(pd.to_numeric(metadata['area_y_m']).unique().tolist())} m Y-area, and {sorted(pd.to_numeric(metadata['simulation_duration_s']).unique().tolist())} s duration.",
        "",
        "## Existing source assessment",
        "",
        "The following files contain candidate coordinates. Their available keys, temporal coverage, or coordinate bounds do not match the current experiment matrix, so they were excluded:",
        "",
        "| File | Rows | Nodes | Time coverage | Position columns | Speed | Mobility model | Run key | Scenario key | Compatibility |",
        "|---|---:|---:|---|---|---|---|---|---|---|",
        *candidate_rows,
        "",
        "`data/raw/positions_*.csv` traces have 51 samples at 10 s intervals over 0–500 s, coordinates approximately 0–1000 m, and no scenario/model key; the manifest requires 1 s observations over 0–600 s in a 200×200 m area with RandomWaypoint. `data/raw/manet_dataset.csv` has 30 nodes and 60 samples over 1–60 s, and lacks compatible seed/model/scenario mapping. `nodes_dynamic.csv` has no coordinates. The existing topology dataset is not joined: its generator selects those position files by node count and seed modulo, so its nominal scenario keys do not identify the same ns-3 realization.",
        "",
        "The full per-file schema and row-count audit is recorded in `mobility_generation_report.json`, including files under `data/raw/`, `cleaned/`, `processed/`, `final/`, `topology/`, and `metadata/`.",
        "",
        "## Configuration and sampling",
        "",
        "Each mobility realization uses the selected manifest values for node count, area, duration, speed, random seed/run, mobility model, and DSR routing. `ns3/scratch/dsr_manet_dataset.cc` samples the installed ns-3 `MobilityModel` at the selected interval, including t=0 and the configured final time when it is an interval boundary. Scenario outputs are isolated under `ns3/results/scenarios/<scenario_id>/`; losslessly compressed raw traces are kept under `ns3/results/mobility_traces/*.csv.gz`.",
        "",
        "Coordinates are Cartesian metres in the ns-3 simulation rectangle. They are not geographic coordinates. Speed comes from each manifest row. The manifest does not define RandomWaypoint pause duration, so the ns-3.48 model default of 2.0 s is used and recorded in `mobility_pause_s`; measured `speed_mps` is the finite-difference average between sampled positions.",
        "",
        "## Features",
        "",
        "- `velocity_x_mps` and `velocity_y_mps`: successive X/Y coordinate differences divided by the actual elapsed time.",
        "- `speed_mps`: Euclidean magnitude of the finite-difference velocity.",
        "- `direction_deg`: `atan2(vy, vx)` converted to degrees and normalized to [0, 360); undefined at the first sample and while stationary.",
        "- `distance_moved_m`: Euclidean displacement from the prior sample.",
        "- `acceleration_mps2`: change in derived speed divided by elapsed time; unavailable until two speeds exist.",
        f"- `distance_to_nearest_neighbor_m`: nearest other node at the same scenario/time, computed from the sampled coordinates.",
        f"- `neighbor_count`: number of other nodes within the configured {radio_range_m:g} m `RangePropagationLossModel` radius at the same time. This is geometry-derived candidate connectivity, not a DSR route or measured RF-neighbor table.",
        "- `relative_speed_mps`: null. The existing Step 2 topology pairs cannot be joined to these exact RandomWaypoint simulations, so no unrelated node pairs are used.",
        "",
        "## Missing values and provenance fields",
        "",
        "The first sample of every node has no prior position, so velocity, speed, direction, and distance moved are null there. Acceleration is null until a prior derived speed exists. Direction is also null at zero speed because direction is undefined. `relative_speed_mps` is null throughout because a compatible topology-pair dataset is not available. `run_id` is the manifest scenario run identifier; `random_run` is the separate ns-3 RNG run. `source_file`, `source_scenario_id`, `source_run_id`, `source_time_s`, and `source_type` trace each row to its archived ns-3 position trace. Every manifest row is simulated independently because a paired traffic-rate pilot produced different positions.",
        "",
        "## Validation",
        "",
        f"- Scenarios: {report['scenario_count']} of {len(metadata)} manifest scenarios selected.",
        f"- Runs: {report['run_count']}; scenario-node instances: {report['nodes_processed']}; records: {report['record_count']}.",
        f"- Expected sampling interval: {sampling_interval_s:g} s; observed model(s): {', '.join(report['mobility_models'])}.",
        f"- Invalid coordinates: {report['validation_results']['invalid_coordinates']}; invalid node IDs: {report['validation_results']['invalid_node_ids']}; duplicate node-time records: {report['validation_results']['duplicate_records']}; missing node-time records: {report['validation_results']['missing_node_time_records']}; unexpected intervals: {report['validation_results']['unexpected_sampling_intervals']}.",
        "- The machine-readable report includes missing-value counts, speed consistency, bounds, mapping, and per-source inventory results.",
        "",
        "## Regeneration",
        "",
        "Run in the project virtual environment with a built ns-3 checkout:",
        "",
        "```bash",
        "python3 ml/generate_mobility_dataset.py --ns3-dir /path/to/ns-3.48 --limit 2 --output-csv data/validation/step_batches/Mobility_data.csv --replace-existing",
        "python3 ml/generate_mobility_dataset.py --ns3-dir /path/to/ns-3.48 --limit 10 --resume --output-csv data/validation/step_batches/Mobility_data.csv",
        "python3 ml/generate_mobility_dataset.py --ns3-dir /path/to/ns-3.48 --all --replace-existing",
        "```",
        "",
        "The generator reads scenarios from the manifest; `--limit` bounds a pilot and `--all` selects every manifest row. Existing outputs require explicit `--resume` or `--replace-existing`; canonical replacement requires `Mobility_data_backup.csv`. Resume validates scenario/run/seed keys, every stored manifest configuration value, trace provenance, and complete node-time row counts. Traces are cached by scenario and reused only when logged configuration, sampling interval, and trace identifiers match. NetAnim packet tracing is disabled, but DSR, UDP/CBR traffic, and mobility sampling remain enabled.",
        "",
        "## Limitations",
        "",
        "This dataset records node mobility only. It does not claim measured RSSI/SNR, packet delivery, route state, failure, or recovery. The geometry-derived neighbor count depends on the configured hard radio-range model. Relative speed by a topology-confirmed link is omitted until Step 2 topology is regenerated from these same scenario traces. Preserve the generation report alongside the CSV when using it in later stages.",
        "",
    ]
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    metadata_path = args.metadata_csv.resolve()
    ns3_dir = args.ns3_dir.resolve()
    metadata = pd.read_csv(metadata_path)
    required_metadata = set(MOBILITY_KEY) | {"scenario_id", "run_id", "routing_protocol"}
    missing = required_metadata - set(metadata.columns)
    if missing:
        raise ValueError(f"Simulation metadata is missing required columns: {sorted(missing)}")
    if metadata.empty or metadata["scenario_id"].duplicated().any():
        raise ValueError("Simulation metadata must be non-empty with unique scenario_id values")
    selected = select_scenarios(metadata, args)
    inventory, warnings = inspect_data_sources(metadata)
    radio_range_m = read_radio_range_m()
    output_path = args.output_csv.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not (args.resume or args.replace_existing):
        raise ValueError("Output already exists; pass --resume or --replace-existing to preserve scenarios explicitly.")
    if args.replace_existing and output_path == OUTPUT_PATH.resolve():
        backup_path = output_path.with_name("Mobility_data_backup.csv")
        if not backup_path.is_file():
            raise ValueError(f"Refusing replacement without the required backup: {backup_path}")
    TRACE_ARCHIVE.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    ensure_free_space(output_path, args.minimum_free_space_gb)
    existing_scenarios = validate_existing_output(output_path, metadata, args.sampling_interval_s) if args.resume else set()
    if existing_scenarios:
        selected = selected[~selected["scenario_id"].astype(str).isin(existing_scenarios)].copy()
    if args.resume and output_path.exists() and selected.empty:
        print("All selected scenarios are already present with valid manifest keys; nothing to do.")
        return
    validation_totals: dict[str, int] = {}
    source_files: set[str] = set()
    mobility_models = sorted(selected["mobility_model"].astype(str).unique().tolist())
    unique_nodes = 0
    scenario_node_total = int(selected["node_count"].sum())
    scenario_count = 0
    generated_trace_count = 0

    try:
        if temporary_path.exists():
            temporary_path.unlink()
        if args.resume and output_path.exists():
            shutil.copy2(output_path, temporary_path)
        first_output = not temporary_path.exists()
        for source_scenario, scenario_group in _mobility_groups(selected):
            ensure_free_space(output_path, args.minimum_free_space_gb)
            ensure_free_space(ns3_dir / "results" / "scenarios", args.minimum_free_space_gb)
            trace = obtain_trace(ns3_dir, metadata_path, source_scenario, args.sampling_interval_s)
            archive_path = archive_trace(trace, source_scenario)
            source_file = archive_path.relative_to(ROOT).as_posix()
            source_files.add(source_file)
            generated_trace_count += 1

            features = build_features(trace, source_scenario, args.sampling_interval_s, radio_range_m)
            expected_nodes = set(range(int(source_scenario["node_count"])))
            if set(features["node_id"].unique()) != expected_nodes:
                raise ValueError(f"Trace node IDs do not match 0..N-1 for {source_scenario['scenario_id']}.")

            for scenario in scenario_group:
                scenario = pd.Series(scenario)
                checks = validate_scenario(features, scenario, args.sampling_interval_s)
                _combine_validation(validation_totals, checks)
                if any(checks[name] for name in (
                    "duplicate_records",
                    "missing_required_values",
                    "invalid_node_ids",
                    "missing_time_or_negative_time",
                    "invalid_coordinates",
                    "impossible_speed",
                    "inconsistent_speed",
                    "broken_scenario_mapping",
                    "missing_node_time_records",
                    "unexpected_sampling_intervals",
                )):
                    raise ValueError(f"Mobility validation failed for {scenario['scenario_id']}: {checks}")
                output_frame = attach_provenance(features.copy(), scenario, source_scenario, source_file, args.sampling_interval_s)
                output_frame.to_csv(
                    temporary_path,
                    index=False,
                    mode="w" if first_output else "a",
                    header=first_output,
                    na_rep="",
                    float_format="%.6f",
                )
                first_output = False
                scenario_count += 1
                unique_nodes = max(unique_nodes, int(output_frame["node_id"].nunique()))
                print(
                    f"Validated {scenario['scenario_id']}: {checks['records']} rows, "
                    f"{checks['observed_nodes']} nodes, {checks['observed_timestamps']} times",
                    flush=True,
                )
                del output_frame
            if trace != archive_path and trace.exists():
                trace.unlink()
            del features
            ensure_free_space(output_path, args.minimum_free_space_gb)

        if first_output:
            raise ValueError("No mobility rows were generated")
        os.replace(temporary_path, output_path)
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        raise

    record_count = validation_totals["records"]
    validation_errors = sum(
        validation_totals[key]
        for key in (
            "duplicate_records",
            "missing_required_values",
            "invalid_node_ids",
            "missing_time_or_negative_time",
            "invalid_coordinates",
            "impossible_speed",
            "inconsistent_speed",
            "broken_scenario_mapping",
            "missing_node_time_records",
            "unexpected_sampling_intervals",
        )
    )
    report = {
        "dataset": output_path.relative_to(ROOT).as_posix() if output_path.is_relative_to(ROOT) else str(output_path),
        "generation_date": datetime.now(timezone.utc).isoformat(),
        "source_files": [
            metadata_path.relative_to(ROOT).as_posix() if metadata_path.is_relative_to(ROOT) else metadata_path.as_posix(),
            *sorted(source_files),
        ],
        "source_types": ["new_ns3_simulation"],
        "scenario_count": scenario_count,
        "run_count": int(selected[["scenario_id", "run_id"]].drop_duplicates().shape[0]),
        "node_count": unique_nodes,
        "nodes_processed": scenario_node_total,
        "record_count": record_count,
        "sampling_interval_s": args.sampling_interval_s,
        "mobility_models": mobility_models,
        "mobility_model_parameters": {
            "speed_source": "data/metadata/Simulation_data.csv:speed_mps",
            "random_waypoint_pause_s": DEFAULT_RANDOM_WAYPOINT_PAUSE_S,
            "random_waypoint_pause_source": "ns-3.48 RandomWaypointMobilityModel registered default",
        },
        "radio_range_m": radio_range_m,
        "derived_features": [
            "velocity_x_mps",
            "velocity_y_mps",
            "speed_mps",
            "direction_deg",
            "distance_moved_m",
            "acceleration_mps2",
            "distance_to_nearest_neighbor_m",
            "neighbor_count",
        ],
        "simulation_generated_records": record_count,
        "existing_source_records": 0,
        "derived_records": record_count,
        "unique_mobility_traces_simulated_or_reused": generated_trace_count,
        "scenario_rows_reusing_equivalent_mobility_trace": 0,
        "scenario_independence_check": {
            "traffic_variant_a": "DSR_N100_MLOW_TLOW_S10001_R001",
            "traffic_variant_b": "DSR_N100_MLOW_THIGH_S10001_R006",
            "positions_identical": False,
            "policy": "run every scenario independently",
        },
        "validation_results": {
            **validation_totals,
            "passed": validation_errors == 0,
            "source_inventory_file_count": sum("file" in item for item in inventory),
            "coordinate_source_candidate_count": sum(bool(item.get("mobility_candidate")) for item in inventory),
            "compatible_existing_source_count": 0,
            "relative_speed_unavailable_records": record_count,
        },
        "source_inventory": inventory,
        "warnings": warnings + [
            "relative_speed_mps is null because available topology pairs are not from the same scenario mobility realization.",
            "neighbor_count is derived from same-time ns-3 positions and the configured hard radio range; it is geometry-based, not a measured DSR neighbor table.",
        ],
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_PATH if output_path == OUTPUT_PATH else output_path.parent / "mobility_generation_report.json"
    readme_path = README_PATH if output_path == OUTPUT_PATH else output_path.parent / "README.md"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _write_readme(metadata, selected, inventory, report, args.sampling_interval_s, radio_range_m, readme_path)
    print(json.dumps({key: report[key] for key in (
        "scenario_count",
        "run_count",
        "nodes_processed",
        "record_count",
        "sampling_interval_s",
        "mobility_models",
        "simulation_generated_records",
        "existing_source_records",
        "validation_results",
        "warnings",
    )}, indent=2))


if __name__ == "__main__":
    main()