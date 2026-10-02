from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCRIPT_VERSION = "2.0.0"
EXACT_TARGETS = ("route_failure", "link_failure", "loss_occurred")
OTHER_TARGETS = ("target", "label", "attack", "cause_label", "sim_label")


def normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def detect_targets(columns: list[str]) -> list[str]:
    normalized = [normalize_name(column) for column in columns]
    exact = [column for column in EXACT_TARGETS if column in normalized]
    other = [column for column in normalized if column in OTHER_TARGETS or column.endswith("_target")]
    return list(dict.fromkeys(exact + other))


def _target_distribution(frame: pd.DataFrame, targets: list[str]) -> dict[str, dict[str, int]]:
    distributions: dict[str, dict[str, int]] = {}
    for column in targets:
        values = frame[column].value_counts(dropna=False).to_dict()
        distributions[column] = {str(key): int(value) for key, value in values.items()}
    return distributions


def _validate_targets(frame: pd.DataFrame, targets: list[str]) -> dict[str, Any]:
    validation: dict[str, Any] = {}
    for column in targets:
        values = frame[column].dropna()
        unique = set(values.tolist())
        binary = unique.issubset({0, 1, 0.0, 1.0, "0", "1", False, True})
        validation[column] = {
            "binary_0_1": bool(binary),
            "unique_values_sample": [str(value) for value in list(unique)[:20]],
            "missing_values": int(frame[column].isna().sum()),
            "meaning": f"Preserved source target column '{column}'; no relabeling was performed.",
        }
    return validation


def _audit_path(cleaned_dir: Path, input_path: Path) -> Path:
    return cleaned_dir / f"{input_path.stem}_audit.json"


def clean_frame(input_path: Path, output_path: Path, target: str | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Clean one CSV and write its CSV plus adjacent audit JSON.

    Exact duplicate rows are removed. Outliers are reported and retained.
    Targets are auto-detected unless an explicit target is supplied.
    """
    raw = pd.read_csv(input_path, low_memory=False)
    original_columns = [str(column) for column in raw.columns]
    normalized_columns = [normalize_name(column) for column in original_columns]
    duplicate_column_names = [column for column in set(normalized_columns) if normalized_columns.count(column) > 1]
    if any(not column for column in normalized_columns):
        raise ValueError("A column name becomes empty after normalization; inspect the source schema")
    if duplicate_column_names:
        raise ValueError(f"Normalized column names collide: {duplicate_column_names}")

    frame = raw.copy()
    frame.columns = normalized_columns
    explicit_target = normalize_name(target) if target else None
    targets = [explicit_target] if explicit_target else detect_targets(normalized_columns)
    targets = [column for column in targets if column in frame.columns]
    rows_before = len(frame)
    duplicate_rows = int(frame.duplicated().sum())
    missing_before = frame.isna().sum().astype(int).to_dict()
    nonfinite_values: dict[str, int] = {}
    converted_columns: list[str] = []
    invalid_values: dict[str, Any] = {}
    outliers: dict[str, dict[str, int]] = {}
    actions: list[str] = ["normalized column names"]

    frame = frame.drop_duplicates().reset_index(drop=True)
    if duplicate_rows:
        actions.append(f"removed {duplicate_rows} exact duplicate rows")

    for column in frame.columns:
        if frame[column].dtype == "object":
            converted = pd.to_numeric(frame[column], errors="coerce")
            non_missing = frame[column].notna().sum()
            if non_missing and converted.notna().sum() / non_missing >= 0.8:
                failed_conversion = int((frame[column].notna() & converted.isna()).sum())
                frame[column] = converted
                converted_columns.append(column)
                if failed_conversion:
                    invalid_values[column] = {"numeric_conversion_failures": failed_conversion}
                actions.append(f"converted '{column}' to numeric")

        if pd.api.types.is_numeric_dtype(frame[column]):
            values = frame[column].astype(float)
            nonfinite = int((~np.isfinite(values)).sum())
            if nonfinite:
                nonfinite_values[column] = nonfinite
                invalid_values.setdefault(column, {})["nonfinite_values"] = nonfinite
                frame.loc[~np.isfinite(values), column] = np.nan
                actions.append(f"replaced {nonfinite} non-finite values in '{column}' with missing values")
            q1, q3 = frame[column].quantile([0.25, 0.75])
            iqr = q3 - q1
            if pd.notna(iqr) and iqr > 0:
                count = int(((frame[column] < q1 - 1.5 * iqr) | (frame[column] > q3 + 1.5 * iqr)).sum())
                outliers[column] = {"iqr_count_reported_not_removed": count}

    for column in targets:
        if frame[column].isna().any():
            invalid_values.setdefault(column, {})["missing_target_values"] = int(frame[column].isna().sum())
        if pd.api.types.is_numeric_dtype(frame[column]):
            values = set(frame[column].dropna().tolist())
            if not values.issubset({0, 1, 0.0, 1.0}):
                invalid_values.setdefault(column, {})["non_binary_values"] = int((~frame[column].isin([0, 1])).sum())

    numeric_columns = frame.select_dtypes(include=[np.number]).columns.tolist()
    for column in numeric_columns:
        if column in targets:
            continue
        if frame[column].isna().any():
            median = frame[column].median()
            if pd.notna(median):
                frame[column] = frame[column].fillna(median)
                actions.append(f"filled missing numeric values in '{column}' with the median")
    for column in frame.columns.difference(numeric_columns):
        if column in targets:
            continue
        if frame[column].isna().any():
            mode = frame[column].mode(dropna=True)
            replacement = mode.iloc[0] if not mode.empty else "unknown"
            frame[column] = frame[column].fillna(replacement)
            actions.append(f"filled missing categorical values in '{column}' with the mode")

    missing_after = frame.isna().sum().astype(int).to_dict()
    report: dict[str, Any] = {
        "script_version": SCRIPT_VERSION,
        "cleaning_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "original_filename": input_path.name,
        "input": str(input_path),
        "output": str(output_path),
        "rows_before": rows_before,
        "rows_after": len(frame),
        "column_count": len(frame.columns),
        "original_columns": original_columns,
        "final_columns": list(frame.columns),
        "renamed_columns": dict(zip(original_columns, normalized_columns)),
        "duplicate_rows_detected": duplicate_rows,
        "duplicate_rows_removed": duplicate_rows,
        "missing_values_before": {str(key): int(value) for key, value in missing_before.items()},
        "missing_values_after": {str(key): int(value) for key, value in missing_after.items()},
        "non_finite_values": nonfinite_values,
        "columns_converted_to_numeric": converted_columns,
        "invalid_value_counts": invalid_values,
        "outlier_counts_by_numeric_column": outliers,
        "target_column": targets[0] if len(targets) == 1 else (targets or None),
        "target_columns": targets,
        "target_distribution": _target_distribution(frame, targets),
        "target_validation": _validate_targets(frame, targets),
        "columns_removed": {},
        "cleaning_actions": actions + ["reported outliers and retained them"],
        "status": "cleaned",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False)
    _audit_path(output_path.parent, input_path).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return frame, report


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def process_all(input_dir: Path, cleaned_dir: Path) -> pd.DataFrame:
    """Process every raw CSV once and write cleaning_summary.csv."""
    cleaned_dir.mkdir(parents=True, exist_ok=True)
    input_files = sorted(input_dir.glob("*.csv"))
    summary_rows: list[dict[str, Any]] = []
    hashes: dict[str, Path] = {}
    for input_path in input_files:
        output_path = cleaned_dir / f"{input_path.stem}_cleaned.csv"
        file_hash = _sha256(input_path)
        duplicate_of = hashes.get(file_hash)
        if duplicate_of:
            audit = {
                "script_version": SCRIPT_VERSION,
                "cleaning_timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "original_filename": input_path.name,
                "input": str(input_path),
                "status": "skipped_duplicate_content",
                "duplicate_sha256": file_hash,
                "duplicate_of": duplicate_of.name,
                "reason": "Identical SHA-256 content; canonical duplicate was processed once.",
                "output_file": None,
            }
            _audit_path(cleaned_dir, input_path).write_text(json.dumps(audit, indent=2), encoding="utf-8")
            summary_rows.append({"filename": input_path.name, "rows_before": 0, "rows_after": 0, "columns": 0,
                                 "target": None, "duplicates_removed": 0, "missing_values_before": 0,
                                 "missing_values_after": 0, "status": audit["status"], "output_file": None})
            continue
        hashes[file_hash] = input_path
        try:
            _, report = clean_frame(input_path, output_path)
            report["sha256"] = file_hash
            report["duplicate_content_of"] = None
            _audit_path(cleaned_dir, input_path).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            summary_rows.append({
                "filename": input_path.name, "rows_before": report["rows_before"], "rows_after": report["rows_after"],
                "columns": report["column_count"], "target": ";".join(report["target_columns"]) or None,
                "duplicates_removed": report["duplicate_rows_removed"],
                "missing_values_before": sum(report["missing_values_before"].values()),
                "missing_values_after": sum(report["missing_values_after"].values()),
                "status": "cleaned", "output_file": str(output_path),
            })
        except Exception as error:
            summary_rows.append({"filename": input_path.name, "rows_before": 0, "rows_after": 0, "columns": 0,
                                 "target": None, "duplicates_removed": 0, "missing_values_before": 0,
                                 "missing_values_after": 0, "status": f"problem: {error}", "output_file": None})
            _audit_path(cleaned_dir, input_path).write_text(json.dumps({
                "script_version": SCRIPT_VERSION,
                "cleaning_timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "original_filename": input_path.name, "status": "problem", "error": str(error),
            }, indent=2), encoding="utf-8")

    columns = ["filename", "rows_before", "rows_after", "columns", "target", "duplicates_removed",
               "missing_values_before", "missing_values_after", "status", "output_file"]
    summary = pd.DataFrame(summary_rows, columns=columns)
    summary.to_csv(cleaned_dir / "cleaning_summary.csv", index=False)
    print(summary.to_string(index=False))
    print(f"\nProcessed successfully: {(summary['status'] == 'cleaned').sum()}")
    print(f"Skipped duplicate content: {(summary['status'] == 'skipped_duplicate_content').sum()}")
    print(f"Problematic files: {summary['status'].astype(str).str.startswith('problem:').sum()}")
    print(f"Total CSV files found: {len(input_files)}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean and audit one CSV or every CSV in data/raw/.")
    parser.add_argument("--input-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--input-file", type=Path)
    parser.add_argument("--project-dir", type=Path, default=Path("."))
    parser.add_argument("--target")
    parser.add_argument("--output-file", type=Path)
    parser.add_argument("--all", action="store_true", help="Process every CSV in input-dir.")
    args = parser.parse_args()

    if args.all:
        input_dir = args.input_dir if args.input_dir.is_absolute() else args.project_dir / args.input_dir
        process_all(input_dir, args.project_dir / "data/cleaned")
        return
    if not args.input_file:
        parser.error("provide --input-file or use --all")
    input_path = args.input_file if args.input_file.is_absolute() else args.project_dir / args.input_file
    output_path = args.output_file or (args.project_dir / "data/cleaned" / f"{input_path.stem}_cleaned.csv")
    if not output_path.is_absolute():
        output_path = args.project_dir / output_path
    cleaned_dir = (args.project_dir / "data/cleaned").resolve()
    output_path = output_path.resolve()
    if output_path.parent != cleaned_dir:
        raise ValueError(f"Cleaned datasets must be saved directly inside {cleaned_dir}")
    _, report = clean_frame(input_path.resolve(), output_path, args.target)
    audit_path = _audit_path(cleaned_dir, input_path)
    print(json.dumps({"cleaned_file": str(output_path), "audit_file": str(audit_path),
                      "rows_before": report["rows_before"], "rows_after": report["rows_after"]}, indent=2))


if __name__ == "__main__":
    main()
