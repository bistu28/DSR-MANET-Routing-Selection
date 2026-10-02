"""Feature engineering for one cleaned CSV or every cleaned CSV."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_VERSION = "2.0.0"
TARGET_NAMES = {"route_failure", "link_failure", "loss_occurred", "target", "label", "attack", "cause_label", "sim_label"}
LEAKAGE_FEATURES = {
    "cause_label": "Describes the cause of the observed packet loss; unavailable before the labeled outcome.",
    "drop_reason": "Describes why the packet was dropped; outcome-derived and unavailable before the labeled outcome.",
}
METADATA_NAMES = {
    "run_id", "run", "seed", "ns3_seed", "timestamp", "time", "node_id", "src_id", "dst_id", "flow_id",
    "node_count", "sim_label", "sim_area_m", "sim_duration_s", "mobility_model", "channel_helper", "stack",
    "routing", "transport", "app", "phy", "random_seed", "random_run",
}


def detect_targets(columns: list[str]) -> list[str]:
    return [column for column in columns if column in TARGET_NAMES or column.endswith("_target")]


def _safe_numeric(frame: pd.DataFrame, column: str) -> bool:
    return column in frame.columns and pd.api.types.is_numeric_dtype(frame[column])


def engineer(input_path: Path, output_path: Path, target: str | None = None) -> tuple[pd.DataFrame, list[str]]:
   
    frame = pd.read_csv(input_path, low_memory=False)
    columns = list(frame.columns)
    targets = [target.lower()] if target else detect_targets(columns)
    targets = [column for column in targets if column in frame.columns]
    metadata = [column for column in columns if column in METADATA_NAMES and column not in targets]
    numeric_candidates = [
        column for column in columns
        if column not in targets and column not in metadata and column not in LEAKAGE_FEATURES
        and _safe_numeric(frame, column)
    ]
    excluded_non_numeric = [
        column for column in columns
        if column not in targets and column not in metadata and column not in numeric_candidates
        and column not in LEAKAGE_FEATURES
    ]
    excluded_leakage = {
        column: {
            "reason": reason,
            "observed_dtype": str(frame[column].dtype),
            "also_non_numeric": not pd.api.types.is_numeric_dtype(frame[column]),
            "excluded_by_explicit_leakage_rule": True,
        }
        for column, reason in LEAKAGE_FEATURES.items()
        if column in columns and column not in targets
    }
    engineered = frame[metadata + numeric_candidates + targets].copy()
    added_features: list[str] = []

    if "packet_loss" in engineered.columns and "end_to_end_delay_ms" in engineered.columns:
        engineered["loss_delay_interaction"] = engineered["packet_loss"] * engineered["end_to_end_delay_ms"]
        added_features.append("loss_delay_interaction")
    elif "packet_loss" in engineered.columns and "delay_ms" in engineered.columns:
        engineered["loss_delay_interaction"] = engineered["packet_loss"] * engineered["delay_ms"]
        added_features.append("loss_delay_interaction")
    if "node_speed" in engineered.columns and "route_stability" in engineered.columns:
        engineered["mobility_risk"] = engineered["node_speed"] * (1 - engineered["route_stability"])
        added_features.append("mobility_risk")
    elif "speed" in engineered.columns and "link_quality" in engineered.columns:
        engineered["mobility_link_risk"] = engineered["speed"] * (1 - engineered["link_quality"])
        added_features.append("mobility_link_risk")
    if "tx_packets" in engineered.columns and "rx_packets" in engineered.columns:
        denominator = engineered["tx_packets"].astype("float64").replace(0, float("nan"))
        engineered["delivery_ratio_engineered"] = (engineered["rx_packets"].astype("float64") / denominator).fillna(0.0)
        added_features.append("delivery_ratio_engineered")
    if "tx_packets" in engineered.columns and "lost_packets" in engineered.columns:
        denominator = engineered["tx_packets"].astype("float64").replace(0, float("nan"))
        engineered["loss_ratio_engineered"] = (engineered["lost_packets"].astype("float64") / denominator).fillna(0.0)
        added_features.append("loss_ratio_engineered")

    feature_columns = numeric_candidates + added_features
    report: dict[str, Any] = {
        "script_version": SCRIPT_VERSION,
        "feature_engineering_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "original_cleaned_file": str(input_path),
        "output_file": str(output_path),
        "rows": len(engineered),
        "columns_before": columns,
        "columns_after": list(engineered.columns),
        "metadata_columns_retained": metadata,
        "target_columns_retained": targets,
        "feature_columns": feature_columns,
        "non_numeric_columns_excluded_from_features": excluded_non_numeric,
        "leakage_columns_excluded_from_features": excluded_leakage,
        "engineered_columns_added": added_features,
        "target_meanings": {column: f"Preserved source target '{column}'; no relabeling performed." for column in targets},
        "status": "engineered",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    engineered.to_csv(output_path, index=False)
    output_path.with_name(f"{output_path.stem[:-9] if output_path.stem.endswith('_features') else output_path.stem}.features.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    return engineered, feature_columns


def process_all(input_dir: Path, output_dir: Path) -> pd.DataFrame:
  
    output_dir.mkdir(parents=True, exist_ok=True)
    input_files = sorted(input_dir.glob("*_cleaned.csv"))
    rows: list[dict[str, Any]] = []
    for input_path in input_files:
        output_path = output_dir / f"{input_path.stem[:-8] if input_path.stem.endswith('_cleaned') else input_path.stem}_features.csv"
        try:
            engineered, features = engineer(input_path, output_path)
            report_path = output_path.with_name(f"{output_path.stem[:-9]}.features.json")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            rows.append({
                "input_file": input_path.name,
                "output_file": str(output_path),
                "rows": len(engineered),
                "target": ";".join(report["target_columns_retained"]) or None,
                "metadata_columns": len(report["metadata_columns_retained"]),
                "features_before_engineering": len(report["feature_columns"]) - len(report["engineered_columns_added"]),
                "features_after_engineering": len(features),
                "engineered_columns": ";".join(report["engineered_columns_added"]),
                "status": "engineered",
            })
        except Exception as error:
            rows.append({
                "input_file": input_path.name, "output_file": None, "rows": 0, "target": None,
                "metadata_columns": 0, "features_before_engineering": 0, "features_after_engineering": 0,
                "engineered_columns": None, "status": f"problem: {error}",
            })
    summary = pd.DataFrame(rows, columns=[
        "input_file", "output_file", "rows", "target", "metadata_columns",
        "features_before_engineering", "features_after_engineering", "engineered_columns", "status",
    ])
    summary.to_csv(output_dir / "feature_engineering_summary.csv", index=False)
    print(summary.to_string(index=False))
    print(f"\nProcessed successfully: {(summary['status'] == 'engineered').sum()}")
    print(f"Problematic files: {summary['status'].astype(str).str.startswith('problem:').sum()}")
    print(f"Total cleaned CSV files found: {len(input_files)}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Engineer one cleaned CSV or every cleaned CSV.")
    parser.add_argument("--input-dir", type=Path, default=Path("data/cleaned"))
    parser.add_argument("--input-file", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--output-file", type=Path)
    parser.add_argument("--target")
    parser.add_argument("--all", action="store_true", help="Process every *_cleaned.csv in input-dir.")
    args = parser.parse_args()
    if args.all:
        process_all(args.input_dir, args.output_dir)
        return
    if not args.input_file:
        parser.error("provide --input-file or use --all")
    output = args.output_file or (args.output_dir / f"{args.input_file.stem}_features.csv")
    engineer(args.input_file, output, args.target)
    print(f"engineered_file={output}")


if __name__ == "__main__":
    main()
