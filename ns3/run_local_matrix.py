#!/usr/bin/env python3
"""Run selected Stage 2 scenarios locally with resumable, validated checkpoints."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any
import xml.etree.ElementTree as ET


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NS3_ROOT = Path("/Users/bistupaul/ns-3.48")
DEFAULT_MATRIX = PROJECT_ROOT / "data/metadata/Simulation_data.csv"
DEFAULT_OUTPUT_ROOT = Path.home() / "Movies/MANET_STAGE2_RUNS"
MANIFEST_NAME = "execution_manifest.json"


class RunnerError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    os.replace(temporary, path)


def read_matrix(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {
            "scenario_id",
            "run_id",
            "random_seed",
            "random_run",
            "simulation_duration_s",
            "node_count",
            "area_x_m",
            "area_y_m",
            "speed_mps",
            "source_id",
            "destination_id",
            "traffic_rate_bps",
            "packet_size_bytes",
            "mobility_model",
            "routing_protocol",
            "wifi_standard",
            "channel_helper",
            "tx_power_dbm",
            "noise_floor_dbm",
            "transport_protocol",
            "application_type",
            "flow_id",
        }
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise RunnerError(f"Matrix is missing required columns: {sorted(missing)}")
        rows = list(reader)
    if not rows:
        raise RunnerError(f"Matrix contains no scenarios: {path}")
    ids = [row["scenario_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise RunnerError("Matrix contains duplicate scenario_id values")
    for scenario_id in ids:
        if not scenario_id or Path(scenario_id).name != scenario_id or scenario_id in {".", ".."}:
            raise RunnerError(f"Unsafe scenario_id in matrix: {scenario_id!r}")
    return rows


def scenario_arguments(
    row: dict[str, str],
    attempt_dir: Path,
    outage: tuple[float, float, float] | None,
) -> list[str]:
    artifacts = attempt_dir / "artifacts"
    events = attempt_dir / "events/dsr_events.jsonl"
    pcap = attempt_dir / "evidence/dsr_control.pcap"
    values = {
        "nodeCount": row["node_count"],
        "simulationTime": row["simulation_duration_s"],
        "areaSize": row["area_x_m"],
        "areaSizeY": row["area_y_m"],
        "samplingInterval": "1.0",
        "mobilityPause": "2.0",
        "nodeSpeed": row["speed_mps"],
        "txPowerDbm": row["tx_power_dbm"],
        "noiseFloorDbm": row["noise_floor_dbm"],
        "trafficRate": f'{row["traffic_rate_bps"]}bps',
        "packetSize": row["packet_size_bytes"],
        "source": row["source_id"],
        "destination": row["destination_id"],
        "randomSeed": row["random_seed"],
        "randomRun": row["random_run"],
        "runId": row["run_id"],
        "port": "9000",
        "mobilityModel": row["mobility_model"],
        "routingProtocol": row["routing_protocol"],
        "scenarioId": row["scenario_id"],
        "wifiStandard": row["wifi_standard"],
        "channelHelper": row["channel_helper"],
        "transportProtocol": row["transport_protocol"],
        "applicationType": row["application_type"],
        "flowId": row["flow_id"],
        "enableAnimation": "false",
        "outputDir": str(artifacts),
        "dsrEventFile": str(events),
        "dsrPcapFile": str(pcap),
        "applicationTraceFile": str(attempt_dir / "events/application_packets.csv"),
    }
    if outage:
        start_s, duration_s, range_m = outage
        if (
            not all(math.isfinite(value) for value in outage)
            or start_s <= 0
            or duration_s <= 0
            or range_m < 0
        ):
            raise RunnerError("Outage start/duration must be positive and range non-negative")
        if start_s + duration_s >= float(row["simulation_duration_s"]):
            raise RunnerError("Outage interval must end before the scenario ends")
        control = attempt_dir / "events/range_interventions.jsonl"
        values.update(
            failureControlFile=str(control),
            failureOutageStartS=str(start_s),
            failureOutageDurationS=str(duration_s),
            failureOutageRangeM=str(range_m),
        )
    return [f"--{key}={value}" for key, value in values.items()]


def pcap_record_count(path: Path) -> int:
    with path.open("rb") as stream:
        header = stream.read(24)
        if len(header) != 24:
            raise RunnerError(f"PCAP global header is missing or truncated: {path}")
        magic = header[:4]
        byte_order = {
            b"\xd4\xc3\xb2\xa1": "<",
            b"\xa1\xb2\xc3\xd4": ">",
            b"\x4d\x3c\xb2\xa1": "<",
            b"\xa1\xb2\x3c\x4d": ">",
        }.get(magic)
        if byte_order is None:
            raise RunnerError(f"Unsupported PCAP magic number in {path}")
        count = 0
        while record_header := stream.read(16):
            if len(record_header) != 16:
                raise RunnerError(f"Truncated PCAP record header in {path}")
            captured_length = struct.unpack(f"{byte_order}I", record_header[8:12])[0]
            if len(stream.read(captured_length)) != captured_length:
                raise RunnerError(f"Truncated PCAP packet data in {path}")
            count += 1
        return count


def process_tree_rss_bytes(root_pid: int) -> int:
    result = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,rss="],
        check=True,
        capture_output=True,
        text=True,
    )
    processes: dict[int, tuple[int, int]] = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 3:
            pid, parent_pid, rss_kib = map(int, fields)
            processes[pid] = (parent_pid, rss_kib)
    descendants = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, (parent_pid, _) in processes.items():
            if parent_pid in descendants and pid not in descendants:
                descendants.add(pid)
                changed = True
    return sum(processes[pid][1] for pid in descendants if pid in processes) * 1024


def validate_application_trace(
    path: Path, expected_tx: int, expected_rx: int
) -> dict[str, Any]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    transmitted: dict[str, dict[str, str]] = {}
    received: dict[str, dict[str, str]] = {}
    for row in rows:
        packet_id = row.get("packet_id", "")
        direction = row.get("direction")
        if not packet_id or direction not in {"tx", "rx"}:
            raise RunnerError("Application trace contains an invalid packet identity/direction")
        target = transmitted if direction == "tx" else received
        if packet_id in target:
            raise RunnerError(f"Duplicate application {direction} packet identity: {packet_id}")
        target[packet_id] = row
    if len(transmitted) != expected_tx or len(received) != expected_rx:
        raise RunnerError(
            f"Application trace packet counts disagree with metrics: "
            f"tx {len(transmitted)}/{expected_tx}, rx {len(received)}/{expected_rx}"
        )
    delays_ns = []
    for packet_id, row in received.items():
        tx_row = transmitted.get(packet_id)
        if tx_row is None:
            raise RunnerError(f"Received application packet has no transmit record: {packet_id}")
        if row["packet_bytes"] != tx_row["packet_bytes"]:
            raise RunnerError(f"Application packet size changed for {packet_id}")
        expected_delay = int(row["simulation_time_ns"]) - int(tx_row["simulation_time_ns"])
        if expected_delay < 0 or int(row["delay_ns"]) != expected_delay:
            raise RunnerError(f"Application packet delay does not align for {packet_id}")
        delays_ns.append(expected_delay)
    if any(row["delay_ns"] for row in transmitted.values()):
        raise RunnerError("Application transmit rows must not contain a delay label")
    if len(delays_ns) != expected_rx:
        raise RunnerError("Application delay is unavailable for one or more received packets")
    return {
        "tx_packets": len(transmitted),
        "rx_packets": len(received),
        "delay_sample_count": len(delays_ns),
        "mean_delay_ms": sum(delays_ns) / len(delays_ns) / 1e6 if delays_ns else None,
    }


def validate_pcap_event_links(
    events: list[dict[str, Any]], index_entries: list[dict[str, Any]]
) -> int:
    by_record_index = {
        entry.get("pcap_record_index"): entry
        for entry in index_entries
        if isinstance(entry.get("pcap_record_index"), int)
    }
    linked_indices: set[int] = set()
    for event in events:
        event_type = event.get("event_type")
        if event_type not in {"packet_tx", "packet_rx"}:
            continue
        record_index = event.get("pcap_record_index")
        entry = by_record_index.get(record_index)
        expected_direction = "tx" if event_type == "packet_tx" else "rx"
        if (
            entry is None
            or record_index in linked_indices
            or entry.get("packet_id") != event.get("packet_id")
            or entry.get("timestamp_ns") != event.get("simulation_time_ns")
            or entry.get("node_id") != event.get("node_id")
            or entry.get("direction") != expected_direction
        ):
            raise RunnerError(f"PCAP record linkage is invalid for record {record_index}")
        linked_indices.add(record_index)
    if len(linked_indices) != len(index_entries):
        raise RunnerError(
            f"PCAP/event record count mismatch: {len(linked_indices)} linked, "
            f"{len(index_entries)} index rows"
        )
    return len(linked_indices)


def validate_outage_evidence(
    path: Path, events: list[dict[str, Any]], outage: tuple[float, float, float]
) -> dict[str, Any]:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    start_s, duration_s, range_m = outage
    expected_times = [round(start_s * 1e9), round((start_s + duration_s) * 1e9)]
    if len(records) != 3 or records[0].get("status") != "scheduled":
        raise RunnerError("Controlled-outage log must contain one schedule and two applied changes")
    schedule = records[0]
    if (
        schedule.get("start_s") != start_s
        or schedule.get("duration_s") != duration_s
        or schedule.get("outage_range_m") != range_m
        or schedule.get("restored_range_m") != 250
    ):
        raise RunnerError("Controlled-outage log does not match the selected intervention")
    applied = records[1:]
    if [record.get("simulation_time_ns") for record in applied] != expected_times:
        raise RunnerError("Controlled-outage changes were not applied at the requested times")
    if [record.get("max_range_m") for record in applied] != [range_m, 250]:
        raise RunnerError("Controlled-outage range was not restored to the baseline")

    observed_types = {event.get("event_type") for event in events}
    if "broken_link_declared" not in observed_types or "recovery_attempt" not in observed_types:
        raise RunnerError("Controlled outage produced no direct DSR link-failure/recovery-attempt evidence")
    outcomes = observed_types.intersection({"recovery_succeeded", "recovery_failed"})
    if not outcomes:
        raise RunnerError("Controlled outage has no direct DSR recovery outcome")
    return {"recovery_outcome": sorted(outcomes)}


def validate_attempt(
    attempt_dir: Path,
    row: dict[str, str],
    outage: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    artifacts = attempt_dir / "artifacts"
    event_file = attempt_dir / "events/dsr_events.jsonl"
    application_trace = attempt_dir / "events/application_packets.csv"
    pcap_file = attempt_dir / "evidence/dsr_control.pcap"
    pcap_index = attempt_dir / "evidence/dsr_control.pcap.index.jsonl"
    metrics_file = artifacts / "csv" / (
        f'dsr_metrics_seed_{row["random_seed"]}_run_{row["random_run"]}.csv'
    )
    mobility_file = artifacts / "csv" / (
        f'dsr_mobility_seed_{row["random_seed"]}_run_{row["random_run"]}.csv'
    )
    flowmon_file = Path(str(metrics_file) + ".flowmon.xml")
    route_file = artifacts / "csv" / (
        f'dsr_route_events_seed_{row["random_seed"]}_run_{row["random_run"]}.csv'
    )
    log_file = artifacts / "logs" / (
        f'simulation_seed_{row["random_seed"]}_run_{row["random_run"]}.log'
    )
    required = (
        event_file,
        application_trace,
        pcap_file,
        pcap_index,
        metrics_file,
        mobility_file,
        flowmon_file,
        route_file,
        log_file,
    )
    missing = [str(path.relative_to(attempt_dir)) for path in required if not path.is_file() or path.stat().st_size == 0]
    if missing:
        raise RunnerError(f"Missing/empty required outputs: {missing}")

    events: list[dict[str, Any]] = []
    previous_time_ns = -1
    event_ids: set[str] = set()
    with event_file.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise RunnerError(f"Invalid event JSON at line {line_number}: {error}") from error
            if event.get("scenario_id") != row["scenario_id"]:
                raise RunnerError(f"Wrong scenario_id in event line {line_number}")
            if (
                event.get("schema_version") != "dsr_event_v2"
                or event.get("run_id") != int(row["run_id"])
            ):
                raise RunnerError(f"Wrong event schema or run_id at line {line_number}")
            if event.get("random_seed") != int(row["random_seed"]):
                raise RunnerError(f"Wrong random_seed in event line {line_number}")
            if event.get("random_run") != int(row["random_run"]):
                raise RunnerError(f"Wrong random_run in event line {line_number}")
            if event.get("event_seq") != len(events):
                raise RunnerError(f"Non-contiguous event_seq at line {line_number}")
            event_time_ns = event.get("simulation_time_ns")
            if not isinstance(event_time_ns, int) or event_time_ns < previous_time_ns:
                raise RunnerError(f"Invalid or decreasing event timestamp at line {line_number}")
            if event_time_ns > float(row["simulation_duration_s"]) * 1e9:
                raise RunnerError(f"Event timestamp exceeds the scenario at line {line_number}")
            previous_time_ns = event_time_ns
            event_id = event.get("event_id")
            if not isinstance(event_id, str) or event_id in event_ids:
                raise RunnerError(f"Missing or duplicate event_id at line {line_number}")
            event_ids.add(event_id)
            events.append(event)
    if not events:
        raise RunnerError("DSR event stream contains no observed events")

    index_entries = []
    with pcap_index.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as error:
                raise RunnerError(f"Invalid PCAP index JSON at line {line_number}: {error}") from error
            if entry.get("pcap_record_index") != len(index_entries):
                raise RunnerError(f"Non-contiguous PCAP index at line {line_number}")
            index_entries.append(entry)
    records = pcap_record_count(pcap_file)
    if records == 0 or records != len(index_entries):
        raise RunnerError(
            f"PCAP/index record count mismatch: {records} records, {len(index_entries)} index rows"
        )
    pcap_link_count = validate_pcap_event_links(events, index_entries)

    with metrics_file.open(newline="", encoding="utf-8") as stream:
        metrics = list(csv.DictReader(stream))
    if len(metrics) != 1 or int(metrics[0].get("tx_packets", "0")) <= 0:
        raise RunnerError("Metrics must contain one row with at least one transmitted packet")
    if (
        metrics[0].get("measurement_layer") != "application_trace"
        or int(metrics[0].get("run_id", "-1")) != int(row["run_id"])
        or int(metrics[0].get("random_seed", "-1")) != int(row["random_seed"])
        or int(metrics[0].get("random_run", "-1")) != int(row["random_run"])
        or int(metrics[0].get("node_count", "-1")) != int(row["node_count"])
    ):
        raise RunnerError("Metrics provenance or measurement layer does not match the scenario")
    tx_packets = int(metrics[0]["tx_packets"])
    rx_packets = int(metrics[0]["rx_packets"])
    app_metrics = validate_application_trace(
        application_trace,
        tx_packets,
        rx_packets,
    )
    if int(metrics[0].get("delay_sample_count", "-1")) != app_metrics["delay_sample_count"]:
        raise RunnerError("Metrics delay sample count disagrees with application packet trace")
    metric_delay_ms = float(metrics[0]["delay_ms"])
    if app_metrics["mean_delay_ms"] is None or abs(metric_delay_ms - app_metrics["mean_delay_ms"]) > 0.000001:
        raise RunnerError("Metrics delay does not agree with packet-level application timestamps")
    expected_loss = max(tx_packets - rx_packets, 0)
    if int(metrics[0]["packet_loss"]) != expected_loss:
        raise RunnerError("Metrics packet loss disagrees with application packet counts")
    expected_pdr = rx_packets / tx_packets
    if abs(float(metrics[0]["pdr"]) - expected_pdr) > 0.000001:
        raise RunnerError("Metrics PDR disagrees with application packet counts")
    expected_throughput = (
        int(metrics[0]["rx_bytes"]) * 8 / max(1.0, float(metrics[0]["timestamp_s"]) - 2.0)
    )
    if abs(float(metrics[0]["throughput_bps"]) - expected_throughput) > 0.001:
        raise RunnerError("Metrics throughput disagrees with application payload bytes and duration")
    ET.parse(flowmon_file)
    mobility_rows = 0
    with mobility_file.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if not {"run_id", "random_seed", "random_run", "time", "node_id"}.issubset(
            reader.fieldnames or []
        ):
            raise RunnerError("Mobility trace is missing required identity/time columns")
        for row_number, mobility_record in enumerate(reader, start=2):
            mobility_time = float(mobility_record["time"])
            if (
                int(mobility_record["run_id"]) != int(row["run_id"])
                or int(mobility_record["random_seed"]) != int(row["random_seed"])
                or int(mobility_record["random_run"]) != int(row["random_run"])
                or not 0 <= int(mobility_record["node_id"]) < int(row["node_count"])
                or not math.isfinite(mobility_time)
                or not 0 <= mobility_time <= float(row["simulation_duration_s"])
            ):
                raise RunnerError(f"Mobility provenance/time mismatch at CSV row {row_number}")
            mobility_rows += 1
    if mobility_rows == 0:
        raise RunnerError("Mobility trace contains no observations")
    log = log_file.read_text(encoding="utf-8", errors="replace")
    if "status=baseline_dsr_run_complete" not in log:
        raise RunnerError("Simulation completion marker is missing from the run log")

    outputs = [*required]
    control_file = attempt_dir / "events/range_interventions.jsonl"
    if control_file.exists():
        outputs.append(control_file)
    result = {
        "event_count": len(events),
        "pcap_record_count": records,
        "mobility_row_count": mobility_rows,
        "transmitted_packets": int(metrics[0]["tx_packets"]),
        "received_packets": int(metrics[0]["rx_packets"]),
        "mean_delay_ms": metric_delay_ms,
        "delay_sample_count": app_metrics["delay_sample_count"],
        "output_bytes": sum(path.stat().st_size for path in outputs),
        "pcap_event_record_alignments": pcap_link_count,
        "outputs": {
            str(path.relative_to(attempt_dir)): {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in outputs
        },
    }
    if outage is not None:
        if not control_file.is_file():
            raise RunnerError("Controlled-outage intervention log is missing")
        result["outage_validation"] = validate_outage_evidence(
            control_file, events, outage
        )
    elif control_file.exists():
        raise RunnerError("Unexpected controlled-outage log in a baseline scenario")
    return result


def load_manifest(path: Path, matrix_path: Path, matrix_hash: str, ns3_root: Path) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "-C", str(ns3_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    patch_path = PROJECT_ROOT / "ns3/dsr_instrumentation/ns3-3.48-dsr.patch"
    package_manifest_path = PROJECT_ROOT / "ns3/dsr_instrumentation/manifest.json"
    driver_path = PROJECT_ROOT / "ns3/dsr_instrumentation/scratch/dsr_manet_dataset.cc"
    patch_hash = sha256_file(patch_path)
    package_manifest_hash = sha256_file(package_manifest_path)
    driver_hash = sha256_file(driver_path)
    source_manifest = json.loads(package_manifest_path.read_text(encoding="utf-8"))
    for source in source_manifest.get("patched_source_files", []):
        source_path = ns3_root / source["path"]
        if not source_path.is_file() or sha256_file(source_path) != source["sha256"]:
            raise RunnerError(f"Patched NS-3 source hash mismatch: {source_path}")
    external_driver = ns3_root / "scratch/dsr_manet_dataset.cc"
    if not external_driver.is_file() or sha256_file(external_driver) != driver_hash:
        raise RunnerError(f"NS-3 scenario driver hash mismatch: {external_driver}")
    runner_hash = sha256_file(Path(__file__).resolve())
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("matrix_sha256") != matrix_hash:
            raise RunnerError("Matrix checksum differs from the existing manifest; use a new output root")
        if manifest.get("ns3_commit") != commit or manifest.get("instrumentation_patch_sha256") != patch_hash:
            raise RunnerError("NS-3 source or instrumentation differs from the existing manifest")
        if manifest.get("instrumentation_manifest_sha256") not in (
            None,
            package_manifest_hash,
        ) or manifest.get("instrumentation_driver_sha256") not in (None, driver_hash):
            raise RunnerError("Instrumentation source differs from the existing manifest")
        previous_runner_hash = manifest.get("runner_sha256")
        if previous_runner_hash not in (None, runner_hash):
            manifest.setdefault("previous_runner_sha256", []).append(previous_runner_hash)
        manifest["runner_sha256"] = runner_hash
        manifest["instrumentation_manifest_sha256"] = package_manifest_hash
        manifest["instrumentation_driver_sha256"] = driver_hash
        return manifest
    return {
        "schema_version": 1,
        "status": "IN_PROGRESS",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "matrix_path": str(matrix_path),
        "matrix_sha256": matrix_hash,
        "ns3_root": str(ns3_root),
        "ns3_commit": commit,
        "instrumentation_patch_sha256": patch_hash,
        "instrumentation_manifest_sha256": package_manifest_hash,
        "instrumentation_driver_sha256": driver_hash,
        "runner_sha256": runner_hash,
        "scenarios": {},
    }


def run_scenario(
    row: dict[str, str],
    scenario_dir: Path,
    manifest: dict[str, Any],
    manifest_path: Path,
    ns3_root: Path,
    retries: int,
    timeout_s: float,
    outage: tuple[float, float, float] | None,
) -> bool:
    scenario_id = row["scenario_id"]
    config_sha256 = hashlib.sha256(
        json.dumps({"row": row, "outage": outage}, sort_keys=True).encode()
    ).hexdigest()
    state = manifest["scenarios"].setdefault(scenario_id, {"attempts": 0})
    if state.get("config_sha256") not in (None, config_sha256):
        raise RunnerError(f"Configuration changed for {scenario_id}; use a new output root")
    state["config_sha256"] = config_sha256
    if state.get("status") == "COMPLETED":
        try:
            state["validation"] = validate_attempt(
                scenario_dir / state["attempt_dir"], row, outage
            )
            state["runner_sha256"] = sha256_file(Path(__file__).resolve())
            write_json_atomic(manifest_path, manifest)
            print(f"SKIP {scenario_id}: prior checkpoint and outputs revalidated")
            return True
        except RunnerError as error:
            state["status"] = "FAILED_VALIDATION"
            state["last_error"] = str(error)
            write_json_atomic(manifest_path, manifest)

    while state["attempts"] <= retries:
        state["attempts"] += 1
        attempt_dir = scenario_dir / f'attempt-{state["attempts"]:03d}'
        while attempt_dir.exists():
            state["attempts"] += 1
            attempt_dir = scenario_dir / f'attempt-{state["attempts"]:03d}'
        attempt_dir.mkdir(parents=True)
        state.update(
            status="RUNNING",
            attempt_dir=str(attempt_dir.relative_to(scenario_dir)),
            started_at_utc=datetime.now(timezone.utc).isoformat(),
        )
        write_json_atomic(manifest_path, manifest)
        log_path = attempt_dir / "runner.log"
        command = [
            "./ns3",
            "run",
            "dsr_manet_dataset",
            "--",
            *scenario_arguments(row, attempt_dir, outage),
        ]
        print(f"RUN {scenario_id} attempt {state['attempts']}/{retries + 1}")
        try:
            started_monotonic = time.monotonic()
            deadline = started_monotonic + timeout_s
            peak_rss_bytes = 0
            with log_path.open("w", encoding="utf-8") as log:
                process = subprocess.Popen(
                    command,
                    cwd=ns3_root,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                try:
                    return_code = None
                    while return_code is None:
                        peak_rss_bytes = max(
                            peak_rss_bytes, process_tree_rss_bytes(process.pid)
                        )
                        return_code = process.poll()
                        if return_code is not None:
                            break
                        if time.monotonic() >= deadline:
                            raise subprocess.TimeoutExpired(command, timeout_s)
                        time.sleep(0.5)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    return_code = -signal.SIGTERM
                    state["last_error"] = f"Timed out after {timeout_s:g} seconds"
                except KeyboardInterrupt:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    state.update(
                        status="INTERRUPTED",
                        last_error="Interrupted by user",
                        completed_at_utc=datetime.now(timezone.utc).isoformat(),
                    )
                    write_json_atomic(manifest_path, manifest)
                    raise
            elapsed_seconds = time.monotonic() - started_monotonic
            if return_code != 0:
                state.setdefault("last_error", f"NS-3 exited with status {return_code}")
                raise RunnerError(state["last_error"])
            validation = validate_attempt(attempt_dir, row, outage)
            state.update(
                status="COMPLETED",
                completed_at_utc=datetime.now(timezone.utc).isoformat(),
                elapsed_seconds=round(elapsed_seconds, 3),
                peak_process_tree_rss_bytes=peak_rss_bytes,
                runner_sha256=sha256_file(Path(__file__).resolve()),
                validation=validation,
            )
            state.pop("last_error", None)
            write_json_atomic(manifest_path, manifest)
            print(
                f"PASS {scenario_id}: events={validation['event_count']} "
                f"pcap={validation['pcap_record_count']} "
                f"mean_delay_ms={validation['mean_delay_ms']:.3f} "
                f"tx={validation['transmitted_packets']} "
                f"rx={validation['received_packets']}"
            )
            return True
        except RunnerError as error:
            state.update(
                status="FAILED",
                last_error=str(error),
                completed_at_utc=datetime.now(timezone.utc).isoformat(),
            )
            write_json_atomic(manifest_path, manifest)
            print(f"FAIL {scenario_id}: {error}", file=sys.stderr)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ns3-dir", type=Path, default=DEFAULT_NS3_ROOT)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--scenario-id")
    selection.add_argument("--limit", type=int)
    parser.add_argument("--allow-full-matrix", action="store_true")
    parser.add_argument("--approval-reference")
    parser.add_argument("--retries", type=int, default=1, help="Additional attempts after the first")
    parser.add_argument("--timeout-s", type=float, default=7200)
    parser.add_argument(
        "--controlled-outage",
        nargs=3,
        type=float,
        metavar=("START_S", "DURATION_S", "RANGE_M"),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    matrix_path = args.matrix.resolve()
    ns3_root = args.ns3_dir.resolve()
    if args.retries < 0 or args.timeout_s <= 0:
        parser.error("--retries must be non-negative and --timeout-s must be positive")
    if not (ns3_root / "ns3").is_file() or not (ns3_root / "scratch/dsr_manet_dataset.cc").is_file():
        parser.error(f"NS-3 or the instrumented scenario driver is missing under {ns3_root}")
    output_root = args.output_root.resolve()
    if output_root.is_relative_to(PROJECT_ROOT.resolve()) or output_root.is_relative_to(
        ns3_root
    ):
        parser.error("Simulation outputs must be outside the repository and NS-3 checkout")
    rows = read_matrix(matrix_path)
    if args.scenario_id:
        rows = [row for row in rows if row["scenario_id"] == args.scenario_id]
        if not rows:
            parser.error(f"Unknown scenario_id: {args.scenario_id}")
    elif args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be at least 1")
        rows = rows[: args.limit]
    elif not args.allow_full_matrix or not args.approval_reference:
        parser.error(
            "Select --scenario-id or --limit. Full-matrix execution requires "
            "--allow-full-matrix and --approval-reference after explicit approval."
        )
    if len(rows) == 180 and (
        not args.allow_full_matrix or not args.approval_reference
    ):
        parser.error("The full 180-scenario matrix is held pending explicit approval")
    if args.controlled_outage is not None and len(rows) != 1:
        parser.error("Controlled-outage validation must select exactly one scenario")

    matrix_hash = sha256_file(matrix_path)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "selected_scenarios": [row["scenario_id"] for row in rows],
                    "scenario_count": len(rows),
                    "matrix_sha256": matrix_hash,
                    "output_root": str(output_root),
                },
                indent=2,
            )
        )
        return 0

    manifest_path = output_root / MANIFEST_NAME
    if (
        output_root.exists()
        and any(output_root.iterdir())
        and not manifest_path.is_file()
    ):
        raise RunnerError(
            f"Output root is non-empty but has no {MANIFEST_NAME}; refusing to mix data"
        )
    output_root.mkdir(parents=True, exist_ok=True)
    lock_path = output_root / ".runner.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise RunnerError(
            f"Runner lock exists at {lock_path}; verify no runner is active before removing it"
        ) from error
    os.write(descriptor, f"pid={os.getpid()}\n".encode())
    os.close(descriptor)

    try:
        manifest = load_manifest(manifest_path, matrix_path, matrix_hash, ns3_root)
        write_json_atomic(manifest_path, manifest)
        passed = 0
        for index, row in enumerate(rows, start=1):
            print(f"PROGRESS {index}/{len(rows)}")
            if run_scenario(
                row,
                output_root / row["scenario_id"],
                manifest,
                manifest_path,
                ns3_root,
                args.retries,
                args.timeout_s,
                tuple(args.controlled_outage) if args.controlled_outage else None,
            ):
                passed += 1
        manifest["status"] = "COMPLETED" if passed == len(rows) else "INCOMPLETE"
        manifest["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_json_atomic(manifest_path, manifest)
        print(f"SUMMARY {passed}/{len(rows)} scenarios validated")
        return 0 if passed == len(rows) else 1
    finally:
        lock_path.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RunnerError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error
