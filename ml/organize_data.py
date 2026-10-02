"""Audit and organize dissertation datasets without merging their meanings."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from clean_dataset import clean_frame, process_all

VERSION = "1.0.0"
TARGETS = {"route_failure", "link_failure", "loss_occurred", "attack", "cause_label", "label", "target", "sim_label"}
METADATA = {
    "run", "run_id", "seed", "ns3_seed", "time", "timestamp", "node_id", "src_id", "dst_id", "flow_id",
    "node_count", "sim_area_m", "sim_duration_s", "mobility_model", "channel_helper", "stack", "routing",
    "transport", "app", "phy", "random_seed", "random_run", "split", "row_id",
}
CANONICAL = {
    "speed": ("node_speed", "unknown", "Potentially equivalent; verify units."),
    "speed_mps": ("node_speed", "m/s", "Potentially equivalent; verify units."),
    "node_speed": ("node_speed", "m/s", "Canonical name already used."),
    "rssi": ("rssi_dbm", "dBm", "Potentially equivalent; verify units."),
    "avg_rssi": ("rssi_dbm", "dBm", "Potentially equivalent; verify units."),
    "rssi_dbm": ("rssi_dbm", "dBm", "Canonical name already used."),
    "snr": ("snr_db", "dB", "Potentially equivalent; verify units."),
    "snr_db": ("snr_db", "dB", "Canonical name already used."),
    "delay": ("delay_ms", "unknown", "Potentially equivalent; verify units."),
    "delay_ms": ("delay_ms", "ms", "Canonical name already used."),
    "end_to_end_delay_ms": ("delay_ms", "ms", "Potentially equivalent; verify units."),
    "pdr": ("pdr", "ratio", "Potentially equivalent; verify definition."),
    "prr": ("pdr", "ratio", "Potentially equivalent; verify definition."),
    "packet_loss": ("packet_loss", "unknown", "May mean packets, rate, or ratio."),
    "lost_packets": ("packet_loss", "packets", "Potentially equivalent only after unit validation."),
    "queue_length": ("queue_length", "unknown", "Potentially equivalent; verify units."),
    "queue_len_norm": ("queue_length", "normalized", "Potentially equivalent; verify definition."),
    "energy": ("remaining_energy", "unknown", "Potentially equivalent; verify units."),
    "remaining_energy": ("remaining_energy", "unknown", "Canonical name already used."),
    "throughput": ("throughput_bps", "unknown", "Potentially equivalent; verify units."),
    "throughput_bps": ("throughput_bps", "bps", "Canonical name already used."),
    "x": ("position_x", "unknown", "Potentially equivalent; verify coordinate system."),
    "position_x": ("position_x", "unknown", "Canonical name already used."),
    "y": ("position_y", "unknown", "Potentially equivalent; verify coordinate system."),
    "position_y": ("position_y", "unknown", "Canonical name already used."),
    "link_changes_per_s": ("link_changes_per_s", "1/s", "Canonical feature dictionary entry."),
    "etx": ("etx", "ratio", "Canonical feature dictionary entry."),
    "jitter_ms": ("jitter_ms", "ms", "Canonical feature dictionary entry."),
    "collisions": ("collisions", "count", "Canonical feature dictionary entry."),
    "mac_retries": ("mac_retries", "count", "Canonical feature dictionary entry."),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def targets(columns: list[str]) -> list[str]:
    return [column for column in columns if normalize(column) in TARGETS or normalize(column).endswith("_target")]


def classify(name: str, columns: list[str], target_columns: list[str]) -> tuple[str, str, str, bool, str]:
    lower = name.lower()
    if lower.startswith("positions_") or set(columns) >= {"run", "time", "node_id", "x", "y", "speed"}:
        return "mobility dataset", "node/time", "Mobility and scalability analysis", False, "No failure target; retain as a source dataset."
    if "link_failure" in target_columns:
        return "MANET/link-failure benchmark", "node/time", "Primary link-failure prediction candidate", True, "Target semantics and prediction window require domain confirmation."
    if "loss_occurred" in target_columns:
        return "NS-3 packet-loss benchmark", "flow/time", "Independent packet-loss experiment", False, "loss_occurred is not route_failure or link_failure."
    if "attack" in target_columns or ("label" in target_columns and "nodes" in lower):
        return "attack/anomaly benchmark", "node/time", "Supplementary attack or anomaly analysis", False, "Attack/label semantics are not route/link failure."
    if "route_failure" in target_columns:
        return "DSR route-failure dataset", "route/time", "Primary route-failure prediction candidate", True, "Verify pre-failure feature timing and prediction window."
    return "feature/source dataset", "unknown", "Feature source for future experiments", False, "No clearly defined route/link failure target."


def node_count(frame: pd.DataFrame, name: str) -> str:
    if "node_count" in frame.columns:
        values = frame["node_count"].dropna().unique()
        if len(values):
            return ";".join(str(value) for value in values[:10])
    if "node_id" in frame.columns:
        return str(frame["node_id"].nunique())
    match = re.search(r"positions_(\d+)", name)
    return match.group(1) if match else ""


def run_count(frame: pd.DataFrame) -> str:
    for column in ("run_id", "run", "random_run"):
        if column in frame.columns:
            return str(frame[column].nunique())
    return ""


def raw_inventory(root: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    for path in sorted((root / "data/raw").glob("*.csv")):
        frame = pd.read_csv(path, low_memory=False)
        columns = [normalize(column) for column in frame.columns]
        target_columns = targets(columns)
        dataset_type, grain, purpose, compatible, notes = classify(path.stem, columns, target_columns)
        digest = sha256(path)
        rows.append({
            "filename": path.name, "sha256": digest, "duplicate_of": hashes.get(digest, ""),
            "rows": len(frame), "columns": len(columns), "column_names": ";".join(columns),
            "data_types": ";".join(f"{normalized}:{frame[original].dtype}" for original, normalized in zip(frame.columns, columns)),
            "target_columns": ";".join(target_columns), "dataset_type": dataset_type, "dataset_grain": grain,
            "node_count": node_count(frame, path.stem), "run_count": run_count(frame),
            "source_information": ";".join(f"{c}={frame[c].dropna().iloc[0]}" for c in ["sim_label", "routing", "mobility_model"] if c in frame and not frame[c].dropna().empty),
            "intended_research_purpose": purpose, "compatible_with_main_ml": compatible, "notes": notes,
        })
        hashes.setdefault(digest, path.name)
    output = pd.DataFrame(rows)
    output.to_csv(root / "data/processed/raw_inventory.csv", index=False)
    return output


def enrich_cleaned_audits(root: Path, inventory: pd.DataFrame) -> None:
    for record in inventory.to_dict("records"):
        audit_path = root / "data/cleaned" / f"{Path(record['filename']).stem}_audit.json"
        if not audit_path.exists():
            continue
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        audit.update({
            "dataset_type": record["dataset_type"], "dataset_grain": record["dataset_grain"],
            "node_count": record["node_count"], "run_count": record["run_count"],
            "source_information": record["source_information"], "intended_research_purpose": record["intended_research_purpose"],
            "raw_sha256": record["sha256"], "target_semantics_preserved": True,
        })
        audit_path.write_text(json.dumps(audit, indent=2, default=str), encoding="utf-8")


def processed_registry(root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    processed = root / "data/processed"
    files = sorted(processed.glob("*.csv"))
    hashes: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    mappings: list[dict[str, str]] = []
    for path in files:
        frame = pd.read_csv(path, low_memory=False)
        columns = [normalize(column) for column in frame.columns]
        target_columns = targets(columns)
        digest = sha256(path)
        if path.name in {"dataset_registry.csv", "column_mapping.csv", "raw_inventory.csv"}:
            category, purpose, compatible = "metadata/audit", "Registry, mapping, or inventory metadata", "no"
            grain = "metadata"
        elif path.name.startswith("split_"):
            category, purpose, compatible = "split membership file", "Fixed split membership", "no"
            grain = "row/split"
        elif "summary" in path.name or path.name.endswith("inventory.csv"):
            category, purpose, compatible = "intermediate summary", "Pipeline summary or inventory", "no"
            grain = "summary"
        elif path.name == "features.csv":
            category, purpose, compatible = "smoke-test dataset", "Pipeline validation only", "no"
            grain = "row/observation"
        else:
            category, purpose, compatible = "feature-engineered dataset", "Independent feature dataset", "conditional"
            grain = "node/time" if "position" in path.name or "nodes" in path.name else "row/observation"
        feature_columns = [column for column in columns if column not in target_columns and column not in METADATA and column != "split"]
        for column in columns:
            if column in CANONICAL:
                canonical, unit, notes = CANONICAL[column]
                mappings.append({"canonical_feature": canonical, "dataset": path.name, "original_column": column, "unit": unit, "confidence": "high" if column == canonical else "medium", "notes": notes})
        rows.append({
            "dataset_name": path.stem, "source_file": path.name, "sha256": digest, "duplicate_of": hashes.get(digest, ""),
            "category": category, "rows": len(frame), "columns": len(columns), "target": ";".join(target_columns),
            "dataset_grain": grain, "node_count": node_count(frame, path.stem), "run_count": run_count(frame),
            "feature_count": len(feature_columns), "purpose": purpose, "compatible_with_main_ml": compatible,
            "notes": "Target/source columns retained; no datasets merged." if target_columns else "No target detected; not a failure-label dataset.",
        })
        hashes.setdefault(digest, path.name)
    registry = pd.DataFrame(rows)
    mapping = pd.DataFrame(mappings).drop_duplicates()
    registry.to_csv(processed / "dataset_registry.csv", index=False)
    mapping.to_csv(processed / "column_mapping.csv", index=False)
    return registry, mapping


def write_final(root: Path, inventory: pd.DataFrame) -> None:
    final = root / "data/final"
    for name in ["ml_link_failure", "ml_packet_loss", "mobility", "dsr_final", "smoke_test", "manifests"]:
        (final / name).mkdir(parents=True, exist_ok=True)
    copies = {
        "manet_dataset_cleaned.csv": "ml_link_failure",
        "packet_loss_cleaned.csv": "ml_packet_loss",
        "features.csv": "smoke_test",
    }
    for source, destination in copies.items():
        source_path = root / "data/cleaned" / source if source != "features.csv" else root / "data/processed/features.csv"
        if source_path.exists():
            shutil.copy2(source_path, final / destination / source)
    for record in inventory.to_dict("records"):
        if record["dataset_type"] == "mobility dataset":
            source = root / "data/cleaned" / f"{Path(record['filename']).stem}_cleaned.csv"
            if source.exists():
                shutil.copy2(source, final / "mobility" / source.name)
    readmes = {
        "ml_link_failure": "# Link-failure experiment\n\nThis is the cleaned `manet_dataset.csv` dataset. Its target remains `link_failure`; it is a MANET/link-failure candidate, not a relabeled `route_failure` dataset. Validate prediction-window and timestamp semantics before dissertation claims.\n",
        "ml_packet_loss": "# Packet-loss experiment\n\nThis is the cleaned `packet_loss.csv` dataset. Its target remains `loss_occurred`; it is an independent packet-loss experiment and must not be used as a route/link-failure target.\n",
        "mobility": "# Mobility datasets\n\nThese files preserve run, time, node_id, x, y, and speed. They are node/time mobility and scalability datasets, not route-failure training data.\n",
        "dsr_final": "# DSR final datasets\n\nReserved for a future custom NS-3 DSR dataset with timestamped pre-failure features and a documented future-window route/link-failure label. No such dataset is claimed here.\n",
        "smoke_test": "# Smoke test\n\n`features.csv` is synthetic/pipeline-validation data and must not be presented as dissertation evidence.\n",
    }
    for directory, text in readmes.items():
        (final / directory / "README.md").write_text(text, encoding="utf-8")


def write_manifests(root: Path, inventory: pd.DataFrame, registry: pd.DataFrame, mapping: pd.DataFrame) -> None:
    manifests = root / "data/final/manifests"
    inventory.to_csv(manifests / "raw_inventory.csv", index=False)
    registry.to_csv(manifests / "dataset_registry.csv", index=False)
    mapping.to_csv(manifests / "feature_dictionary.csv", index=False)
    target_rows = [
        {"target": "route_failure", "meaning": "Future active-route failure within a documented prediction window", "status": "required for primary route-failure experiment"},
        {"target": "link_failure", "meaning": "Source link-failure label; source semantics preserved", "status": "separate link-failure candidate"},
        {"target": "loss_occurred", "meaning": "Packet-loss occurrence", "status": "separate packet-loss experiment"},
        {"target": "attack", "meaning": "Attack classification", "status": "not route/link failure"},
        {"target": "cause_label", "meaning": "Packet-loss cause label", "status": "not route/link failure"},
        {"target": "label", "meaning": "Source-defined label", "status": "requires domain definition"},
    ]
    pd.DataFrame(target_rows).to_csv(manifests / "target_dictionary.csv", index=False)
    decisions = [
        {"datasets": "manet_dataset", "decision": "keep separate; copy to ml_link_failure", "reason": "link_failure target and node/time MANET grain; no relabeling"},
        {"datasets": "packet_loss", "decision": "keep separate; copy to ml_packet_loss", "reason": "loss_occurred target and flow/time grain"},
        {"datasets": "nodes_dynamic", "decision": "do not merge or promote", "reason": "attack/label semantics are not route/link failure"},
        {"datasets": "positions_*", "decision": "keep separate mobility files", "reason": "node/time positions and speed; no failure target"},
        {"datasets": "features.csv", "decision": "keep as smoke_test", "reason": "synthetic pipeline-validation data"},
    ]
    pd.DataFrame(decisions).to_csv(manifests / "merge_decisions.csv", index=False)
    report = [
        "# Dataset selection report", "", f"Generated UTC: {now()}", "",
        "## Primary ML candidates", "- `manet_dataset_cleaned.csv`: conditional link-failure candidate. The source target `link_failure` is preserved and is not silently converted to `route_failure`. Confirm the target definition, prediction timestamp, future window, and leakage exclusions before using it as primary evidence.",
        "- No dataset currently proves a DSR-specific `route_failure` target with all timing requirements. Reserve `data/final/dsr_final/` for the future custom NS-3 dataset.", "",
        "## Supplementary datasets", "- `packet_loss_cleaned.csv`: independent NS-3 packet-loss benchmark with `loss_occurred`, `cause_label`, and `drop_reason` concepts kept separate.", "- `nodes_dynamic_cleaned.csv`: supplementary attack/anomaly dataset; its labels are not route/link failure.", "",
        "## Mobility and smoke data", "- `positions_*_cleaned.csv`: mobility/scalability datasets retained independently with run/time/node context.", "- `features.csv`: smoke-test data only; it is not dissertation evidence.", "",
        "## Joining policy", "No datasets were merged. Similar names are documented in `feature_dictionary.csv`, but unit, time alignment, key uniqueness, and target semantics are not sufficient to authorize a join. Future joins must validate composite keys such as run/time/node or run/time/src/dst/flow and report unmatched and duplicate keys.", "",
        "## Reproducibility", "Raw files remain immutable. Cleaning audits, hashes, inventories, registries, target definitions, and merge decisions are stored alongside the outputs. Re-run `venv/bin/python ml/organize_data.py --project-dir .` after adding raw files.", "",
    ]
    (manifests / "dataset_selection_report.md").write_text("\n".join(report), encoding="utf-8")


def validate(root: Path, inventory: pd.DataFrame) -> None:
    raw_paths = sorted((root / "data/raw").glob("*.csv"))
    missing = [path.name for path in raw_paths if not (root / "data/cleaned" / f"{path.stem}_cleaned.csv").exists()]
    if missing:
        raise RuntimeError(f"Missing cleaned counterparts: {missing}")
    if len(inventory) != len(raw_paths):
        raise RuntimeError("Raw inventory does not cover every raw CSV")
    if any(not (root / "data/final/manifests" / name).exists() for name in ["dataset_registry.csv", "feature_dictionary.csv", "target_dictionary.csv", "merge_decisions.csv", "dataset_selection_report.md"]):
        raise RuntimeError("Final manifest set is incomplete")
    print(json.dumps({
        "raw_csvs": len(raw_paths), "cleaned_counterparts": len(raw_paths),
        "raw_duplicate_groups": int((inventory["duplicate_of"] != "").sum()),
        "primary_candidates": inventory.loc[inventory["compatible_with_main_ml"] == True, "filename"].tolist(),
        "merged_datasets": 0, "status": "validated",
    }, indent=2))


def print_final_report(inventory: pd.DataFrame) -> None:
    print("\nRAW DATASETS")
    print("\n".join(f"- {name}" for name in inventory["filename"]) or "- None")
    print("\nCLEANED DATASETS")
    print("- One cleaned counterpart and audit JSON for every raw CSV")
    print("\nPROCESSED DATASETS")
    print("- Independent feature datasets, summaries, split files, and metadata registries")
    print("\nFINAL DATASETS")
    print("- ml_link_failure, ml_packet_loss, mobility, smoke_test; dsr_final is reserved")
    print("\nDUPLICATES")
    duplicates = inventory.loc[inventory["duplicate_of"] != "", "filename"].tolist()
    print("- None detected by SHA-256" if not duplicates else "- " + ", ".join(duplicates))
    print("\nPOSSIBLE MERGES")
    print("- None approved; similar columns are documented only in feature_dictionary.csv")
    print("\nDATASETS REQUIRING SEPARATE EXPERIMENTS")
    print("- manet_dataset, packet_loss, nodes_dynamic, and every positions_* file")
    print("\nPRIMARY ML CANDIDATES")
    print("- manet_dataset.csv as a conditional link_failure candidate; no verified route_failure dataset")
    print("\nSUPPLEMENTARY DATASETS")
    print("- packet_loss.csv and nodes_dynamic.csv")
    print("\nDATASETS UNSUITABLE FOR ROUTE/LINK FAILURE PREDICTION")
    print("- positions_* mobility datasets and the synthetic features.csv smoke dataset")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", type=Path, default=Path("."))
    args = parser.parse_args()
    root = args.project_dir.resolve()
    raw = inventory = raw_inventory(root)
    process_all(root / "data/raw", root / "data/cleaned")
    enrich_cleaned_audits(root, inventory)
    registry, mapping = processed_registry(root)
    write_final(root, inventory)
    write_manifests(root, inventory, registry, mapping)
    validate(root, inventory)
    print_final_report(inventory)
    print(f"Organization complete: {len(raw)} raw datasets audited; no datasets merged.")


if __name__ == "__main__":
    main()