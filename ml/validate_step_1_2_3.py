#!/usr/bin/env python3
"""Validate metadata, topology, mobility, joins, and ns-3 provenance."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "metadata" / "Simulation_data.csv"
TOPOLOGY = ROOT / "data" / "topology" / "Topology_data.csv"
MOBILITY = ROOT / "data" / "mobility" / "Mobility_data.csv"
REPORT_DIR = ROOT / "data" / "validation"
SAMPLE_INTERVAL_S = 1.0
RADIO_RANGE_M = 250.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata-csv", type=Path, default=MANIFEST)
    parser.add_argument("--topology-csv", type=Path, default=TOPOLOGY)
    parser.add_argument("--mobility-csv", type=Path, default=MOBILITY)
    parser.add_argument("--ns3-dir", type=Path, required=True, help="Built ns-3 tree containing scenario logs")
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--chunk-rows", type=int, default=250_000)
    return parser.parse_args()


def _summary() -> dict[str, Any]:
    return {"rows": 0, "nodes": set(), "times": set(), "source_files": set(), "issues": []}


def _manifest_issue(frame: pd.DataFrame, manifest: pd.DataFrame, columns: list[str], path: Path, issues: list[str]) -> None:
    indexed = manifest.set_index("scenario_id")
    for column in columns:
        expected = frame["scenario_id"].map(indexed[column])
        mismatch = ~frame[column].eq(expected)
        if mismatch.any():
            affected = frame.loc[mismatch, "scenario_id"].astype(str).drop_duplicates().tolist()
            issues.append(f"{path}: {column} mismatch for {affected[:20]}")


def validate_dataset(path: Path, kind: str, manifest: pd.DataFrame, chunk_rows: int) -> dict[str, Any]:
    issues: list[str] = []
    headers = set(pd.read_csv(path, nrows=0).columns) if path.is_file() else set()
    if not headers:
        return {"path": str(path), "kind": kind, "status": "RED", "scenario_count": 0, "expected_scenario_count": len(manifest), "observed_scenario_ids": [], "scenarios": {}, "issues": [f"{path}: file missing or empty"]}
    if kind == "mobility":
        required = {
            "scenario_id", "run_id", "random_seed", "random_run", "time_s", "node_id", "x_m", "y_m",
            "speed_mps", "velocity_x_mps", "velocity_y_mps", "direction_deg", "node_count", "mobility_model",
            "area_x_m", "area_y_m", "simulation_duration_s", "sampling_interval_s", "source_type",
            "source_scenario_id", "source_run_id", "source_file",
        }
        order_columns = ["scenario_id", "time_s", "node_id"]
    else:
        required = {
            "scenario_id", "run_id", "random_seed", "random_run", "time_s", "node_id", "node_count",
            "neighbor_count", "neighbor_ids_hex",
        }
        order_columns = ["scenario_id", "time_s", "node_id"]
    missing = required - headers
    if missing:
        counts: dict[str, int] = {}
        for chunk in pd.read_csv(path, usecols=["scenario_id"], chunksize=chunk_rows):
            counts.update({str(sid): counts.get(str(sid), 0) + int(count) for sid, count in chunk.groupby("scenario_id").size().items()})
        return {
            "path": str(path), "kind": kind, "status": "RED", "scenario_count": len(counts),
            "expected_scenario_count": len(manifest),
            "observed_scenario_ids": sorted(counts),
            "scenarios": {sid: {"status": "RED", "rows": count} for sid, count in counts.items()},
            "issues": [f"{path}: missing columns {sorted(missing)}"],
        }

    manifest_index = manifest.set_index("scenario_id")
    manifest_order = {sid: index for index, sid in enumerate(manifest["scenario_id"].astype(str))}
    summaries: dict[str, dict[str, Any]] = {}
    previous_key: tuple[int, float, int] | None = None
    duplicate_count = 0
    out_of_order_count = 0
    read_columns = list(required)
    for chunk in pd.read_csv(path, usecols=read_columns, chunksize=chunk_rows):
        chunk["scenario_id"] = chunk["scenario_id"].astype(str)
        unknown = ~chunk["scenario_id"].isin(manifest_index.index)
        if unknown.any():
            issues.append(f"{path}: unknown scenarios {chunk.loc[unknown, 'scenario_id'].drop_duplicates().tolist()[:20]}")
            chunk = chunk.loc[~unknown].copy()
        if chunk.empty:
            continue

        _manifest_issue(chunk, manifest, ["run_id", "random_seed", "random_run"], path, issues)
        order = chunk[order_columns].copy()
        order["_manifest_order"] = order["scenario_id"].map(manifest_order)
        keys = pd.MultiIndex.from_frame(order[["_manifest_order", "time_s", "node_id"]])
        if not keys.is_monotonic_increasing:
            out_of_order_count += 1
        if previous_key is not None and tuple(keys[0]) <= previous_key:
            out_of_order_count += 1
            duplicate_count += int(tuple(keys[0]) == previous_key)
        duplicate_count += int(order.duplicated(["_manifest_order", "time_s", "node_id"]).sum())
        previous_key = tuple(keys[-1])

        for scenario_id, rows in chunk.groupby("scenario_id", sort=False):
            item = summaries.setdefault(scenario_id, _summary())
            item["rows"] += len(rows)
            item["nodes"].update(pd.to_numeric(rows["node_id"], errors="coerce").dropna().astype(int).tolist())
            item["times"].update(pd.to_numeric(rows["time_s"], errors="coerce").dropna().astype(float).tolist())
            if "source_file" in rows:
                item["source_files"].update(rows["source_file"].dropna().astype(str).unique().tolist())

        if kind == "mobility":
            _manifest_issue(chunk, manifest, [column for column in (
                "node_count", "mobility_model", "area_m", "traffic_rate_bps", "packet_size_bytes", "source_id",
                "destination_id", "routing_protocol", "wifi_standard",
            ) if column in chunk.columns], path, issues)
            source_bad = ~chunk["source_scenario_id"].eq(chunk["scenario_id"])
            source_bad |= ~chunk["source_run_id"].eq(chunk["run_id"])
            source_bad |= ~chunk["source_type"].eq("new_ns3_simulation")
            if source_bad.any():
                issues.append(f"{path}: mobility provenance mismatch for {chunk.loc[source_bad, 'scenario_id'].drop_duplicates().tolist()[:20]}")
            for column in ("x_m", "y_m", "time_s", "node_id", "speed_mps", "velocity_x_mps", "velocity_y_mps"):
                chunk[column] = pd.to_numeric(chunk[column], errors="coerce")
                if not np.isfinite(chunk[column].dropna()).all():
                    issues.append(f"{path}: non-finite {column} values")
            x_limit = chunk["scenario_id"].map(manifest_index["area_x_m"])
            y_limit = chunk["scenario_id"].map(manifest_index["area_y_m"])
            invalid = ~chunk["node_id"].between(0, chunk["scenario_id"].map(manifest_index["node_count"]) - 1)
            invalid |= ~chunk["time_s"].between(0, chunk["scenario_id"].map(manifest_index["simulation_duration_s"]))
            invalid |= ~chunk["x_m"].between(0, x_limit) | ~chunk["y_m"].between(0, y_limit)
            if invalid.any():
                issues.append(f"{path}: invalid node/time/coordinate values for {chunk.loc[invalid, 'scenario_id'].drop_duplicates().tolist()[:20]}")
            if not chunk["sampling_interval_s"].eq(SAMPLE_INTERVAL_S).all():
                issues.append(f"{path}: sampling_interval_s differs from {SAMPLE_INTERVAL_S}")
            expected_speed = np.hypot(chunk["velocity_x_mps"], chunk["velocity_y_mps"])
            actual_speed = pd.to_numeric(chunk["speed_mps"], errors="coerce")
            comparable = actual_speed.notna()
            if comparable.any() and not np.isclose(actual_speed[comparable], expected_speed[comparable], rtol=1e-6, atol=1e-6).all():
                issues.append(f"{path}: speed does not match velocity components")
            direction = pd.to_numeric(chunk["direction_deg"], errors="coerce")
            moving = comparable & actual_speed.gt(1e-12)
            expected_direction = np.degrees(np.arctan2(chunk["velocity_y_mps"], chunk["velocity_x_mps"])) % 360.0
            if moving.any() and not np.isclose(direction[moving], expected_direction[moving], rtol=0.0, atol=1e-4).all():
                issues.append(f"{path}: direction does not match velocity components")
            speed_limit = chunk["scenario_id"].map(manifest_index["speed_mps"])
            if (actual_speed.dropna() > speed_limit.loc[actual_speed.notna()] + 0.05).any():
                issues.append(f"{path}: measured speed exceeds manifest speed limit")
            missing_archives = []
            for sid, source_file in chunk[["scenario_id", "source_file"]].drop_duplicates().itertuples(index=False, name=None):
                archive = ROOT / str(source_file)
                if not archive.is_file():
                    missing_archives.append(str(sid))
            if missing_archives:
                issues.append(f"{path}: missing archived traces for {missing_archives[:20]}")
        else:
            _manifest_issue(chunk, manifest, ["node_count"], path, issues)
            invalid = ~chunk["node_id"].between(0, chunk["node_count"] - 1)
            invalid |= ~chunk["neighbor_count"].between(0, chunk["node_count"] - 1)
            if invalid.any():
                issues.append(f"{path}: invalid topology node or neighbor counts")
            for row in chunk[["node_id", "node_count", "neighbor_count", "neighbor_ids_hex"]].itertuples(index=False):
                try:
                    bits = int(row.neighbor_ids_hex, 16)
                    valid = bits.bit_count() == int(row.neighbor_count)
                    valid &= bits >> int(row.node_count) == 0
                    valid &= bits & (1 << int(row.node_id)) == 0
                except (TypeError, ValueError):
                    valid = False
                if not valid:
                    issues.append(f"{path}: invalid neighbor bitset at node_id={row.node_id}")
                    break

    if duplicate_count:
        issues.append(f"{path}: {duplicate_count} duplicate node-time keys")
    if out_of_order_count:
        issues.append(f"{path}: records are not in unique manifest/time/node order")

    per_scenario: dict[str, Any] = {}
    for row in manifest.itertuples(index=False):
        sid = str(row.scenario_id)
        item = summaries.get(sid)
        expected_times = int(math.floor(float(row.simulation_duration_s) / SAMPLE_INTERVAL_S + 1e-9)) + 1
        expected_rows = int(row.node_count) * expected_times
        if item is None:
            per_scenario[sid] = {"status": "MISSING", "rows": 0}
            continue
        nodes = item["nodes"]
        times = item["times"]
        valid_nodes = nodes == set(range(int(row.node_count)))
        expected_time_values = {index * SAMPLE_INTERVAL_S for index in range(expected_times)}
        valid_times = times == expected_time_values
        scenario_status = "GREEN" if item["rows"] == expected_rows and valid_nodes and valid_times else "RED"
        per_scenario[sid] = {
            "status": scenario_status,
            "rows": item["rows"],
            "expected_rows": expected_rows,
            "nodes": len(nodes),
            "expected_nodes": int(row.node_count),
            "time_count": len(times),
            "expected_time_count": expected_times,
            "source_files": sorted(item["source_files"]),
        }
        if scenario_status == "RED":
            issues.append(f"{path}: {sid} has rows/nodes/time coverage {item['rows']}/{len(nodes)}/{len(times)}; expected {expected_rows}/{row.node_count}/{expected_times}")

    scenario_ids = set(summaries)
    report = {
        "path": str(path),
        "kind": kind,
        "scenario_count": len(scenario_ids),
        "expected_scenario_count": len(manifest),
        "observed_scenario_ids": sorted(scenario_ids),
        "scenarios": per_scenario,
        "issues": sorted(set(issues)),
        "status": "GREEN" if len(scenario_ids) == len(manifest) and not issues else "RED",
    }
    return report


def validate_simulation_logs(manifest: pd.DataFrame, ns3_dir: Path) -> dict[str, Any]:
    issues: list[str] = []
    for row in manifest.itertuples(index=False):
        scenario_id = str(row.scenario_id)
        log_path = ns3_dir / "results" / "scenarios" / scenario_id / "logs" / f"simulation_seed_{int(row.random_seed)}_run_{int(row.random_run)}.log"
        if not log_path.is_file():
            issues.append(f"{log_path}: missing run log for {scenario_id}")
            continue
        values = dict(line.split("=", 1) for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines() if "=" in line)
        expected = {
            "scenario_id": scenario_id,
            "run_id": str(int(row.run_id)),
            "random_seed": str(int(row.random_seed)),
            "random_run": str(int(row.random_run)),
            "node_count": str(int(row.node_count)),
            "packet_size": str(int(row.packet_size_bytes)),
            "source": str(int(row.source_id)),
            "destination": str(int(row.destination_id)),
            "routing_protocol": str(row.routing_protocol),
            "mobility_model": str(row.mobility_model),
            "wifi_standard": str(row.wifi_standard),
            "channel_helper": str(row.channel_helper),
            "transport_protocol": str(row.transport_protocol),
            "application_type": str(row.application_type),
            "flow_id": str(int(row.flow_id)),
            "udp_port": "9000",
            "traffic_rate": f"{int(row.traffic_rate_bps)}bps",
            "animation_enabled": "false",
            "status": "baseline_dsr_run_complete",
        }
        float_expected = {
            "simulation_time": float(row.simulation_duration_s),
            "area_x_m": float(row.area_x_m),
            "area_y_m": float(row.area_y_m),
            "node_speed": float(row.speed_mps),
            "tx_power_dbm": float(row.tx_power_dbm),
            "noise_floor_dbm": float(row.noise_floor_dbm),
            "sampling_interval_s": SAMPLE_INTERVAL_S,
            "radio_range_m": RADIO_RANGE_M,
        }
        bad = [key for key, expected_value in expected.items() if values.get(key) != expected_value]
        for key, expected_value in float_expected.items():
            try:
                if not math.isclose(float(values[key]), expected_value, rel_tol=0.0, abs_tol=1e-6):
                    bad.append(key)
            except (KeyError, ValueError):
                bad.append(key)
        if bad:
            issues.append(f"{log_path}: configuration mismatch for {scenario_id}: {bad}")
    return {"status": "GREEN" if not issues else "RED", "issues": issues}


def main() -> None:
    args = parse_args()
    metadata = pd.read_csv(args.metadata_csv)
    required_manifest = {
        "scenario_id", "run_id", "random_seed", "random_run", "node_count", "mobility_model", "area_m",
        "area_x_m", "area_y_m", "simulation_duration_s", "traffic_rate_bps", "packet_size_bytes",
        "routing_protocol", "source_id", "destination_id", "speed_mps", "wifi_standard", "channel_helper",
        "tx_power_dbm", "noise_floor_dbm", "transport_protocol", "application_type", "flow_id",
    }
    manifest_issues = []
    missing = required_manifest - set(metadata.columns)
    if missing:
        manifest_issues.append(f"{args.metadata_csv}: missing columns {sorted(missing)}")
    if len(metadata) != 180:
        manifest_issues.append(f"{args.metadata_csv}: expected 180 rows, found {len(metadata)}")
    if metadata["scenario_id"].nunique() != len(metadata):
        manifest_issues.append(f"{args.metadata_csv}: duplicate scenario_id values")
    if metadata["run_id"].nunique() != len(metadata):
        manifest_issues.append(f"{args.metadata_csv}: duplicate run_id values")
    metadata_status = "GREEN" if not manifest_issues else "RED"
    topology = validate_dataset(args.topology_csv, "topology", metadata, args.chunk_rows)
    mobility = validate_dataset(args.mobility_csv, "mobility", metadata, args.chunk_rows)
    logs = validate_simulation_logs(metadata, args.ns3_dir.resolve())

    topology_report_path = args.topology_csv.parent / "topology_generation_report.json"
    provenance_issues = []
    if topology_report_path.is_file():
        topology_report = json.loads(topology_report_path.read_text(encoding="utf-8"))
        if not math.isclose(float(topology_report.get("radio_range_m", -1)), RADIO_RANGE_M, rel_tol=0.0, abs_tol=1e-9):
            provenance_issues.append(f"{topology_report_path}: radio range is absent or inconsistent")
        if not math.isclose(float(topology_report.get("observation_interval_s", -1)), SAMPLE_INTERVAL_S, rel_tol=0.0, abs_tol=1e-9):
            provenance_issues.append(f"{topology_report_path}: observation interval is absent or inconsistent")
        trace_map = topology_report.get("source_trace_by_scenario", {})
        for sid, item in topology.get("scenarios", {}).items():
            source_file = trace_map.get(sid)
            if not source_file:
                provenance_issues.append(f"{topology_report_path}: missing source trace mapping for {sid}")
                item["source_files"] = []
                continue
            if not (ROOT / source_file).is_file():
                provenance_issues.append(f"{ROOT / source_file}: missing archived trace for {sid}")
            item["source_files"] = [str(source_file)]
    else:
        provenance_issues.append(f"{topology_report_path}: missing topology provenance report")
    if provenance_issues:
        topology["issues"] = sorted(set(topology["issues"] + provenance_issues))
        topology["status"] = "RED"

    topology_ids = set(topology["observed_scenario_ids"])
    mobility_ids = set(mobility["observed_scenario_ids"])
    manifest_ids = set(metadata["scenario_id"].astype(str))
    topology_missing_ids = sorted(manifest_ids - topology_ids)
    mobility_missing_ids = sorted(manifest_ids - mobility_ids)
    cross_issues = []
    if topology_ids != mobility_ids:
        cross_issues.append(f"Topology/mobility scenario sets differ: topology={len(topology_ids)}, mobility={len(mobility_ids)}")
    if topology_missing_ids:
        cross_issues.append(f"{args.topology_csv}: missing manifest scenarios: {', '.join(topology_missing_ids)}")
    if mobility_missing_ids:
        cross_issues.append(f"{args.mobility_csv}: missing manifest scenarios: {', '.join(mobility_missing_ids)}")
    mobility_sources = {
        sid: item.get("source_files", set()) for sid, item in mobility.get("scenarios", {}).items()
    }
    for sid, item in topology.get("scenarios", {}).items():
        source_files = mobility_sources.get(sid, set())
        topo_files = item.get("source_files", set())
        if source_files and topo_files and source_files != topo_files:
            cross_issues.append(f"Topology/mobility source trace differs for {sid}")
    cross_issues.extend(provenance_issues)
    cross_status = "GREEN" if not cross_issues else "RED"
    statuses = [metadata_status, topology["status"], mobility["status"], logs["status"], cross_status]
    overall = "GREEN" if all(status == "GREEN" for status in statuses) else "RED"

    report = {
        "project": "DSR MANET dissertation pipeline",
        "step_1_metadata": {"status": metadata_status, "rows": len(metadata), "unique_scenarios": int(metadata["scenario_id"].nunique()), "issues": manifest_issues},
        "step_2_topology": topology,
        "step_3_mobility": mobility,
        "cross_dataset_validation": {"status": cross_status, "issues": cross_issues},
        "missing_scenario_ids": {"topology": topology_missing_ids, "mobility": mobility_missing_ids},
        "dsr_consistency": logs,
        "overall_status": overall,
        "final_step_4_readiness": "GREEN" if overall == "GREEN" else "RED",
    }
    args.report_dir.mkdir(parents=True, exist_ok=True)
    (args.report_dir / "step_1_2_3_validation.json").write_text(json.dumps(report, indent=2, default=lambda value: sorted(value) if isinstance(value, set) else str(value)) + "\n", encoding="utf-8")
    lines = [
        "========================================",
        "🟢 GREEN SIGNAL" if overall == "GREEN" else "🔴 RED — NOT READY",
        "========================================",
        f"STEP 1 Metadata: {metadata_status}",
        f"STEP 2 Topology: {topology['status']}",
        f"STEP 3 Mobility: {mobility['status']}",
        f"Cross-Dataset Validation: {cross_status}",
        f"Scenario Coverage: topology {len(topology_ids)}/{len(metadata)}, mobility {len(mobility_ids)}/{len(metadata)}",
        f"Run-ID Consistency: {'GREEN' if topology['status'] == 'GREEN' and mobility['status'] == 'GREEN' else 'RED'}",
        f"Seed Consistency: {'GREEN' if topology['status'] == 'GREEN' and mobility['status'] == 'GREEN' else 'RED'}",
        f"Node Consistency: {'GREEN' if topology['status'] == 'GREEN' and mobility['status'] == 'GREEN' else 'RED'}",
        f"Time Consistency: {'GREEN' if topology['status'] == 'GREEN' and mobility['status'] == 'GREEN' else 'RED'}",
        f"DSR Consistency: {logs['status']}",
        f"Provenance: {'GREEN' if topology['status'] == 'GREEN' and mobility['status'] == 'GREEN' and cross_status == 'GREEN' else 'RED'}",
        "",
        "FINAL DECISION:",
        "🟢 READY FOR STEP 4 — WIRELESS / LINK QUALITY DATA" if overall == "GREEN" else "🔴 NOT READY — do not start Step 4",
    ]
    all_issues = manifest_issues + topology["issues"] + mobility["issues"] + logs["issues"] + cross_issues
    if all_issues:
        lines.extend(["", "Blocking issues:", *[f"- {issue}" for issue in all_issues]])
    print("\n".join(lines))
    (args.report_dir / "step_1_2_3_validation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()