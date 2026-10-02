"""Create a complete, read-only schema inventory for processed CSV files."""
from __future__ import annotations

import argparse
import hashlib
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

TARGET_NAMES = {
    "route_failure", "link_failure", "loss_occurred", "attack", "label", "target",
    "cause_label", "sim_label", "route_failure_events", "recovery_success_rate",
}
ID_NAMES = {
    "id", "run_id", "run", "seed", "ns3_seed", "node_id", "src_id", "dst_id", "flow_id", "row_id",
}
METADATA_NAMES = {
    "timestamp", "time", "split", "node_count", "sim_area_m", "sim_duration_s", "mobility_model",
    "channel_helper", "stack", "routing", "transport", "app", "phy", "random_seed", "random_run",
    "input_file", "output_file", "status", "target", "filename", "columns", "duplicates_removed",
    "missing_values_before", "missing_values_after", "metadata_columns", "features_before_engineering",
    "features_after_engineering", "engineered_columns", "rows_before", "rows_after",
}

ALIASES = {
    "speed": "speed / node_speed / speed_mps",
    "node_speed": "speed / node_speed / speed_mps",
    "speed_mps": "speed / node_speed / speed_mps",
    "delay": "delay / delay_ms / end_to_end_delay_ms",
    "delay_ms": "delay / delay_ms / end_to_end_delay_ms",
    "end_to_end_delay_ms": "delay / delay_ms / end_to_end_delay_ms",
    "pdr": "pdr / prr / delivery_ratio_engineered",
    "prr": "pdr / prr / delivery_ratio_engineered",
    "delivery_ratio_engineered": "pdr / prr / delivery_ratio_engineered",
    "energy": "energy / remaining_energy",
    "remaining_energy": "energy / remaining_energy",
    "x": "x / position_x",
    "position_x": "x / position_x",
    "y": "y / position_y",
    "position_y": "y / position_y",
    "packet_loss": "packet_loss / loss_ratio_engineered / lost_packets",
    "loss_ratio_engineered": "packet_loss / loss_ratio_engineered / lost_packets",
    "lost_packets": "packet_loss / loss_ratio_engineered / lost_packets",
    "rssi": "rssi / avg_rssi / rssi_dbm",
    "avg_rssi": "rssi / avg_rssi / rssi_dbm",
    "rssi_dbm": "rssi / avg_rssi / rssi_dbm",
    "throughput": "throughput / throughput_bps",
    "throughput_bps": "throughput / throughput_bps",
    "queue_length": "queue_length / queue_len_norm",
    "queue_len_norm": "queue_length / queue_len_norm",
}


def normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def example(value: Any) -> str:
    if pd.isna(value):
        return "<missing>"
    text = repr(value)
    return text if len(text) <= 120 else text[:117] + "..."


def role(column: str, dtype: str, target_columns: set[str]) -> str:
    name = normalize(column)
    if name in target_columns or name in TARGET_NAMES or name.endswith("_target"):
        return "target/label"
    if name in ID_NAMES or name.endswith("_id"):
        return "ID"
    if name in METADATA_NAMES or name.endswith(("_model", "_helper", "_protocol", "_name", "_file")):
        return "metadata/control"
    if name in {"split"}:
        return "metadata/control"
    if dtype == "object" or dtype.startswith("string") or dtype.startswith("category"):
        return "categorical feature/metadata"
    return "numeric feature"


def format_value_counts(values: list[str]) -> str:
    return ", ".join(values) if values else "None"


def inventory_csv(path: Path) -> dict[str, Any]:
    frame = pd.read_csv(path, low_memory=False)
    columns = list(frame.columns)
    target_columns = {column for column in columns if normalize(column) in TARGET_NAMES or normalize(column).endswith("_target")}
    details = []
    duplicate_columns = []
    for index, column in enumerate(columns, start=1):
        series = frame[column]
        same_as = [other for other in columns if other != column and series.equals(frame[other])]
        if same_as:
            duplicate_columns.append({"column": column, "identical_to": same_as})
        unique = int(series.nunique(dropna=True))
        details.append({
            "index": index,
            "name": str(column),
            "dtype": str(series.dtype),
            "example": example(series.dropna().iloc[0] if not series.dropna().empty else pd.NA),
            "missing": int(series.isna().sum()),
            "unique": unique,
            "role": role(str(column), str(series.dtype), target_columns),
            "target": str(column) in target_columns,
        })
    return {
        "path": str(path),
        "filename": path.name,
        "rows": len(frame),
        "columns": len(columns),
        "column_names": [str(column) for column in columns],
        "details": details,
        "targets": [str(column) for column in columns if str(column) in target_columns],
        "duplicate_columns": duplicate_columns,
        "hash": sha256(path),
    }


def build_report(input_dir: Path) -> str:
    paths = sorted(input_dir.glob("*.csv"))
    datasets = [inventory_csv(path) for path in paths]
    column_datasets: dict[str, list[str]] = defaultdict(list)
    alias_datasets: dict[str, set[str]] = defaultdict(set)
    for dataset in datasets:
        for column in dataset["column_names"]:
            column_datasets[column].append(dataset["filename"])
            alias = ALIASES.get(normalize(column))
            if alias:
                alias_datasets[alias].add(dataset["filename"])

    duplicate_hashes: dict[str, list[str]] = defaultdict(list)
    for dataset in datasets:
        duplicate_hashes[dataset["hash"]].append(dataset["filename"])
    duplicate_datasets = [files for files in duplicate_hashes.values() if len(files) > 1]

    all_columns = sorted(column_datasets)
    common_columns = [column for column in all_columns if len(column_datasets[column]) == len(datasets)]
    dataset_specific = {
        dataset["filename"]: [column for column in dataset["column_names"] if len(column_datasets[column]) == 1]
        for dataset in datasets
    }
    targets = {dataset["filename"]: dataset["targets"] for dataset in datasets if dataset["targets"]}
    key_candidates = [
        column for column in all_columns
        if normalize(column) in {"run_id", "run", "seed", "ns3_seed", "timestamp", "time", "node_id", "src_id", "dst_id", "flow_id"}
    ]

    lines: list[str] = []
    lines.append("PROCESSED CSV COLUMN/SCHEMA INVENTORY")
    lines.append(f"Generated UTC: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"Input directory: {input_dir}")
    lines.append(f"CSV files inspected: {len(datasets)}")
    lines.append("")
    for dataset in datasets:
        lines.extend([
            "=" * 50,
            f"DATASET: {dataset['filename']}",
            "=" * 50,
            f"Path: {dataset['path']}",
            f"Rows: {dataset['rows']}",
            f"Columns: {dataset['columns']}",
            f"SHA-256: {dataset['hash']}",
            "",
            "COLUMN DETAILS",
            "-" * 50,
        ])
        for detail in dataset["details"]:
            lines.extend([
                f"{detail['index']}. {detail['name']}",
                f"   Type: {detail['dtype']}",
                f"   Example: {detail['example']}",
                f"   Missing: {detail['missing']}",
                f"   Unique: {detail['unique']}",
                f"   Role: {detail['role']}",
            ])
        lines.extend(["", "TARGET COLUMNS", "-" * 50])
        lines.append(format_value_counts(dataset["targets"]))
        lines.extend(["", "COMMON/SIMILAR COLUMNS", "-" * 50])
        local_aliases = sorted({ALIASES.get(normalize(column)) for column in dataset["column_names"] if ALIASES.get(normalize(column))})
        lines.append(format_value_counts(local_aliases))
        lines.extend(["", "DATASET-SPECIFIC COLUMNS", "-" * 50])
        lines.append(format_value_counts(dataset_specific[dataset["filename"]]))
        if dataset["duplicate_columns"]:
            lines.extend(["", "DUPLICATE COLUMNS", "-" * 50])
            for duplicate in dataset["duplicate_columns"]:
                lines.append(f"{duplicate['column']} == {', '.join(duplicate['identical_to'])}")
        else:
            lines.extend(["", "DUPLICATE COLUMNS", "-" * 50, "None detected"])
        lines.append("")

    lines.extend(["=" * 50, "CROSS-DATASET SUMMARY", "=" * 50])
    lines.append(f"All datasets: {', '.join(dataset['filename'] for dataset in datasets) or 'None'}")
    lines.append(f"Common columns: {format_value_counts(common_columns)}")
    lines.append("Potentially equivalent columns:")
    for alias, files in sorted(alias_datasets.items()):
        members = [column for column in all_columns if ALIASES.get(normalize(column)) == alias]
        lines.append(f"  - {alias}: columns [{', '.join(members)}]; datasets [{', '.join(sorted(files))}]")
    lines.append("Dataset-specific columns:")
    for filename, columns in dataset_specific.items():
        lines.append(f"  - {filename}: {format_value_counts(columns)}")
    lines.append("Target columns:")
    for filename, columns in targets.items():
        lines.append(f"  - {filename}: {', '.join(columns)} (original meanings preserved; not assumed equivalent)")
    lines.append(f"Possible merge keys: {format_value_counts(key_candidates)}")
    lines.append("Potential conflicts:")
    lines.append("  - Different target names may represent different labels and must not be merged as one target without domain validation.")
    lines.append("  - Similar names may use different units or definitions; inspect ranges and metadata before merging.")
    lines.append("  - Datasets have different row grains: node/time, flow/time, simulation summaries, and split/control tables.")
    lines.append("  - Metadata columns such as run, seed, time, node_id, src_id, dst_id, and flow_id may need a composite key.")
    lines.append("Duplicate datasets:")
    if duplicate_datasets:
        for files in duplicate_datasets:
            lines.append(f"  - Identical SHA-256 content: {', '.join(files)}")
    else:
        lines.append("  None detected by SHA-256")
    lines.append("Duplicate columns within datasets:")
    duplicates = [(dataset["filename"], dataset["duplicate_columns"]) for dataset in datasets if dataset["duplicate_columns"]]
    if duplicates:
        for filename, entries in duplicates:
            lines.append(f"  - {filename}: " + "; ".join(f"{entry['column']} == {', '.join(entry['identical_to'])}" for entry in entries))
    else:
        lines.append("  None detected")
    lines.append("")
    lines.append("No datasets were merged, renamed, transformed, or deleted by this inventory.")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Inventory every processed CSV without modifying it.")
    parser.add_argument("--input-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/all_columns_inventory.txt"))
    args = parser.parse_args()
    report = build_report(args.input_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Generated inventory: {args.output}")


if __name__ == "__main__":
    main()
